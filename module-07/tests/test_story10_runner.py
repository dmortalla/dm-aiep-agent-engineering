"""Story 10 release-artifact runner contract tests (focused, live-free)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reliability_safety_observability import story10_runner
from reliability_safety_observability.evidence_records import (
    EvidenceError,
    EvidenceStore,
    digest,
    encoded,
)
from reliability_safety_observability.release_readiness import ReadinessVerifier

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reviewer(tmp_path):
    """Provide one bounded reviewer runtime root for publication tests."""
    return tmp_path / "reviewer"


def _publish(reviewer, **overrides):
    return story10_runner.execute_release_publication(
        ROOT, reviewer_root=reviewer, **overrides
    )


def test_publication_binds_eight_artifacts_and_open_live_claims(reviewer):
    """The manifest binds candidate/contract and keeps live lanes open."""
    publication = _publish(reviewer)
    assert set(publication.artifact_digests) == {
        "integrated_acceptance",
        "traceability",
        "failure_path",
        "adversarial_security",
        "quality_gate",
        "dependency",
        "claim_audit",
        "live_claim_ledger",
    }
    manifest = json.loads(publication.manifest_path.read_bytes())
    assert manifest["candidate"] == publication.candidate
    assert manifest["contract"] == publication.contract
    ledger = manifest["artifacts"]["live_claim_ledger"]
    assert ledger["lanes"] and all(lane["status"] == "open" for lane in ledger["lanes"])
    assert all(lane["live_evidence"] is None for lane in ledger["lanes"])
    quality = manifest["artifacts"]["quality_gate"]
    assert quality["reference"] is None and quality["status"] == "open"


def test_manifest_publication_is_digest_addressed_and_idempotent(reviewer):
    """Identical manifest bytes republish to the same reference; different bytes never replace."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    path = publication.manifest_path
    content = path.read_bytes()
    reference = story10_runner._publish_manifest_bytes(path, content)
    assert reference == publication.manifest_reference
    assert path.read_bytes() == content
    path.write_bytes(content + b" ")
    with pytest.raises(EvidenceError, match="collision"):
        story10_runner._publish_manifest_bytes(path, content)
    assert path.read_bytes() == content + b" "
    path.write_bytes(content)
    again = story10_runner.verify_release_artifacts(
        ROOT, path, store_root=path.parents[2] / "records"
    )
    assert set(again) == set(publication.artifact_digests)


def test_manifest_collision_refuses_replacement(reviewer):
    """An existing manifest with different content is never replaced."""
    publication = _publish(reviewer)
    path = publication.manifest_path
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    with pytest.raises(EvidenceError, match="collision"):
        _publish(reviewer)
    assert path.read_bytes() == original + b" "


def test_verification_rederives_without_writing(reviewer, monkeypatch):
    """Independent verification reloads, re-derives and writes nothing."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    store_root = publication.manifest_path.parents[2] / "records"
    store = EvidenceStore(store_root)
    inventory = {path.name: path.read_bytes() for path in store.root.glob("*.json")}
    manifest_before = publication.manifest_path.read_bytes()
    rederived = story10_runner.verify_release_artifacts(
        ROOT, publication.manifest_path, store_root=store_root
    )
    assert set(rederived) == set(publication.artifact_digests)
    for name, payload in rederived.items():
        assert digest(encoded(payload)) == publication.artifact_digests[name]
    assert {path.name: path.read_bytes() for path in store.root.glob("*.json")} == inventory
    assert publication.manifest_path.read_bytes() == manifest_before


def test_verification_refuses_missing_store_without_side_effects(reviewer, tmp_path):
    """D4: a missing store is rejected before any directory or key creation."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    source_records = publication.manifest_path.parents[2] / "records"
    missing_root = tmp_path / "absent-store" / "records"
    manifest = publication.manifest_path
    # Copy the manifest beside the absent store so its default sibling
    # resolution is exercised, then point the store root at the absent path.
    copied_manifest = missing_root.parent / "release" / "manifest.json"
    copied_manifest.parent.mkdir(parents=True)
    copied_manifest.write_bytes(manifest.read_bytes())
    with pytest.raises(EvidenceError, match="store is missing"):
        story10_runner.verify_release_artifacts(
            ROOT, copied_manifest, store_root=missing_root
        )
    assert not missing_root.parent.joinpath("records").exists()
    assert not missing_root.parent.joinpath("records", "origin.key").exists()
    assert not copied_manifest.parent.joinpath("records").exists()
    _ = source_records


def test_verification_rejects_missing_manifest(reviewer, tmp_path):
    """A missing or directory manifest fails closed without mutation."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    store_root = publication.manifest_path.parents[2] / "records"
    missing = tmp_path / "absent.json"
    with pytest.raises(EvidenceError, match="missing"):
        story10_runner.verify_release_artifacts(ROOT, missing, store_root=store_root)
    directory = tmp_path / "directory-manifest.json"
    directory.mkdir()
    with pytest.raises(EvidenceError, match="missing"):
        story10_runner.verify_release_artifacts(ROOT, directory, store_root=store_root)


def test_verification_rejects_malformed_manifests(reviewer, tmp_path):
    """D2: malformed manifests raise actionable EvidenceError, never KeyError."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    store_root = publication.manifest_path.parents[2] / "records"
    genuine = json.loads(publication.manifest_path.read_bytes())
    cases: list[tuple[str, dict]] = [
        ("missing keys", {key: value for key, value in genuine.items() if key != "inputs"}),
        ("missing artifact", {**genuine,
                              "artifact_digests": {k: v for k, v in
                                                   genuine["artifact_digests"].items()
                                                   if k != "dependency"}}),
        ("wrong container", {**genuine, "artifacts": [genuine["artifacts"]]}),
        ("missing input key", {**genuine,
                               "inputs": {k: v for k, v in genuine["inputs"].items()
                                          if k != "lab"}}),
        ("invalid reference", {**genuine, "inputs": {**genuine["inputs"],
                                                     "evaluation": "not-a-digest"}}),
        ("wrong input container", {**genuine, "inputs": [genuine["inputs"]]}),
        ("contradictory gate", {**genuine, "gate_reference": "0" * 64}),
        ("malformed candidate", {**genuine, "candidate": "xyz"}),
        ("bad schema", {**genuine, "schema": 99}),
    ]
    for reason, changed in cases:
        path = tmp_path / "changed-manifest.json"
        path.write_bytes(encoded(changed))
        with pytest.raises(EvidenceError) as caught:
            story10_runner.verify_release_artifacts(ROOT, path, store_root=store_root)
        assert type(caught.value) is EvidenceError
        assert str(caught.value)
        _ = reason


def test_verification_rejects_stale_candidate(reviewer, monkeypatch):
    """A manifest from a different candidate is stale and fails closed."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    store_root = publication.manifest_path.parents[2] / "records"
    verifier = ReadinessVerifier(ROOT, EvidenceStore(store_root))
    stale = type(verifier.binding())(
        candidate_id="0" * 64, contract_sha256=verifier.binding().contract_sha256
    )
    monkeypatch.setattr(
        story10_runner.ReadinessVerifier, "binding", lambda self: stale
    )
    with pytest.raises(EvidenceError, match="stale"):
        story10_runner.verify_release_artifacts(
            ROOT, publication.manifest_path, store_root=store_root
        )


def test_verification_rejects_corruption(reviewer):
    """Tampered manifest bytes cannot authenticate."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    path = publication.manifest_path
    original = path.read_bytes()
    tampered = json.loads(original)
    tampered["artifact_digests"]["dependency"] = "f" * 64
    path.write_bytes(encoded(tampered))
    store_root = path.parents[2] / "records"
    with pytest.raises(EvidenceError):
        story10_runner.verify_release_artifacts(ROOT, path, store_root=store_root)
    path.write_bytes(original)


def test_verification_rejects_secret_bearing_manifest(reviewer):
    """Secret-shaped or content-bearing manifests are refused."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    path = publication.manifest_path
    original = path.read_bytes()
    canary = json.loads(original)
    canary["artifacts"]["claim_audit"]["occurrences"] = [
        {"claim": "module7::canary::x", "source": "README.md", "line": 1}
    ]
    path.write_bytes(encoded(canary))
    store_root = path.parents[2] / "records"
    with pytest.raises(EvidenceError, match="forbidden content markers"):
        story10_runner.verify_release_artifacts(ROOT, path, store_root=store_root)
    path.write_bytes(original)


def test_concurrent_publication_race_is_atomic(reviewer):
    """D1: concurrent writers cannot overwrite one another's manifests."""
    import threading

    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    path = publication.manifest_path
    original = path.read_bytes()
    tampered = json.loads(original)
    tampered["candidate"] = "f" * 64
    other_bytes = encoded(tampered)
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def race(content: bytes, label: str):
        barrier.wait()
        try:
            story10_runner._publish_manifest_bytes(path, content)
            outcomes.append(f"{label}:published")
        except EvidenceError as error:
            outcomes.append(f"{label}:{'collision' if 'collision' in str(error) else 'error'}")

    threads = [
        threading.Thread(target=race, args=(content, label))
        for content, label in ((original, "original"), (other_bytes, "other"))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(outcomes) == 2
    assert any(entry.startswith("original:") for entry in outcomes)
    # The stored bytes are always one of the two complete documents.
    stored = path.read_bytes()
    assert stored in (original, other_bytes)
    # The original content remains retrievable: no destructive overwrite.
    assert "original:published" in outcomes or stored == original
    story10_runner._publish_manifest_bytes(path, original)
    assert path.read_bytes() == original


def test_reviewer_root_inside_candidate_identity_rejected():
    """D6: a caller-supplied reviewer root that is not Git-ignored is refused.

    The root is placed inside the module tree (so candidate identity could
    enumerate it) under a name that is demonstrably not Git-ignored.
    """
    tracked_root = ROOT / "untracked-reviewer"
    with pytest.raises(EvidenceError, match="never enter"):
        story10_runner.execute_release_publication(
            ROOT, reviewer_root=tracked_root,
            include_accepted_tests=False, include_workflow=False, include_audit=False,
        )
    assert not tracked_root.exists()


def test_no_synthetic_producer_can_mint_release_evidence(reviewer):
    """The frozen producer-authority contract is untouched by the runner."""
    from reliability_safety_observability.evidence_records import (
        _RECORDING_AUTHORITY,
    )

    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    store_root = publication.manifest_path.parents[2] / "records"
    store = EvidenceStore(store_root)
    inventory = {path.name: path.read_bytes() for path in store.root.glob("*.json")}
    with pytest.raises(EvidenceError, match="capability"):
        store._publish(
            "release_manifest",
            publication.candidate,
            publication.contract,
            {"artifacts": {}},
            _authority=_RECORDING_AUTHORITY,
        )
    assert {path.name: path.read_bytes() for path in store.root.glob("*.json")} == inventory
    inputs = publication.inputs
    assert set(inputs) == {
        "evaluation", "lab", "workflow", "accepted_tests", "audit", "gate"
    }


def test_historical_gate_from_other_candidate_fails_closed(reviewer, monkeypatch):
    """A historical gate bound to another candidate never verifies here."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    store_root = publication.manifest_path.parents[2] / "records"
    store = EvidenceStore(store_root)
    verifier = ReadinessVerifier(ROOT, store)
    binding = verifier.binding()
    gate_entries = [
        {
            "gate": 0,
            "command": list(
                (
                    str(ROOT / ".venv" / "Scripts" / "python.exe"),
                    "-m",
                    "ruff",
                    "check",
                    ".",
                )
            ),
            "started_ns": 1,
            "ended_ns": 2,
            "exit_code": 0,
            "output_digest": "a" * 64,
            "retry": False,
            "failure_kind": None,
        },
        {
            "gate": 1,
            "command": list(
                (
                    str(ROOT / ".venv" / "Scripts" / "python.exe"),
                    "-m",
                    "pytest",
                    "-m",
                    "not live_vendor",
                )
            ),
            "started_ns": 3,
            "ended_ns": 4,
            "exit_code": 0,
            "output_digest": "b" * 64,
            "retry": False,
            "failure_kind": None,
        },
        {
            "gate": 2,
            "command": list(
                (
                    str(ROOT / ".venv" / "Scripts" / "python.exe"),
                    "-m",
                    "compileall",
                    "src",
                    "tests",
                    "streamlit_app.py",
                )
            ),
            "started_ns": 5,
            "ended_ns": 6,
            "exit_code": 0,
            "output_digest": "c" * 64,
            "retry": False,
            "failure_kind": None,
        },
    ]
    reference = store._publish(
        "gate_executor",
        binding.candidate_id,
        binding.contract_sha256,
        {"entries": gate_entries, "resolved_failures": []},
        _authority=_recording_authority(),
    )
    # A different candidate binding must never accept this gate record.
    stale = type(binding)(candidate_id="1" * 64, contract_sha256=binding.contract_sha256)
    monkeypatch.setattr(ReadinessVerifier, "binding", lambda self: stale)
    with pytest.raises(EvidenceError):
        story10_runner.execute_release_publication(
            ROOT, reviewer_root=reviewer, gate=reference,
            include_accepted_tests=False, include_workflow=False, include_audit=False,
        )


def _recording_authority():
    from reliability_safety_observability import evidence_records as records

    return records._RECORDING_AUTHORITY


def test_dedicated_reviewer_storage_is_git_ignored():
    """The .review-storage default is excluded from Git candidate identity."""
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--verbose", ".review-storage/"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert ".gitignore" in result.stdout


def test_publication_leaves_candidate_identity_unchanged(reviewer):
    """Publishing evidence never rebinds the candidate."""
    from reliability_safety_observability.evidence_records import EvidenceStore
    from reliability_safety_observability.release_readiness import ReadinessVerifier

    before = ReadinessVerifier(ROOT, EvidenceStore(reviewer / "records")).binding()
    _publish(reviewer, include_accepted_tests=False,
             include_workflow=False, include_audit=False)
    after = ReadinessVerifier(ROOT, EvidenceStore(reviewer / "records")).binding()
    assert (after.candidate_id, after.contract_sha256) == (
        before.candidate_id, before.contract_sha256
    )


def test_different_candidates_do_not_overwrite(reviewer, monkeypatch):
    """Two candidates publish side-by-side; neither replaces the other."""
    publication_a = _publish(reviewer, include_accepted_tests=False,
                             include_workflow=False, include_audit=False)
    verifier = ReadinessVerifier(
        ROOT, EvidenceStore(reviewer / "records")
    )
    binding_b = type(verifier.binding())(
        candidate_id="f" * 64, contract_sha256=verifier.binding().contract_sha256
    )
    monkeypatch.setattr(
        story10_runner.ReadinessVerifier, "binding", lambda self: binding_b
    )
    publication_b = _publish(reviewer, include_accepted_tests=False,
                             include_workflow=False, include_audit=False)
    assert publication_a.manifest_path != publication_b.manifest_path
    assert publication_a.manifest_path.parent.name == publication_a.candidate
    assert publication_b.manifest_path.parent.name == publication_b.candidate
    assert publication_a.manifest_path.exists()
    assert publication_b.manifest_path.exists()


def test_retention_prunes_oldest_and_preserves_current(reviewer, monkeypatch):
    """Bounded retention keeps the current candidate and the newest others."""
    first = _publish(reviewer, include_accepted_tests=False,
                     include_workflow=False, include_audit=False)
    verifier = ReadinessVerifier(
        ROOT, EvidenceStore(reviewer / "records")
    )
    template = verifier.binding()
    published = [first]
    for index in range(3):
        shifted = type(template)(
            candidate_id=f"{index:064x}", contract_sha256=template.contract_sha256
        )
        monkeypatch.setattr(
            story10_runner.ReadinessVerifier, "binding", lambda self, s=shifted: s
        )
        published.append(_publish(reviewer, include_accepted_tests=False,
                                  include_workflow=False, include_audit=False))
    release_dir = reviewer / "release"
    assert len(list(release_dir.glob("*/manifest.json"))) == 4
    pruned = story10_runner.prune_release_history(
        reviewer, current_candidate=published[-1].candidate,
        retained_generations=2,
    )
    remaining = sorted(path.parent.name for path in release_dir.glob("*/manifest.json"))
    # The current candidate always survives; the digest-oldest two are pruned.
    assert published[-1].candidate in remaining
    assert len(remaining) == 3
    assert pruned == sorted(
        {publication.candidate for publication in published} - set(remaining)
    )


def test_retention_refuses_foreign_content_and_escapes(reviewer):
    """Cleanup fails closed on unexpected directories or escaped paths."""
    reviewer.mkdir(parents=True, exist_ok=True)
    release_dir = reviewer / "release"
    foreign = release_dir / "not-a-candidate"
    foreign.mkdir(parents=True)
    (foreign / "manifest.json").write_bytes(b"{}")
    with pytest.raises(EvidenceError, match="unexpected directory"):
        story10_runner.prune_release_history(reviewer)
    (foreign / "manifest.json").unlink()
    foreign.rmdir()
    forged = release_dir / ("f" * 64)
    forged.mkdir(parents=True)
    document = {"schema": 1, "candidate": "a" * 64}
    (forged / "manifest.json").write_bytes(encoded(document))
    with pytest.raises(EvidenceError, match="contradicts its candidate"):
        story10_runner.prune_release_history(reviewer)
    (forged / "manifest.json").unlink()
    forged.rmdir()
    assert not any(release_dir.iterdir())


def test_retention_never_deletes_current_or_escapes_tree(reviewer):
    """Cleanup is bounded to the dedicated release subtree."""
    runtime = reviewer
    runtime.mkdir(parents=True, exist_ok=True)
    release_dir = runtime / "release"
    decoy = runtime / "decoy.json"
    decoy.write_bytes(b"keep me")
    sibling = runtime / "release-sibling.json"
    sibling.write_bytes(b"keep me too")
    manifest_dir = release_dir / ("b" * 64)
    manifest_dir.mkdir(parents=True)
    manifest = manifest_dir / "manifest.json"
    manifest.write_bytes(encoded({
        "schema": 1, "candidate": "b" * 64, "contract": "c" * 64,
        "inputs": {}, "gate_reference": None, "artifact_digests": {},
        "artifacts": {},
    }))
    story10_runner.prune_release_history(
        runtime, current_candidate="b" * 64, retained_generations=1,
    )
    assert manifest.exists()
    assert decoy.read_bytes() == b"keep me"
    assert sibling.read_bytes() == b"keep me too"


def test_retention_bounds_fail_closed(reviewer):
    """Retention bounds outside the accepted range refuse to run."""
    with pytest.raises(EvidenceError, match="Retention bound"):
        story10_runner.prune_release_history(reviewer, retained_generations=0)
    with pytest.raises(EvidenceError, match="Retention bound"):
        story10_runner.prune_release_history(reviewer, retained_generations=33)


def test_verification_never_triggers_cleanup_or_writes(reviewer):
    """Verification performs no writes and leaves history untouched."""
    publication = _publish(reviewer, include_accepted_tests=False,
                           include_workflow=False, include_audit=False)
    release_dir = reviewer / "release"
    before = {
        path: path.read_bytes()
        for path in sorted(release_dir.rglob("*")) if path.is_file()
    }
    story10_runner.verify_release_artifacts(
        ROOT, publication.manifest_path,
        store_root=publication.manifest_path.parents[2] / "records",
    )
    after = {
        path: path.read_bytes()
        for path in sorted(release_dir.rglob("*")) if path.is_file()
    }
    assert after == before
