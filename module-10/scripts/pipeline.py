"""Fail-fast local/hosted validation; evidence never confers deployment authority."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from container_acceptance import ROOT, accept, docker

STAGES = (
    ("ruff", ["-m", "ruff", "check", "."]),
    ("pytest", ["-m", "pytest"]),
    ("compileall", ["-m", "compileall", "-q", "src", "tests", "scripts", "ui"]),
)
PINS = {
    "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",
    "actions/setup-python": "83679a892e2d95755f2dac6acb0bfd1e9ac5d548",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}


def workflow() -> dict:
    """Return the module-owned GitHub workflow, serialized as JSON (valid YAML)."""
    return {
        "name": "Module 10 validation (no deployment)",
        "on": {
            "pull_request": {"paths": ["module-10/**", ".github/workflows/module-10.yml"]},
            "push": {"paths": ["module-10/**", ".github/workflows/module-10.yml"]},
            "workflow_dispatch": {},
        },
        "permissions": {"contents": "read"},
        "concurrency": {"group": "module10-${{ github.workflow }}-${{ github.ref }}",
                        "cancel-in-progress": True},
        "jobs": {"validate": {
            "runs-on": "ubuntu-24.04", "timeout-minutes": 25,
            "defaults": {"run": {"working-directory": "module-10", "shell": "bash"}},
            "steps": [
                {"uses": "actions/checkout@" + PINS["actions/checkout"],
                 "with": {"persist-credentials": False}},
                {"uses": "actions/setup-python@" + PINS["actions/setup-python"],
                 "with": {"python-version": "3.12.14"}},
                {"name": "Setup locked environment",
                 "run": "python -m pip install uv==0.12.5\n"
                        "uv sync --locked --group reviewer --python 3.12"},
                {"name": "Validate, build, accept and record",
                 "run": 'uv run --no-sync python scripts/pipeline.py '
                        '--evidence "$RUNNER_TEMP/module10-evidence.json"'},
                {"uses": "actions/upload-artifact@" + PINS["actions/upload-artifact"],
                 "with": {"name": "module10-validation-${{ github.sha }}",
                          "path": "${{ runner.temp }}/module10-evidence.json",
                          "if-no-files-found": "error", "retention-days": 7}},
            ],
        }},
    }


def validate_contract() -> None:
    """Reject specification drift before Docker work; no YAML dependency needed."""
    actual = json.loads((ROOT / "ci/workflow.json").read_text(encoding="utf-8"))
    if actual != workflow():
        raise ValueError("Pipeline contract drift: review and regenerate ci/workflow.json.")


def candidate(commit: str, image_id: str) -> dict:
    """Validate immutable identities and prepare data without deployment authority.

    Args:
        commit: Full Git source identity.
        image_id: Docker content identity (not a registry manifest digest).

    Returns:
        Data-only candidate with deployment explicitly deferred.

    Raises:
        ValueError: An identity is missing or malformed.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full source commit is required.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("A Docker content ID is required.")
    return {"source_commit": commit, "image_tag": f"module10-ai:sha-{commit}",
            "image_id": image_id, "deployment": "deferred-story-10.9",
            "deployment_authorized": False}


def run(evidence: Path) -> dict:
    """Execute required gates once, recording success only after container cleanup.

    Args:
        evidence: New output file outside the repository.

    Returns:
        Bounded validation manifest, never an approval or signed attestation.

    Raises:
        RuntimeError: Python, source cleanliness or evidence destination is unsafe.
        subprocess.SubprocessError: A required gate fails.
    """
    repository = ROOT.parent
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use the Module 10 Python 3.12 environment.")
    if evidence.resolve().is_relative_to(repository) or evidence.exists():
        raise RuntimeError("Use a new evidence file outside the repository.")
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--", "module-10"], cwd=repository, text=True
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    # Local worktree validation is useful, but cannot represent a releasable commit.
    results = {}
    for name, args in STAGES:
        subprocess.run([sys.executable, *args], cwd=ROOT, check=True, timeout=300)
        results[name] = "passed"
    validate_contract()
    results["security_contract"] = "passed/targeted-not-vulnerability-audit"
    tag = candidate(commit, "sha256:" + "0" * 64)["image_tag"]
    # Dirty candidates use unique tags and are explicitly ineligible for release.
    if status:
        import uuid

        tag += "-worktree-" + uuid.uuid4().hex[:12]
    docker("build", "--tag", tag, str(ROOT), timeout=600)
    facts = accept(tag)
    identity = candidate(commit, facts["image_id"])
    identity["image_tag"] = tag
    manifest = {
        "schema_version": 1, "classification": "LOCAL CI/CD CONTRACT",
        **identity, "source_clean": not bool(status), "python": sys.version.split()[0],
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "gates": results, "build": "passed", "container_acceptance": "passed",
        "registry_digest": None, "github_hosted_execution_verified": False,
    }
    encoded = json.dumps(manifest, indent=2) + "\n"
    if len(encoded.encode()) > 8192:
        raise RuntimeError("Evidence exceeds 8192-byte bound.")
    with evidence.open("x", encoding="utf-8") as output:
        output.write(encoded)
    return manifest


def main() -> None:
    """Validate locally or materialize into an existing external staging directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--materialize", type=Path)
    args = parser.parse_args()
    validate_contract()
    if args.materialize:
        target = args.materialize.resolve()
        if target.is_relative_to(ROOT.parent) or target.exists():
            parser.error("Materialize to a new file outside this repository; root needs approval.")
        with target.open("x", encoding="utf-8") as output:
            output.write(json.dumps(workflow(), indent=2) + "\n")
    elif args.evidence:
        print(json.dumps(run(args.evidence), indent=2))
    else:
        parser.error("Provide --evidence or --materialize.")


if __name__ == "__main__":
    main()
