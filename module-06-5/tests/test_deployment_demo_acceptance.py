"""Deployment acceptance: the base dependency set alone runs all eight reviewer demos.

The hosted app installs the project's base dependencies from ``uv.lock`` and nothing else.
This test derives the base closure from the lock, makes every optional-extra package that is
NOT in that closure unimportable in a fresh interpreter, and runs all eight reviewer
demonstrations. A negative control also blocks ``mcp`` and shows exactly demos 7 and 8
becoming unavailable, so the probe demonstrably detects the deployment gap it guards.
No network, credential or provider call is used (external sockets are denied).
"""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((MODULE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
LOCK = tomllib.loads((MODULE / "uv.lock").read_text(encoding="utf-8"))
PROJECT_NAME = "dm-aiep-harness-engineering"
# Importable names for optional-extra distributions (explicit so a new extra forces a decision).
IMPORT_NAMES = {
    "langgraph-checkpoint-sqlite": "langgraph.checkpoint.sqlite",
    "mem0ai": "mem0", "langsmith": "langsmith", "langfuse": "langfuse",
    "guardrails-ai": "guardrails", "streamlit": "streamlit",
    "pytest": "pytest", "pytest-cov": "pytest_cov", "ruff": "ruff",
}
DEMO_PROBE = r'''
import importlib.abc, json, socket, sys
blocked = tuple(sys.argv[1:])
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name in blocked or any(name.startswith(b + ".") for b in blocked):
            raise ModuleNotFoundError("blocked: " + name, name=name)
        return None
sys.meta_path.insert(0, Blocker())
_connect = socket.socket.connect
def guard(self, address, *a, **k):
    if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
        return _connect(self, address, *a, **k)
    raise OSError("external network denied")
socket.socket.connect = guard
from harness_engineering.reviewer_service import Demo, run_demo
result = {}
for demo in Demo:
    try:
        result[demo.value] = "ok:" + str(len(run_demo(demo).details))
    except Exception as exc:
        result[demo.value] = "FAIL:" + type(exc).__name__ + ":" + str(getattr(exc, "name", ""))
print(json.dumps(result))
'''


def name_of(requirement: str) -> str:
    for index, char in enumerate(requirement):
        if char in " <>=!~;[(":
            return requirement[:index].lower().replace("_", "-")
    return requirement.lower().replace("_", "-")


def base_closure() -> set[str]:
    """Distributions a plain sync installs: the project's base dependencies, transitively."""
    packages = {p["name"]: p for p in LOCK["package"]}
    pending = [d["name"] for d in packages[PROJECT_NAME]["dependencies"]]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen or current not in packages:
            continue
        seen.add(current)
        pending += [d["name"] for d in packages[current].get("dependencies", [])]
    return seen


def run_probe(*blocked: str) -> dict[str, str]:
    completed = subprocess.run(
        [sys.executable, "-B", "-c", DEMO_PROBE, *blocked], cwd=MODULE, capture_output=True,
        text=True, timeout=600, check=False,
    )
    assert completed.returncode == 0, completed.stderr[-400:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


def non_base_optional_packages() -> list[str]:
    closure = base_closure()
    optional = {name_of(r) for group in PROJECT["optional-dependencies"].values() for r in group}
    return sorted(optional - closure)


def test_every_optional_package_outside_the_base_closure_has_a_known_import_name() -> None:
    missing = [n for n in non_base_optional_packages() if n not in IMPORT_NAMES]
    assert not missing, f"map import names for new optional packages: {missing}"
    closure = base_closure()
    for runtime in ("openai", "anthropic", "mcp"):
        assert runtime in closure
    assert "streamlit" not in closure  # Supplied by the hosting platform, not the base set.


def test_all_eight_reviewer_demos_run_with_only_the_base_dependency_set() -> None:
    blocked = [IMPORT_NAMES[n] for n in non_base_optional_packages()]
    assert "mcp" not in blocked and "openai" not in blocked and "anthropic" not in blocked
    outcome = run_probe(*blocked)
    assert len(outcome) == 8
    failures = {demo: result for demo, result in outcome.items() if not result.startswith("ok:")}
    assert failures == {}, f"demos unavailable on the base dependency set: {failures}"


def test_negative_control_blocking_mcp_makes_exactly_demos_7_and_8_unavailable() -> None:
    blocked = [IMPORT_NAMES[n] for n in non_base_optional_packages()]
    outcome = run_probe("mcp", *blocked)
    failed = sorted(demo for demo, result in outcome.items() if result.startswith("FAIL:"))
    assert failed == ["7 · MCP capability boundary", "8 · Evaluation and regression"]
    for demo in failed:
        assert outcome[demo] == "FAIL:ModuleNotFoundError:mcp"
    assert sum(result.startswith("ok:") for result in outcome.values()) == 6


@pytest.mark.parametrize("module", ["openai", "anthropic", "mcp"])
def test_runtime_dependencies_import_in_the_default_environment(module: str) -> None:
    __import__(module)
