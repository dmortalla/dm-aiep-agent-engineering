"""Story 6 Slice 2: lifecycle checkpoints and reconciled crash recovery.

Trusted bootstrap binds a lifecycle runtime, a local checkpoint store, and an
explicit workflow identity. Checkpoints are historical claims: recovery
reconciles them against the fresh runtime's trusted plan, retry policy,
deadline, and budget before any work resumes. A checkpoint never supplies
routes, limits, permissions, callbacks, or cancellation resets.

Resume starts only at a clean action boundary. Committed-effect verification,
replay prevention, and re-entry into a partially attempted action are deferred.
"""

from math import ceil

from pydantic import ValidationError

from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.orchestration import (
    BoundarySnapshot,
    LifecycleBounds,
    LifecycleInput,
    LifecycleRuntime,
    LifecycleState,
    RestoredProgress,
    StepResult,
    StopReason,
)
from harness_engineering.persistence import (
    SCHEMA_VERSION,
    STATE_VERSION,
    Checkpoint,
    CheckpointIdentity,
    CheckpointNotFoundError,
    CompletedWork,
    ConsumedBudget,
    PersistenceError,
    RetrySnapshot,
    SQLiteCheckpointStore,
)

MAX_SEQUENCE = 1000
MAX_ELAPSED_MILLISECONDS = 1_000_000


class RecoveryError(HarnessError):
    """Persisted history cannot be safely reconciled; no work was executed."""


def reconcile(
    checkpoint: Checkpoint,
    identity: CheckpointIdentity,
    bounds: LifecycleBounds,
    restart_safe_work: frozenset[str],
) -> RestoredProgress:
    """Reconcile an untrusted historical checkpoint against trusted inputs.

    Args:
        checkpoint: Latest stored snapshot; structurally valid but unauthenticated.
        identity: Trusted workflow and thread the caller expects.
        bounds: Limits and scheduling order from the current trusted runtime.
        restart_safe_work: Trusted declaration of work whose re-execution after
            an interrupted attempt has no external side effect.

    Returns:
        The completed prefix, without identifiers or limits, for the runtime to
        rebuild against its own trusted plan. The value is inert: no public
        runtime method accepts it, so calling this function resumes nothing.

    Raises:
        RecoveryError: If history is malformed, mismatched, cancelled, impossible,
            beyond a trusted limit, or needs semantics deferred to a later slice.
    """
    try:
        checked = Checkpoint.model_validate(checkpoint)
    except ValidationError as exc:
        raise RecoveryError("Checkpoint is malformed or uses an unsupported version.") from exc
    if checked.identity != identity:
        raise RecoveryError("Checkpoint identity does not match the trusted workflow.")
    if checked.cancelled:
        raise RecoveryError(
            "Workflow was cancelled; persisted history cannot authorize re-entry."
        )
    completed = tuple(item.work_id for item in checked.completed_work)
    if completed + checked.pending_work != bounds.task_ids:
        raise RecoveryError(
            "Checkpoint work does not match the trusted plan's work and order."
        )
    recorded = {item.work_id: item.attempts for item in checked.retry_state}
    attempts = tuple(recorded.pop(work_id, 0) for work_id in completed)
    if any(
        not 1 <= count <= min(bounds.max_attempts_per_action, bounds.failure_threshold)
        for count in attempts
    ):
        raise RecoveryError(
            "Completed work records attempts that trusted retry policy cannot produce."
        )
    pending = checked.pending_work
    if pending and recorded.get(pending[0], 0) >= 1 and len(recorded) == 1:
        raise RecoveryError(
            "Incomplete work already consumed attempts; re-entry into a partially "
            "attempted action is deferred and its attempts are not reset."
        )
    if recorded:
        raise RecoveryError("Retry records on unstarted work are impossible or ambiguous.")
    if checked.sequence < sum(attempts):
        raise RecoveryError("Checkpoint sequence cannot account for its recorded attempts.")
    consumed, budget = checked.consumed_budget, bounds.budget
    if (
        consumed.tool_calls > budget.max_tool_calls
        or consumed.provider_attempts > budget.max_provider_attempts
        or consumed.context_tokens > budget.max_context_tokens * budget.max_provider_attempts
        or consumed.output_tokens > budget.max_output_tokens * budget.max_provider_attempts
    ):
        raise RecoveryError("Recorded consumption exceeds a trusted current budget limit.")
    if consumed.elapsed_milliseconds >= bounds.deadline_seconds * 1000:
        raise RecoveryError("Recorded elapsed time already exhausts the trusted deadline.")
    if pending and pending[0] not in restart_safe_work:
        raise RecoveryError(
            "First incomplete work is not declared restart-safe; an interrupted attempt "
            "may have committed an effect, which requires later effect verification."
        )
    remaining_writes = len(pending) * bounds.max_attempts_per_action + 1
    if checked.sequence + remaining_writes > MAX_SEQUENCE:
        raise RecoveryError("Remaining checkpoint sequence capacity cannot cover resumed work.")
    try:
        results = tuple(StepResult(text=item.result) for item in checked.completed_work)
    except ValidationError as exc:
        raise RecoveryError("Persisted result violates the lifecycle result contract.") from exc
    return RestoredProgress(
        results=results, attempts=attempts,
        elapsed_seconds=consumed.elapsed_milliseconds / 1000,
    )


class CheckpointedLifecycle:
    """Run and recover one identified workflow through the real lifecycle graph.

    The lifecycle remains the only executor. This class observes its validated
    boundaries, appends one snapshot per boundary, and on recovery hands the
    runtime a reconciled completed prefix. Recovery is always an explicit call;
    interruptions and defects are never masked or retried automatically.
    """

    def __init__(
        self, runtime: LifecycleRuntime, store: SQLiteCheckpointStore,
        identity: CheckpointIdentity,
    ) -> None:
        """Bind trusted bootstrap objects; none may come from persisted data.

        Args:
            runtime: Lifecycle built from the current accepted plan and policies.
            store: Application-selected local checkpoint store.
            identity: Explicit workflow and thread identity for this workflow.

        Raises:
            ContractValidationError: For a wrong runtime, store, or identity type.
        """
        if not isinstance(runtime, LifecycleRuntime) or not isinstance(
            store, SQLiteCheckpointStore
        ):
            raise ContractValidationError("Bind a lifecycle runtime and a checkpoint store.")
        try:
            self._identity = CheckpointIdentity.model_validate(identity)
        except ValidationError as exc:
            raise ContractValidationError("Bind an explicit workflow/thread identity.") from exc
        self._runtime = runtime
        self._store = store

    def run(self, request: LifecycleInput) -> LifecycleState:
        """Start a new workflow, checkpointing every lifecycle boundary.

        Args:
            request: Untrusted text passed unchanged to the lifecycle.

        Returns:
            The lifecycle's validated completed or safe-stop state.

        Raises:
            PersistenceError: If history already exists for this identity, the
                identity is bound to another thread, or a checkpoint write fails.
            ContractValidationError: For invalid input or lifecycle invariants.
            Exception: Unexpected defects propagate; committed checkpoints remain.
        """
        try:
            self._store.load(self._identity)
        except CheckpointNotFoundError:
            pass
        else:
            raise PersistenceError(
                "Workflow already has checkpoint history; recover it explicitly."
            )
        return self._runtime.run_observed(
            request, observer=_Writer(self, 1, _unmetered()),
        )

    def recover(
        self, request: LifecycleInput, *, restart_safe_work: frozenset[str],
    ) -> LifecycleState:
        """Reconcile the latest checkpoint and resume at the first incomplete action.

        Completed work is restored from validated results and is not executed
        again. Recorded attempts, consumption, and elapsed time stay consumed.

        Args:
            request: Trusted caller's request text for the remaining work; it is
                not persisted and is not compared with the original request.
            restart_safe_work: Work IDs the application declares free of external
                side effects when re-executed after an interrupted attempt.

        Returns:
            The lifecycle's validated completed or safe-stop state.

        Raises:
            CheckpointNotFoundError: If no checkpoint exists for the identity.
            PersistenceError: For a corrupt, mismatched, or unreadable latest
                checkpoint; an older snapshot is never substituted.
            RecoveryError: If history cannot be reconciled with trusted inputs.
            ContractValidationError: For an invalid declaration or lifecycle state.
            Exception: Unexpected defects propagate; committed checkpoints remain.
        """
        bounds = self._runtime.bounds()
        if (
            type(restart_safe_work) is not frozenset
            or any(type(work_id) is not str for work_id in restart_safe_work)
            or not restart_safe_work.issubset(bounds.task_ids)
        ):
            raise ContractValidationError(
                "Restart-safe declaration must be a frozenset of trusted plan work IDs."
            )
        latest = self._store.load(self._identity)
        restored = reconcile(latest, self._identity, bounds, restart_safe_work)
        # Sole caller of the runtime's private resume seam: the prefix always
        # comes from the stored latest checkpoint reconciled just above.
        return self._runtime._resume_reconciled(
            request, observer=_Writer(self, latest.sequence + 1, latest.consumed_budget),
            restored=restored,
        )

    def _save(self, snapshot: BoundarySnapshot, sequence: int, carried: ConsumedBudget) -> None:
        lifecycle = snapshot.lifecycle
        task_ids = self._runtime.bounds().task_ids
        milliseconds = min(MAX_ELAPSED_MILLISECONDS, ceil(snapshot.elapsed_seconds * 1000))
        try:
            checkpoint = Checkpoint(
                schema_version=SCHEMA_VERSION,
                state_version=STATE_VERSION,
                identity=self._identity,
                sequence=sequence,
                completed_work=tuple(
                    CompletedWork(work_id=work_id, result=result.text)
                    for work_id, result in zip(
                        lifecycle.completed_task_ids, lifecycle.results, strict=True
                    )
                ),
                pending_work=task_ids[lifecycle.step_count:],
                consumed_budget=carried.model_copy(
                    update={"elapsed_milliseconds": milliseconds}
                ),
                retry_state=tuple(
                    RetrySnapshot(work_id=work_id, attempts=count)
                    for work_id, count in zip(task_ids, snapshot.attempts, strict=False)
                ),
                cancelled=lifecycle.stop_reason is StopReason.CANCELLED,
                approval_records=(),
                committed_effects=(),
            )
        except ValidationError as exc:
            raise PersistenceError(
                "Lifecycle boundary exceeds checkpoint storage bounds; progress not persisted."
            ) from exc
        self._store.save(checkpoint)


def _unmetered() -> ConsumedBudget:
    """Return zero consumption; this lifecycle meters attempts and time only."""
    return ConsumedBudget(
        tool_calls=0, provider_attempts=0, context_tokens=0, output_tokens=0,
        elapsed_milliseconds=0,
    )


class _Writer:
    """Invocation-local observer assigning one increasing sequence per boundary."""

    def __init__(
        self, owner: CheckpointedLifecycle, first_sequence: int, carried: ConsumedBudget,
    ) -> None:
        self._owner = owner
        self._sequence = first_sequence
        self._carried = carried

    def __call__(self, snapshot: BoundarySnapshot) -> None:
        self._owner._save(snapshot, self._sequence, self._carried)
        self._sequence += 1
