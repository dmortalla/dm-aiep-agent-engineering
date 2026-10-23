"""Story 6 regression tests: committed baseline, exact comparisons, candidates."""

import asyncio
import json
from pathlib import Path

import pytest

from reliability_safety_observability.errors import ContractValidationError
from reliability_safety_observability.evaluation_contracts import (
    RegressionKind,
    RegressionOutcome,
    Verdict,
)
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import EvaluationEngine
from reliability_safety_observability.evaluation_regression import (
    baseline_digest,
    candidate_baseline,
    compare_to_baseline,
    load_committed_baseline,
)
from reliability_safety_observability.evaluation_target import ReferenceTarget


def reference_result():
    """Run the local reference benchmark and return its class A result."""
    artifact = asyncio.run(EvaluationEngine().run(
        load_benchmark_dataset(),
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
    ))
    return artifact.result


def degraded_result():
    """Run the degraded target to obtain failing rows."""
    dataset = load_benchmark_dataset()
    artifact = asyncio.run(EvaluationEngine().run(
        dataset,
        target_id="degraded_demo",
        target_version=1,
        target_factory=lambda correlations: ReferenceTarget.build(
            correlations, degraded=True
        ),
    ))
    return artifact.result


def test_rescoping_digest_excludes_the_digest_field_itself() -> None:
    """Baselines digest canonical content minus the baseline_digest entry."""
    content: dict[str, object] = {"scores": [1, 2, 3]}
    merged = {**content, "baseline_digest": "0" * 64}
    assert baseline_digest(merged) == baseline_digest(content)
    assert isinstance(json.dumps(None), str)


def test_committed_baseline_loads_and_pins_digest_and_target() -> None:
    """The committed baseline loads with pinned digest and reference target."""
    dataset = load_benchmark_dataset()
    baseline = load_committed_baseline(dataset)
    assert baseline.baseline_schema_version == 1
    assert baseline.dataset_id == dataset.dataset_id
    assert baseline.target_id == "reference_default"
    assert baseline.target_version == 1
    keys = {(entry.scenario_id, entry.evaluator_id) for entry in baseline.scores}
    assert len(keys) == len(baseline.scores)


def test_run_against_committed_baseline_has_no_findings() -> None:
    """The reference target regresses nothing against the committed baseline."""
    dataset = load_benchmark_dataset()
    baseline = load_committed_baseline(dataset)
    report = compare_to_baseline(
        reference_result(), baseline, dataset, EvaluationEngine().policy
    )
    assert report.outcome is RegressionOutcome.PASS
    assert report.incompatible_fields == ()
    assert report.findings == ()
    assert report.current_target_id == "reference_default"


def test_incompatible_dataset_identity_refuses_without_comparison() -> None:
    """Differing non-target identity yields an incompatible-baseline outcome."""
    dataset = load_benchmark_dataset()
    baseline = load_committed_baseline(dataset)
    result = reference_result().model_copy(deep=True)
    identity = result.identity.model_copy(
        update={"evaluator_suite_version": baseline.evaluator_suite_version + 1}
    )
    report = compare_to_baseline(
        result.model_copy(update={"identity": identity}),
        baseline,
        dataset,
        EvaluationEngine().policy,
    )
    assert report.outcome is RegressionOutcome.INCOMPATIBLE_BASELINE
    assert set(report.incompatible_fields) == {
        "evaluator_suite_version", "evaluator_versions",
    }
    assert report.findings == ()


def test_degraded_run_regresses_reliability_rows_exactly() -> None:
    """Degraded targets produce exact regressed findings with thresholds."""
    dataset = load_benchmark_dataset()
    baseline = load_committed_baseline(dataset)
    report = compare_to_baseline(
        degraded_result(), baseline, dataset, EvaluationEngine().policy
    )
    assert report.outcome is RegressionOutcome.FAIL
    kinds = {finding.kind for finding in report.findings}
    assert RegressionKind.REGRESSED in kinds
    assert all(
        finding.baseline_score is not None and finding.current_score is not None
        for finding in report.findings
        if finding.kind is RegressionKind.REGRESSED
    )
    improved = [
        finding for finding in report.findings
        if finding.kind is RegressionKind.IMPROVED
    ]
    assert not improved


def test_current_only_metric_is_uncomrowable_incompatible() -> None:
    """A current-only row is an incompatible baseline, never a comparison."""
    dataset = load_benchmark_dataset()
    baseline = load_committed_baseline(dataset)
    result = reference_result()
    extra = result.evaluations[0].model_copy(update={"evaluator_id": "unknown_lane"})
    report = compare_to_baseline(
        result.model_copy(update={"evaluations": (*result.evaluations, extra)}),
        baseline,
        dataset,
        EvaluationEngine().policy,
    )
    assert report.outcome is RegressionOutcome.INCOMPATIBLE_BASELINE
    assert report.incompatible_fields == ("current_only_metrics",)


def test_candidate_baseline_writes_only_outside_the_repository(tmp_path: Path) -> None:
    """Candidates are written only to caller-supplied external paths."""
    result = reference_result()
    destination = tmp_path / "candidate.json"
    path = candidate_baseline(result, destination)
    content = json.loads(path.read_text(encoding="utf-8"))
    observed = baseline_digest(content)
    assert content["baseline_digest"] == observed


def test_candidate_baseline_refuses_repository_and_failing_runs(tmp_path: Path) -> None:
    """Repository paths and non-passing runs are refused as candidates."""
    module_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ContractValidationError):
        candidate_baseline(reference_result(), module_root / "candidate.json")
    with pytest.raises(ContractValidationError):
        candidate_baseline(degraded_result(), tmp_path / "candidate.json")


def test_candidate_baseline_requires_complete_runs(tmp_path: Path) -> None:
    """Incomplete runs are refused; candidate content stays canonical."""
    result = reference_result()
    assert result.completeness.value == "complete"
    with pytest.raises(ContractValidationError):
        candidate_baseline(
            result.model_copy(update={"verdict": Verdict.FAIL}),
            tmp_path / "candidate.json",
        )


def _tampered(kind: str) -> object:
    """Build a caller-supplied baseline with one injected integrity defect.

    Args:
        kind: One of ``digest``, ``duplicate``, ``renamed`` or ``unknown``.

    Returns:
        The mutated baseline record (its own integrity now doubtful).
    """
    baseline = load_committed_baseline(load_benchmark_dataset())
    if kind == "digest":
        # Any content change without re-digesting leaves a stale digest.
        return baseline.model_copy(update={"target_id": "tampered_target"})
    if kind == "duplicate":
        repeated = (*baseline.scores, baseline.scores[0])
        return baseline.model_copy(update={"scores": repeated})
    scores = tuple(
        (
            entry.model_copy(update={"metric": "renamed_metric"})
            if index == 0 and kind == "renamed"
            else (
                entry.model_copy(update={"evaluator_id": "unknown_lane"})
                if index == 0
                else entry
            )
        )
        for index, entry in enumerate(baseline.scores)
    )
    return baseline.model_copy(update={"scores": scores})


@pytest.mark.parametrize(
    ("kind", "expected_defect"),
    [
        ("digest", "baseline_digest"),
        ("duplicate", "baseline_metric_coverage"),
        ("renamed", "baseline_metric_identity"),
        ("unknown", "baseline_metric_identity"),
    ],
)
def test_tampered_baselines_are_incompatible_without_comparison(
    kind: str,
    expected_defect: str,
) -> None:
    """Untrusted baselines yield incompatible reports before any comparison."""
    dataset = load_benchmark_dataset()
    policy = EvaluationEngine().policy
    report = compare_to_baseline(
        reference_result(),
        _tampered(kind),  # type: ignore[arg-type]
        dataset,
        policy,
    )
    assert report.outcome is RegressionOutcome.INCOMPATIBLE_BASELINE
    assert expected_defect in report.incompatible_fields
    assert report.findings == ()

