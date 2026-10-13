"""Story 5 Slice 1: application-owned finite LangGraph lifecycle.

Bootstrap owns the validated plan and synchronous local step executor. Never
deserialize bootstrap bindings from generated content. The public run boundary
accepts data only, not graph state, config, commands, permissions, or node names.
Tool adapters must retain BoundedToolExecutor's independent authorization.
Slice 2 adds bounded retries/backoff and a workflow-local circuit breaker.
Slice 3 adds finite fallback, workflow deadlines, and application cancellation.
Recovery remains deferred.
Trusted executors must terminate; graph bounds do not preempt Python callbacks.
"""

from collections.abc import Callable
from enum import StrEnum
from time import monotonic, sleep
from typing import Annotated, Self, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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


class _GraphState(TypedDict):
    lifecycle: LifecycleState
    request: LifecycleInput
    controls: RunControls


StepExecutor = Callable[[ExecutableSubtask, LifecycleInput], StepResult]


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
        self._fallback_step = fallback_step
        self._clock = clock
        self._off_switch = OffSwitch()
        self._cancellation = (
            cancellation if cancellation is not None else self._off_switch.is_active
        )
        self._wait = wait
        self._tasks = PriorityScheduler(snapshot).deterministic_order()
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
        try:
            checked = LifecycleInput.model_validate(request)
        except ValidationError as exc:
            raise ContractValidationError("Lifecycle input accepts bounded text only.") from exc
        started = checked_time(self._clock)
        output = self._graph.invoke(
            {"lifecycle": LifecycleState(), "request": checked,
             "controls": RunControls(started, started)},
            config={"recursion_limit": (2 + 2 * self._retry_policy.max_retries)
                    * len(self._tasks) + 3},
        )
        result = self._checked(output)
        if result.phase not in {LifecyclePhase.COMPLETED, LifecyclePhase.SAFE_STOP}:
            raise ContractValidationError("Graph did not reach a terminal outcome.")
        return result

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
        try:
            binding = (self._fallback_step if task.task_id in value.fallback_task_ids
                       else self._execute_step)
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
                return {"lifecycle": self._move(
                    value, LifecyclePhase.RETRY_PENDING, **counters, circuit=circuit,
                    backoff_delays=(*value.backoff_delays, delay),
                    fallback_task_ids=fallback_ids, fallback_activation_attempts=activations,
                )}
            return {"lifecycle": self._move(
                value, LifecyclePhase.SAFE_STOP, **counters, circuit=circuit, stop_reason=reason,
            )}
        except (HarnessError, ValidationError):
            # Expected boundary failures stop without retry or granting authority.
            return {"lifecycle": self._move(
                value, LifecyclePhase.SAFE_STOP, **counters, stop_reason=StopReason.STEP_FAILURE
            )}
        return {"lifecycle": self._move(
            value, LifecyclePhase.STEP_COMPLETED,
            **counters, circuit=value.circuit.succeeded(policy.failure_threshold),
            completed_task_ids=(*value.completed_task_ids, task.task_id),
            results=(*value.results, result), step_count=value.step_count + 1,
        )}

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
        return {"lifecycle": value}
