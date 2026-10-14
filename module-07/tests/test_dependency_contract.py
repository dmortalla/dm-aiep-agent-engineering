"""Story 2 tests for the Guardrails AI dependency and supply-chain contract."""

import ast
import tomllib
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

MODULE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = MODULE_ROOT / "src"
PROHIBITED = Version("0.10.1")
STALE_HUB_PATTERNS = (
    "hub://",
    "guardrails hub install",
    "guardrails.hub",
    "from guardrails import install",
    "guardrails.install(",
    "guardrails configure",
)


def guardrails_requirement() -> Requirement:
    """Return the declared guardrails-ai runtime requirement."""
    project = tomllib.loads((MODULE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    matches = [
        Requirement(entry)
        for entry in project["project"]["dependencies"]
        if Requirement(entry).name == "guardrails-ai"
    ]
    assert len(matches) == 1
    return matches[0]


def locked_packages() -> list[dict[str, object]]:
    """Return every package pinned in the Module 7 lockfile."""
    lock = tomllib.loads((MODULE_ROOT / "uv.lock").read_text(encoding="utf-8"))
    return lock["package"]


def test_prohibited_guardrails_version_cannot_satisfy_declared_requirement() -> None:
    """Reject guardrails-ai 0.10.1 at the declared dependency boundary."""
    requirement = guardrails_requirement()

    assert not requirement.specifier.contains(PROHIBITED, prereleases=True)
    assert PROHIBITED not in set(requirement.specifier.filter([PROHIBITED, "0.10.0", "0.11.0"]))


def test_prohibited_version_is_rejected_even_if_bounds_widen() -> None:
    """Keep the explicit exclusion independent of the lower bound."""
    explicit_exclusions = [
        spec for spec in guardrails_requirement().specifier if spec.operator == "!="
    ]

    assert any(not spec.contains(PROHIBITED) for spec in explicit_exclusions)


def test_locked_and_installed_guardrails_satisfy_the_contract() -> None:
    """Resolve and install only an allowed guardrails-ai release."""
    requirement = guardrails_requirement()
    locked = [package for package in locked_packages() if package["name"] == "guardrails-ai"]
    installed = Version(version("guardrails-ai"))

    assert len(locked) == 1
    assert Version(str(locked[0]["version"])) != PROHIBITED
    assert requirement.specifier.contains(str(locked[0]["version"]))
    assert installed != PROHIBITED
    assert requirement.specifier.contains(installed)


def test_lockfile_resolves_only_from_the_package_index() -> None:
    """Prevent Hub, git, or direct-URL validator sources in the lockfile."""
    for package in locked_packages():
        source = package["source"]
        assert isinstance(source, dict)
        assert set(source) <= {"registry", "editable", "virtual"}, package["name"]
        if "registry" in source:
            assert source["registry"] == "https://pypi.org/simple"


def test_stale_guardrails_hub_patterns_are_not_introduced() -> None:
    """Keep Hub installation and remote-validator patterns out of Module 7."""
    texts = [
        path.read_text(encoding="utf-8").casefold() for path in SOURCE_ROOT.rglob("*.py")
    ]
    texts.append((MODULE_ROOT / "pyproject.toml").read_text(encoding="utf-8").casefold())

    for text in texts:
        for pattern in STALE_HUB_PATTERNS:
            assert pattern not in text


def test_guardrails_import_is_confined_to_the_adapter() -> None:
    """Confine the vendor dependency to one replaceable adapter module."""
    importers = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: set[str] = set()
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            if any(name.split(".")[0] == "guardrails" for name in names):
                importers.add(path.name)

    assert importers == {"guardrails_adapter.py"}


def test_package_import_does_not_load_guardrails() -> None:
    """Keep the authorization boundary importable without the vendor adapter."""
    package_init = (SOURCE_ROOT / "reliability_safety_observability" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert "guardrails_adapter" not in package_init
