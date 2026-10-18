"""REQ-COST-002: deterministic percentile mechanics, not performance evidence."""

import pytest
from pydantic import ValidationError

from harness_engineering.domain import EvidenceClass
from harness_engineering.latency import (
    Cohort,
    LatencyReport,
    LatencyWindow,
    Measurement,
    Outcome,
    TimingSource,
)


def window(
    *, measurement: Measurement = Measurement.WORKFLOW, outcome: Outcome = Outcome.SUCCEEDED,
    evidence: EvidenceClass = EvidenceClass.DETERMINISTIC,
    timing: TimingSource = TimingSource.MONOTONIC,
) -> LatencyWindow:
    return LatencyWindow(Cohort(
        measurement=measurement, outcome=outcome, evidence=evidence, timing=timing,
    ))


def test_empty_and_one_sample() -> None:
    samples = window()
    empty = samples.report()
    assert empty.sample_count == 0
    assert empty.p50_seconds is empty.p95_seconds is empty.slo_met is None
    samples.add(0.0)
    single = samples.report()
    assert single.sample_count == 1
    assert single.p50_seconds == single.p95_seconds == 0.0
    assert not single.sufficient_samples and single.slo_met is None


@pytest.mark.parametrize("n,p50,p95", [(2, 1.0, 2.0), (19, 10.0, 19.0), (20, 10.0, 19.0),
                                        (21, 11.0, 20.0), (100, 50.0, 95.0)])
def test_nearest_rank_including_unsorted_samples(n: int, p50: float, p95: float) -> None:
    samples = window()
    for number in range(n, 0, -1):
        samples.add(float(number))
    report = samples.report()
    assert (report.p50_seconds, report.p95_seconds) == (p50, p95)
    assert report.sufficient_samples is (n >= 20)
    assert report.slo_met is (False if n >= 20 else None)


@pytest.mark.parametrize("seconds,expected", [(5.0, True), (5.0001, False)])
def test_slo_threshold_inclusive(seconds: float, expected: bool) -> None:
    samples = window()
    for _ in range(20):
        samples.add(seconds)
    assert samples.report().slo_met is expected


@pytest.mark.parametrize("options", [
    {"measurement": Measurement.ACTION}, {"measurement": Measurement.PROVIDER},
    {"measurement": Measurement.SEGMENT},
    {"outcome": Outcome.SUSPENDED}, {"outcome": Outcome.STOPPED},
    {"outcome": Outcome.FAILED}, {"evidence": EvidenceClass.LIVE_PROVIDER},
    {"evidence": EvidenceClass.MOCKED}, {"timing": TimingSource.INJECTED},
])
def test_ineligible_cohorts_never_claim_slo_pass(options: dict[str, object]) -> None:
    samples = window(**options)
    for _ in range(20):
        samples.add(0.01)
    assert samples.report().slo_met is None


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), 86401.0, True, "1", 1])
def test_invalid_samples_fail_closed(value: object) -> None:
    samples = window()
    with pytest.raises((ValueError, ValidationError)):
        samples.add(value)
    assert samples.report().sample_count == 0


def test_retention_reports_window_and_evictions() -> None:
    samples = window()
    for value in range(1100):
        samples.add(float(value))
    report = samples.report()
    assert report.sample_count == 1000
    assert report.evicted_samples == 100
    assert report.p50_seconds == 599.0
    assert report.p95_seconds == 1049.0


@pytest.mark.parametrize("slo", [0.0, 5.1, 180.0, float("nan"), float("inf")])
def test_slo_cannot_be_replaced_by_workflow_deadline(slo: float) -> None:
    with pytest.raises(ValidationError):
        LatencyWindow(window().report().cohort, slo_p95_seconds=slo)


def test_forged_insufficient_report_cannot_claim_slo_compliance() -> None:
    report = window().report()
    with pytest.raises(ValidationError):
        LatencyReport.model_validate(report.model_copy(update={"slo_met": True}))
