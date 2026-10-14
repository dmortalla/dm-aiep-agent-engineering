"""Story 6 integrated local recovery lab; no provider, network, or UI dependency.

Run ``python -m harness_engineering.recovery_lab --directory <fresh directory>``.
The structured result can feed the later reviewer UI. This composition owns no
recovery algorithm: accepted persistence, effects, and lifecycle services do that.
"""

import argparse
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.domain import EvidenceClass, RuntimeBudget
from harness_engineering.effects import EffectDeclaration, EffectObservation, EffectSpec
from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.orchestration import (
    LifecycleInput,
    LifecyclePhase,
    LifecycleRuntime,
    LifecycleState,
    StepResult,
)
from harness_engineering.persistence import (
    CheckpointIdentity,
    ConsumedBudget,
    EffectCheckpoint,
    EffectIdentity,
    RetrySnapshot,
    SQLiteCheckpointStore,
)
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan
from harness_engineering.recovery import CheckpointedLifecycle

Count = Annotated[int, Field(ge=0, le=1_000_000, strict=True)]
Text = Annotated[str, Field(max_length=256, strict=True)]
Work = Literal["prepare", "deliver", "summarize"]
COMPONENTS = (
    "application_adapter",
    "clock",
    "plan",
    "declaration",
    "runtime",
    "store",
    "coordinator",
)
NON_CLAIMS = (
    "Injected Python interruption; no OS process termination or host/power-loss test.",
    "Two local SQLite files; no distributed transaction or universal exactly-once delivery.",
    "No cross-process lease, live provider, deployment durability, or production-readiness claim.",
    "Recorded time is preserved; downtime and interrupted-call time are not measured.",
    "Synchronous callbacks cooperate with bounds; no forced Python preemption or effect rollback.",
    "Tool/provider/token/money usage is not metered; verification does not fabricate charges.",
)


class RecoveryLabError(HarnessError):
    """Local lab setup or evidence failed; inspect the preserved lab artifacts."""


class _InjectedInterruption(RuntimeError):
    """Deterministic interruption of a callback, not an OS process crash."""


class _Evidence(BaseModel):
    """Immutable strictly revalidated presentation data, never execution authority."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class CheckpointEvidence(_Evidence):
    """Read-only reviewer view derived from an actual stored checkpoint."""

    sequence: Annotated[int, Field(ge=1, le=1000)]
    boundary: Literal["attempt_reserved", "retry_pending", "step_completed", "safe_stop"]
    completed_work: tuple[Work, ...] = Field(max_length=3)
    pending_work: tuple[Work, ...] = Field(max_length=3)
    attempts: tuple[RetrySnapshot, ...] = Field(max_length=3)
    committed_effect_keys: tuple[Text, ...] = Field(max_length=1)
    consumed: ConsumedBudget


class RecoveryPassEvidence(_Evidence):
    """Observed fresh-object reconstruction and before/after durable counters."""

    fresh_components: tuple[Text, ...] = Field(max_length=7)
    declarations_match_history: bool
    loaded_checkpoint_sequence: Annotated[int, Field(ge=1, le=1000)]
    phase: LifecyclePhase
    total_attempts: Count
    completed_work: tuple[Work, ...] = Field(max_length=3)
    results: tuple[StepResult, ...] = Field(max_length=3)
    newly_executed_safe_work: tuple[Work, ...] = Field(max_length=3)
    effect_invocations_before: Count
    effect_invocations_after: Count
    external_commits: Count
    verifications_before: Count
    verifications_after: Count
    elapsed_before_milliseconds: Count
    elapsed_after_milliseconds: Count
    remaining_deadline_seconds: Annotated[float, Field(ge=0, le=5, allow_inf_nan=False)]


class RecoveryLabEvidence(_Evidence):
    """Bounded inert report for the CLI or a future presentation consumer."""

    purpose: Text
    checkpoint_file: Annotated[str, Field(max_length=4096)]
    effect_file: Annotated[str, Field(max_length=4096)]
    identity: CheckpointIdentity
    effect_identity: EffectIdentity
    clock_source: Literal["injected_deterministic_monotonic"]
    interruption_point: Literal["after_external_commit_before_completion_checkpoint"]
    reservation_visible_before_invocation: bool
    interruption_checkpoint_sequence: Annotated[int, Field(ge=1, le=1000)]
    checkpoints: tuple[CheckpointEvidence, ...] = Field(min_length=2, max_length=20)
    recovery_passes: tuple[RecoveryPassEvidence, ...] = Field(min_length=3, max_length=3)
    initial_safe_work: tuple[Work, ...] = Field(max_length=1)
    reserved_effect_attempts: Count
    effect_invocations: Count
    external_commits: Count
    replay_invocations: Count
    verification_count: Count
    trusted_deadline_seconds: Annotated[float, Field(ge=5.0, le=5.0)]
    evidence_classes: tuple[EvidenceClass, ...] = Field(min_length=2, max_length=2)
    limitations: tuple[Text, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def validate_demonstration(self) -> Self:
        """Refuse to render a successful demonstration with contradictory evidence."""
        if (
            self.effect_invocations != 1
            or self.external_commits != 1
            or self.replay_invocations != 0
            or not self.reservation_visible_before_invocation
        ):
            raise ValueError("Lab did not prove one invocation/commit without replay.")
        sequences = [item.sequence for item in self.checkpoints]
        if sequences != sorted(set(sequences)):
            raise ValueError("Checkpoint evidence must be ordered append-only history.")
        for result in self.recovery_passes:
            if (
                result.fresh_components != COMPONENTS
                or not result.declarations_match_history
                or result.phase is not LifecyclePhase.COMPLETED
                or result.completed_work != ("prepare", "deliver", "summarize")
                or result.total_attempts != 3
                or result.effect_invocations_before != result.effect_invocations_after
                or result.elapsed_after_milliseconds < result.elapsed_before_milliseconds
            ):
                raise ValueError(
                    "Recovery evidence contradicts fresh, bounded, duplicate-free resume."
                )
        return self


@dataclass
class _Clock:
    """Invocation-local deterministic monotonic clock with a fresh origin."""

    seconds: float

    def read(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


@contextmanager
def _connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Bound SQLite lock waiting, close connections, and preserve failure causes."""
    try:
        with closing(sqlite3.connect(path, timeout=1.0)) as connection, connection:
            yield connection
    except sqlite3.Error as exc:
        raise RecoveryLabError(
            "Local effect evidence failed; inspect the effect SQLite file."
        ) from exc


class _LocalEffect:
    """Fixed authorized local fixture with independent durable commitment and audit.

    Its scope is one expected identity and one harmless fixed local value. The
    checkpoint is inspected to prove ordering, not to grant effect authority.
    Calls are synchronous; absent commitment cannot later appear from an old call.
    """

    def __init__(
        self,
        directory: Path,
        identity: EffectIdentity,
        clock: _Clock,
    ) -> None:
        self.path = directory / "local-effect.sqlite"
        self.checkpoint_path = directory / "checkpoints.sqlite"
        self.expected = identity
        self.clock = clock
        self.interrupt_before_commit = False
        self.safe_calls: list[str] = []
        with _connection(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS effects "
                "(key TEXT PRIMARY KEY, identity TEXT, result TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS invocations "
                "(key TEXT, reservation_sequence INTEGER, reserved_attempts INTEGER)"
            )
            connection.execute("CREATE TABLE IF NOT EXISTS verifications (key TEXT, status TEXT)")

    def _require_expected(self, identity: EffectIdentity, timeout: float) -> None:
        if identity != self.expected or not 0 < timeout <= 1.0:
            raise ContractValidationError(
                "Local adapter accepts only its fixed trusted effect scope."
            )

    def invoke(self, identity: EffectIdentity, timeout: float) -> StepResult:
        """Observe the durable reservation, commit once, then inject interruption."""
        self._require_expected(identity, timeout)
        checkpoint = _latest(SQLiteCheckpointStore(self.checkpoint_path))
        attempts = {item.work_id: item.attempts for item in checkpoint.retry_state}
        if (
            checkpoint.boundary != "attempt_reserved"
            or checkpoint.pending_work[0] != "deliver"
            or checkpoint.effect_bindings != (self.expected,)
            or attempts.get("deliver") != 1
        ):
            raise RecoveryLabError(
                "Effect invocation did not observe its prior durable reservation."
            )
        with _connection(self.path) as connection:
            connection.execute(
                "INSERT INTO invocations VALUES (?, ?, ?)",
                (identity.key, checkpoint.sequence, attempts["deliver"]),
            )
        if self.interrupt_before_commit:
            raise _InjectedInterruption("Injected interruption before local external commit.")
        self.clock.advance(0.25)
        with _connection(self.path) as connection:
            connection.execute(
                "INSERT INTO effects VALUES (?, ?, ?)",
                (identity.key, identity.model_dump_json(), "Local delivery committed"),
            )
        raise _InjectedInterruption("Injected interruption after local external commit.")

    def verify(self, identity: EffectIdentity, timeout: float) -> EffectObservation:
        """Independently query and validate local commitment and reconstruction data."""
        self._require_expected(identity, timeout)
        self.clock.advance(0.125)
        with _connection(self.path) as connection:
            rows = connection.execute(
                "SELECT identity, result FROM effects WHERE key=? LIMIT 2",
                (identity.key,),
            ).fetchall()
            status = "not_committed"
            result = None
            if rows:
                if (
                    len(rows) != 1
                    or rows[0][0] != identity.model_dump_json()
                    or rows[0][1] != "Local delivery committed"
                ):
                    status = "unknown"
                else:
                    status, result = "committed", rows[0][1]
            connection.execute("INSERT INTO verifications VALUES (?, ?)", (identity.key, status))
        return EffectObservation(identity=identity, status=status, result=result)

    def safe_step(self, task: ExecutableSubtask, request: LifecycleInput) -> StepResult:
        """Run only the fixed pure prepare/summary steps; request text grants nothing."""
        if task.task_id not in {"prepare", "summarize"}:
            raise ContractValidationError("Local lab pure executor cannot perform an effect.")
        self.safe_calls.append(task.task_id)
        self.clock.advance(0.5)
        return StepResult(
            text="Prepared local delivery"
            if task.task_id == "prepare"
            else "Recovery finished; local delivery was independently verified"
        )

    def counts(self) -> tuple[int, int, int]:
        with _connection(self.path) as connection:
            return tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("invocations", "effects", "verifications")
            )


@dataclass(frozen=True)
class _Bootstrap:
    adapter: _LocalEffect
    clock: _Clock
    plan: ExecutionPlan
    declaration: EffectDeclaration
    runtime: LifecycleRuntime
    store: SQLiteCheckpointStore
    coordinator: CheckpointedLifecycle


def _bootstrap(
    directory: Path, generation: int, *, spec: EffectSpec | None = None, max_retries: int = 2
) -> _Bootstrap:
    """Construct fresh trusted application objects; read no authority from history."""
    identity = CheckpointIdentity(workflow_id=UUID(int=6506), thread_id=UUID(int=6504))
    spec = spec or EffectSpec(
        application="module-06-5-recovery-lab",
        work_id="deliver",
        operation="local-delivery-v1",
        input_digest=hashlib.sha256(b"Local delivery committed").hexdigest(),
    )
    clock = _Clock(float(generation * 1000))
    adapter = _LocalEffect(directory, spec.identity(identity), clock)
    plan = ExecutionPlan(
        goal="Demonstrate persisted interruption, verified effect recovery, and safe resume",
        budget=RuntimeBudget(
            max_plan_steps=3,
            max_retries_per_action=max_retries,
            workflow_deadline_seconds=5.0,
            max_provider_attempts=0,
            max_tool_calls=0,
        ),
        tasks=(
            ExecutableSubtask(task_id="prepare", description="Prepare the local delivery"),
            ExecutableSubtask(
                task_id="deliver",
                description="Commit the fixed local delivery",
                dependencies=("prepare",),
            ),
            ExecutableSubtask(
                task_id="summarize",
                description="Complete safe remaining work",
                dependencies=("deliver",),
            ),
        ),
    )
    declaration = EffectDeclaration(spec, adapter.invoke, adapter.verify, allow_retry=True)
    runtime = LifecycleRuntime(plan, adapter.safe_step, clock=clock.read)
    store = SQLiteCheckpointStore(directory / "checkpoints.sqlite")
    coordinator = CheckpointedLifecycle(runtime, store, identity, effects=(declaration,))
    return _Bootstrap(adapter, clock, plan, declaration, runtime, store, coordinator)


def _latest(store: SQLiteCheckpointStore) -> EffectCheckpoint:
    identity = CheckpointIdentity(workflow_id=UUID(int=6506), thread_id=UUID(int=6504))
    checkpoint = store.load(identity)
    if not isinstance(checkpoint, EffectCheckpoint):
        raise RecoveryLabError("Lab requires explicit accepted version 2 effect history.")
    return checkpoint


def _start_interrupted_lab(directory: Path) -> _Bootstrap:
    """Create a new artifact directory and execute to the intended interruption."""
    if not isinstance(directory, Path):
        raise ContractValidationError("Supply a fresh local lab directory Path.")
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise RecoveryLabError(
            "Use a new writable lab directory; existing evidence is preserved."
        ) from exc
    initial = _bootstrap(directory, 0)
    try:
        initial.coordinator.run(LifecycleInput(text="Context only; no effect authority"))
    except _InjectedInterruption:
        return initial
    raise RecoveryLabError(
        "Expected post-commit interruption was not observed; inspect lab evidence."
    )


def _fresh_components(previous: tuple[_Bootstrap, ...], fresh: _Bootstrap) -> tuple[str, ...]:
    fields = ("adapter", "clock", "plan", "declaration", "runtime", "store", "coordinator")
    return tuple(
        label
        for field, label in zip(fields, COMPONENTS, strict=True)
        if all(getattr(old, field) is not getattr(fresh, field) for old in previous)
    )


def _checkpoint_evidence(checkpoint: EffectCheckpoint) -> CheckpointEvidence:
    return CheckpointEvidence(
        sequence=checkpoint.sequence,
        boundary=checkpoint.boundary,
        completed_work=tuple(item.work_id for item in checkpoint.completed_work),
        pending_work=checkpoint.pending_work,
        attempts=checkpoint.retry_state,
        committed_effect_keys=tuple(item.identity.key for item in checkpoint.committed_effects),
        consumed=checkpoint.consumed_budget,
    )


def run_recovery_lab(directory: Path) -> RecoveryLabEvidence:
    """Demonstrate accepted Story 6 recovery through actual local SQLite files.

    Args:
        directory: New application-owned directory for two retained SQLite files.
            CLI/reviewer evidence belongs under parent TECHADEMY/EVIDENCE.

    Returns:
        Validated inert evidence of interruption, three fresh reconstructions,
        verified commitment, safe resume, preserved limits, and zero replay.

    Raises:
        RecoveryLabError: If setup, local SQLite, or scenario invariants fail.
        HarnessError: Accepted persistence/recovery failures propagate unchanged.
        Exception: Unexpected programming defects propagate without retry/cleanup.
    """
    directory = directory.resolve() if isinstance(directory, Path) else directory
    initial = _start_interrupted_lab(directory)
    interrupted = _latest(initial.store)
    passes: list[RecoveryPassEvidence] = []
    bootstraps = [initial]
    for generation in range(1, 4):
        fresh = _bootstrap(directory, generation)
        before = _latest(fresh.store)
        invocations, _, verifications = fresh.adapter.counts()
        state: LifecycleState = fresh.coordinator.recover(
            LifecycleInput(text="Fresh application context only"),
            restart_safe_work=frozenset({"prepare", "summarize"}),
        )
        after = _latest(fresh.store)
        after_invocations, commits, after_verifications = fresh.adapter.counts()
        passes.append(
            RecoveryPassEvidence(
                fresh_components=_fresh_components(tuple(bootstraps), fresh),
                declarations_match_history=before.effect_bindings == (fresh.adapter.expected,),
                loaded_checkpoint_sequence=before.sequence,
                phase=state.phase,
                total_attempts=state.total_attempts,
                completed_work=state.completed_task_ids,
                results=state.results,
                newly_executed_safe_work=tuple(fresh.adapter.safe_calls),
                effect_invocations_before=invocations,
                effect_invocations_after=after_invocations,
                external_commits=commits,
                verifications_before=verifications,
                verifications_after=after_verifications,
                elapsed_before_milliseconds=before.consumed_budget.elapsed_milliseconds,
                elapsed_after_milliseconds=after.consumed_budget.elapsed_milliseconds,
                remaining_deadline_seconds=max(
                    0.0, 5.0 - after.consumed_budget.elapsed_milliseconds / 1000
                ),
            )
        )
        bootstraps.append(fresh)
    final = bootstraps[-1]
    invocations, commits, verifications = final.adapter.counts()
    history = tuple(
        _checkpoint_evidence(final.store.load(interrupted.identity, sequence=sequence))
        for sequence in range(1, _latest(final.store).sequence + 1)
    )
    with _connection(final.adapter.path) as connection:
        reservations = connection.execute(
            "SELECT reservation_sequence, reserved_attempts FROM invocations"
        ).fetchall()
    return RecoveryLabEvidence(
        purpose="Observe commit, interruption, fresh recovery, safe resume, and zero replay",
        checkpoint_file=str(directory / "checkpoints.sqlite"),
        effect_file=str(final.adapter.path),
        identity=interrupted.identity,
        effect_identity=initial.adapter.expected,
        clock_source="injected_deterministic_monotonic",
        interruption_point="after_external_commit_before_completion_checkpoint",
        reservation_visible_before_invocation=reservations == [(interrupted.sequence, 1)],
        interruption_checkpoint_sequence=interrupted.sequence,
        checkpoints=history,
        recovery_passes=tuple(passes),
        initial_safe_work=tuple(initial.adapter.safe_calls),
        reserved_effect_attempts=next(
            item.attempts for item in interrupted.retry_state if item.work_id == "deliver"
        ),
        effect_invocations=invocations,
        external_commits=commits,
        replay_invocations=invocations - passes[0].effect_invocations_before,
        verification_count=verifications,
        trusted_deadline_seconds=5.0,
        evidence_classes=(EvidenceClass.DETERMINISTIC, EvidenceClass.LOCAL_INTEGRATION),
        limitations=NON_CLAIMS,
    )


def main() -> None:
    """Run one new local lab and print self-describing structured JSON evidence."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the Story 6 recovery lab. Use a fresh directory outside the repository; "
            "both SQLite files are retained. An injected Python interruption is not an OS crash."
        )
    )
    parser.add_argument(
        "--directory", type=Path, required=True, help="Fresh lab artifact directory"
    )
    args = parser.parse_args()
    print(run_recovery_lab(args.directory).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
