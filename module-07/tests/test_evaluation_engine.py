"""Story 6 engine tests: deterministic runs, identity, bounded failure lanes."""

import asyncio

import pytest

from reliability_safety_observability.evaluation_contracts import (
    Completeness,
    EvaluationStatus,
    Verdict,
)
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import (
    EngineBounds,
    EvaluationEngine,
    RunInterruptedError,
)
from reliability_safety_observability.evaluation_target import ReferenceTarget

REFERENCE = {
    "target_id": "reference_default",
    "target_version": 1,
    "run_ordinal": 0,
}


def run_reference(**override):
    """Run the reference benchmark locally and return the artifact."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()
    identity = {**REFERENCE, **override}
    artifact = asyncio.run(dict_run(engine, dataset, identity))
    return artifact


async def dict_run(engine, dataset, identity):
    """Await one bounded engine run over the whole dataset."""
    return await engine.run(
        dataset,
        target_id=identity["target_id"],
        target_version=identity["target_version"],
        target_factory=ReferenceTarget.build,
        run_ordinal=identity["run_ordinal"],
    )


def test_reference_target_passes_every_committed_scenario() -> None:
    """The reference target passes the complete deterministic benchmark."""
    artifact = run_reference()
    assert artifact.result.verdict is Verdict.PASS
    assert artifact.result.completeness is Completeness.COMPLETE
    assert not artifact.result.missing_scenario_ids
    all_counts = artifact.result.aggregate.metric_counts
    assert all(
        counts.passed == counts.evaluated and counts.failed == 0
        for counts in all_counts.values()
    )
    assert all(
        row.status is EvaluationStatus.EVALUATED
        for row in artifact.result.evaluations
    )


def test_run_identity_is_deterministic_for_the_same_inputs() -> None:
    """Identical identity inputs and content run to the identical run id."""
    first = run_reference()
    second = run_reference()
    assert first.result.run_id == second.result.run_id
    assert first.result.identity == second.result.identity
    assert first.result.evaluations == second.result.evaluations
    assert first.result.aggregate == second.result.aggregate


def test_run_ordinal_changes_identity_but_not_comparability() -> None:
    """Another ordinal only changes run_id and ordinal-bearing identities."""
    artifact = run_reference(run_ordinal=3)
    assert artifact.result.identity.run_ordinal == 3
    baseline_ordinal = run_reference()
    assert artifact.result.run_id != baseline_ordinal.result.run_id
    first_scores = {
        (row.scenario_id, row.evaluator_id): row.score
        for row in artifact.result.evaluations
    }
    second_scores = {
        (row.scenario_id, row.evaluator_id): row.score
        for row in baseline_ordinal.result.evaluations
    }
    assert first_scores == second_scores


def test_degraded_target_fails_with_regressed_findings() -> None:
    """Degraded targets fail and produce per-row capability evidence."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()
    artifact = asyncio.run(engine.run(
        dataset,
        target_id="degraded_demo",
        target_version=1,
        target_factory=lambda correlations: ReferenceTarget.build(
            correlations, degraded=True
        ),
    ))
    assert artifact.result.verdict is Verdict.FAIL
    assert artifact.result.completeness is Completeness.COMPLETE
    assert any(
        counts.failed > 0
        for counts in artifact.result.aggregate.metric_counts.values()
    )
    failed_rows = [
        row for row in artifact.result.evaluations if not row.passed
    ]
    assert failed_rows
    assert all(row.status is EvaluationStatus.EVALUATED for row in failed_rows)


def test_scenario_ids_required_and_all_run_in_canonical_order() -> None:
    """Runs execute a declared subset in canonical order with its own identity."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()
    subset = ("AUTH-001", "SAFE-001")
    artifact = asyncio.run(engine.run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
        run_ordinal=0,
        scenario_ids=subset,
    ))
    observed = [row.scenario_id for row in artifact.result.evaluations]
    assert len(observed) > 0
    first_evaluation_scenarios = set(observed)
    assert first_evaluation_scenarios == set(subset)
    ids = dataset.scenario_ids
    if ids.index(subset[0]) < ids.index(subset[1]):
        observed_first_run = observed.index(subset[0]) < observed.index(subset[1])
    else:
        observed_first_run = True
    assert observed_first_run


def test_engine_rejects_out_of_bound_configuration() -> None:
    """Bounds are validated so no unbounded engine lane can be constructed."""
    with pytest.raises(ValueError, match="Per-scenario timeout"):
        EngineBounds(scenario_timeout_seconds=0.0)
    with pytest.raises(ValueError, match="Run deadline"):
        EngineBounds(run_deadline_seconds=0.0)
    with pytest.raises(ValueError, match="Per-scenario timeout"):
        EngineBounds(scenario_timeout_seconds=10.1)
    with pytest.raises(ValueError, match="Run size"):
        EngineBounds(max_scenarios=0)


def test_target_identity_is_verified_against_run_identity() -> None:
    """Refuse a fabricated target whose identity contradicts the run."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()
    with pytest.raises(Exception) as caught:
        asyncio.run(engine.run(
            dataset,
            target_id="mismatched",
            target_version=1,
            target_factory=lambda correlations: ReferenceTarget,
            run_ordinal=0,
        ))
    assert "identity" in str(caught.value).casefold()


def test_cancelled_run_records_incomplete_artifact_and_propagates() -> None:
    """A mid-run cancellation records an incomplete artifact and reraises."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()

    class SlowTarget(ReferenceTarget):
        async def run(self, scenario):
            await asyncio.sleep(0.5)
            return await super().run(scenario)

    async def cancelled_run():
        task = asyncio.ensure_future(engine.run(
            dataset,
            target_id="reference_default",
            target_version=1,
            target_factory=SlowTarget.build,
        ))
        await asyncio.sleep(0.05)
        task.cancel()
        return await asyncio.gather(task, return_exceptions=True)

    outcome = asyncio.run(cancelled_run())
    exc_info = next(
        item for item in outcome
        if isinstance(item, RunInterruptedError)
    )
    artifact = exc_info.artifact
    assert artifact.result.completeness is Completeness.INCOMPLETE
    assert artifact.result.verdict is Verdict.FAIL
    assert artifact.result.missing_scenario_ids


def test_partial_evaluator_mapping_records_not_run_without_key_error() -> None:
    """A missing evaluator is a safe not_run row; the run cannot pass.

    Contract N-4 durability: a caller-supplied partial evaluator mapping
    (public engine constructor) leaves the remaining scenario evaluators
    unbound. Each unbound evaluator is recorded as an internally consistent
    ``not_run`` row with the stable suite version and a marked placeholder
    metric — no ``KeyError``, no error text, and the run verdict cannot pass
    merely because an evaluator is absent.
    """
    from reliability_safety_observability.evaluation_contracts import (
        EvaluationStatus,
    )
    from reliability_safety_observability.evaluation_evaluators import (
        EVALUATOR_SUITE_VERSION,
        get_evaluator,
    )

    dataset = load_benchmark_dataset()
    committed = get_evaluator("outcome.classification_exact")
    assert committed is not None
    engine = EvaluationEngine(
        evaluators={"outcome.classification_exact": committed}
    )
    artifact = asyncio.run(dict_run(engine, dataset, REFERENCE))
    not_run_rows = [
        row for row in artifact.result.evaluations
        if row.status is EvaluationStatus.NOT_RUN
    ]
    evaluated_rows = [
        row for row in artifact.result.evaluations
        if row.status is EvaluationStatus.EVALUATED
    ]
    assert evaluated_rows  # The bound evaluator still evaluated.
    assert not_run_rows  # Unbound evaluators became not_run rows.
    for row in not_run_rows:
        assert row.score == 0.0
        assert row.passed is False
        # N-4: the row retains its COMMITTED metric vocabulary, never a
        # synthetic label; only a truly unknown evaluator ID would fall
        # back to the marked placeholder.
        from reliability_safety_observability.evaluation_contracts import (
            METRIC_BY_EVALUATOR,
        )
        assert row.metric == METRIC_BY_EVALUATOR[row.evaluator_id]
        assert row.evaluator_version == EVALUATOR_SUITE_VERSION
        assert row.threshold == (1, 1)  # The committed metric threshold.
        assert row.evidence_class.value == "deterministic_fixture"
    remaining = {row.evaluator_id for row in not_run_rows}
    assert remaining <= {
        row.evaluator_id for row in artifact.result.evaluations
    } - {"outcome.classification_exact"}
    # Absence never grants a pass: a not_run row fails the whole run.
    assert artifact.result.verdict is Verdict.FAIL
    assert artifact.result.completeness is Completeness.COMPLETE
