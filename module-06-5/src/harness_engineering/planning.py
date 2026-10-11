"""Typed task-planning contracts and deterministic dependency validation."""

from collections import deque
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.domain import Identifier, RuntimeBudget


class TaskStatus(StrEnum):
    """Lifecycle state for an executable subtask."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class ExecutableSubtask(BaseModel):
    """A typed executable unit produced by task decomposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: Identifier
    description: str = Field(min_length=1, max_length=2000)
    dependencies: tuple[Identifier, ...] = ()
    priority: int = Field(default=0, ge=0, le=100)
    status: TaskStatus = TaskStatus.PENDING

    @model_validator(mode="after")
    def validate_dependencies(self) -> "ExecutableSubtask":
        """Reject self-dependencies and duplicate dependency identifiers."""
        if self.task_id in self.dependencies:
            raise ValueError("A subtask cannot depend on itself.")

        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("A subtask cannot declare duplicate dependencies.")

        return self


class ExecutionPlan(BaseModel):
    """Validated bounded dependency graph of executable subtasks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str = Field(min_length=1, max_length=4000)
    tasks: tuple[ExecutableSubtask, ...] = Field(min_length=1)
    budget: RuntimeBudget = Field(default_factory=RuntimeBudget)

    @model_validator(mode="after")
    def validate_plan(self) -> "ExecutionPlan":
        """Fail closed on invalid graph structure or plan bounds."""
        if len(self.tasks) > self.budget.max_plan_steps:
            raise ValueError(
                "Plan exceeds the configured maximum number of plan steps."
            )

        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Plan contains duplicate task identifiers.")

        known_ids = set(task_ids)
        for task in self.tasks:
            missing = set(task.dependencies) - known_ids
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(
                    f"Task {task.task_id} references missing dependencies: {missing_text}."
                )

        self._reject_cycles()
        return self

    def _reject_cycles(self) -> None:
        """Reject dependency cycles using deterministic topological validation."""
        indegree = {task.task_id: len(task.dependencies) for task in self.tasks}
        dependents: dict[str, list[str]] = {task.task_id: [] for task in self.tasks}

        for task in self.tasks:
            for dependency in task.dependencies:
                dependents[dependency].append(task.task_id)

        ready = deque(
            sorted(task_id for task_id, degree in indegree.items() if degree == 0)
        )
        visited = 0

        while ready:
            task_id = ready.popleft()
            visited += 1

            for dependent in sorted(dependents[task_id]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)

        if visited != len(self.tasks):
            raise ValueError("Plan contains a dependency cycle.")

class PriorityScheduler:
    """Select dependency-ready subtasks using deterministic priority ordering.

    Higher numeric priority values execute first. Tasks with equal priority
    preserve their declaration order in the validated execution plan.
    """

    def __init__(self, plan: ExecutionPlan) -> None:
        """Initialize a scheduler for an already validated execution plan.

        Args:
            plan: Validated execution plan to schedule.
        """
        self._plan = plan
        self._known_ids = frozenset(task.task_id for task in plan.tasks)
        self._declaration_order = {
            task.task_id: index for index, task in enumerate(plan.tasks)
        }

    def ready_tasks(
        self,
        completed_task_ids: frozenset[str] = frozenset(),
    ) -> tuple[ExecutableSubtask, ...]:
        """Return currently executable tasks in deterministic priority order.

        Args:
            completed_task_ids: Task identifiers already completed successfully.

        Returns:
            Ready, incomplete tasks ordered by descending priority and then
            original declaration order.

        Raises:
            ValueError: If completion state contains an unknown task identifier.
        """
        self._validate_completed_ids(completed_task_ids)

        ready = [
            task
            for task in self._plan.tasks
            if task.task_id not in completed_task_ids
            and set(task.dependencies).issubset(completed_task_ids)
        ]

        return tuple(
            sorted(
                ready,
                key=lambda task: (
                    -task.priority,
                    self._declaration_order[task.task_id],
                ),
            )
        )

    def deterministic_order(self) -> tuple[ExecutableSubtask, ...]:
        """Return the complete dependency-valid deterministic execution order.

        Returns:
            Every task ordered as it would become executable when each selected
            task completes successfully.

        Raises:
            RuntimeError: If a validated plan cannot make scheduling progress.
        """
        completed: set[str] = set()
        ordered: list[ExecutableSubtask] = []

        while len(completed) < len(self._plan.tasks):
            ready = self.ready_tasks(frozenset(completed))
            if not ready:
                raise RuntimeError("Validated plan cannot make scheduling progress.")

            selected = ready[0]
            ordered.append(selected)
            completed.add(selected.task_id)

        return tuple(ordered)

    def _validate_completed_ids(self, completed_task_ids: frozenset[str]) -> None:
        """Reject completion state that does not belong to this execution plan."""
        unknown = completed_task_ids - self._known_ids
        if unknown:
            unknown_text = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown completed task identifiers: {unknown_text}.")
