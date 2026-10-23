"""Story 6 benchmark tests: canonical reports, selection bounds, verdicts."""

import asyncio

import pytest

from reliability_safety_observability.evaluation_benchmark import (
    BenchmarkOutput,
    BenchmarkRunner,
    benchmark_report,
    select_export_subset,
)
from reliability_safety_observability.evaluation_contracts import (
    RegressionOutcome,
    Verdict,
    canonical_digest,
)
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import EvaluationEngine
from reliability_safety_observability.evaluation_regression import (
    load_committed_baseline,
)
from reliability_safety_observability.evaluation_target import ReferenceTarget


async def run_reference(ordinal=0, baseline=None, target_id="reference_default"):
    """Run one reference benchmark with the committed dataset."""
    runner = BenchmarkRunner(EvaluationEngine())
    return await runner.run_full(
        load_benchmark_dataset(),
        target_factory=ReferenceTarget.build,
        target_id=target_id,
        target_version=1,
        run_ordinal=ordinal,
        baseline=baseline,
    )


def test_reference_benchmark_passes_with_canonical_report() -> None:
    """The reference run produces a passing, digest-bound canonical report."""
    output = asyncio.run(run_reference())
    assert isinstance(output, BenchmarkOutput)
    assert output.verdict is Verdict.PASS
    assert output.regression is None
    assert output.subset is None
    assert output.report_digest == canonical_digest(output.report_json)
    parsed = __import__("json").loads(output.report_json)
    assert parsed["run"]["verdict"] == Verdict.PASS.value
    assert parsed["regression"] is None
    assert parsed["subset"] is None


def test_identical_runs_produce_byte_identical_reports() -> None:
    """Deterministic runs digest identically; no wall-clock data participates."""
    first = asyncio.run(run_reference())
    second = asyncio.run(run_reference())
    assert first.report_json == second.report_json
    assert first.report_digest == second.report_digest


def test_report_carries_declared_subset_and_no_unknown_fields() -> None:
    """Declared subsets appear in the canonical report when supplied."""
    dataset = load_benchmark_dataset()
    artifact = asyncio.run(EvaluationEngine().run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
        scenario_ids=("AUTH-001",),
    ))
    report = benchmark_report(artifact, ("AUTH-001",), None)
    parsed = __import__("json").loads(report)
    assert parsed["subset"] == ["AUTH-001"]
    second = benchmark_report(artifact, ("AUTH-001",), None)
    assert report == second


def test_select_export_subset_bounds_and_none_for_full_dataset() -> None:
    """Selection is a bounded declared subset; full dataset selects None."""
    dataset = load_benchmark_dataset()
    assert select_export_subset(dataset, limit=2) == ("AUTH-001", "AUTH-002")
    assert select_export_subset(dataset, limit=64) is None
    with pytest.raises(ValueError):
        select_export_subset(dataset, limit=0)
    with pytest.raises(ValueError):
        select_export_subset(dataset, limit=65)


def test_run_with_committed_baseline_passes_regression() -> None:
    """The reference run vs. the committed baseline stays at PASS."""
    baseline = load_committed_baseline(load_benchmark_dataset())
    output = asyncio.run(run_reference(baseline=baseline))
    assert output.regression is not None
    assert output.regression.outcome is RegressionOutcome.PASS
    assert output.regression.findings == ()
    assert output.verdict is Verdict.PASS


def test_degraded_run_with_baseline_fails_and_reports_regressions() -> None:
    """A degraded target fails the baseline comparison and the verdict."""
    dataset = load_benchmark_dataset()
    baseline = load_committed_baseline(dataset)
    runner = BenchmarkRunner(EvaluationEngine())
    output = asyncio.run(runner.run_full(
        dataset,
        target_factory=lambda correlations: ReferenceTarget.build(
            correlations, degraded=True
        ),
        target_id="degraded_demo",
        target_version=1,
        baseline=baseline,
    ))
    assert output.regression.outcome is RegressionOutcome.FAIL
    assert output.regression.findings
    assert output.verdict is Verdict.FAIL
    assert any(
        finding.scenario_id == "REL-001" for finding in output.regression.findings
    )
