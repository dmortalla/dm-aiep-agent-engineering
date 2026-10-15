"""Fast artifact contracts; actual Docker execution is a separate acceptance gate."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def instructions() -> list[tuple[str, str]]:
    """Read logical Docker instructions without depending on line wrapping."""
    content = (ROOT / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
    return [
        tuple(line.split(None, 1))
        for raw in content.splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]


def test_runtime_contract() -> None:
    """Runtime uses one non-root ASGI process, explicit port and direct signals."""
    values = dict(instructions())
    assert values["FROM"].startswith("python:3.12.14-slim-bookworm")
    assert values["USER"] == "10001:10001"
    assert values["EXPOSE"] == "8000"
    assert values["STOPSIGNAL"] == "SIGTERM"
    command = json.loads(values["CMD"])
    assert command[:4] == ["python", "-m", "uvicorn", "module10_ai.api:create_app"]
    assert "--factory" in command
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "8000"
    assert "--reload" not in command
    assert "--timeout-graceful-shutdown" in command


def test_build_and_content_contract() -> None:
    """Locked runtime-only dependencies and narrow copies preserve isolation."""
    steps = instructions()
    copies = [value for key, value in steps if key in {"COPY", "ADD"}]
    assert copies == [
        "--from=uv /uv /usr/local/bin/uv",
        "pyproject.toml uv.lock ./",
        "--from=builder /opt/venv /opt/venv",
        "src/module10_ai /app/src/module10_ai",
    ]
    build = next(value for key, value in steps if key == "RUN" and "uv sync" in value)
    assert all(flag in build.split() for flag in (
        "--locked", "--no-dev", "--no-install-project", "--no-cache"
    ))
    assert not any(key in {"ARG", "ADD"} for key, _ in steps)


def test_context_allowlist() -> None:
    """Only required manifests and Python package source enter the build context."""
    patterns = [line for line in (ROOT / ".dockerignore").read_text().splitlines()
                if line and not line.startswith("#")]
    assert patterns == [
        "**", "!pyproject.toml", "!uv.lock", "!src/", "!src/module10_ai/",
        "!src/module10_ai/*.py", "!Dockerfile", "!.dockerignore",
    ]


def test_readiness_probe() -> None:
    """Docker checks readiness using Python already present in the runtime image."""
    health = dict(instructions())["HEALTHCHECK"]
    command = json.loads(health.split(" CMD ", 1)[1])
    assert command[:2] == ["python", "-c"]
    assert "/health/ready" in command[2]
    assert "timeout=2" in command[2]
    assert "/health/live" not in command[2]
