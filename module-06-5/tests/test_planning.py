"""Tests for typed planning and dependency validation."""

import pytest
from pydantic import ValidationError

from harness_engineering.domain import RuntimeBudget
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan, TaskStatus


def task(
    task_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    priority: int = 0,
) -> ExecutableSubtask:
    """Build a concise planning fixture."""
    return ExecutableSubtask(
        task_id=task_id,
        description=f"Execute {task_id}",
        dependencies=dependencies,
        priority=priority,
    )


def test_executable_subtask_defaults_to_pending() -> None:
    """Executable work starts in the pending state."""
    assert task("research").status is TaskStatus.PENDING


def test_subtask_rejects_self_dependency() -> None:
    """A task cannot create a dependency edge to itself."""
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        task("research", dependencies=("research",))


def test_subtask_rejects_duplicate_dependencies() -> None:
    """Duplicate dependency edges fail closed."""
    with pytest.raises(ValidationError, match="duplicate dependencies"):
        task("write", dependencies=("research", "research"))


def test_plan_accepts_valid_dependency_graph() -> None:
    """A valid acyclic dependency graph passes validation."""
    plan = ExecutionPlan(
        goal="Produce a reviewed report",
        tasks=(
            task("research", priority=10),
            task("write", dependencies=("research",), priority=20),
            task("review", dependencies=("write",), priority=30),
        ),
    )

    assert len(plan.tasks) == 3


def test_plan_rejects_duplicate_task_identifiers() -> None:
    """Task identifiers are unique within a plan."""
    with pytest.raises(ValidationError, match="duplicate task identifiers"):
        ExecutionPlan(
            goal="Duplicate identifiers",
            tasks=(task("same"), task("same")),
        )


def test_plan_rejects_missing_dependency() -> None:
    """Every dependency must reference a task in the same plan."""
    with pytest.raises(ValidationError, match="missing dependencies: research"):
        ExecutionPlan(
            goal="Missing dependency",
            tasks=(task("write", dependencies=("research",)),),
        )


def test_plan_rejects_two_node_cycle() -> None:
    """Mutual dependencies are rejected deterministically."""
    with pytest.raises(ValidationError, match="dependency cycle"):
        ExecutionPlan(
            goal="Cyclic plan",
            tasks=(
                task("first", dependencies=("second",)),
                task("second", dependencies=("first",)),
            ),
        )


def test_plan_rejects_longer_cycle() -> None:
    """Cycles remain invalid when they span multiple tasks."""
    with pytest.raises(ValidationError, match="dependency cycle"):
        ExecutionPlan(
            goal="Long cyclic plan",
            tasks=(
                task("first", dependencies=("third",)),
                task("second", dependencies=("first",)),
                task("third", dependencies=("second",)),
            ),
        )


def test_plan_enforces_runtime_plan_bound() -> None:
    """The configured plan-step budget bounds decomposition size."""
    budget = RuntimeBudget(max_plan_steps=2)

    with pytest.raises(ValidationError, match="maximum number of plan steps"):
        ExecutionPlan(
            goal="Oversized plan",
            tasks=(task("one"), task("two"), task("three")),
            budget=budget,
        )


def test_plan_rejects_empty_task_collection() -> None:
    """A plan must contain at least one executable subtask."""
    with pytest.raises(ValidationError):
        ExecutionPlan(goal="No work", tasks=())


def test_planning_contracts_reject_unknown_fields() -> None:
    """Planning contracts fail closed on undeclared input fields."""
    with pytest.raises(ValidationError):
        ExecutableSubtask(
            task_id="research",
            description="Research",
            unexpected=True,
        )
