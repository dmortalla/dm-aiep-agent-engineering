"""Human-controlled improvement proposals and before/after cycle records.

Proposals are non-executable advisory records; the system never applies them.
Cycle records never self-approve: the decision of record is always
``pending_human_review``.
"""

from collections.abc import Mapping

from .evaluation_contracts import (
    OWNING_AREA_BY_CATEGORY,
    Completeness,
    CycleStatus,
    EvaluationStatus,
    ImprovementCycle,
    ImprovementDecision,
    ImprovementProposal,
    MetricDelta,
    RegressionKind,
    RegressionOutcome,
    RunResult,
    ScenarioEvaluation,
    canonical_digest,
)
from .evaluation_dataset import DatasetView
from .evaluation_engine import EvaluationEngine


def _rows_by_key(run: RunResult) -> Mapping[tuple[str, str], ScenarioEvaluation]:
    """Index one run's evaluation rows by (scenario, evaluator)."""
    return {(row.scenario_id, row.evaluator_id): row for row in run.evaluations}


def improvement_proposals(
    run: RunResult,
    engine: EvaluationEngine,
    dataset: DatasetView,
) -> tuple[ImprovementProposal, ...]:
    """Derive advisory proposals from the failing evaluations of one run.

    Args:
        run: The compared class A run result.
        engine: The bounded engine (threshold authority).
        dataset: The committed dataset view (expected-facts authority).

    Returns:
        Deterministically ordered proposals; empty for a passing run.

    Raises:
        ContractValidationError: For a malformed run/dataset pairing.
    """
    proposals: list[ImprovementProposal] = []
    for row in run.evaluations:
        if row.passed and row.status is EvaluationStatus.EVALUATED:
            continue
        category = dataset.get(row.scenario_id).category
        proposals.append(
            ImprovementProposal(
                run_id=run.run_id,
                scenario_id=row.scenario_id,
                category=category,
                evaluator_id=row.evaluator_id,
                evaluator_version=row.evaluator_version,
                metric=row.metric,
                threshold=(row.threshold[0], row.threshold[1]),
                observed=row.observed,
                expected=dataset.expected_facts(row.scenario_id),
                owning_area=OWNING_AREA_BY_CATEGORY[category],
            )
        )
    return tuple(proposals)


def improvement_cycle(before: RunResult, after: RunResult) -> ImprovementCycle:
    """Build the before/after comparison record for one change attempt.

    Args:
        before: The run result before the change attempt.
        after: The run result after the change attempt.

    Returns:
        An immutable cycle record with deterministic deltas; ``new_regressions``
        contains only deltas regressing after the attempt.
    """
    before_fields = before.identity.model_dump()
    after_fields = after.identity.model_dump()
    target_fields = {"target_id", "target_version", "run_ordinal"}
    complete = (
        before.completeness is Completeness.COMPLETE
        and after.completeness is Completeness.COMPLETE
    )
    comparable = (
        all(
            after_fields[name] == before_fields[name]
            for name in before_fields
            if name not in target_fields
        )
        and complete
    )
    if not comparable:
        return ImprovementCycle(
            before_run_id=before.run_id,
            before_report_digest=run_digest(before),
            after_run_id=after.run_id,
            after_report_digest=run_digest(after),
            compatibility=RegressionOutcome.NOT_COMPARABLE,
            status=CycleStatus.NOT_COMPARABLE,
        )
    before_rows = _rows_by_key(before)
    after_rows = _rows_by_key(after)
    deltas: list[MetricDelta] = []
    for key in sorted(set(before_rows) | set(after_rows)):
        delta = _delta(key, before_rows.get(key), after_rows.get(key))
        if delta is not None:
            deltas.append(delta)
    new_regressions = tuple(
        delta for delta in deltas if delta.kind is RegressionKind.REGRESSED
    )
    return ImprovementCycle(
        before_run_id=before.run_id,
        before_report_digest=run_digest(before),
        after_run_id=after.run_id,
        after_report_digest=run_digest(after),
        compatibility=RegressionOutcome.PASS
        if not new_regressions
        else RegressionOutcome.FAIL,
        deltas=tuple(deltas),
        new_regressions=new_regressions,
        decision=ImprovementDecision.PENDING_HUMAN_REVIEW,
        status=CycleStatus.COMPARABLE,
    )


def _delta(
    key: tuple[str, str],
    before_row: ScenarioEvaluation | None,
    after_row: ScenarioEvaluation | None,
) -> MetricDelta | None:
    """Project one evaluated metric delta; None for unchanged full pairs."""
    scenario_id, evaluator_id = key
    before_score = before_row.score if before_row is not None else None
    after_score = after_row.score if after_row is not None else None
    if before_score == after_score:
        return None
    kind = RegressionKind.IMPROVED
    if before_score is None or after_score is None:
        kind = RegressionKind.MISSING
    elif after_score < before_score:
        kind = RegressionKind.REGRESSED
    row = after_row if after_row is not None else before_row
    assert row is not None
    return MetricDelta(
        scenario_id=scenario_id,
        category=row.category,
        evaluator_id=evaluator_id,
        evaluator_version=row.evaluator_version,
        metric=row.metric,
        before_score=before_score,
        after_score=after_score,
        kind=kind,
    )


def run_digest(run: RunResult) -> str:
    """Return the canonical content digest of one run result.

    Args:
        run: The class A run result.

    Returns:
        The SHA-256 digest over the canonical serialization of the result.
    """
    return canonical_digest(run.model_dump(mode="json"))


__all__ = [
    "improvement_cycle",
    "improvement_proposals",
    "run_digest",
]
