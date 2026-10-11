"""Tests for deterministic dependency-aware priority scheduling."""

import pytest

from harness_engineering.planning import (
    ExecutableSubtask,
    ExecutionPlan,
    PriorityScheduler,
)


def task(
    task_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    priority: int = 0,
) -> ExecutableSubtask:
    """Build a concise scheduler fixture."""
    return ExecutableSubtask(
        task_id=task_id,
        description=f"Execute {task_id}",
        dependencies=dependencies,
        priority=priority,
    )


def test_ready_tasks_exclude_blocked_dependencies() -> None:
    """Only tasks whose dependencies are satisfied enter the ready queue."""
    plan = ExecutionPlan(
        goal="Dependency blocking",
        tasks=(
            task("research", priority=10),
            task("write", dependencies=("research",), priority=100),
        ),
    )

    ready = PriorityScheduler(plan).ready_tasks()

    assert tuple(item.task_id for item in ready) == ("research",)


def test_completed_dependency_unblocks_dependent_task() -> None:
    """Completing a dependency makes its dependent task ready."""
    plan = ExecutionPlan(
        goal="Dependency release",
        tasks=(
            task("research"),
            task("write", dependencies=("research",)),
        ),
    )

    ready = PriorityScheduler(plan).ready_tasks(frozenset({"research"}))

    assert tuple(item.task_id for item in ready) == ("write",)


def test_higher_priority_ready_task_is_selected_first() -> None:
    """Higher numeric priority wins when multiple tasks are ready."""
    plan = ExecutionPlan(
        goal="Priority behavior",
        tasks=(
            task("low", priority=10),
            task("high", priority=90),
            task("medium", priority=50),
        ),
    )

    ready = PriorityScheduler(plan).ready_tasks()

    assert tuple(item.task_id for item in ready) == ("high", "medium", "low")


def test_equal_priority_preserves_declaration_order() -> None:
    """Stable tie-breaking preserves reproducible plan declaration order."""
    plan = ExecutionPlan(
        goal="Stable tie breaking",
        tasks=(
            task("first", priority=50),
            task("second", priority=50),
            task("third", priority=50),
        ),
    )

    ready = PriorityScheduler(plan).ready_tasks()

    assert tuple(item.task_id for item in ready) == ("first", "second", "third")


def test_completed_tasks_are_not_returned_to_ready_queue() -> None:
    """Successfully completed work cannot be scheduled again."""
    plan = ExecutionPlan(
        goal="No duplicate execution",
        tasks=(task("first"), task("second")),
    )

    ready = PriorityScheduler(plan).ready_tasks(frozenset({"first"}))

    assert tuple(item.task_id for item in ready) == ("second",)


def test_unknown_completed_task_identifier_fails_closed() -> None:
    """External completion state cannot introduce unknown task authority."""
    plan = ExecutionPlan(
        goal="Validate completion state",
        tasks=(task("known"),),
    )

    with pytest.raises(ValueError, match="Unknown completed task identifiers: forged"):
        PriorityScheduler(plan).ready_tasks(frozenset({"forged"}))


def test_deterministic_order_respects_dependencies_and_priority() -> None:
    """Full scheduling order combines dependency readiness with priority."""
    plan = ExecutionPlan(
        goal="Produce reviewed deliverable",
        tasks=(
            task("research", priority=20),
            task("outline", priority=80),
            task("write", dependencies=("research", "outline"), priority=100),
            task("review", dependencies=("write",), priority=90),
        ),
    )

    ordered = PriorityScheduler(plan).deterministic_order()

    assert tuple(item.task_id for item in ordered) == (
        "outline",
        "research",
        "write",
        "review",
    )


def test_priority_never_bypasses_unsatisfied_dependency() -> None:
    """Priority affects only ready work and cannot bypass graph dependencies."""
    plan = ExecutionPlan(
        goal="Priority cannot bypass dependencies",
        tasks=(
            task("foundation", priority=1),
            task("blocked", dependencies=("foundation",), priority=100),
            task("independent", priority=50),
        ),
    )

    ordered = PriorityScheduler(plan).deterministic_order()

    assert tuple(item.task_id for item in ordered) == (
        "independent",
        "foundation",
        "blocked",
    )
