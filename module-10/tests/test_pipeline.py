"""Pipeline trust boundaries, fail-fast behavior and immutable candidate contracts."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("pipeline", ROOT / "scripts/pipeline.py")
assert spec and spec.loader
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def test_workflow_trust() -> None:
    """Ordinary branch/PR validation has no privileged job or secret expressions."""
    pipeline.validate_contract()
    config = pipeline.workflow()
    assert set(config["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert config["permissions"] == {"contents": "read"}
    assert set(config["jobs"]) == {"validate"}
    job = config["jobs"]["validate"]
    assert job["timeout-minutes"] == 25
    assert "environment" not in job and "permissions" not in job
    assert "secrets." not in json.dumps(config)
    for event in ("pull_request", "push"):
        assert config["on"][event]["paths"] == [
            "module-10/**", ".github/workflows/module-10.yml"
        ]
    steps = job["steps"]
    assert steps[0]["with"]["persist-credentials"] is False
    assert steps[1]["with"]["python-version"] == "3.12.14"
    assert "uv sync --locked --group reviewer --python 3.12" in steps[2]["run"]
    assert all("continue-on-error" not in step and "if" not in step for step in steps)
    assert [step["uses"] for step in steps if "uses" in step] == [
        name + "@" + sha for name, sha in pipeline.PINS.items()
    ]


@pytest.mark.parametrize("commit,image", [
    ("", "sha256:" + "a" * 64), ("a" * 39, "sha256:" + "a" * 64),
    ("a" * 40, "latest"), ("a" * 40, ""),
])
def test_invalid_identity(commit: str, image: str) -> None:
    """Missing or malformed identities cannot prepare a candidate."""
    with pytest.raises(ValueError):
        pipeline.candidate(commit, image)


def test_candidate_has_no_authority() -> None:
    """Even valid immutable identities do not authorize deployment."""
    candidate = pipeline.candidate("a" * 40, "sha256:" + "b" * 64)
    assert candidate["image_tag"] == "module10-ai:sha-" + "a" * 40
    assert candidate["deployment_authorized"] is False
    assert candidate["deployment"] == "deferred-story-10.9"


@pytest.mark.parametrize("failed", range(3))
def test_quality_failure_stops_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                       failed: int) -> None:
    """Every native gate failure prevents build, acceptance and manifest creation."""
    calls = []
    monkeypatch.setattr(pipeline.subprocess, "check_output", lambda *a, **kw: "a" * 40)

    def execute(command: list[str], **kwargs: object) -> None:
        calls.append(command)
        if len(calls) == failed + 1:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(pipeline.subprocess, "run", execute)
    monkeypatch.setattr(pipeline, "docker", lambda *a, **kw: pytest.fail("Docker reached"))
    evidence = tmp_path / "result.json"
    with pytest.raises(subprocess.CalledProcessError):
        pipeline.run(evidence)
    assert len(calls) == failed + 1
    assert not evidence.exists()


@pytest.mark.parametrize("failure", ["build", "acceptance", "identity"])
def test_container_failure_blocks_evidence(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path, failure: str) -> None:
    """Build, native acceptance and metadata failures leave no successful artifact."""
    monkeypatch.setattr(pipeline.subprocess, "check_output", lambda *a, **kw: "a" * 40)
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *a, **kw: None)

    def build(*args: str, **kwargs: object) -> str:
        if failure == "build":
            raise RuntimeError("build failed")
        return ""

    def accept(image: str) -> dict:
        if failure == "acceptance":
            raise RuntimeError("acceptance failed")
        return {"image_id": "invalid"}

    monkeypatch.setattr(pipeline, "docker", build)
    monkeypatch.setattr(pipeline, "accept", accept)
    evidence = tmp_path / "result.json"
    with pytest.raises((RuntimeError, ValueError)):
        pipeline.run(evidence)
    assert not evidence.exists()


def test_success_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """One build feeds native acceptance; bounded evidence remains data only."""
    monkeypatch.setattr(pipeline.subprocess, "check_output",
                        lambda command, **kw: "" if "status" in command else "a" * 40)
    commands = []
    monkeypatch.setattr(pipeline.subprocess, "run", lambda command, **kw: commands.append(command))
    builds = []
    monkeypatch.setattr(pipeline, "docker", lambda *a, **kw: builds.append(a))
    images = []

    def accept(image: str) -> dict:
        images.append(image)
        return {"image_id": "sha256:" + "b" * 64}

    monkeypatch.setattr(pipeline, "accept", accept)
    target = tmp_path / "result.json"
    result = pipeline.run(target)
    assert len(builds) == 1 and builds[0][-1] == str(ROOT)
    assert images == ["module10-ai:sha-" + "a" * 40]
    assert [command[1:] for command in commands] == [args for _, args in pipeline.STAGES]
    assert list(result["gates"]) == ["ruff", "pytest", "compileall", "security_contract"]
    assert result["container_acceptance"] == "passed"
    assert result["deployment_authorized"] is False
    assert result["source_clean"] is True
    assert result["classification"] == "LOCAL CI/CD CONTRACT"
    assert result["github_hosted_execution_verified"] is False
    assert target.stat().st_size <= 8192
    assert json.loads(target.read_text()) == result


def test_materialization(tmp_path: Path) -> None:
    """Materialization produces valid YAML-compatible JSON without touching root scope."""
    target = tmp_path / "module-10.yml"
    subprocess.run([sys.executable, str(ROOT / "scripts/pipeline.py"),
                    "--materialize", str(target)], check=True)
    assert json.loads(target.read_text()) == pipeline.workflow()
    duplicate = subprocess.run([sys.executable, str(ROOT / "scripts/pipeline.py"),
                                "--materialize", str(target)], capture_output=True)
    assert duplicate.returncode != 0


def test_promotion_rollback_contract() -> None:
    """Future promotion requires platform authority and preserves prior revision identity."""
    contract = json.loads((ROOT / "ci/promotion.json").read_text())
    assert contract["deployment_implemented"] is False
    assert contract["allow_pull_request_deployment"] is False
    assert contract["allow_model_approval"] is False
    assert contract["required_authority"] == contract["rollback_authority"]
    assert "protected GitHub Environment" in contract["required_authority"]
    assert set(contract["required_candidate"]) == {
        "source_commit", "source_clean", "image_id", "registry_manifest_digest",
        "successful_validation_run",
    }
    assert set(contract["previous_accepted"]) == {
        "source_commit", "registry_manifest_digest", "container_app_revision"
    }
    assert {"liveness", "readiness", "deterministic_inference"} <= set(
        contract["post_deployment_checks"]
    )
