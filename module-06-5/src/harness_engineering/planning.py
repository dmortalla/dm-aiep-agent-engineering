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
