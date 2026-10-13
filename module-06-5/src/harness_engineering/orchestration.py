"""Story 5 Slice 1: application-owned finite LangGraph lifecycle.

Bootstrap owns the validated plan and synchronous local step executor. Never
deserialize bootstrap bindings from generated content. The public run boundary
accepts data only, not graph state, config, commands, permissions, or node names.
Tool adapters must retain BoundedToolExecutor's independent authorization.
This foundation does not implement retries, deadlines, cancellation, or recovery.
Trusted executors must terminate; graph bounds do not preempt Python callbacks.
"""

from collections.abc import Callable
from enum import StrEnum
from typing import Self, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan, PriorityScheduler


class LifecyclePhase(StrEnum):
    """Finite application phases; no generated routing discriminator exists."""

    PENDING = "pending"
    EXECUTING = "executing"
    STEP_COMPLETED = "step_completed"
    COMPLETED = "completed"
    SAFE_STOP = "safe_stop"


class StopReason(StrEnum):
    """Explicit terminal reason owned by application execution policy."""

    STEP_FAILURE = "step_failure"


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
        {LifecyclePhase.STEP_COMPLETED, LifecyclePhase.SAFE_STOP}
    ),
    LifecyclePhase.STEP_COMPLETED: frozenset(
        {LifecyclePhase.EXECUTING, LifecyclePhase.COMPLETED}
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
    history: tuple[LifecyclePhase, ...] = Field(
        default=(LifecyclePhase.PENDING,), min_length=1, max_length=202
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
        if (self.phase is LifecyclePhase.SAFE_STOP) != (self.stop_reason is not None):
            raise ValueError("Only safe-stop state must carry a stop reason.")
        return self


class _GraphState(TypedDict):
    lifecycle: LifecycleState
    request: LifecycleInput


StepExecutor = Callable[[ExecutableSubtask, LifecycleInput], StepResult]


class LifecycleRuntime:
    """Compile and invoke bounded scheduling with application-owned routing."""

    def __init__(self, plan: ExecutionPlan, execute_step: StepExecutor) -> None:
        """Bind trusted application configuration, never contextual authority.

        Args:
            plan: Application-accepted plan, snapshotted and fully revalidated.
            execute_step: Trusted terminating local adapter. Tool execution must
                independently authorize through the accepted tool executor.

        Raises:
            ContractValidationError: For malformed bootstrap configuration.
        """
        if not callable(execute_step) or not isinstance(plan, ExecutionPlan):
            raise ContractValidationError("Bind a validated plan and callable step executor.")
        try:
            snapshot = ExecutionPlan.model_validate(plan.model_dump())
        except ValidationError as exc:
            raise ContractValidationError("Invalid lifecycle plan.") from exc
        self._tasks = PriorityScheduler(snapshot).deterministic_order()
        self._execute_step = execute_step
        self._task_ids = tuple(task.task_id for task in self._tasks)
        graph = StateGraph(_GraphState)
        graph.add_node("schedule", self._schedule)
        graph.add_node("execute", self._execute)
        graph.add_node("complete", self._complete)
        graph.add_node("safe_stop", self._safe_stop)
        graph.add_edge(START, "schedule")
        graph.add_conditional_edges(
            "schedule", self._route_scheduled,
            {LifecyclePhase.EXECUTING: "execute", LifecyclePhase.COMPLETED: "complete"},
        )
        graph.add_conditional_edges(
            "execute", self._route_executed,
            {LifecyclePhase.STEP_COMPLETED: "schedule", LifecyclePhase.SAFE_STOP: "safe_stop"},
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
        output = self._graph.invoke(
            {"lifecycle": LifecycleState(), "request": checked},
            config={"recursion_limit": 2 * len(self._tasks) + 3},
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
        target = (
            LifecyclePhase.COMPLETED if value.step_count == len(self._tasks)
            else LifecyclePhase.EXECUTING
        )
        return {"lifecycle": self._move(value, target)}

    def _execute(self, state: _GraphState) -> dict[str, LifecycleState]:
        value = self._checked(state)
        if value.phase is not LifecyclePhase.EXECUTING:
            raise ContractValidationError("Execution requires application-scheduled state.")
        task = self._tasks[value.step_count]
        try:
            result = StepResult.model_validate(self._execute_step(task, state["request"]))
        except (HarnessError, ValidationError):
            # Expected boundary failures stop without retry or granting authority.
            return {"lifecycle": self._move(
                value, LifecyclePhase.SAFE_STOP, stop_reason=StopReason.STEP_FAILURE
            )}
        return {"lifecycle": self._move(
            value, LifecyclePhase.STEP_COMPLETED,
            completed_task_ids=(*value.completed_task_ids, task.task_id),
            results=(*value.results, result), step_count=value.step_count + 1,
        )}

    def _route_scheduled(self, state: _GraphState) -> LifecyclePhase:
        value = self._checked(state)
        if value.phase not in {LifecyclePhase.EXECUTING, LifecyclePhase.COMPLETED}:
            raise ContractValidationError("Invalid scheduling route.")
        return value.phase

    def _route_executed(self, state: _GraphState) -> LifecyclePhase:
        value = self._checked(state)
        if value.phase not in {LifecyclePhase.STEP_COMPLETED, LifecyclePhase.SAFE_STOP}:
            raise ContractValidationError("Invalid execution route.")
        return value.phase

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
