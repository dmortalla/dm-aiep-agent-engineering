"""Story 6 Slice 2: lifecycle checkpoints and reconciled crash recovery.

Trusted bootstrap binds a lifecycle runtime, a local checkpoint store, and an
explicit workflow identity. Checkpoints are historical claims: recovery
reconciles them against the fresh runtime's trusted plan, retry policy,
deadline, and budget before any work resumes. A checkpoint never supplies
routes, limits, permissions, callbacks, or cancellation resets.

Pure-work recovery retains version 1 semantics. Version 2 adds durable attempt
reservations and application-verified effect re-entry; ambiguous outcomes fail closed.
"""

from math import ceil

from pydantic import ValidationError

from harness_engineering.effects import (
    EffectDeclaration,
    EffectObservation,
    EffectVerificationError,
    checked_declarations,
    checked_observation,
)
from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.lifecycle_controls import checked_time
from harness_engineering.orchestration import (
    BoundarySnapshot,
    LifecycleBounds,
    LifecycleInput,
    LifecyclePhase,
    LifecycleRuntime,
    LifecycleState,
    RestoredProgress,
    StepResult,
    StopReason,
    TransientStepError,
)
from harness_engineering.persistence import (
    SCHEMA_VERSION,
    STATE_VERSION,
    Checkpoint,
    CheckpointIdentity,
    CheckpointNotFoundError,
    CommittedEffect,
    CompletedWork,
    ConsumedBudget,
    EffectCheckpoint,
    EffectIdentity,
    PersistenceError,
    RetrySnapshot,
    SQLiteCheckpointStore,
    StoredCheckpoint,
)
from harness_engineering.planning import ExecutableSubtask

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
        self,
        runtime: LifecycleRuntime,
        store: SQLiteCheckpointStore,
        identity: CheckpointIdentity,
        *,
        effects: tuple[EffectDeclaration, ...] = (),
    ) -> None:
        """Bind trusted bootstrap objects; none may come from persisted data.

        Args:
            runtime: Lifecycle built from the current accepted plan and policies.
            store: Application-selected local checkpoint store.
            identity: Explicit workflow and thread identity for this workflow.
            effects: Exact trusted application declarations, never persisted authority.
                Effect inputs must be fixed in bootstrap and independently authorized.

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
        self._effects = checked_declarations(effects, runtime.bounds().task_ids)
        if self._effects and runtime._fallback_step is not None:
            raise ContractValidationError("Effect recovery does not support fallback bindings.")

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
        if self._effects:
            session = _EffectSession(self, 0.0)
            return self._runtime._run_checkpointed_effects(
                request,
                observer=_Writer(self, 1, _unmetered(), session),
                effect_executor=session.execute,
                effect_work=frozenset(session.bindings),
            )
        return self._runtime.run_observed(
            request, observer=_Writer(self, 1, _unmetered()),
        )

    def recover(
        self,
        request: LifecycleInput,
        *,
        restart_safe_work: frozenset[str],
    ) -> LifecycleState:
        """Reconcile the latest checkpoint and resume at the first incomplete action.

        Pure completed work is restored from validated historical results. Effect
        work requires fresh application verification and reconstruction. Attempts,
        consumption, and elapsed time stay consumed; ambiguity blocks re-entry.

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
        if self._effects or isinstance(latest, EffectCheckpoint):
            return self._recover_effects(request, latest, restart_safe_work)
        restored = reconcile(latest, self._identity, bounds, restart_safe_work)
        # Sole caller of the runtime's private resume seam: the prefix always
        # comes from the stored latest checkpoint reconciled just above.
        return self._runtime._resume_reconciled(
            request, observer=_Writer(self, latest.sequence + 1, latest.consumed_budget),
            restored=restored,
        )

    def _recover_effects(
        self,
        request: LifecycleInput,
        latest: StoredCheckpoint,
        restart_safe_work: frozenset[str],
    ) -> LifecycleState:
        """Verify effects against bootstrap before using the private resume seam."""
        if not isinstance(latest, EffectCheckpoint) or not self._effects:
            raise RecoveryError(
                "Effect recovery requires version 2 history and trusted declarations."
            )
        if latest.stop_reason in {"circuit_open", "deadline_exhausted"}:
            raise RecoveryError("Persisted circuit/deadline stop remains latched during recovery.")
        if latest.sequence < sum(item.attempts for item in latest.retry_state):
            raise RecoveryError("Checkpoint sequence cannot account for reserved attempts.")
        session = _EffectSession(self, latest.consumed_budget.elapsed_milliseconds / 1000)
        expected = tuple(
            session.bindings[w] for w in self._runtime.bounds().task_ids if w in session.bindings
        )
        if latest.effect_bindings != expected:
            raise RecoveryError("Persisted effect identity conflicts with trusted declarations.")
        completed = {item.work_id: item for item in latest.completed_work}
        retries = {item.work_id: item.attempts for item in latest.retry_state}
        first = latest.pending_work[0] if latest.pending_work else None
        partial = retries.get(first, 0)
        claimed = {item.identity.work_id for item in latest.committed_effects}
        if not claimed.issubset(set(completed) | ({first} if partial else set())):
            raise RecoveryError("Commit claim refers to unattempted work.")
        normalized = _legacy_view(
            latest, drop_pending_attempt=bool(partial and first in session.bindings)
        )
        safe = restart_safe_work | frozenset(session.bindings)
        reconcile(normalized, self._identity, self._runtime.bounds(), safe)
        if partial and (
            first not in session.bindings
            or partial
            > min(
                self._runtime.bounds().max_attempts_per_action,
                self._runtime.bounds().failure_threshold,
            )
        ):
            raise RecoveryError(
                "Partially attempted work conflicts with trusted effect/retry policy."
            )
        bounds = self._runtime.bounds()
        required = 2 * len(latest.pending_work) * bounds.max_attempts_per_action
        required += len(session.bindings) + 2
        if latest.sequence + required > MAX_SEQUENCE:
            raise RecoveryError("Insufficient checkpoint capacity for verified effect recovery.")
        sequence = latest.sequence
        pending_attempts = 0
        verified_prefix = list(latest.completed_work)
        for work_id in self._runtime.bounds().task_ids:
            if work_id not in session.bindings or (work_id not in completed and work_id != first):
                continue
            if work_id == first and not partial:
                continue
            try:
                observation = session.verify(work_id)
            except (EffectVerificationError, ContractValidationError) as exc:
                self._charge_verification(latest, sequence + 1, session)
                raise RecoveryError("Effect verification failed closed.") from exc
            sequence += 1
            latest = self._charge_verification(latest, sequence, session)
            if observation.status == "committed":
                session.committed[work_id] = CommittedEffect(identity=observation.identity)
                reconstructed = CompletedWork(work_id=work_id, result=observation.result)
                if work_id in completed:
                    if completed[work_id].result != observation.result:
                        raise RecoveryError(
                            "Persisted effect result conflicts with verified result."
                        )
                    verified_prefix[list(completed).index(work_id)] = reconstructed
                else:
                    verified_prefix.append(reconstructed)
            elif work_id in completed or work_id in claimed:
                raise RecoveryError("Persisted commitment conflicts with verified noncommitment.")
            else:
                declaration = session.declarations[work_id]
                bounds = self._runtime.bounds()
                if (
                    not declaration.allow_retry
                    or latest.boundary not in {"attempt_reserved", "retry_pending"}
                    or partial >= min(bounds.max_attempts_per_action, bounds.failure_threshold)
                ):
                    raise RecoveryError(
                        "No trusted remaining attempt/circuit authority for this effect."
                    )
                pending_attempts = partial
        normalized = _legacy_view(latest, drop_pending_attempt=bool(partial))
        if len(verified_prefix) > len(normalized.completed_work):
            normalized = normalized.model_copy(
                update={
                    "completed_work": tuple(verified_prefix),
                    "pending_work": normalized.pending_work[1:],
                    "retry_state": (
                        *normalized.retry_state,
                        RetrySnapshot(work_id=first, attempts=partial),
                    ),
                }
            )
        restored = reconcile(normalized, self._identity, self._runtime.bounds(), safe)
        restored = RestoredProgress(
            restored.results,
            restored.attempts,
            session.elapsed(),
            pending_attempts,
        )
        reconciled = latest.model_copy(
            update={
                "sequence": sequence + 1,
                "completed_work": normalized.completed_work,
                "pending_work": normalized.pending_work,
                "retry_state": tuple(
                    RetrySnapshot(work_id=w, attempts=retries[w])
                    for w in bounds.task_ids
                    if w in retries
                ),
                "committed_effects": tuple(session.committed.values()),
                "boundary": "retry_pending" if pending_attempts else "step_completed",
                "stop_reason": None,
            }
        )
        self._store.save(reconciled)
        sequence += 1
        restored = RestoredProgress(
            restored.results, restored.attempts, session.elapsed(), pending_attempts,
        )
        return self._runtime._resume_reconciled(
            request,
            restored=restored,
            observer=_Writer(self, sequence + 1, latest.consumed_budget, session),
            effect_executor=session.execute,
            effect_work=frozenset(session.bindings),
        )

    def _charge_verification(
        self, latest: EffectCheckpoint, sequence: int, session: "_EffectSession",
    ) -> EffectCheckpoint:
        """Persist observed verification time before any further call or re-entry.

        No external transaction is claimed. Unexpected programming defects are
        deliberately not caught; their pre-call reservation remains recoverable.
        """
        charged = latest.model_copy(update={
            "sequence": sequence,
            "consumed_budget": latest.consumed_budget.model_copy(update={
                "elapsed_milliseconds": ceil(session.elapsed() * 1000),
            }),
        })
        self._store.save(charged)
        return charged

    def _save(
        self,
        snapshot: BoundarySnapshot,
        sequence: int,
        carried: ConsumedBudget,
        session: "_EffectSession | None" = None,
    ) -> None:
        lifecycle = snapshot.lifecycle
        task_ids = self._runtime.bounds().task_ids
        elapsed = (
            max(snapshot.elapsed_seconds, session.elapsed())
            if session else snapshot.elapsed_seconds
        )
        milliseconds = min(MAX_ELAPSED_MILLISECONDS, ceil(elapsed * 1000))
        reserved = lifecycle.phase is LifecyclePhase.EXECUTING and session is not None
        attempts = snapshot.attempts
        if reserved:
            attempts = (*attempts[: lifecycle.step_count], lifecycle.attempt_count + 1)
        if session is not None:
            for work_id, count in zip(task_ids, attempts, strict=False):
                session.reservations[work_id] = max(count, session.reservations.get(work_id, 0))
            attempts = tuple(session.reservations[w] for w in task_ids if w in session.reservations)
        extra = {}
        model = Checkpoint
        if session is not None:
            model = EffectCheckpoint
            extra = {
                "effect_bindings": tuple(
                    session.bindings[w] for w in task_ids if w in session.bindings
                ),
                "boundary": "attempt_reserved" if reserved else lifecycle.phase.value,
                "stop_reason": lifecycle.stop_reason.value if lifecycle.stop_reason else None,
            }
        try:
            checkpoint = model(
                schema_version=SCHEMA_VERSION,
                state_version=2 if session is not None else STATE_VERSION,
                identity=self._identity,
                sequence=sequence,
                completed_work=tuple(
                    CompletedWork(work_id=work_id, result=result.text)
                    for work_id, result in zip(
                        lifecycle.completed_task_ids, lifecycle.results, strict=True
                    )
                ),
                pending_work=task_ids[lifecycle.step_count :],
                consumed_budget=carried.model_copy(update={"elapsed_milliseconds": milliseconds}),
                retry_state=tuple(
                    RetrySnapshot(work_id=work_id, attempts=count)
                    for work_id, count in zip(task_ids, attempts, strict=False)
                ),
                cancelled=lifecycle.stop_reason is StopReason.CANCELLED,
                approval_records=(),
                committed_effects=tuple(session.committed.values()) if session else (),
                **extra,
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
        self,
        owner: CheckpointedLifecycle,
        first_sequence: int,
        carried: ConsumedBudget,
        session: "_EffectSession | None" = None,
    ) -> None:
        self._owner = owner
        self._sequence = first_sequence
        self._carried = carried
        self._session = session

    def __call__(self, snapshot: BoundarySnapshot) -> None:
        self._owner._save(snapshot, self._sequence, self._carried, self._session)
        self._sequence += 1


def _legacy_view(checkpoint: EffectCheckpoint, *, drop_pending_attempt: bool) -> Checkpoint:
    """Create a legacy bounds-validation view, never effect authority."""
    data = checkpoint.model_dump()
    for field in ("effect_bindings", "boundary", "stop_reason"):
        del data[field]
    data.update(state_version=1, committed_effects=())
    if drop_pending_attempt and checkpoint.pending_work:
        data["retry_state"] = tuple(
            item for item in checkpoint.retry_state if item.work_id != checkpoint.pending_work[0]
        )
    return Checkpoint.model_validate(data)


class _EffectSession:
    """Invocation-local trusted declarations, verified claims, and bounded time."""

    def __init__(self, owner: CheckpointedLifecycle, consumed: float) -> None:
        self.owner = owner
        self.started = checked_time(owner._runtime._clock)
        self.last = self.started
        self.consumed = consumed
        self.declarations = {item.spec.work_id: item for item in owner._effects}
        self.bindings: dict[str, EffectIdentity] = {
            work: item.spec.identity(owner._identity) for work, item in self.declarations.items()
        }
        self.committed: dict[str, CommittedEffect] = {}
        self.reservations: dict[str, int] = {}

    def elapsed(self) -> float:
        reading = checked_time(self.owner._runtime._clock)
        if reading < self.last:
            raise ContractValidationError("Effect verification clock regressed.")
        self.last = reading
        return self.consumed + reading - self.started

    def timeout(self, work_id: str) -> float:
        elapsed = self.elapsed()
        self.owner._runtime._recovery_guard(elapsed)
        return min(
            self.declarations[work_id].timeout_seconds,
            self.owner._runtime.bounds().deadline_seconds - elapsed,
        )

    def verify(self, work_id: str) -> EffectObservation:
        expected = self.bindings[work_id]
        timeout = self.timeout(work_id)
        started = self.elapsed()
        observation = self.declarations[work_id].verify(expected, timeout)
        if self.elapsed() - started >= timeout:
            raise EffectVerificationError("Verification exceeded its trusted timeout.")
        self.owner._runtime._recovery_guard(self.elapsed())
        return checked_observation(observation, expected)

    def execute(self, task: ExecutableSubtask, request: LifecycleInput) -> StepResult:
        work_id = task.task_id
        observed = self.verify(work_id)
        if observed.status == "committed":
            self.committed[work_id] = CommittedEffect(identity=observed.identity)
            return StepResult(text=observed.result)
        declaration = self.declarations[work_id]
        timeout = self.timeout(work_id)
        started = self.elapsed()
        try:
            result = StepResult.model_validate(
                declaration.invoke(self.bindings[work_id], timeout),
            )
            if self.elapsed() - started >= timeout:
                raise EffectVerificationError("Effect invocation exceeded its trusted timeout.")
        except TransientStepError:
            observed = self.verify(work_id)
            if observed.status == "committed":
                self.committed[work_id] = CommittedEffect(identity=observed.identity)
                return StepResult(text=observed.result)
            if not declaration.allow_retry:
                raise EffectVerificationError("Trusted declaration forbids effect retry.") from None
            raise
        observed = self.verify(work_id)
        if observed.status != "committed" or observed.result != result.text:
            raise EffectVerificationError("Effect result conflicts with commitment verification.")
        self.committed[work_id] = CommittedEffect(identity=observed.identity)
        return StepResult(text=observed.result)
