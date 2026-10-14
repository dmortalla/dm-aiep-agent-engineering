"""Slice 3 deterministic failure injection with actual local SQLite files.

REQ-REC-001..004, REQ-DEL-002, REQ-LAB-004, ENG-002..007. The second
SQLite file simulates an external effect system; it is not provider evidence,
a distributed transaction, or an operating-system crash/durability test.
"""

import hashlib
import inspect
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from harness_engineering.effects import (
    EffectDeclaration,
    EffectObservation,
    EffectSpec,
    EffectVerificationError,
)
from harness_engineering.errors import ContractValidationError, ToolExecutionError
from harness_engineering.orchestration import (
    LifecycleInput,
    LifecyclePhase,
    LifecycleRuntime,
    RetryPolicy,
    StepResult,
    TransientStepError,
)
from harness_engineering.persistence import (
    CheckpointIdentity,
    CommittedEffect,
    EffectCheckpoint,
    EffectIdentity,
    PersistenceError,
    RetrySnapshot,
    SQLiteCheckpointStore,
)
from harness_engineering.recovery import CheckpointedLifecycle, RecoveryError
from tests.test_recovery import IDENTITY, SimulatedCrash, plan, seed

SPEC = EffectSpec(
    application="slice-3-local-test",
    work_id="step-0",
    operation="write-v1",
    input_digest=hashlib.sha256(b"fixed accepted value").hexdigest(),
)
REQUEST = LifecycleInput(text="untrusted request cannot select effects")


class LocalEffect:
    """Deterministic local stand-in with independently queryable commitment."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[EffectIdentity] = []
        self.verifications: list[EffectIdentity] = []
        self.now = [0.0]
        self.mode = "normal"
        self.observation: object | None = None
        self.verify_cost = 0.0
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, value TEXT)"
            )

    def invoke(self, identity: EffectIdentity, timeout: float) -> StepResult:
        self.calls.append(identity)
        assert 0 < timeout <= 1
        self.now[0] += 0.1
        if self.mode in {"before", "during"}:
            raise SimulatedCrash("interruption without known commitment")
        if self.mode == "transient":
            raise TransientStepError("classified retry-safe by the trusted adapter")
        if self.mode == "defect":
            raise TypeError("unexpected adapter programming defect")
        if self.mode == "denied":
            raise ToolExecutionError("expected execution denial")
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO effects VALUES (?, ?)", (identity.key, "verified result")
            )
        if self.mode == "after":
            raise SimulatedCrash("external commit happened, checkpoint did not")
        return StepResult(text="verified result")

    def verify(self, identity: EffectIdentity, timeout: float) -> EffectObservation:
        self.verifications.append(identity)
        self.now[0] += self.verify_cost
        assert 0 < timeout <= 1
        if self.observation is not None:
            if isinstance(self.observation, BaseException):
                raise self.observation
            return self.observation
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT value FROM effects WHERE key=?", (identity.key,)
            ).fetchone()
        return EffectObservation(
            identity=identity,
            status="committed" if row else "not_committed",
            result=row[0] if row else None,
        )

    def declaration(self, **changes: object) -> EffectDeclaration:
        return replace(
            EffectDeclaration(SPEC, self.invoke, self.verify, allow_retry=True), **changes
        )

    def count(self) -> int:
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0]


def coordinator(
    path: Path,
    effect: LocalEffect,
    *,
    count: int = 1,
    declaration: EffectDeclaration | None = None,
    **bootstrap: object,
) -> CheckpointedLifecycle:
    """Construct entirely fresh bootstrap/runtime/store over the same durable files."""
    accepted = bootstrap.pop("accepted", plan(count))
    runtime = LifecycleRuntime(
        accepted,
        lambda _task, _request: StepResult(text="pure result"),
        clock=lambda: effect.now[0],
        wait=lambda _: None,
        **bootstrap,
    )
    return CheckpointedLifecycle(
        runtime,
        SQLiteCheckpointStore(path),
        IDENTITY,
        effects=(declaration or effect.declaration(),),
    )


def recover(path: Path, effect: LocalEffect, **bootstrap: object):
    return coordinator(path, effect, **bootstrap).recover(
        REQUEST,
        restart_safe_work=frozenset({"step-1"}) if bootstrap.get("count") == 2 else frozenset(),
    )


def interrupted(path: Path, effect: LocalEffect, mode: str = "after", **bootstrap: object) -> None:
    effect.mode = mode
    with pytest.raises(SimulatedCrash):
        coordinator(path, effect, **bootstrap).run(REQUEST)
    effect.mode = "normal"


def latest(path: Path) -> EffectCheckpoint:
    value = SQLiteCheckpointStore(path).load(IDENTITY)
    assert isinstance(value, EffectCheckpoint)
    return value


def append(path: Path, **updates: object) -> None:
    value = latest(path)
    SQLiteCheckpointStore(path).save(
        value.model_copy(update={"sequence": value.sequence + 1, **updates})
    )


def test_normal_effect_once_and_repeated_fresh_recovery(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    state = coordinator(path, effect).run(REQUEST)
    assert state.phase is LifecyclePhase.COMPLETED
    for _ in range(3):
        fresh = LocalEffect(effect.path)
        state = recover(path, fresh)
        assert not fresh.calls
        assert state.results[0].text == "verified result"
    assert effect.count() == 1
    assert len(effect.calls) == 1
    value = latest(path)
    assert value.state_version == 2
    assert value.committed_effects == (CommittedEffect(identity=SPEC.identity(IDENTITY)),)
    assert set(value.committed_effects[0].model_dump()) == {"identity"}


def test_external_commit_before_checkpoint_reconstructed_without_replay(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect, count=2)
    reservation = latest(path)
    assert reservation.boundary == "attempt_reserved"
    assert reservation.retry_state[0].attempts == 1
    assert not reservation.committed_effects
    assert not reservation.completed_work
    for _ in range(3):
        fresh = LocalEffect(effect.path)
        state = recover(path, fresh, count=2)
        assert state.completed_task_ids == ("step-0", "step-1")
        assert state.total_attempts == 2
        assert not fresh.calls
        assert fresh.verifications[0] == effect.calls[0]
    assert effect.count() == 1
    assert latest(path).committed_effects


@pytest.mark.parametrize("window", ["before-save", "after-reservation", "during-invocation"])
def test_crash_before_or_during_effect_is_fail_closed_or_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    window: str,
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    owner = coordinator(path, effect)
    original = owner._store.save

    def crash(value: EffectCheckpoint) -> None:
        if window == "before-save":
            raise SimulatedCrash("no reservation was persisted")
        original(value)
        raise SimulatedCrash("reservation persisted, invocation has not started")

    if window == "during-invocation":
        interrupted(path, effect, "during")
    else:
        monkeypatch.setattr(owner._store, "save", crash)
        with pytest.raises(SimulatedCrash):
            owner.run(REQUEST)
        assert not effect.calls
    if window == "before-save":
        assert not effect.count()
        with pytest.raises(PersistenceError):
            recover(path, effect)
    else:
        assert latest(path).retry_state[0].attempts == 1
        effect.observation = EffectObservation(
            identity=SPEC.identity(IDENTITY),
            status="unknown",
            result=None,
        )
        before = len(effect.calls)
        with pytest.raises(RecoveryError):
            recover(path, effect)
        assert len(effect.calls) == before


def test_verified_noncommitment_uses_remaining_attempts(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect, "before")
    fresh = LocalEffect(effect.path)
    state = recover(path, fresh)
    assert state.total_attempts == 2
    assert len(fresh.calls) == 1
    assert latest(path).retry_state[0].attempts == 2
    assert fresh.calls[0] == effect.calls[0]


@pytest.mark.parametrize("limit", ["attempts", "circuit", "declaration", "terminal", "tighter"])
def test_noncommitment_cannot_reset_or_widen_retry_authority(tmp_path: Path, limit: str) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect, "before")
    options = {}
    if limit == "attempts":
        append(path, retry_state=(RetrySnapshot(work_id="step-0", attempts=3),), sequence=3)
    elif limit == "circuit":
        options["retry_policy"] = RetryPolicy(failure_threshold=1)
    elif limit == "declaration":
        options["declaration"] = effect.declaration(allow_retry=False)
    elif limit == "terminal":
        append(path, boundary="safe_stop", stop_reason="step_failure")
    else:
        options["retry_policy"] = RetryPolicy(max_retries=0)
    before = len(effect.calls)
    with pytest.raises(RecoveryError):
        recover(path, effect, **options)
    assert len(effect.calls) == before
    assert not effect.count()


@pytest.mark.parametrize(
    "attack",
    [
        "unknown",
        "malformed",
        "wrong-key",
        "wrong-workflow",
        "wrong-thread",
        "wrong-work",
        "wrong-app",
        "no-result",
        "large-result",
        "extra-authority",
        "unavailable",
    ],
)
def test_verification_observations_fail_closed(tmp_path: Path, attack: str) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect)
    identity = SPEC.identity(IDENTITY)
    status, result = "committed", "verified result"
    if attack == "unknown":
        status, result = "unknown", None
    elif attack.startswith("wrong-"):
        changes = {
            "wrong-key": {"key": "f" * 64},
            "wrong-work": {"work_id": "step-1"},
            "wrong-app": {"application": "other"},
            "wrong-workflow": {
                "workflow": CheckpointIdentity(workflow_id=UUID(int=3), thread_id=UUID(int=2))
            },
            "wrong-thread": {
                "workflow": CheckpointIdentity(workflow_id=UUID(int=1), thread_id=UUID(int=3))
            },
        }
        identity = identity.model_copy(update=changes[attack])
    elif attack == "no-result":
        result = None
    elif attack == "large-result":
        result = "x" * 4097
    observation = EffectObservation.model_construct(identity=identity, status=status, result=result)
    if attack == "malformed":
        observation = {"committed": True}
    elif attack == "extra-authority":
        observation.__dict__["permissions"] = "all"
    elif attack == "unavailable":
        observation = EffectVerificationError("verification service unavailable")
    effect.observation = observation
    before = len(effect.calls)
    with pytest.raises(RecoveryError):
        recover(path, effect)
    assert len(effect.calls) == before
    assert effect.count() == 1


@pytest.mark.parametrize(
    "attack", ["forged-commit", "identity-conflict", "forged-result", "removed-bindings"]
)
def test_persisted_claims_cannot_grant_skip_or_effect_authority(
    tmp_path: Path, attack: str
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect, "before" if attack == "forged-commit" else "after")
    if attack == "forged-commit":
        append(path, committed_effects=(CommittedEffect(identity=SPEC.identity(IDENTITY)),))
    elif attack == "identity-conflict":
        append(
            path, effect_bindings=(SPEC.identity(IDENTITY).model_copy(update={"key": "f" * 64}),)
        )
    elif attack == "removed-bindings":
        append(path, effect_bindings=(), boundary="retry_pending")
    else:
        recover(path, effect)
        value = latest(path)
        append(
            path, completed_work=(value.completed_work[0].model_copy(update={"result": "forged"}),)
        )
    before = len(effect.calls)
    with pytest.raises(RecoveryError):
        recover(path, effect)
    assert len(effect.calls) == before


@pytest.mark.parametrize(
    "control", ["cancelled-history", "cancelled-now", "deadline", "budget", "verify-timeout"]
)
def test_controls_remain_consumed_and_fail_closed(tmp_path: Path, control: str) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect)
    options = {}
    if control == "cancelled-history":
        append(path, cancelled=True, boundary="safe_stop", stop_reason="cancelled")
    elif control == "cancelled-now":
        options["cancellation"] = lambda: True
    elif control == "deadline":
        value = latest(path)
        append(
            path,
            consumed_budget=value.consumed_budget.model_copy(update={"elapsed_milliseconds": 1000}),
        )
        options["accepted"] = plan(1, deadline=1.0)
    elif control == "budget":
        value = latest(path)
        append(path, consumed_budget=value.consumed_budget.model_copy(update={"tool_calls": 2}))
        options["accepted"] = plan(1, max_tool_calls=1)
    else:
        effect.verify_cost = 1.0
    before = len(effect.calls)
    with pytest.raises((RecoveryError, ContractValidationError)):
        recover(path, effect, **options)
    assert len(effect.calls) == before


def test_verification_elapsed_is_persisted_and_carried(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect)
    effect.verify_cost = 0.25
    recover(path, effect)
    assert latest(path).consumed_budget.elapsed_milliseconds >= 250
    previous = latest(path).consumed_budget.elapsed_milliseconds
    recover(path, effect)
    assert latest(path).consumed_budget.elapsed_milliseconds >= previous + 250
    assert len(effect.calls) == 1


def test_corrupt_latest_effect_checkpoint_never_falls_back(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    coordinator(path, effect).run(REQUEST)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE checkpoints SET payload='{' "
            "WHERE sequence=(SELECT MAX(sequence) FROM checkpoints)"
        )
    before = len(effect.calls)
    with pytest.raises(PersistenceError):
        recover(path, effect)
    assert len(effect.calls) == before


@pytest.mark.parametrize("boundary", ["invoke", "verify", "recovery-verify"])
def test_unexpected_defects_propagate_without_automatic_retry(
    tmp_path: Path, boundary: str
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    if boundary == "invoke":
        effect.mode = "defect"
    elif boundary == "verify":
        effect.observation = TypeError("verification programming defect")
    else:
        interrupted(path, effect)
        effect.observation = TypeError("verification programming defect")
    with pytest.raises(TypeError):
        if boundary == "recovery-verify":
            recover(path, effect)
        else:
            coordinator(path, effect).run(REQUEST)
    assert len(effect.calls) <= 1
    assert latest(path).retry_state[0].attempts == 1


def test_legacy_history_cannot_be_silently_reinterpreted_as_effect_history(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    seed(path, completed=(), pending=("step-0",), retries={})
    with pytest.raises(RecoveryError, match="version 2"):
        recover(path, effect)
    assert not effect.calls
    assert not effect.verifications


def test_identity_is_stable_and_scoped_to_exact_trusted_inputs() -> None:
    assert SPEC.identity(IDENTITY) == EffectSpec.model_validate(SPEC.model_dump()).identity(
        IDENTITY
    )
    for change in (
        {"input_digest": "f" * 64},
        {"operation": "write-v2"},
        {"application": "other"},
        {"work_id": "step-1"},
    ):
        assert SPEC.model_copy(update=change).identity(IDENTITY) != SPEC.identity(IDENTITY)
    assert SPEC.identity(
        CheckpointIdentity(workflow_id=UUID(int=3), thread_id=UUID(int=2))
    ) != SPEC.identity(IDENTITY)


def test_effect_contracts_are_bounded_inert_and_strict(tmp_path: Path) -> None:
    identity = SPEC.identity(IDENTITY)
    for changes in ({"key": "arbitrary"}, {"permissions": "all"}, {"work_id": "x" * 129}):
        with pytest.raises(ValidationError):
            EffectIdentity.model_validate({**identity.model_dump(), **changes})
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    coordinator(path, effect).run(REQUEST)
    value = latest(path)
    for changes in (
        {"committed_effects": value.committed_effects * 2},
        {"effect_bindings": value.effect_bindings * 2},
        {"state_version": 1},
        {"approval_records": ("approved",)},
    ):
        with pytest.raises(PersistenceError):
            SQLiteCheckpointStore(path).save(value.model_copy(update={"sequence": 3, **changes}))
    data = value.model_dump(mode="json")
    del data["boundary"]
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE checkpoints SET payload=?", (json.dumps(data),))
    with pytest.raises(PersistenceError):
        latest(path)


def test_public_runtime_still_rejects_restored_effect_authority(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    owner = coordinator(tmp_path / "checkpoint.sqlite", effect)
    for method in (owner._runtime.run, owner._runtime.run_observed):
        assert "effect_executor" not in inspect.signature(method).parameters
        assert "restored" not in inspect.signature(method).parameters
        with pytest.raises(TypeError):
            method(REQUEST, effect_executor=effect.invoke)
    assert list(inspect.signature(owner.recover).parameters) == ["request", "restart_safe_work"]
    assert not effect.calls


@pytest.mark.parametrize("window", ["before-completion-write", "after-completion-write"])
def test_checkpoint_write_interruptions_after_external_commit_do_not_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    window: str,
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    owner = coordinator(path, effect)
    save = owner._store.save

    def interrupted_save(value: EffectCheckpoint) -> None:
        if value.boundary == "step_completed":
            if window == "after-completion-write":
                save(value)
            raise PersistenceError("simulated checkpoint write failure")
        save(value)

    monkeypatch.setattr(owner._store, "save", interrupted_save)
    with pytest.raises(PersistenceError):
        owner.run(REQUEST)
    assert effect.count() == 1
    for _ in range(2):
        fresh = LocalEffect(effect.path)
        assert recover(path, fresh).results[0].text == "verified result"
        assert not fresh.calls
    assert effect.count() == 1


def test_control_stop_after_reservation_preserves_consumed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    owner = coordinator(path, effect)
    save = owner._store.save

    def cancel_after_reservation(value: EffectCheckpoint) -> None:
        save(value)
        if value.boundary == "attempt_reserved":
            owner._runtime.cancel()

    monkeypatch.setattr(owner._store, "save", cancel_after_reservation)
    owner.run(REQUEST)
    assert not effect.calls
    value = latest(path)
    assert value.cancelled
    assert value.retry_state[0].attempts == 1
    with pytest.raises(RecoveryError):
        recover(path, effect)


@pytest.mark.parametrize("stop", ["circuit_open", "deadline_exhausted"])
def test_terminal_control_latches_are_not_reset_by_verified_commit(
    tmp_path: Path, stop: str
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect)
    append(path, boundary="safe_stop", stop_reason=stop)
    with pytest.raises(RecoveryError, match="latched"):
        recover(path, effect)
    assert len(effect.calls) == 1
    assert effect.count() == 1


def test_repeated_interrupted_noncommitted_attempts_exhaust_original_budget(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect, "before")
    for expected in (2, 3):
        fresh = LocalEffect(effect.path)
        fresh.mode = "before"
        with pytest.raises(SimulatedCrash):
            recover(path, fresh)
        assert latest(path).retry_state[0].attempts == expected
        assert len(fresh.calls) == 1
    fresh = LocalEffect(effect.path)
    with pytest.raises(RecoveryError, match="remaining"):
        recover(path, fresh)
    assert not fresh.calls
    assert latest(path).retry_state[0].attempts == 3
    assert not fresh.count()


@pytest.mark.parametrize("retry", [True, False])
def test_live_effect_transient_retries_require_verified_noncommitment_and_policy(
    tmp_path: Path,
    retry: bool,
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    effect.mode = "transient"
    state = coordinator(path, effect, declaration=effect.declaration(allow_retry=retry)).run(
        REQUEST
    )
    assert state.phase is LifecyclePhase.SAFE_STOP
    assert len(effect.calls) == (3 if retry else 1)
    assert latest(path).retry_state[0].attempts == (3 if retry else 1)
    assert not effect.count()


def test_noncommitted_retry_keeps_backoff_and_circuit_state(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect, "before")
    fresh = LocalEffect(effect.path)
    waits: list[float] = []
    runtime = LifecycleRuntime(
        plan(1),
        lambda _task, _request: StepResult(text="unused"),
        clock=lambda: fresh.now[0],
        wait=waits.append,
    )
    owner = CheckpointedLifecycle(
        runtime, SQLiteCheckpointStore(path), IDENTITY, effects=(fresh.declaration(),)
    )
    state = owner.recover(REQUEST, restart_safe_work=frozenset())
    assert waits == [0.1]
    assert state.total_attempts == 2
    assert state.backoff_delays == (0.1,)


def test_verified_commit_without_remaining_replay_budget_is_reconstructed(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect)
    fresh = LocalEffect(effect.path)
    state = recover(path, fresh, retry_policy=RetryPolicy(max_retries=0))
    assert state.total_attempts == 1
    assert not fresh.calls


@pytest.mark.parametrize("resource", ["provider_attempts", "context_tokens", "output_tokens"])
def test_recorded_resource_counters_carry_through_effect_recovery(
    tmp_path: Path, resource: str
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect)
    usage = latest(path).consumed_budget.model_copy(update={resource: 1})
    append(path, consumed_budget=usage)
    recover(path, effect)
    assert getattr(latest(path).consumed_budget, resource) == 1


def test_effectful_work_cannot_implicitly_enable_fallback(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    with pytest.raises(ContractValidationError, match="fallback"):
        coordinator(
            tmp_path / "checkpoint.sqlite",
            effect,
            fallback_step=lambda _task, _request: StepResult(text="fallback"),
        )
    assert not effect.calls


def test_late_invocation_result_stops_then_verified_commit_recovers_without_replay(
    tmp_path: Path,
) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"

    def slow(identity: EffectIdentity, timeout: float) -> StepResult:
        effect.now[0] += 1.0
        return effect.invoke(identity, timeout)

    state = coordinator(path, effect, declaration=effect.declaration(invoke=slow)).run(REQUEST)
    assert state.phase is LifecyclePhase.SAFE_STOP
    assert latest(path).consumed_budget.elapsed_milliseconds >= 1100
    fresh = LocalEffect(effect.path)
    assert recover(path, fresh).phase is LifecyclePhase.COMPLETED
    assert not fresh.calls
    assert effect.count() == 1


def test_verification_cannot_obtain_fresh_remaining_deadline(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect)
    append(
        path,
        consumed_budget=latest(path).consumed_budget.model_copy(
            update={"elapsed_milliseconds": 400},
        ),
    )
    effect.verify_cost = 0.2
    with pytest.raises(RecoveryError):
        recover(path, effect, accepted=plan(1, deadline=0.5))
    assert latest(path).consumed_budget.elapsed_milliseconds >= 600
    checked = len(effect.verifications)
    with pytest.raises(RecoveryError):
        recover(path, effect, accepted=plan(1, deadline=0.5))
    assert len(effect.verifications) == checked
    assert len(effect.calls) == 1


def test_pending_attempt_is_conservatively_retained_in_circuit(tmp_path: Path) -> None:
    effect = LocalEffect(tmp_path / "external.sqlite")
    path = tmp_path / "checkpoint.sqlite"
    interrupted(path, effect, "before")
    fresh = LocalEffect(effect.path)
    fresh.mode = "transient"
    state = recover(path, fresh, retry_policy=RetryPolicy(failure_threshold=2))
    assert state.phase is LifecyclePhase.SAFE_STOP
    assert state.circuit.consecutive_failures == 2
    assert len(fresh.calls) == 1
    assert latest(path).retry_state[0].attempts == 2
    with pytest.raises(RecoveryError, match="latched"):
        recover(path, fresh)
