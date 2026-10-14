"""Application-owned asynchronous HITL through the accepted real LangGraph lifecycle.

Human-approved Option 1: no native interrupt, Command resume, or framework saver.
Only current bootstrap supplies plans, callbacks, human handles, safety, and an
independent workflow-age source including human wait. The accepted checkpoint
coordinator remains the sole executor/recovery bridge. This slice supports its
restart-safe version 1 path; consumed-before-execution ambiguity always stops.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from math import ceil
from typing import Literal

from pydantic import Field, ValidationError

from harness_engineering.approval_persistence import (
    ApprovalEventKind,
    ApprovalHistory,
    ApprovalNotFoundError,
    SQLiteApprovalStore,
)
from harness_engineering.approvals import (
    ActionBinding,
    ApprovalContract,
    ApprovalObservation,
    ApprovalPolicy,
    ApprovalPolicyEvaluator,
    ApprovalRequest,
    ApprovalSafetyState,
    HumanIdentity,
)
from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.lifecycle_controls import WorkflowPolicy, checked_time
from harness_engineering.orchestration import (
    BeforeStep,
    LifecycleInput,
    LifecycleRuntime,
    LifecycleState,
    RetryPolicy,
    StepExecutor,
)
from harness_engineering.persistence import (
    Checkpoint,
    CheckpointIdentity,
    CheckpointNotFoundError,
    SQLiteCheckpointStore,
)
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan, PriorityScheduler
from harness_engineering.recovery import MAX_SEQUENCE, CheckpointedLifecycle, reconcile


class ApprovalLifecycleError(HarnessError):
    """Approval re-entry cannot be safely authorized; no automatic retry is allowed."""


class SuspendedWorkflow(ApprovalContract):
    """Inert inspection references; possession never grants resume authority."""

    status: Literal["suspended"] = "suspended"
    binding: ActionBinding
    checkpoint_sequence: int = Field(ge=1, le=MAX_SEQUENCE, strict=True)
    approval_sequence: int = Field(ge=1, le=34, strict=True)


@dataclass(frozen=True)
class ApprovalAction:
    """Trusted declaration for one plan action; never deserialize from history.

    Attributes:
        request: Current action metadata and version; ID must equal plan task ID.
        observation: Confidence/evidence only, never approval authority.
        policy: Current trusted threshold/risk policy.
        approvers: Current original installed ordinary human handles.
        override_approvers: Separately installed override-capable handles.
        safety: Current scope/authorization/budget/safety facts from application sources.
    """

    request: ApprovalRequest
    observation: ApprovalObservation
    policy: ApprovalPolicy
    approvers: tuple[HumanIdentity, ...]
    override_approvers: tuple[HumanIdentity, ...]
    safety: Callable[[], ApprovalSafetyState]

    def evaluator(self) -> ApprovalPolicyEvaluator:
        """Construct current policy/authority independently of stored actor text."""
        return ApprovalPolicyEvaluator(
            self.request,
            self.policy,
            approvers=self.approvers,
            override_approvers=self.override_approvers,
        )


class _Pause(Exception):
    """Private non-framework control transfer, outside lifecycle retry classification."""

    def __init__(self, binding: ActionBinding) -> None:
        super().__init__("Application-owned human approval suspension.")
        self.binding = binding


class ApprovalLifecycle:
    """Suspend without waiting, then explicitly resume from a fresh trusted bootstrap.

    Every plan task has an explicit declaration. The workflow-age source must
    include time awaiting humans and survive reconstruction independently of
    snapshots. Callback/tool adapters retain their own capability authorization.
    No external effect-verification declaration or exactly-once execution is claimed.
    """

    def __init__(
        self,
        plan: ExecutionPlan,
        execute_step: StepExecutor,
        checkpoint_store: SQLiteCheckpointStore,
        approval_store: SQLiteApprovalStore,
        identity: CheckpointIdentity,
        actions: tuple[ApprovalAction, ...],
        *,
        restart_safe_work: frozenset[str],
        elapsed_seconds: Callable[[], float],
        clock: Callable[[], float],
        cancellation: Callable[[], bool],
        retry_policy: RetryPolicy | None = None,
        workflow_policy: WorkflowPolicy | None = None,
        fallback_step: StepExecutor | None = None,
        wait: Callable[[float], None] | None = None,
    ) -> None:
        """Bind current trusted application objects, never resume payload configuration.

        Args:
            plan: Current accepted scheduling plan.
            execute_step: Terminating trusted adapter retaining independent authorization.
            checkpoint_store: Existing application-owned checkpoint file.
            approval_store: Accepted dedicated durable approval store.
            identity: Explicit trusted workflow/thread identity.
            actions: One current declaration per exact task, with original human handles.
            restart_safe_work: Explicit restart-safe work; this slice excludes effect sessions.
            elapsed_seconds: Trusted total workflow age including human wait, not a reset timer.
            clock: Current application monotonic execution clock.
            cancellation: Current trusted one-way off-switch source.
            retry_policy: Existing bounded retries; approval allows only one action entry.
            workflow_policy: Optional tightening of the accepted workflow deadline.
            fallback_step: Existing trusted fallback; it cannot reuse consumed approval.
            wait: Optional trusted backoff implementation, never a human wait/poll operation.

        Raises:
            ContractValidationError: For invalid, incomplete, or unsupported bootstrap declarations.
        """
        if (
            not isinstance(checkpoint_store, SQLiteCheckpointStore)
            or type(approval_store) is not SQLiteApprovalStore
            or not callable(elapsed_seconds)
        ):
            raise ContractValidationError(
                "Bind trusted stores and an independent workflow-age source."
            )
        try:
            self._identity = CheckpointIdentity.model_validate(identity)
            checked_plan = ExecutionPlan.model_validate(plan)
        except ValidationError as exc:
            raise ContractValidationError("Invalid approval lifecycle identity/plan.") from exc
        order = PriorityScheduler(checked_plan).deterministic_order()
        ids = frozenset(task.task_id for task in order)
        if (
            type(restart_safe_work) is not frozenset
            or restart_safe_work != ids
            or type(actions) is not tuple
            or len(actions) != len(order)
        ):
            raise ContractValidationError(
                "Provide one declaration per task and explicitly declare all work restart-safe."
            )
        declarations: dict[str, ApprovalAction] = {}
        for action in actions:
            if type(action) is not ApprovalAction or not callable(action.safety):
                raise ContractValidationError(
                    "Bind application-owned approval declarations/safety sources."
                )
            try:
                current = replace(
                    action,
                    request=ApprovalRequest.model_validate(action.request),
                    observation=ApprovalObservation.model_validate(action.observation),
                    policy=ApprovalPolicy.model_validate(action.policy),
                )
            except ValidationError as exc:
                raise ContractValidationError("Malformed approval action declaration.") from exc
            current.evaluator()  # Validate allowlists without copying/minting human handles.
            binding = current.request.binding
            if (
                binding.workflow_id != self._identity.workflow_id
                or binding.thread_id != self._identity.thread_id
                or binding.pending_action_id not in ids
                or binding.pending_action_id in declarations
            ):
                raise ContractValidationError(
                    "Approval declarations must uniquely match workflow/tasks."
                )
            declarations[binding.pending_action_id] = current
        self._actions = declarations
        self._tasks = {task.task_id: task for task in order}
        self._checkpoints = checkpoint_store
        self._approvals = approval_store
        self._elapsed_source = elapsed_seconds
        self._last_elapsed = 0.0
        self._safe_work = restart_safe_work
        self._permit: ActionBinding | None = None
        self._actor: HumanIdentity | None = None
        self._entered = False
        self._active = False
        self._invoked = False
        options = {} if wait is None else {"wait": wait}
        gate: BeforeStep = self._gate
        self._runtime = LifecycleRuntime(
            checked_plan,
            execute_step,
            retry_policy=retry_policy,
            workflow_policy=workflow_policy,
            fallback_step=fallback_step,
            clock=clock,
            cancellation=cancellation,
            before_step=gate,
            **options,
        )
        self._coordinator = CheckpointedLifecycle(self._runtime, checkpoint_store, self._identity)

    def _elapsed(self, checkpoint: Checkpoint | None = None) -> float:
        value = checked_time(self._elapsed_source)
        minimum = self._last_elapsed
        if checkpoint is not None:
            minimum = max(minimum, checkpoint.consumed_budget.elapsed_milliseconds / 1000)
        rounded = ceil(value * 1000) / 1000
        if value < 0 or rounded < minimum:
            raise ApprovalLifecycleError(
                "Trusted workflow age regressed; deadline cannot be reset."
            )
        self._last_elapsed = rounded
        try:
            self._runtime._recovery_guard(rounded)
        except ContractValidationError:
            if checkpoint is not None and self._runtime._off_switch.is_active():
                self._record_cancellation(checkpoint)
            raise
        return rounded

    def _record_cancellation(self, checkpoint: Checkpoint) -> None:
        if not checkpoint.cancelled:
            self._checkpoints.save(
                checkpoint.model_copy(
                    update={"sequence": checkpoint.sequence + 1, "cancelled": True}
                )
            )

    def _latest(self) -> Checkpoint:
        latest = self._checkpoints.load(self._identity)
        if type(latest) is not Checkpoint:
            raise ApprovalLifecycleError(
                "This approval boundary supports restart-safe version 1 history only."
            )
        return latest

    def _safety(self, action: ApprovalAction) -> ApprovalSafetyState:
        value = action.safety()
        if type(value) is not ApprovalSafetyState:
            raise ContractValidationError("Current safety source must return ApprovalSafetyState.")
        try:
            return ApprovalSafetyState.model_validate(value)
        except ValidationError as exc:
            raise ContractValidationError("Malformed current approval safety facts.") from exc

    @staticmethod
    def _input(value: LifecycleInput) -> LifecycleInput:
        if type(value) is not LifecycleInput:
            raise ContractValidationError(
                "Workflow input accepts only explicit LifecycleInput data."
            )
        try:
            return LifecycleInput.model_validate(value)
        except ValidationError as exc:
            raise ContractValidationError(
                "Malformed workflow input; no approval was consumed."
            ) from exc

    def _observation(
        self, action: ApprovalAction, task: ExecutableSubtask, request: LifecycleInput
    ) -> ApprovalObservation:
        # Digest binds exact callback inputs; it is equality evidence, not a signature.
        encoded = json.dumps(
            {"task": task.model_dump(mode="json"), "input": request.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        evidence = json.dumps(
            {
                "contract": "approval-input-v1",
                "digest": hashlib.sha256(encoded).hexdigest(),
                "evidence": action.observation.evidence,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            return ApprovalObservation(confidence=action.observation.confidence, evidence=evidence)
        except ValidationError as exc:
            raise ContractValidationError(
                "Approval evidence plus input binding exceeds its bound."
            ) from exc

    @staticmethod
    def _matches(
        history: ApprovalHistory, action: ApprovalAction, observation: ApprovalObservation
    ) -> None:
        pending = next(
            event.requested for event in reversed(history.events) if event.requested is not None
        )
        if pending.request != action.request or pending.observation != observation:
            raise ApprovalLifecycleError(
                "Current exact action/input differs from durable approval request."
            )

    def _gate(self, task: ExecutableSubtask, request: LifecycleInput) -> None:
        if not self._active:
            raise ApprovalLifecycleError("Use the application-owned start/resume boundary.")
        latest = self._latest()
        if not latest.pending_work or latest.pending_work[0] != task.task_id:
            raise ApprovalLifecycleError(
                "Scheduled action differs from the latest checkpoint boundary."
            )
        self._elapsed(latest)
        action = self._actions[task.task_id]
        observed = self._observation(action, task, request)
        evaluator = action.evaluator()
        assessment = evaluator.evaluate(observed, safety=self._safety(action))
        if assessment.hard_stops:
            raise ApprovalLifecycleError("Current hard safety prevents action execution.")
        try:
            history = self._approvals.load(action.request.binding)
        except ApprovalNotFoundError:
            if not assessment.approval_required:
                return
            self._approvals.request(evaluator, observed, safety=self._safety(action))
            raise _Pause(action.request.binding) from None
        self._matches(history, action, observed)
        if history.prior_denial:
            raise ApprovalLifecycleError("Durable human denial is terminal for this action.")
        if history.status is ApprovalEventKind.CONSUMED:
            if self._permit != action.request.binding or self._entered:
                raise ApprovalLifecycleError(
                    "Approval consumed: replay or execution outcome is ambiguous."
                )
            prior = history.events[-1].decided
            evaluator.check_decision(
                prior.decision, actor=self._actor, observation=observed, safety=self._safety(action)
            )
            self._entered = True  # One entry only, including retry/fallback attempts.
            return
        # Even an approved historical record does not grant execution without explicit resume.
        raise _Pause(action.request.binding)

    def _invoke(
        self, request: LifecycleInput, *, recovering: bool
    ) -> LifecycleState | SuspendedWorkflow:
        if self._active or self._invoked:
            raise ApprovalLifecycleError(
                "Each invocation requires a fresh lifecycle/bootstrap instance."
            )
        self._invoked = True
        self._active = True
        try:
            if recovering:
                return self._coordinator.recover(request, restart_safe_work=self._safe_work)
            return self._coordinator.run(request)
        except _Pause as pause:
            latest = self._latest()
            history = self._approvals.load(pause.binding)
            if (
                not latest.pending_work
                or latest.pending_work[0] != pause.binding.pending_action_id
                or history.status
                not in (
                    ApprovalEventKind.PENDING,
                    ApprovalEventKind.APPROVED,
                    ApprovalEventKind.OVERRIDDEN,
                )
            ):
                raise ApprovalLifecycleError(
                    "Suspension is not a coherent durable pending boundary."
                ) from pause
            return SuspendedWorkflow(
                binding=pause.binding,
                checkpoint_sequence=latest.sequence,
                approval_sequence=history.events[-1].sequence,
            )
        finally:
            self._active = False
            self._permit = None
            self._actor = None
            self._entered = False
            if self._runtime._off_switch.is_active():
                self._record_cancellation(self._latest())

    def start(self, request: LifecycleInput) -> LifecycleState | SuspendedWorkflow:
        """Start through real orchestration; return suspension without waiting for a human.

        Args:
            request: Inert workflow text; exact callback inputs bind any approval request.

        Returns:
            Completed/safe-stop lifecycle data or durable suspended references.

        Raises:
            HarnessError: For invalid configuration, unsafe state, or failed persistence.
            Exception: Unexpected programming defects propagate.
        """
        data = self._input(request)
        self._elapsed()
        return self._invoke(data, recovering=False)

    def resume(
        self, request: LifecycleInput, *, actor: HumanIdentity | None
    ) -> LifecycleState | SuspendedWorkflow:
        """Reconcile fresh state, check current authority, consume once, and explicitly continue.

        Args:
            request: Exact current callback input data, not a suspended result/framework Command.
            actor: Current independently installed approving/overriding human handle.

        Returns:
            Actual lifecycle outcome or suspension at the next independently evaluated action.

        Raises:
            HarnessError: For pending/missing/denied/stale/consumed approval, changed action,
                revoked authority, unsafe/budget/deadline state, or ambiguous recovery.
            Exception: Unexpected defects propagate; consumption is never automatically replayed.
        """
        if self._active or self._invoked:
            raise ApprovalLifecycleError(
                "Resume requires a fresh lifecycle/current-authority bootstrap."
            )
        data = self._input(request)
        latest = self._latest()
        reconcile(latest, self._identity, self._runtime.bounds(), self._safe_work)
        if not latest.pending_work:
            raise ApprovalLifecycleError("No incomplete action remains to resume.")
        task_id = latest.pending_work[0]
        action = self._actions[task_id]
        binding = action.request.binding
        history = self._approvals.load(binding)
        if history.status not in (ApprovalEventKind.APPROVED, ApprovalEventKind.OVERRIDDEN):
            raise ApprovalLifecycleError(
                "Resume requires an unconsumed accepted approval; denial is terminal."
            )
        observed = self._observation(action, self._tasks[task_id], data)
        self._matches(history, action, observed)
        age = self._elapsed(latest)
        current_safety = self._safety(action)
        evaluator = action.evaluator()
        prior = history.events[-1].decided
        checked = evaluator.check_decision(
            prior.decision, actor=actor, observation=observed, safety=current_safety
        )
        previous = prior.assessment
        current = checked.assessment
        if current.confidence_threshold > previous.confidence_threshold or not set(
            current.triggers
        ).issubset(previous.triggers):
            raise ApprovalLifecycleError(
                "Current policy tightened; historical decision is insufficient."
            )
        # Gate observation adds at most one write per attempt to accepted checkpoint behavior.
        required = 2 * len(latest.pending_work) * self._runtime.bounds().max_attempts_per_action + 2
        if latest.sequence + required > MAX_SEQUENCE:
            raise ApprovalLifecycleError(
                "Insufficient checkpoint capacity for bounded approval re-entry."
            )
        charged = latest.model_copy(
            update={
                "sequence": latest.sequence + 1,
                "consumed_budget": latest.consumed_budget.model_copy(
                    update={"elapsed_milliseconds": ceil(age * 1000)}
                ),
            }
        )
        self._checkpoints.save(charged)
        self._elapsed(charged)
        self._approvals.consume(
            binding, evaluator=evaluator, actor=actor, safety=self._safety(action)
        )
        self._permit = binding
        self._actor = actor
        self._entered = False
        return self._invoke(data, recovering=True)

    def cancel(self) -> None:
        """Latch the off-switch and record cancellation if checkpoint history exists.

        Raises:
            HarnessError: If known history cannot be safely loaded or cancellation persisted.
                The in-memory switch remains active even if persistence fails.
        """
        self._runtime.cancel()
        if self._active:
            return  # Let the active writer retain completed work before recording the stop.
        try:
            latest = self._latest()
        except CheckpointNotFoundError:
            return  # No started durable workflow exists; the current runtime remains latched.
        self._record_cancellation(latest)
