"""Deployment dependency contract: provider SDKs and the MCP SDK are runtime dependencies.

Secure opt-in BYOK live mode is an intentional production capability of the deployed app,
so ``openai`` and ``anthropic`` must be installed by a plain ``uv sync`` (the hosted install
path), not by an optional extra the host may never select. The same holds for ``mcp``: the
hosted reviewer demonstrations 7 (MCP boundary) and 8 (evaluation and regression) import it.
Streamlit stays in the ``ui`` extra on purpose: the hosting platform supplies Streamlit itself
after the project sync, and duplicating it in the base set would only widen the runtime
install; the SDKs above have no such external supplier. Metadata is parsed structurally; the
install plan is computed offline from the frozen lock
(``uv sync --frozen --offline --dry-run``). No network, provider call or credential is used.
"""

import importlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((MODULE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
LOCK = tomllib.loads((MODULE / "uv.lock").read_text(encoding="utf-8"))
# Runtime dependencies the hosted app needs, with the accepted specifier and locked version.
SDK_BOUNDS = {
    "openai": (">=2.54,<3", "2.54.0"),
    "anthropic": (">=1.13,<2", "1.13.0"),
    "mcp": (">=2.3,<3", "2.3.0"),
}
REMOVED_EXTRAS = ("providers", "mcp")  # Promoted to base; extra selection is no longer needed.
PROJECT_NAME = "dm-aiep-harness-engineering"


def requirement_name(requirement: str) -> str:
    """Return the normalized distribution name of a PEP 508 requirement string."""
    return re.split(r"[\s<>=!~;\[(]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def split_specifier(requirement: str) -> str:
    """Return the version specifier of a simple ``name<specifier>`` requirement."""
    return requirement[len(requirement_name(requirement)):].strip()


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".")[:3])


def locked_package(name: str) -> dict:
    matches = [p for p in LOCK["package"] if p["name"] == name]
    assert len(matches) == 1, f"{name}: expected exactly one locked package"
    return matches[0]


def test_runtime_dependencies_are_base_dependencies_with_bounded_specifiers() -> None:
    base = {requirement_name(r): split_specifier(r) for r in PROJECT["dependencies"]}
    for sdk, (specifier, _) in SDK_BOUNDS.items():
        assert base.get(sdk) == specifier, f"{sdk} must be a base dependency {specifier}"


def test_runtime_dependencies_do_not_require_an_optional_extra_and_are_not_duplicated() -> None:
    extras = PROJECT["optional-dependencies"]
    for removed in REMOVED_EXTRAS:
        assert removed not in extras, f"extra {removed!r} must stay removed"
    for group, requirements in extras.items():
        names = {requirement_name(r) for r in requirements}
        assert not names & set(SDK_BOUNDS), f"SDK duplicated in optional group {group}"
    assert "streamlit" in {requirement_name(r) for r in extras["ui"]}
    assert "streamlit" not in {requirement_name(r) for r in PROJECT["dependencies"]}


def test_lock_records_runtime_dependencies_as_base_at_the_accepted_versions() -> None:
    project = locked_package(PROJECT_NAME)
    assert {d["name"] for d in project["dependencies"]} >= set(SDK_BOUNDS)
    for removed in REMOVED_EXTRAS:
        assert removed not in project["metadata"]["provides-extras"]
        assert removed not in project.get("optional-dependencies", {})
    requires = {r["name"]: r for r in project["metadata"]["requires-dist"]}
    for sdk, (specifier, locked) in SDK_BOUNDS.items():
        assert "marker" not in requires[sdk], f"{sdk} must not be gated by an extra marker"
        assert requires[sdk]["specifier"] == specifier
        assert locked_package(sdk)["version"] == locked, f"{sdk} lock drifted from {locked}"


def test_installed_runtime_dependencies_match_the_locked_supported_versions() -> None:
    for sdk, (_, locked) in SDK_BOUNDS.items():
        module = importlib.import_module(sdk)
        assert module.__name__ == sdk
        assert importlib.metadata.version(sdk) == locked


def test_a_plain_frozen_sync_plan_includes_every_runtime_dependency_without_any_extra(
    tmp_path: Path,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not available; the structural lock tests above still enforce this")
    environment = tmp_path / "plain-sync-plan"
    result = subprocess.run(
        [uv, "sync", "--frozen", "--offline", "--dry-run"], cwd=MODULE, capture_output=True,
        text=True, timeout=120, env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(environment)},
        check=False,
    )
    plan = result.stdout + result.stderr
    assert result.returncode == 0, "plain sync plan must resolve from the frozen lock offline"
    assert "Would install" in plan
    for sdk, (_, locked) in SDK_BOUNDS.items():
        assert f"+ {sdk}=={locked}" in plan, f"plain sync would not install {sdk}=={locked}"
    assert not environment.exists()  # Dry run only.


@pytest.mark.parametrize("removed", REMOVED_EXTRAS)
def test_removed_extras_are_unnecessary_and_rejected(removed: str, tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not available")
    result = subprocess.run(
        [uv, "sync", "--frozen", "--offline", "--dry-run", "--extra", removed], cwd=MODULE,
        capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "extra-plan")},
    )
    assert result.returncode != 0 and removed in (result.stdout + result.stderr)
