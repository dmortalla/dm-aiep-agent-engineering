"""Story 6 Slice 4: complete local lab and focused fail-closed compositions.

REQ-REC-001..004, REQ-DEL-002, REQ-LAB-004; ENG-001..007 where applicable.
Actual temporary SQLite files, deterministic clocks, and injected Python
interruptions; no network, credentials, provider, OS crash, or deployment claims.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness_engineering.domain import EvidenceClass
from harness_engineering.orchestration import LifecycleInput, LifecyclePhase, StepResult
from harness_engineering.persistence import PersistenceError
from harness_engineering.recovery import RecoveryError
from harness_engineering.recovery_lab import (
    COMPONENTS,
    RecoveryLabError,
    RecoveryLabEvidence,
    _bootstrap,
    _InjectedInterruption,
    _latest,
    _LocalEffect,
    _start_interrupted_lab,
    main,
    run_recovery_lab,
)


def test_complete_lab_proves_fresh_resume_and_repeated_duplicate_prevention(tmp_path: Path) -> None:
    """Assert the entire scenario against independently inspected durable artifacts."""
    report = run_recovery_lab(tmp_path / "lab")
    assert report.initial_safe_work == ("prepare",)
    assert report.interruption_point == "after_external_commit_before_completion_checkpoint"
    assert report.reservation_visible_before_invocation
    assert report.interruption_checkpoint_sequence == 2
    assert report.reserved_effect_attempts == 1
    assert (report.effect_invocations, report.external_commits, report.replay_invocations) == (
        1,
        1,
        0,
    )
    assert report.verification_count == 4
    assert report.evidence_classes == (EvidenceClass.DETERMINISTIC, EvidenceClass.LOCAL_INTEGRATION)
    assert [item.sequence for item in report.checkpoints] == list(range(1, 10))
    reserved = report.checkpoints[1]
    assert reserved.boundary == "attempt_reserved"
    assert reserved.completed_work == ("prepare",)
    assert reserved.pending_work == ("deliver", "summarize")
    assert not reserved.committed_effect_keys
    assert [(item.work_id, item.attempts) for item in reserved.attempts] == [
        ("prepare", 1),
        ("deliver", 1),
    ]
    assert reserved.consumed.elapsed_milliseconds == 500
    assert report.checkpoints[3].committed_effect_keys == (report.effect_identity.key,)
    for index, result in enumerate(report.recovery_passes):
        assert result.fresh_components == COMPONENTS
        assert result.declarations_match_history
        assert result.phase is LifecyclePhase.COMPLETED
        assert result.total_attempts == 3
        assert result.completed_work == ("prepare", "deliver", "summarize")
        assert result.results[1].text == "Local delivery committed"
        assert result.newly_executed_safe_work == (("summarize",) if index == 0 else ())
        assert result.effect_invocations_before == result.effect_invocations_after == 1
        assert result.verifications_after == result.verifications_before + 1
        assert result.elapsed_after_milliseconds > result.elapsed_before_milliseconds
        assert result.remaining_deadline_seconds == 5.0 - result.elapsed_after_milliseconds / 1000
    assert [item.elapsed_after_milliseconds for item in report.recovery_passes] == [
        1125,
        1250,
        1375,
    ]
    for checkpoint in report.checkpoints:
        assert checkpoint.consumed.tool_calls == checkpoint.consumed.provider_attempts == 0
        assert checkpoint.consumed.context_tokens == checkpoint.consumed.output_tokens == 0
    with sqlite3.connect(report.effect_file) as connection:
        assert connection.execute(
            "SELECT key, reservation_sequence, reserved_attempts FROM invocations"
        ).fetchall() == [
            (report.effect_identity.key, 2, 1),
        ]
        assert connection.execute("SELECT key, result FROM effects").fetchall() == [
            (report.effect_identity.key, "Local delivery committed"),
        ]
        assert connection.execute("SELECT status FROM verifications").fetchall() == [
            ("not_committed",),
            ("committed",),
            ("committed",),
            ("committed",),
        ]
    with sqlite3.connect(report.checkpoint_file) as connection:
        assert connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 9
    assert RecoveryLabEvidence.model_validate_json(report.model_dump_json()) == report
    assert any("OS process" in limitation for limitation in report.limitations)
    assert any("universal exactly-once" in limitation for limitation in report.limitations)
    assert any("production-readiness" in limitation for limitation in report.limitations)


def test_lab_is_deterministic_across_independent_directories(tmp_path: Path) -> None:
    first = run_recovery_lab(tmp_path / "first").model_dump(
        exclude={"checkpoint_file", "effect_file"}
    )
    second = run_recovery_lab(tmp_path / "second").model_dump(
        exclude={"checkpoint_file", "effect_file"}
    )
    assert first == second


def test_cli_renders_strict_self_describing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "cli"
    monkeypatch.setattr("sys.argv", ["recovery_lab", "--directory", str(directory)])
    main()
    output = capsys.readouterr().out
    report = RecoveryLabEvidence.model_validate_json(output)
    assert report.external_commits == 1
    assert report.replay_invocations == 0
    with pytest.raises(ValidationError):
        RecoveryLabEvidence.model_validate_json(
            json.dumps({**json.loads(output), "permissions": "all"})
        )
    with pytest.raises(ValidationError, match="one invocation"):
        RecoveryLabEvidence.model_validate(report.model_copy(update={"effect_invocations": 2}))


def test_existing_artifacts_are_preserved_instead_of_reused_or_deleted(tmp_path: Path) -> None:
    directory = tmp_path / "existing"
    directory.mkdir()
    sentinel = directory / "keep.txt"
    sentinel.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(RecoveryLabError, match="new writable"):
        run_recovery_lab(directory)
    assert sentinel.read_text(encoding="utf-8") == "existing evidence"
    assert list(directory.iterdir()) == [sentinel]


def test_ambiguous_independent_effect_state_blocks_full_lab_recovery(tmp_path: Path) -> None:
    directory = tmp_path / "ambiguous"
    initial = _start_interrupted_lab(directory)
    with sqlite3.connect(initial.adapter.path) as connection:
        connection.execute("UPDATE effects SET result='inconsistent external result'")
    fresh = _bootstrap(directory, 1)
    assert fresh.adapter is not initial.adapter
    assert fresh.coordinator is not initial.coordinator
    before = fresh.adapter.counts()
    with pytest.raises(RecoveryError, match="verification failed closed"):
        fresh.coordinator.recover(LifecycleInput(), restart_safe_work=frozenset({"summarize"}))
    assert fresh.adapter.counts()[:2] == before[:2] == (1, 1)
    assert not fresh.adapter.safe_calls
    assert _latest(fresh.store).retry_state[-1].attempts == 1


def test_corrupted_latest_lab_checkpoint_never_falls_back(tmp_path: Path) -> None:
    directory = tmp_path / "corrupt"
    initial = _start_interrupted_lab(directory)
    with sqlite3.connect(directory / "checkpoints.sqlite") as connection:
        connection.execute("UPDATE checkpoints SET payload='{' WHERE sequence=2")
    fresh = _bootstrap(directory, 1)
    before = fresh.adapter.counts()
    with pytest.raises(PersistenceError):
        fresh.coordinator.recover(LifecycleInput(), restart_safe_work=frozenset({"summarize"}))
    assert fresh.adapter.counts() == before == (1, 1, 1)
    assert not fresh.adapter.safe_calls
    assert initial.store.load(initial.adapter.expected.workflow, sequence=1).sequence == 1


def test_fresh_trusted_identity_conflict_blocks_before_verification(tmp_path: Path) -> None:
    directory = tmp_path / "mismatch"
    initial = _start_interrupted_lab(directory)
    changed = initial.declaration.spec.model_copy(update={"input_digest": "f" * 64})
    fresh = _bootstrap(directory, 1, spec=changed)
    before = fresh.adapter.counts()
    with pytest.raises(RecoveryError, match="identity conflicts"):
        fresh.coordinator.recover(LifecycleInput(), restart_safe_work=frozenset({"summarize"}))
    assert fresh.adapter.counts() == before == (1, 1, 1)
    assert not fresh.adapter.safe_calls


@pytest.mark.parametrize("reason", ["cancelled", "circuit_open", "deadline_exhausted"])
def test_cancelled_or_terminal_lab_history_remains_nonresumable(
    tmp_path: Path, reason: str
) -> None:
    directory = tmp_path / reason
    initial = _start_interrupted_lab(directory)
    previous = _latest(initial.store)
    initial.store.save(
        previous.model_copy(
            update={
                "sequence": previous.sequence + 1,
                "boundary": "safe_stop",
                "stop_reason": reason,
                "cancelled": reason == "cancelled",
            }
        )
    )
    fresh = _bootstrap(directory, 1)
    before = fresh.adapter.counts()
    with pytest.raises(RecoveryError):
        fresh.coordinator.recover(LifecycleInput(), restart_safe_work=frozenset({"summarize"}))
    assert fresh.adapter.counts() == before
    assert not fresh.adapter.safe_calls


def test_no_remaining_authority_prevents_noncommitted_effect_replay(tmp_path: Path) -> None:
    directory = tmp_path / "exhausted"
    directory.mkdir()
    initial = _bootstrap(directory, 0, max_retries=0)
    initial.adapter.interrupt_before_commit = True
    with pytest.raises(_InjectedInterruption):
        initial.coordinator.run(LifecycleInput())
    assert initial.adapter.counts() == (1, 0, 1)
    fresh = _bootstrap(directory, 1, max_retries=0)
    with pytest.raises(RecoveryError, match="remaining attempt"):
        fresh.coordinator.recover(LifecycleInput(), restart_safe_work=frozenset({"summarize"}))
    assert fresh.adapter.counts()[:2] == (1, 0)
    assert not fresh.adapter.safe_calls
    assert _latest(fresh.store).retry_state[-1].attempts == 1


def test_verified_commit_can_reconstruct_without_granting_a_replay_attempt(tmp_path: Path) -> None:
    directory = tmp_path / "committed"
    initial = _start_interrupted_lab(directory)
    fresh = _bootstrap(directory, 1, max_retries=0)
    state = fresh.coordinator.recover(LifecycleInput(), restart_safe_work=frozenset({"summarize"}))
    assert state.phase is LifecyclePhase.COMPLETED
    assert state.total_attempts == 3
    assert fresh.adapter.counts()[:2] == (1, 1)
    assert initial.adapter.counts()[:2] == (1, 1)


def test_lab_does_not_hide_or_retry_unexpected_programming_defects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def defect(self: _LocalEffect, *_args: object) -> StepResult:
        raise TypeError("injected programming defect")

    monkeypatch.setattr(_LocalEffect, "invoke", defect)
    directory = tmp_path / "defect"
    with pytest.raises(TypeError, match="programming defect"):
        run_recovery_lab(directory)
    fresh = _bootstrap(directory, 1)
    assert fresh.adapter.counts()[:2] == (0, 0)
    assert _latest(fresh.store).boundary == "attempt_reserved"
