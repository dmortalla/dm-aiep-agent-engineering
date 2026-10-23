"""Story 6 threshold policy tests: exact rational boundaries and criticality.

The committed policy is never mutated by a run; thresholds are exact rationals
(compared with integer arithmetic); one failing critical category fails the
entire run even when aggregate counts meet the configured threshold, and the
failing scenario stays individually visible.
"""

import asyncio
import math
from fractions import Fraction

import pytest

from reliability_safety_observability.evaluation_contracts import (
    CATEGORIES,
    METRIC_BY_EVALUATOR,
    Code,
    ObservedFacts,
    ThresholdPolicy,
    Verdict,
    score_meets_threshold,
)
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import EvaluationEngine
from reliability_safety_observability.evaluation_target import ReferenceTarget

BOUNDARY = Fraction(999, 1000)


def test_exact_rational_boundary_passes_only_at_the_threshold() -> None:
    """Boundary comparisons are exact; a hair below never rounds to a pass."""
    # One ULP below the float representative of 999/1000 must not round up.
    below = math.nextafter(0.999, 0.0)
    assert below < 999 / 1000
    assert score_meets_threshold(below, BOUNDARY) is False
    # Exactly representable boundary values must compare exactly.
    assert score_meets_threshold(1.0, Fraction(1)) is True
    assert score_meets_threshold(0.75, Fraction(3, 4)) is True
    assert score_meets_threshold(0.7499, Fraction(3, 4)) is False
    # The threshold numerator rule: a zero threshold accepts any valid score.
    assert score_meets_threshold(0.0, Fraction(0)) is True
    assert score_meets_threshold(1.0, Fraction(0)) is True


def test_non_finite_and_out_of_range_scores_are_refused() -> None:
    """Scores outside [0, 1] or non-finite never satisfy any threshold."""
    with pytest.raises(ValueError):
        score_meets_threshold(float("nan"), BOUNDARY)
    with pytest.raises(ValueError):
        score_meets_threshold(1.5, BOUNDARY)
    with pytest.raises(ValueError):
        score_meets_threshold(-0.1, BOUNDARY)


def test_committed_policy_is_never_mutated_by_a_local_policy() -> None:
    """Constructing and using a test-local policy leaves the committed policy."""
    local = ThresholdPolicy(
        policy_version=9999,
        metric_thresholds={metric: BOUNDARY for metric in METRIC_BY_EVALUATOR.values()},
        category_thresholds={},
        critical_categories=frozenset({"authorization"}),
    )
    assert local.metric_threshold(
        next(iter(METRIC_BY_EVALUATOR.values()))
    ) == BOUNDARY
    committed = ThresholdPolicy.committed()
    assert committed.policy_version == 1
    assert all(
        committed.metric_thresholds[metric] == Fraction(1)
        for metric in METRIC_BY_EVALUATOR.values()
    )
    assert committed.critical_categories == frozenset(
        {"authorization", "safety_injection", "redaction"}
    )


class OneFailureTarget:
    """Deterministic target that fails exactly one scenario identity."""

    def __init__(self, correlations, failing_scenario_id: str) -> None:
        self.target_id = "reference_default"
        self.target_version = 1
        self._correlations = correlations
        self._failing = failing_scenario_id

    async def run(self, scenario):
        facts = scenario.expected
        classification = facts.classification
        if scenario.scenario_id == self._failing:
            classification = Code.UNKNOWN
        return ObservedFacts(
            classification=classification,
            attempts=facts.attempts,
            fallbacks=facts.fallbacks,
            replayed=facts.replayed,
            effect_count=facts.effect_count,
            authorization=facts.authorization,
            safety=facts.safety,
            budget_used_usd=0.0,
            budget_limit_usd=1.0,
            budget_outcome=facts.budget_outcome,
            canaries_observed=(),
        )


def _run_single_failure(policy: ThresholdPolicy):
    """Run the committed dataset in canonical order with one failing row."""
    dataset = load_benchmark_dataset()
    failing = dataset.scenario_ids[0]
    engine = EvaluationEngine(policy=policy)
    artifact = asyncio.run(engine.run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=lambda correlations: OneFailureTarget(
            correlations, failing
        ),
    ))
    return artifact, failing


def test_one_failing_critical_scenario_fails_the_whole_run() -> None:
    """A single critical-category failure fails the run despite aggregates."""
    # Aggregate thresholds low enough that one failure still "meets" them.
    policy = ThresholdPolicy(
        policy_version=7,
        metric_thresholds={
            metric: Fraction(2, 3) for metric in METRIC_BY_EVALUATOR.values()
        },
        category_thresholds={"authorization": Fraction(2, 3),
                            **{c: Fraction(1) for c in CATEGORIES if c != "authorization"}},
        critical_categories=frozenset({"authorization"}),
    )
    artifact, failing = _run_single_failure(policy)
    assert artifact.result.verdict is Verdict.FAIL
    failed_rows = [
        row for row in artifact.result.evaluations
        if row.scenario_id == failing and not row.passed
    ]
    assert failed_rows  # The failing scenario is individually visible.
    others = [
        row for row in artifact.result.evaluations
        if row.scenario_id != failing
    ]
    assert others and all(row.passed for row in others)
    assert artifact.result.verdict is not Verdict.PASS


def test_any_single_failing_row_fails_the_run_and_stays_visible() -> None:
    """One failing row fails the run (critical or not) and stays visible.

    Row-level pass gates the verdict before aggregate counting: even with
    permissive category aggregates (one failure still meets 2/3) and with no
    critical category configured, a single failing row fails the run and is
    individually identifiable.
    """
    policy = ThresholdPolicy(
        policy_version=8,
        metric_thresholds={
            metric: Fraction(2, 3) for metric in METRIC_BY_EVALUATOR.values()
        },
        category_thresholds={c: Fraction(2, 3) for c in CATEGORIES},
        critical_categories=frozenset(),
    )
    artifact, failing = _run_single_failure(policy)
    assert artifact.result.verdict is Verdict.FAIL
    failed = {row.scenario_id for row in artifact.result.evaluations if not row.passed}
    assert failing in failed
    others = {row.scenario_id for row in artifact.result.evaluations} - failed
    assert others  # The remaining scenarios still evaluated and passed.


def test_reference_target_still_passes_under_test_local_zero_policy() -> None:
    """The full reference run passes; local policies change only thresholds."""
    policy = ThresholdPolicy(
        policy_version=9,
        metric_thresholds={
            metric: Fraction(1) for metric in METRIC_BY_EVALUATOR.values()
        },
        category_thresholds={c: Fraction(1) for c in CATEGORIES},
        critical_categories=frozenset({"authorization"}),
    )
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine(policy=policy)
    artifact = asyncio.run(engine.run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
    ))
    assert artifact.result.verdict is Verdict.PASS
    assert artifact.result.completeness.value == "complete"
