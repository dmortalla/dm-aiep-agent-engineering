"""Story 6 improvement tests: advisory proposals and cycle records."""

import asyncio
import json

from reliability_safety_observability.evaluation_contracts import (
    CycleStatus,
    ImprovementDecision,
    RegressionKind,
    RegressionOutcome,
)
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import EvaluationEngine
from reliability_safety_observability.evaluation_improvement import (
    improvement_cycle,
    improvement_proposals,
    run_digest,
)
from reliability_safety_observability.evaluation_target import ReferenceTarget


def produce(target="reference_default", version=1, degraded=False):
    """Produce one bounded run result with a deterministic target."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()
    fact = engine.run(
        dataset,
        target_id=target,
        target_version=version,
        target_factory=lambda correlations: ReferenceTarget.build(
            correlations, degraded=degraded
        ),
    )
    return asyncio.run(fact).result


def test_passing_runs_require_no_improvement_proposals() -> None:
    """A fully passing run yields an empty advisory proposal set."""
    dataset = load_benchmark_dataset()
    result = produce()
    assert improvement_proposals(result, EvaluationEngine(), dataset) == ()


def test_failing_rows_generate_advisory_proposals_with_thresholds() -> None:
    """Failing rows carry thresholds, expected facts and owning areas."""
    dataset = load_benchmark_dataset()
    result = produce(target="degraded_demo", version=1, degraded=True)
    proposals = improvement_proposals(result, EvaluationEngine(), dataset)
    assert proposals
    first = proposals[0]
    assert isinstance(json.dumps(first.model_dump(mode="json")), str)
    assert first.owning_area
    assert first.threshold[0] <= first.threshold[1]


def test_proposals_cover_each_failing_row_deterministically() -> None:
    """Proposals are frozen, run-bound and repeat identically."""
    dataset = load_benchmark_dataset()
    result = produce(target="degraded_demo", version=1, degraded=True)
    engine = EvaluationEngine()
    first = improvement_proposals(result, engine, dataset)
    second = improvement_proposals(result, engine, dataset)
    assert first == second
    assert all(p.run_id == result.run_id for p in first)


def test_cycle_between_comparable_runs_records_decided_deltas() -> None:
    """Comparable before/after runs produce decision-pending cycle records."""
    before = produce(target="degraded_demo", version=1, degraded=True)
    after = produce()
    cycle = improvement_cycle(before, after)
    assert cycle.compatibility is RegressionOutcome.PASS
    assert cycle.status is CycleStatus.COMPARABLE
    assert cycle.decision is ImprovementDecision.PENDING_HUMAN_REVIEW
    regressions = cycle.new_regressions
    assert not regressions
    assert all("delta" not in delta.model_dump(mode="json") for delta in cycle.deltas)
    assert isinstance(json.dumps(cycle.model_dump(mode="json")), str)


def test_cycle_between_incomparable_ids_becomes_not_comparable() -> None:
    """Different dataset/suite identities yield NOT_COMPARABLE without deltas."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()
    before = asyncio.run(engine.run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
    )).result
    after = asyncio.run(engine.run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
    )).result
    identity = after.identity.model_copy(update={"dataset_version": 2})
    cycle = improvement_cycle(before, after.model_copy(update={"identity": identity}))
    assert cycle.status is CycleStatus.NOT_COMPARABLE
    assert cycle.compatibility is RegressionOutcome.NOT_COMPARABLE
    assert cycle.deltas == ()


def test_regression_into_attempt_marks_failed_cycle() -> None:
    """Attempts that regress a metric produce identical cycle failure labels."""
    before = produce()
    after = produce(target="degraded_demo", version=1, degraded=True)
    cycle = improvement_cycle(before, after)
    assert cycle.compatibility is RegressionOutcome.FAIL
    regressions = cycle.new_regressions
    assert regressions
    assert all(delta.kind is RegressionKind.REGRESSED for delta in regressions)
    assert cycle.decision is ImprovementDecision.PENDING_HUMAN_REVIEW


def test_run_digest_binds_canonical_content() -> None:
    """Run digests are deterministic for identical content only."""
    first = produce()
    second = produce()
    assert run_digest(first) == run_digest(second)
    degraded = produce(target="degraded_demo", version=1, degraded=True)
    assert run_digest(first) != run_digest(degraded)
