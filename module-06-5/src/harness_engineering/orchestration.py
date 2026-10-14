"""Story 5 Slice 1: application-owned finite LangGraph lifecycle.

Bootstrap owns the validated plan and synchronous local step executor. Never
deserialize bootstrap bindings from generated content. The public run boundary
accepts data only, not graph state, config, commands, permissions, or node names.
Tool adapters must retain BoundedToolExecutor's independent authorization.
Slice 2 adds bounded retries/backoff and a workflow-local circuit breaker.
Slice 3 adds finite fallback, workflow deadlines, and application cancellation.
Story 6 Slice 2 adds public boundary observation. Resuming from a restored
prefix is not part of the public API: only the recovery coordinator invokes the
private resume seam, after reconciling a stored checkpoint. Story 6 Slice 3
adds private effect execution and pre-invocation reservation seams.
Trusted executors must terminate; graph bounds do not preempt Python callbacks.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from time import monotonic, sleep
from typing import Annotated, Self, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    ContractValidationError,
    HarnessError,
    ToolExecutionError,
)
from harness_engineering.lifecycle_controls import (
    OffSwitch,
    RunControls,
    WorkflowPolicy,
    checked_time,
)
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan, PriorityScheduler


class LifecyclePhase(StrEnum):
    """Finite application phases; no generated routing discriminator exists."""

    PENDING = "pending"
    EXECUTING = "executing"
    RETRY_PENDING = "retry_pending"
    STEP_COMPLETED = "step_completed"
    COMPLETED = "completed"
    SAFE_STOP = "safe_stop"


class StopReason(StrEnum):
    """Explicit terminal reason owned by application execution policy."""

    STEP_FAILURE = "step_failure"
    RETRIES_EXHAUSTED = "retries_exhausted"
    CIRCUIT_OPEN = "circuit_open"
    PREFERRED_UNAVAILABLE = "preferred_unavailable"
    DEADLINE_EXHAUSTED = "deadline_exhausted"
    CANCELLED = "cancelled"


class TransientStepError(ToolExecutionError):
    """Trusted adapter's explicit retry-safe transient failure classification.

    Never classify from generated text or wrap arbitrary errors in this type.
    Only raise when another attempt is safe, including any possible side effects.
    Generic ToolExecutionError (which can wrap defects) is not retryable.
    """


class PreferredPathUnavailable(TransientStepError):
    """Trusted adapter classifies a retry-safe unavailable preferred path.

    This is circuit-qualifying, never inferred from generated data. It may
    select the sole bootstrap fallback only while attempt budget remains.
    Do not wrap programming defects or authority/safety denials in this type.
    """


class RetryPolicy(BaseModel):
    """Immutable bootstrap-only retry/backoff and circuit threshold policy."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    max_retries: int = Field(default=2, ge=0, le=2, strict=True)
    initial_delay_seconds: float = Field(
        default=0.1, gt=0, le=30, allow_inf_nan=False, strict=True
    )
    max_delay_seconds: float = Field(default=1.0, gt=0, le=30, allow_inf_nan=False, strict=True)
    failure_threshold: int = Field(default=3, ge=1, le=300, strict=True)

    @model_validator(mode="after")
    def validate_delay_bounds(self) -> Self:
        """Require the initial delay to fit the application delay cap."""
        if self.initial_delay_seconds > self.max_delay_seconds:
            raise ValueError("Initial backoff must not exceed the delay cap.")
        return self

    def delay(self, retry_number: int) -> float:
        """Calculate capped exponential backoff without waiting.

        Args:
            retry_number: One-based retry number, at most max_retries.

        Returns:
            min(max_delay_seconds, initial_delay_seconds * 2**(retry_number - 1)).

        Raises:
            ContractValidationError: For invalid policy or retry number.
        """
        try:
            checked = RetryPolicy.model_validate(self)
        except ValidationError as exc:
            raise ContractValidationError("Invalid retry policy.") from exc
        if type(retry_number) is not int or not 1 <= retry_number <= checked.max_retries:
            raise ContractValidationError("Backoff requires an enabled one-based retry number.")
        return min(
            checked.max_delay_seconds, checked.initial_delay_seconds * 2 ** (retry_number - 1)
        )


class CircuitPhase(StrEnum):
    """Finite circuit states; open remains latched for the current run."""

    CLOSED = "closed"
    OPEN = "open"


class CircuitState(BaseModel):
    """Immutable application-owned consecutive transient-failure counter."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    phase: CircuitPhase = CircuitPhase.CLOSED
    consecutive_failures: int = Field(default=0, ge=0, le=300, strict=True)

    def checked(self, threshold: int) -> "CircuitState":
        """Validate state against a trusted threshold; reject forged instances."""
        if type(threshold) is not int or not 1 <= threshold <= 300:
            raise ContractValidationError("Circuit threshold must be an integer from 1 to 300.")
        try:
            value = CircuitState.model_validate(self)
        except ValidationError as exc:
            raise ContractValidationError("Malformed circuit state.") from exc
        if (value.phase is CircuitPhase.OPEN) != (value.consecutive_failures >= threshold):
            raise ContractValidationError("Circuit phase conflicts with its failure threshold.")
        if value.consecutive_failures > threshold:
            raise ContractValidationError("Open circuit failure counter must latch at threshold.")
        return value

    def require_closed(self, threshold: int) -> None:
        """Deny an attempt before execution if the application circuit is open."""
        if self.checked(threshold).phase is CircuitPhase.OPEN:
            raise AuthorityViolationError("Circuit is open; further execution is blocked.")

    def failed(self, threshold: int) -> "CircuitState":
        """Count one qualifying transient failure, opening exactly at threshold."""
        self.require_closed(threshold)
        count = self.consecutive_failures + 1
        return CircuitState(
            phase=CircuitPhase.OPEN if count == threshold else CircuitPhase.CLOSED,
            consecutive_failures=count,
        )

    def succeeded(self, threshold: int) -> "CircuitState":
        """Reset consecutive failures on validated success; never reset open state."""
        self.require_closed(threshold)
        return CircuitState()


class LifecycleInput(BaseModel):
    """Bounded untrusted contextual data with no authority fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    text: str = Field(default="", max_length=20_000, strict=True)


class StepResult(BaseModel):
    """Validated step data; text never controls graph routing."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    text: str = Field(max_length=20_000, strict=True)


_LEGAL_TRANSITIONS = {
    LifecyclePhase.PENDING: frozenset({LifecyclePhase.EXECUTING}),
    LifecyclePhase.EXECUTING: frozenset(
        {LifecyclePhase.STEP_COMPLETED, LifecyclePhase.SAFE_STOP, LifecyclePhase.RETRY_PENDING}
    ),
    LifecyclePhase.RETRY_PENDING: frozenset({
        LifecyclePhase.EXECUTING, LifecyclePhase.SAFE_STOP
    }),
    LifecyclePhase.STEP_COMPLETED: frozenset(
        {LifecyclePhase.EXECUTING, LifecyclePhase.COMPLETED, LifecyclePhase.SAFE_STOP}
    ),
    LifecyclePhase.COMPLETED: frozenset(),
    LifecyclePhase.SAFE_STOP: frozenset(),
}


class LifecycleState(BaseModel):
    """Immutable internal lifecycle snapshot, never accepted as run input."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    phase: LifecyclePhase = LifecyclePhase.PENDING
    completed_task_ids: tuple[str, ...] = Field(default=(), max_length=100)
    results: tuple[StepResult, ...] = Field(default=(), max_length=100)
    step_count: int = Field(default=0, ge=0, le=100, strict=True)
    stop_reason: StopReason | None = None
    blocked_execution: bool = Field(default=False, strict=True)
    fallback_task_ids: tuple[str, ...] = Field(default=(), max_length=100)
    fallback_activation_attempts: tuple[Annotated[int, Field(ge=1, le=300, strict=True)], ...] = (
        Field(default=(), max_length=100)
    )
    attempt_count: int = Field(default=0, ge=0, le=3, strict=True)
    total_attempts: int = Field(default=0, ge=0, le=300, strict=True)
    circuit: CircuitState = Field(default_factory=CircuitState)
    backoff_delays: tuple[
        Annotated[float, Field(gt=0, le=30, allow_inf_nan=False, strict=True)], ...
    ] = Field(default=(), max_length=200)
    history: tuple[LifecyclePhase, ...] = Field(
        default=(LifecyclePhase.PENDING,), min_length=1, max_length=602
    )

    @model_validator(mode="after")
    def validate_progression(self) -> Self:
        """Reject inconsistent counters, illegal histories, and terminal claims."""
        if self.step_count != len(self.completed_task_ids) or self.step_count != len(self.results):
            raise ValueError("Step counter must match completed tasks and validated results.")
        if len(set(self.completed_task_ids)) != self.step_count:
            raise ValueError("Tasks cannot complete more than once.")
        if self.history[0] is not LifecyclePhase.PENDING or self.history[-1] is not self.phase:
            raise ValueError("History must start pending and end at the current phase.")
        for before, after in zip(self.history, self.history[1:], strict=False):
            if after not in _LEGAL_TRANSITIONS[before]:
                raise ValueError("Illegal lifecycle transition.")
        if self.history.count(LifecyclePhase.STEP_COMPLETED) != self.step_count:
            raise ValueError("Step count must match observed successful transitions.")
        scheduled = self.history.count(LifecyclePhase.EXECUTING)
        if scheduled != (self.total_attempts + int(self.phase is LifecyclePhase.EXECUTING)
                         + int(self.blocked_execution)):
            raise ValueError("Total attempts must match executed lifecycle transitions.")
        if len(self.backoff_delays) != self.history.count(LifecyclePhase.RETRY_PENDING):
            raise ValueError("Backoff records must match retry transitions.")
        if self.blocked_execution and (
            self.phase is not LifecyclePhase.SAFE_STOP
            or self.stop_reason not in {StopReason.CANCELLED, StopReason.DEADLINE_EXHAUSTED}
            or len(self.history) < 2
            or self.history[-2] is not LifecyclePhase.EXECUTING
        ):
            raise ValueError("Only an uninvoked execution may carry a blocked marker.")
        if self.attempt_count > self.total_attempts:
            raise ValueError("Action attempts cannot exceed total attempts.")
        if (self.phase is LifecyclePhase.SAFE_STOP) != (self.stop_reason is not None):
            raise ValueError("Only safe-stop state must carry a stop reason.")
        return self


@dataclass(frozen=True)
class LifecycleBounds:
    """Trusted bootstrap limits exposed read-only for recovery reconciliation.

    Attributes:
        task_ids: Accepted work in deterministic application scheduling order.
        max_attempts_per_action: Retry policy attempts allowed for one action.
        failure_threshold: Consecutive transient failures that open the circuit.
        deadline_seconds: Effective workflow deadline, never above the plan's.
        budget: Accepted plan budget carrying tool, provider, and token limits.
    """

    task_ids: tuple[str, ...]
    max_attempts_per_action: int
    failure_threshold: int
    deadline_seconds: float
    budget: RuntimeBudget


@dataclass(frozen=True)
class BoundarySnapshot:
    """Validated lifecycle state observed at a coherent application boundary.

    Attributes:
        lifecycle: State already checked against trusted plan and policy.
        attempts: Consumed attempts per action in scheduling order, covering
            each completed action and any partially attempted current action.
        elapsed_seconds: Workflow time consumed, including restored consumption.
    """

    lifecycle: LifecycleState
    attempts: tuple[int, ...]
    elapsed_seconds: float


@dataclass(frozen=True)
class RestoredProgress:
    """Inert result of recovery reconciliation; constructing one grants nothing.

    No public runtime method accepts this type. Only the recovery coordinator
    passes it to the private resume seam, after reconciling a stored checkpoint.
    It carries no work identifiers, routes, limits, or policy. The runtime maps
    the prefix onto its own trusted scheduling order and rebuilds its state.

    Attributes:
        results: Validated result for each completed action, in order.
        attempts: Attempts each completed action consumed, in the same order.
        elapsed_seconds: Workflow time already consumed before this invocation.
        pending_attempts: Conservatively consumed attempts on verified noncommitted
            effect work; recovery retains these as circuit-qualifying failures.
    """

    results: tuple[StepResult, ...]
    attempts: tuple[int, ...]
    elapsed_seconds: float
    pending_attempts: int = 0


BoundaryObserver = Callable[[BoundarySnapshot], None]


class _GraphState(TypedDict):
    lifecycle: LifecycleState
    request: LifecycleInput
    controls: RunControls
    observer: BoundaryObserver | None
    effect_executor: "StepExecutor | None"
    effect_work: frozenset[str]


StepExecutor = Callable[[ExecutableSubtask, LifecycleInput], StepResult]
BeforeStep = Callable[[ExecutableSubtask, LifecycleInput], None]


class LifecycleRuntime:
    """Compile and invoke bounded scheduling with application-owned routing."""

    def __init__(
        self, plan: ExecutionPlan, execute_step: StepExecutor, *,
        retry_policy: RetryPolicy | None = None,
        wait: Callable[[float], None] = sleep,
        fallback_step: StepExecutor | None = None,
        workflow_policy: WorkflowPolicy | None = None,
        clock: Callable[[], float] = monotonic,
        cancellation: Callable[[], bool] | None = None,
        before_step: BeforeStep | None = None,
    ) -> None:
        """Bind trusted application configuration, never contextual authority.

        Args:
            plan: Application-accepted plan, snapshotted and fully revalidated.
            execute_step: Trusted terminating local adapter. Tool execution must
                independently authorize through the accepted tool executor.
            retry_policy: Trusted bootstrap policy; no more than two retries.
            fallback_step: Sole trusted fallback; shares retry budget and circuit.
            workflow_policy: May tighten but never exceed the accepted plan deadline.
                When omitted, derive from the plan with a 180-second ceiling.
            clock: Trusted monotonic clock, injectable without real waiting.
            cancellation: Trusted bool source. Failure aborts; activation latches.
            before_step: Optional application gate outside retry/error classification.
                Observed runs persist a pre-attempt boundary before calling it.
                This seam supports restart-safe work, not effect-session reservations.
            wait: Trusted waiting implementation. Inject a recorder for deterministic
                tests; normal execution uses sleep. Exceptions abort without retry.

        Raises:
            ContractValidationError: For malformed bootstrap configuration.
        """
        if not callable(execute_step) or not isinstance(plan, ExecutionPlan):
            raise ContractValidationError("Bind a validated plan and callable step executor.")
        try:
            snapshot = ExecutionPlan.model_validate(plan.model_dump())
            self._retry_policy = RetryPolicy.model_validate(
                retry_policy if retry_policy is not None else RetryPolicy(
                    max_retries=min(2, snapshot.budget.max_retries_per_action)
                )
            )
        except ValidationError as exc:
            raise ContractValidationError("Invalid lifecycle plan.") from exc
        if self._retry_policy.max_retries > snapshot.budget.max_retries_per_action:
            raise ContractValidationError("Retry policy exceeds the accepted plan budget.")
        if not callable(wait):
            raise ContractValidationError("Bind a callable application waiting implementation.")
        try:
            self._workflow_policy = WorkflowPolicy.model_validate(
                workflow_policy if workflow_policy is not None else WorkflowPolicy(
                    deadline_seconds=min(
                        snapshot.budget.workflow_deadline_seconds,
                        WorkflowPolicy().deadline_seconds,
                    )
                )
            )
        except ValidationError as exc:
            raise ContractValidationError("Invalid workflow deadline policy.") from exc
        if self._workflow_policy.deadline_seconds > snapshot.budget.workflow_deadline_seconds:
            raise ContractValidationError(
                "Workflow deadline policy exceeds the accepted plan budget."
            )
        if fallback_step is not None and not callable(fallback_step):
            raise ContractValidationError("Fallback must be a trusted callable or absent.")
        if not callable(clock) or (cancellation is not None and not callable(cancellation)):
            raise ContractValidationError("Bind callable clock and cancellation sources.")
        if before_step is not None and not callable(before_step):
            raise ContractValidationError("Before-step gate must be a trusted callable or absent.")
        self._before_step = before_step
        self._fallback_step = fallback_step
        self._clock = clock
        self._off_switch = OffSwitch()
        self._cancellation = (
            cancellation if cancellation is not None else self._off_switch.is_active
        )
        self._wait = wait
        self._tasks = PriorityScheduler(snapshot).deterministic_order()
        self._budget = snapshot.budget
        self._execute_step = execute_step
        self._task_ids = tuple(task.task_id for task in self._tasks)
        graph = StateGraph(_GraphState)
        graph.add_node("schedule", self._schedule)
        graph.add_node("execute", self._execute)
        graph.add_node("retry", self._retry)
        graph.add_node("complete", self._complete)
        graph.add_node("safe_stop", self._safe_stop)
        graph.add_edge(START, "schedule")
        graph.add_conditional_edges(
            "schedule", self._route_scheduled,
            {LifecyclePhase.EXECUTING: "execute", LifecyclePhase.COMPLETED: "complete",
             LifecyclePhase.SAFE_STOP: "safe_stop"},
        )
        graph.add_conditional_edges(
            "execute", self._route_executed,
            {LifecyclePhase.STEP_COMPLETED: "schedule", LifecyclePhase.SAFE_STOP: "safe_stop",
             LifecyclePhase.RETRY_PENDING: "retry"},
        )
        graph.add_conditional_edges(
            "retry", self._route_scheduled,
            {LifecyclePhase.EXECUTING: "execute", LifecyclePhase.SAFE_STOP: "safe_stop"},
        )
        graph.add_edge("complete", END)
        graph.add_edge("safe_stop", END)
        self._graph = graph.compile()

    def run(self, request: LifecycleInput) -> LifecycleState:
        """Invoke the real compiled graph from fresh application state.

        Args:
            request: Untrusted text; extra authority or routing fields fail closed.

        Returns:
            A validated completed or safe-stop snapshot with observed progression.

        Raises:
            ContractValidationError: For invalid input or lifecycle invariants.
            Exception: Unexpected adapter/framework defects propagate without retry.
        """
        return self._invoke(request, LifecycleState(), 0.0, None)

    def bounds(self) -> LifecycleBounds:
        """Return trusted bootstrap limits for reconciling persisted history.

        Returns:
            Immutable copies of application-owned order and limits. Nothing in
            the result can be written back to change runtime authority.
        """
        return LifecycleBounds(
            task_ids=self._task_ids,
            max_attempts_per_action=self._retry_policy.max_retries + 1,
            failure_threshold=self._retry_policy.failure_threshold,
            deadline_seconds=self._workflow_policy.deadline_seconds,
            budget=self._budget,
        )

    def run_observed(
        self, request: LifecycleInput, *, observer: BoundaryObserver,
    ) -> LifecycleState:
        """Invoke the same compiled graph from fresh state, reporting boundaries.

        Like run(), this always starts from fresh application state. It accepts
        no prior progress, completed work, or restored state of any kind. The
        observer runs after each consumed attempt and at each cancellation or
        deadline stop; its exceptions abort the run.

        Args:
            request: Untrusted text; extra authority or routing fields fail closed.
            observer: Trusted callable receiving validated boundary snapshots.

        Returns:
            A validated completed or safe-stop snapshot with observed progression.

        Raises:
            ContractValidationError: For invalid input, a non-callable observer,
                or violated lifecycle invariants.
            Exception: Unexpected adapter, observer, or framework defects propagate.
        """
        if not callable(observer):
            raise ContractValidationError("Bind a callable trusted boundary observer.")
        return self._invoke(request, LifecycleState(), 0.0, observer)

    def _resume_reconciled(
        self,
        request: LifecycleInput,
        *,
        observer: BoundaryObserver,
        restored: RestoredProgress,
        effect_executor: StepExecutor | None = None,
        effect_work: frozenset[str] = frozenset(),
    ) -> LifecycleState:
        """Resume after a reconciled completed prefix; private to recovery.

        Not a supported application entry point. The sole intended caller is
        CheckpointedLifecycle.recover, which first loads the latest stored
        checkpoint and reconciles it against this runtime's bounds. The prefix
        is still rebuilt and fully validated here against the trusted plan,
        order, and policy; the workflow deadline is reduced by consumed time.

        Raises:
            ContractValidationError: For invalid input, an invalid restored
                prefix, or violated lifecycle invariants.
        """
        if not callable(observer):
            raise ContractValidationError("Bind a callable trusted boundary observer.")
        if type(restored) is not RestoredProgress:
            raise ContractValidationError("Restored progress must come from trusted recovery.")
        elapsed = restored.elapsed_seconds
        if type(elapsed) is not float or not isfinite(elapsed) or elapsed < 0:
            raise ContractValidationError("Restored elapsed time must be finite and non-negative.")
        return self._invoke(
            request,
            self._restored(restored),
            elapsed,
            observer,
            effect_executor,
            effect_work,
        )

    def _run_checkpointed_effects(
        self,
        request: LifecycleInput,
        *,
        observer: BoundaryObserver,
        effect_executor: StepExecutor,
        effect_work: frozenset[str],
    ) -> LifecycleState:
        """Private fresh invocation seam for the store-backed effect coordinator."""
        return self._invoke(request, LifecycleState(), 0.0, observer, effect_executor, effect_work)

    def _recovery_guard(self, consumed_seconds: float) -> None:
        """Check current trusted cancellation and deadline before verification."""
        now = checked_time(self._clock)
        reason = self._control_reason({"controls": RunControls(now - consumed_seconds, now)})
        if reason is not None:
            raise ContractValidationError(f"Effect recovery blocked by {reason.value}.")

    def _invoke(
        self,
        request: LifecycleInput,
        lifecycle: LifecycleState,
        consumed_seconds: float,
        observer: BoundaryObserver | None,
        effect_executor: StepExecutor | None = None,
        effect_work: frozenset[str] = frozenset(),
    ) -> LifecycleState:
        try:
            checked = LifecycleInput.model_validate(request)
        except ValidationError as exc:
            raise ContractValidationError("Lifecycle input accepts bounded text only.") from exc
        now = checked_time(self._clock)
        output = self._graph.invoke(
            {
                "lifecycle": lifecycle,
                "request": checked,
                "controls": RunControls(now - consumed_seconds, now),
                "observer": observer,
                "effect_executor": effect_executor,
                "effect_work": effect_work,
            },
            config={
                "recursion_limit": (2 + 2 * self._retry_policy.max_retries) * len(self._tasks) + 3
            },
        )
        result = self._checked(output)
        if result.phase not in {LifecyclePhase.COMPLETED, LifecyclePhase.SAFE_STOP}:
            raise ContractValidationError("Graph did not reach a terminal outcome.")
        return result

    def _restored(self, restored: RestoredProgress) -> LifecycleState:
        """Rebuild a completed-prefix state from trusted order and policy only."""
        results, attempts = restored.results, restored.attempts
        if (type(results) is not tuple or type(attempts) is not tuple
                or len(results) != len(attempts) or len(results) > len(self._tasks)):
            raise ContractValidationError("Restored prefix conflicts with the trusted plan.")
        policy = self._retry_policy
        history = [LifecyclePhase.PENDING]
        delays: list[float] = []
        for count in attempts:
            if (type(count) is not int or not 1 <= count <= policy.max_retries + 1
                    or count > policy.failure_threshold):
                raise ContractValidationError(
                    "Restored attempts are impossible under trusted retry policy."
                )
            for retry_number in range(1, count):
                history += [LifecyclePhase.EXECUTING, LifecyclePhase.RETRY_PENDING]
                delays.append(policy.delay(retry_number))
            history += [LifecyclePhase.EXECUTING, LifecyclePhase.STEP_COMPLETED]
        pending = restored.pending_attempts
        if (
            type(pending) is not int
            or not 0 <= pending < min(policy.max_retries + 1, policy.failure_threshold)
            or (pending and len(results) >= len(self._tasks))
        ):
            raise ContractValidationError("No trusted retry/circuit capacity for pending attempts.")
        for retry_number in range(1, pending + 1):
            history += [LifecyclePhase.EXECUTING, LifecyclePhase.RETRY_PENDING]
            delays.append(policy.delay(retry_number))
        try:
            lifecycle = LifecycleState(
                phase=history[-1],
                completed_task_ids=self._task_ids[: len(results)],
                results=results,
                step_count=len(results),
                attempt_count=pending or (attempts[-1] if attempts else 0),
                total_attempts=sum(attempts) + pending,
                circuit=CircuitState(consecutive_failures=pending),
                backoff_delays=tuple(delays),
                history=tuple(history),
            )
        except ValidationError as exc:
            raise ContractValidationError("Restored prefix is not a valid lifecycle.") from exc
        return self._checked({"lifecycle": lifecycle})

    def _observe(self, state: _GraphState, value: LifecycleState) -> dict[str, LifecycleState]:
        """Report a validated boundary to the trusted observer before continuing."""
        observer = state.get("observer")
        if observer is not None:
            checked = self._checked({"lifecycle": value})
            controls = state.get("controls")
            if type(controls) is not RunControls:
                raise ContractValidationError("Missing trusted invocation time accounting.")
            reading = checked_time(self._clock)
            if reading < controls.last_reading:
                raise ContractValidationError("Application monotonic clock regressed.")
            controls.last_reading = reading
            counts: list[int] = []
            current = 0
            for phase in checked.history[1:]:
                if phase is LifecyclePhase.EXECUTING:
                    current += 1
                elif phase is LifecyclePhase.STEP_COMPLETED:
                    counts.append(current)
                    current = 0
            current -= int(checked.phase is LifecyclePhase.EXECUTING) + int(
                checked.blocked_execution
            )
            if current:
                counts.append(current)
            observer(BoundarySnapshot(checked, tuple(counts), reading - controls.started))
        return {"lifecycle": value}

    def _checked(self, state: _GraphState) -> LifecycleState:
        try:
            value = LifecycleState.model_validate(state["lifecycle"])
        except (ValidationError, KeyError) as exc:
            raise ContractValidationError("Malformed internal lifecycle state.") from exc
        if value.step_count > len(self._tasks):
            raise ContractValidationError("Lifecycle exceeds application plan bound.")
        policy = self._retry_policy
        value.circuit.checked(policy.failure_threshold)
        if value.total_attempts > len(self._tasks) * (policy.max_retries + 1):
            raise ContractValidationError("Total attempts exceed the application workflow bound.")
        if value.attempt_count > policy.max_retries + 1:
            raise ContractValidationError("Action attempts exceed application retry policy.")
        if value.circuit.consecutive_failures > value.total_attempts:
            raise ContractValidationError("Circuit failures cannot exceed executed attempts.")
        retry_number = 0
        delays = iter(value.backoff_delays)
        action_attempts = 0
        last_completed_attempts = 0
        observed_attempts = 0
        observed_steps = 0
        activations = dict(zip(
            value.fallback_activation_attempts, value.fallback_task_ids, strict=True
        )) if len(value.fallback_activation_attempts) == len(value.fallback_task_ids) else None
        if activations is None or len(activations) != len(value.fallback_task_ids):
            raise ContractValidationError("Fallback selection records must be unique and paired.")
        observed_selections = []
        for phase in value.history[1:]:
            if phase is LifecyclePhase.EXECUTING:
                if observed_steps >= len(self._tasks):
                    raise ContractValidationError("History schedules work beyond the plan.")
                action_attempts += 1
                observed_attempts += 1
                if action_attempts > policy.max_retries + 1:
                    raise ContractValidationError("History exceeds per-action attempt bound.")
            elif phase is LifecyclePhase.RETRY_PENDING:
                if observed_attempts in activations:
                    if activations[observed_attempts] != self._task_ids[observed_steps]:
                        raise ContractValidationError(
                            "Fallback activation conflicts with task history."
                        )
                    observed_selections.append(observed_attempts)
                retry_number += 1
                if next(delays) != policy.delay(retry_number):
                    raise ContractValidationError("Backoff record violates application policy.")
            elif phase is LifecyclePhase.STEP_COMPLETED:
                observed_steps += 1
                last_completed_attempts = action_attempts
                retry_number = 0
                action_attempts = 0
        if tuple(observed_selections) != value.fallback_activation_attempts:
            raise ContractValidationError("Fallback requires an observed bounded retry transition.")
        expected_attempts = (
            last_completed_attempts
            if (value.phase in {LifecyclePhase.STEP_COMPLETED, LifecyclePhase.COMPLETED}
                or (value.phase is LifecyclePhase.SAFE_STOP
                    and value.history[-2] is LifecyclePhase.STEP_COMPLETED))
            else action_attempts - int(value.phase is LifecyclePhase.EXECUTING)
            - int(value.blocked_execution)
        )
        if value.attempt_count != expected_attempts:
            raise ContractValidationError("Action counter conflicts with execution history.")
        expected_failures = retry_number + int(
            value.stop_reason in {
                StopReason.CIRCUIT_OPEN, StopReason.RETRIES_EXHAUSTED,
                StopReason.PREFERRED_UNAVAILABLE,
            }
        )
        if value.circuit.consecutive_failures != expected_failures:
            raise ContractValidationError(
                "Circuit counter conflicts with qualifying failure history."
            )
        if (value.circuit.phase is CircuitPhase.OPEN) != (
            value.stop_reason is StopReason.CIRCUIT_OPEN
        ):
            raise ContractValidationError("Open circuit must terminate with a circuit-open reason.")
        allowed_fallback_ids = self._task_ids[:min(value.step_count + 1, len(self._tasks))]
        if (len(set(value.fallback_task_ids)) != len(value.fallback_task_ids)
            or any(t not in allowed_fallback_ids for t in value.fallback_task_ids)
            or tuple(t for t in allowed_fallback_ids if t in value.fallback_task_ids)
            != value.fallback_task_ids
            or (value.fallback_task_ids and self._fallback_step is None)):
            raise ContractValidationError("Fallback history violates trusted bindings or order.")
        if value.completed_task_ids != self._task_ids[:value.step_count]:
            raise ContractValidationError("Completion state violates application scheduling order.")
        if value.phase is LifecyclePhase.COMPLETED and value.step_count != len(self._tasks):
            raise ContractValidationError("Cannot complete unfinished application work.")
        if value.phase is LifecyclePhase.EXECUTING and value.step_count >= len(self._tasks):
            raise ContractValidationError("No incomplete step remains for execution.")
        return value

    def _move(
        self, state: LifecycleState, target: LifecyclePhase, **updates: object
    ) -> LifecycleState:
        if target not in _LEGAL_TRANSITIONS[state.phase]:
            raise ContractValidationError("Unsupported application lifecycle transition.")
        return LifecycleState.model_validate({
            **state.model_dump(), **updates,
            "phase": target, "history": (*state.history, target),
        })

    def _schedule(self, state: _GraphState) -> dict[str, LifecycleState]:
        value = self._checked(state)
        if value.phase is LifecyclePhase.RETRY_PENDING:
            # Reconciled pending attempts enter the existing backoff/control node.
            return self._retry(state)
        if value.phase not in {LifecyclePhase.PENDING, LifecyclePhase.STEP_COMPLETED}:
            raise ContractValidationError("Scheduling requires pending or just-completed state.")
        if value.phase is LifecyclePhase.STEP_COMPLETED:
            reason = self._control_reason(state)
            if reason is not None:
                return {"lifecycle": self._move(
                    value, LifecyclePhase.SAFE_STOP, stop_reason=reason,
                )}
        target = (
            LifecyclePhase.COMPLETED if value.step_count == len(self._tasks)
            else LifecyclePhase.EXECUTING
        )
        return {"lifecycle": self._move(
            value, target, attempt_count=0 if target is LifecyclePhase.EXECUTING
            else value.attempt_count,
        )}

    def _execute(self, state: _GraphState) -> dict[str, LifecycleState]:
        value = self._checked(state)
        if value.phase is not LifecyclePhase.EXECUTING:
            raise ContractValidationError("Execution requires application-scheduled state.")
        reason = self._control_reason(state)
        if reason is not None:
            return {"lifecycle": self._move(
                value, LifecyclePhase.SAFE_STOP, stop_reason=reason, blocked_execution=True,
            )}
        task = self._tasks[value.step_count]
        policy = self._retry_policy
        value.circuit.require_closed(policy.failure_threshold)
        if value.attempt_count >= policy.max_retries + 1:
            raise ContractValidationError("No application-authorized attempts remain.")
        counters = {"attempt_count": value.attempt_count + 1,
                    "total_attempts": value.total_attempts + 1}
        effectful = task.task_id in state.get("effect_work", frozenset())
        if self._before_step is not None:
            if effectful:
                raise ContractValidationError(
                    "Before-step gates do not support effect-session reservations."
                )
            # Approval suspension is not a failed/consumed action attempt. The
            # existing observer persists the prefix before any gate can suspend.
            self._observe(state, value)
            self._before_step(task, state["request"])
            reason = self._control_reason(state)
            if reason is not None:
                return {"lifecycle": self._move(
                    value, LifecyclePhase.SAFE_STOP, stop_reason=reason, blocked_execution=True,
                )}
        if effectful:
            # Persist a conservative attempt reservation before any external call.
            # Observer errors occur outside the step-error classification boundary.
            self._observe(state, value)
            reason = self._control_reason(state)
            if reason is not None:
                return {
                    "lifecycle": self._move(
                        value,
                        LifecyclePhase.SAFE_STOP,
                        stop_reason=reason,
                        blocked_execution=True,
                    )
                }
        try:
            binding = (
                state["effect_executor"]
                if effectful
                else (
                    self._fallback_step
                    if task.task_id in value.fallback_task_ids
                    else self._execute_step
                )
            )
            result = StepResult.model_validate(binding(task, state["request"]))
        except TransientStepError as exc:
            circuit = value.circuit.failed(policy.failure_threshold)
            if circuit.phase is CircuitPhase.OPEN:
                reason = StopReason.CIRCUIT_OPEN
            elif counters["attempt_count"] > policy.max_retries:
                reason = StopReason.RETRIES_EXHAUSTED
            elif (isinstance(exc, PreferredPathUnavailable)
                  and task.task_id not in value.fallback_task_ids
                  and self._fallback_step is None):
                reason = StopReason.PREFERRED_UNAVAILABLE
            else:
                fallback_ids = value.fallback_task_ids
                activations = value.fallback_activation_attempts
                if (isinstance(exc, PreferredPathUnavailable)
                    and task.task_id not in fallback_ids):
                    fallback_ids = (*fallback_ids, task.task_id)
                    activations = (*activations, counters["total_attempts"])
                delay = policy.delay(counters["attempt_count"])
                moved = self._move(
                    value, LifecyclePhase.RETRY_PENDING, **counters, circuit=circuit,
                    backoff_delays=(*value.backoff_delays, delay),
                    fallback_task_ids=fallback_ids, fallback_activation_attempts=activations,
                )
            if reason is not None:
                moved = self._move(
                    value, LifecyclePhase.SAFE_STOP, **counters, circuit=circuit,
                    stop_reason=reason,
                )
        except (HarnessError, ValidationError):
            # Expected boundary failures stop without retry or granting authority.
            moved = self._move(
                value, LifecyclePhase.SAFE_STOP, **counters, stop_reason=StopReason.STEP_FAILURE
            )
        else:
            moved = self._move(
                value, LifecyclePhase.STEP_COMPLETED,
                **counters, circuit=value.circuit.succeeded(policy.failure_threshold),
                completed_task_ids=(*value.completed_task_ids, task.task_id),
                results=(*value.results, result), step_count=value.step_count + 1,
            )
        # Every consumed attempt is a boundary; observer failures are never step failures.
        return self._observe(state, moved)

    def _route_scheduled(self, state: _GraphState) -> LifecyclePhase:
        value = self._checked(state)
        if value.phase not in {
            LifecyclePhase.EXECUTING, LifecyclePhase.COMPLETED, LifecyclePhase.SAFE_STOP
        }:
            raise ContractValidationError("Invalid scheduling route.")
        return value.phase

    def _route_executed(self, state: _GraphState) -> LifecyclePhase:
        value = self._checked(state)
        if value.phase not in {
            LifecyclePhase.STEP_COMPLETED, LifecyclePhase.SAFE_STOP, LifecyclePhase.RETRY_PENDING
        }:
            raise ContractValidationError("Invalid execution route.")
        return value.phase

    def _retry(self, state: _GraphState) -> dict[str, LifecycleState]:
        value = self._checked(state)
        if value.phase is not LifecyclePhase.RETRY_PENDING:
            raise ContractValidationError(
                "Retry requires an application-classified transient failure."
            )
        value.circuit.require_closed(self._retry_policy.failure_threshold)
        if not 1 <= value.attempt_count <= self._retry_policy.max_retries:
            raise ContractValidationError("Retry attempt budget exhausted.")
        reason = self._control_reason(state)
        if reason is not None:
            return {"lifecycle": self._move(value, LifecyclePhase.SAFE_STOP, stop_reason=reason)}
        self._wait(self._retry_policy.delay(value.attempt_count))
        reason = self._control_reason(state)
        if reason is not None:
            return {"lifecycle": self._move(value, LifecyclePhase.SAFE_STOP, stop_reason=reason)}
        return {"lifecycle": self._move(value, LifecyclePhase.EXECUTING)}

    def cancel(self) -> None:
        """Activate the runtime's one-way application off-switch."""
        self._off_switch.activate()

    def _control_reason(self, state: _GraphState) -> StopReason | None:
        # Trusted source defects propagate; never ignore or retry a failed read.
        if self._off_switch.is_active():
            return StopReason.CANCELLED
        active = self._cancellation()
        if type(active) is not bool:
            raise ContractValidationError("Cancellation source must return an exact bool.")
        if active:
            self._off_switch.activate()
            return StopReason.CANCELLED
        controls = state.get("controls")
        if type(controls) is not RunControls:
            raise ContractValidationError("Missing trusted invocation time accounting.")
        if controls.expired(self._clock, self._workflow_policy):
            return StopReason.DEADLINE_EXHAUSTED
        return None

    def _complete(self, state: _GraphState) -> dict[str, LifecycleState]:
        value = self._checked(state)
        if value.phase is not LifecyclePhase.COMPLETED:
            raise ContractValidationError("Completion requires finished application work.")
        return {"lifecycle": value}

    def _safe_stop(self, state: _GraphState) -> dict[str, LifecycleState]:
        value = self._checked(state)
        if value.phase is not LifecyclePhase.SAFE_STOP:
            raise ContractValidationError("Safe stop requires an application failure outcome.")
        if value.stop_reason in {StopReason.CANCELLED, StopReason.DEADLINE_EXHAUSTED}:
            return self._observe(state, value)
        return {"lifecycle": value}
