"""Acceptance tests for the deterministic planning engine and lab."""

import pytest
from pydantic import ValidationError

from harness_engineering.domain import RuntimeBudget
from harness_engineering.planning import PlanningEngine, SubtaskDefinition
from harness_engineering.planning_lab import run_planning_lab


def definition(
    task_id: str,
    *,
    action: str = "work",
    dependencies: tuple[str, ...] = (),
    priority: int = 0,
) -> SubtaskDefinition:
    """Build a concise decomposition fixture."""
    return SubtaskDefinition(
        task_id=task_id,
        action=action,
        description=f"Execute {task_id}",
        dependencies=dependencies,
        priority=priority,
    )


def test_planning_engine_decomposes_goal_into_executable_subtasks() -> None:
    """A high-level goal becomes a validated executable plan."""
    engine = PlanningEngine(frozenset({"work"}))

    plan = engine.decompose(
        "Produce deliverable",
        (
            definition("research"),
            definition("write", dependencies=("research",)),
        ),
    )

    assert plan.goal == "Produce deliverable"
    assert tuple(task.task_id for task in plan.tasks) == ("research", "write")


def test_planning_engine_rejects_unsupported_action() -> None:
    """Unsupported proposed actions fail before executable plan creation."""
    engine = PlanningEngine(frozenset({"safe"}))

    with pytest.raises(ValueError, match="Unsupported planning action: privileged"):
        engine.decompose(
            "Reject unsupported work",
            (definition("unsafe", action="privileged"),),
        )


def test_planning_engine_requires_supported_action_registry() -> None:
    """Planning cannot operate without an application-owned action boundary."""
    with pytest.raises(ValueError, match="at least one supported action"):
        PlanningEngine(frozenset())


def test_planning_engine_enforces_configured_plan_bound() -> None:
    """Decomposition cannot exceed the configured maximum plan size."""
    engine = PlanningEngine(
        frozenset({"work"}),
        RuntimeBudget(max_plan_steps=1),
    )

    with pytest.raises(ValidationError, match="maximum number of plan steps"):
        engine.decompose(
            "Oversized decomposition",
            (definition("one"), definition("two")),
        )


def test_planning_engine_preserves_dependency_validation() -> None:
    """Planner output remains subject to execution-plan graph validation."""
    engine = PlanningEngine(frozenset({"work"}))

    with pytest.raises(ValidationError, match="missing dependencies: absent"):
        engine.decompose(
            "Invalid graph",
            (definition("write", dependencies=("absent",)),),
        )


def test_planning_lab_demonstrates_dependency_blocking_and_priority() -> None:
    """The source-required lab exposes deterministic scheduling evidence."""
    result = run_planning_lab()

    assert result.initial_ready == ("research", "metadata")
    assert result.after_research_ready == ("analyze", "metadata")
    assert result.execution_order == (
        "research",
        "analyze",
        "draft",
        "review",
        "metadata",
    )


def test_subtask_definition_rejects_unknown_fields() -> None:
    """Decomposition input fails closed on undeclared fields."""
    with pytest.raises(ValidationError):
        SubtaskDefinition(
            task_id="research",
            action="work",
            description="Research",
            unexpected=True,
        )
