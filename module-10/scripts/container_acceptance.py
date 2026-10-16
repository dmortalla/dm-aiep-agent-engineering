"""Explicit local Docker acceptance; prints facts and never writes evidence in the repo."""

import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str, timeout: int = 60) -> str:
    """Execute bounded Docker CLI calls, preserving useful failure context."""
    try:
        result = subprocess.run(
            ["docker", *args], check=True, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"Docker acceptance failed at {args[0]}; inspect Docker engine/CLI."
        ) from exc
    return (result.stdout + (result.stderr if args[0] == "logs" else "")).strip()


def request(base: str, path: str, payload: bytes | None = None) -> tuple[int, dict]:
    """Read a bounded local HTTP response, including expected validation failures."""
    call = urllib.request.Request(
        base + path, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(call, timeout=2) as response:
            return response.status, json.loads(response.read(65536))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read(65536))


def accept(image: str | None = None) -> dict:
    """Exercise and clean up an owned container, optionally building a new image.

    Args:
        image: Existing image to exercise; None builds a unique local image.

    Returns:
        Successful container facts after cleanup. Failures propagate.
    """
    docker("info")  # Fail before creating resources if the engine is unavailable.
    name = "module10-story105-" + uuid.uuid4().hex[:12]
    build = image is None
    image = image or name + ":local"
    facts: dict = {"classification": "local-container/deterministic", "image_tag": image}
    created = False
    try:
        if build:
            docker("build", "--tag", image, str(ROOT), timeout=600)
        facts["build"] = "passed"
        metadata = json.loads(docker("image", "inspect", image))[0]
        facts["image_id"] = metadata["Id"]
        config = metadata["Config"]
        assert config["User"] == "10001:10001"
        assert set(config["ExposedPorts"]) == {"8000/tcp"}
        assert "--reload" not in config["Cmd"]
        docker(
            "create", "--name", name, "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--memory=256m", "--cpus=1",
            "--pids-limit=64", "--publish", "127.0.0.1::8000", image,
        )
        created = True
        docker("start", name)
        facts["startup"] = "passed"
        address = docker("port", name, "8000/tcp").splitlines()[0]
        base = "http://" + address
        for _ in range(40):
            try:
                status, body = request(base, "/health/ready")
                if status == 200 and body["status"] == "ready":
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass  # Startup polling only; total attempts and request time are bounded.
            time.sleep(0.25)
        else:
            raise RuntimeError("Container did not become ready within bounded startup polling.")
        facts["readiness"] = "passed"
        for _ in range(40):
            state = json.loads(docker("inspect", name))[0]["State"]
            if state.get("Health", {}).get("Status") == "healthy":
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Docker HEALTHCHECK did not report healthy.")
        facts["docker_healthcheck"] = "passed"
        assert request(base, "/health/live") == (
            200, {"status": "alive", "mode": "deterministic"}
        )
        facts["liveness"] = "passed"
        uid = int(docker("exec", name, "python", "-c", "import os; print(os.geteuid())"))
        assert uid == 10001
        facts["effective_uid"] = uid
        probe = (
            "from pathlib import Path; import importlib.util; "
            "assert not any(Path('/app').rglob('.env*')); "
            "assert not Path('/app/tests').exists(); "
            "assert not Path('/app/.git').exists(); "
            "assert not any(Path('/app').rglob('*.pem')); "
            "assert not Path('/usr/local/bin/uv').exists(); "
            "assert importlib.util.find_spec('pytest') is None; "
            "assert importlib.util.find_spec('ruff') is None; "
            "assert importlib.util.find_spec('streamlit') is None; "
            "import os; assert not os.access('/app/src/module10_ai/api.py', os.W_OK)"
        )
        docker("exec", name, "python", "-c", probe)
        facts["content_and_permissions"] = "passed (targeted checks, not a vulnerability audit)"
        status, body = request(
            base, "/api/v1/inference", b'{"text":"Beta alpha beta gamma","keyword_limit":3}'
        )
        assert status == 200 and body["evidence"] == "deterministic"
        assert body["word_count"] == 4 and body["keywords"] == ["beta", "alpha", "gamma"]
        facts["inference"] = "passed/deterministic"
        successful_request_id = body["request_id"]
        status, body = request(base, "/api/v1/inference", b'{"text":"","keyword_limit":true}')
        assert status == 422 and set(body) == {"code", "message", "request_id"}
        facts["invalid_request"] = "passed/422"
        status, body = request(base, "/api/v1/inference", b'{')
        assert status in {400, 422} and set(body) == {"code", "message", "request_id"}
        facts["malformed_json"] = "passed"
        docker("stop", "--time", "15", name)
        state = json.loads(docker("inspect", name))[0]["State"]
        assert not state["Running"] and state["ExitCode"] == 0 and not state["OOMKilled"]
        logs = docker("logs", name)  # Uvicorn lifecycle logs use stderr.
        assert "Application shutdown complete" in logs
        records = [json.loads(line) for line in logs.splitlines() if line.startswith('{')]
        assert {record["event"] for record in records} >= {
            "http.completed", "queue.admitted", "job.completed", "cache.miss",
            "inference.completed",
        }
        http_records = [record for record in records if record["event"] == "http.completed"]
        assert sum(record["status"] == "success" for record in http_records) == 1
        assert sum(record["status"] == "failure" for record in http_records) == 2
        assert all("correlation_id" in record for record in http_records)
        assert successful_request_id not in logs
        assert "Beta alpha beta gamma" not in logs
        facts["structured_telemetry"] = "passed/correlated/minimized"
        facts["stop"] = {"exit_code": state["ExitCode"], "running": state["Running"]}
        del logs
    finally:
        if created:
            docker("rm", "--force", name)
            assert not docker("ps", "--all", "--quiet", "--filter", f"name=^{name}$")
            facts["container_cleanup"] = "passed"
        print(json.dumps(facts, indent=2))
    return facts
    # Retain the uniquely tagged image for review; never prune shared Docker resources.


if __name__ == "__main__":
    accept()
