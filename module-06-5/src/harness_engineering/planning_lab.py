"""Deterministic task-planning lab for Module 6.5."""

from dataclasses import dataclass

from harness_engineering.domain import RuntimeBudget
from harness_engineering.planning import (
    PlanningEngine,
    PriorityScheduler,
    SubtaskDefinition,
)


@dataclass(frozen=True)
class PlanningLabResult:
    """Observable deterministic evidence produced by the planning lab."""

    goal: str
    initial_ready: tuple[str, ...]
    after_research_ready: tuple[str, ...]
    execution_order: tuple[str, ...]


def run_planning_lab() -> PlanningLabResult:
    """Run deterministic decomposition, dependency, and priority behavior.

    Returns:
        Stable evidence showing dependency blocking and priority ordering.
    """
    goal = "Prepare and review an evidence-based customer brief"
    engine = PlanningEngine(
        supported_actions=frozenset({"research", "analyze", "draft", "review"}),
        budget=RuntimeBudget(max_plan_steps=6),
    )

    plan = engine.decompose(
        goal,
        (
            SubtaskDefinition(
                task_id="research",
                action="research",
                description="Collect customer evidence.",
                priority=80,
            ),
            SubtaskDefinition(
                task_id="analyze",
                action="analyze",
                description="Analyze collected evidence.",
                dependencies=("research",),
                priority=100,
            ),
            SubtaskDefinition(
                task_id="draft",
                action="draft",
                description="Draft the customer brief.",
                dependencies=("analyze",),
                priority=90,
            ),
            SubtaskDefinition(
                task_id="review",
                action="review",
                description="Review the customer brief.",
                dependencies=("draft",),
                priority=100,
            ),
            SubtaskDefinition(
                task_id="metadata",
                action="analyze",
                description="Prepare independent metadata.",
                priority=20,
            ),
        ),
    )

    scheduler = PriorityScheduler(plan)
    initial_ready = tuple(task.task_id for task in scheduler.ready_tasks())
    after_research_ready = tuple(
        task.task_id
        for task in scheduler.ready_tasks(frozenset({"research"}))
    )
    execution_order = tuple(
        task.task_id for task in scheduler.deterministic_order()
    )

    return PlanningLabResult(
        goal=goal,
        initial_ready=initial_ready,
        after_research_ready=after_research_ready,
        execution_order=execution_order,
    )
