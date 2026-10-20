"""REQ-LAB-006/DEL-004 and Story 10 integrated authority/security evidence."""

import json
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from harness_engineering.anomaly_signals import RULES, AnomalyDetector
from harness_engineering.cost_governance import (
    FixtureLedger,
    LedgerError,
    require_real_monetary_admission,
)
from harness_engineering.domain import EvidenceClass
from harness_engineering.errors import AuthorityViolationError
from harness_engineering.latency import Measurement, Outcome
from harness_engineering.observability import LocalTelemetrySink, TelemetrySession, TraceContext
from harness_engineering.observability_lab import run_observability_lab
from harness_engineering.observability_presentation import PresentationError, render_report
from harness_engineering.observability_report import LabConfig, ObservabilityReport
from harness_engineering.usage import UsageCapture, UsageFacts, UsageState

SECRET = "SENTINEL-PROMPT-OUTPUT-AUTHORIZATION-EXCEPTION-DO-NOT-EXPORT"


@pytest.fixture(autouse=True)
def zero_network(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    attempts = [0]

    def denied(*args: object, **kwargs: object) -> None:
        attempts[0] += 1
        raise OSError("Offline lab network attempt")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for key in ("OPENAI_API_KEY", "LANGSMITH_API_KEY", "LANGFUSE_SECRET_KEY", "HELICONE_API_KEY"):
        monkeypatch.setenv(key, SECRET)
    yield attempts
    assert attempts == [0], "Blocked attempts are not zero attempts"


def test_runnable_services_trace_cost_and_read_only_dashboard(tmp_path: Path) -> None:
    directory = tmp_path / "lab"
    report = run_observability_lab(directory)
    assert report.phase == "completed"
    assert report.cost.committed_units == 120
    assert report.cost.outstanding_units == 40
    assert report.cost.cap_units == 160
    assert report.cost.warnings == (80, 100)
    assert report.hard_cap_denied and report.recovery_preserved
    assert len(report.usage) == 3
    assert {r.usage.state for r in report.usage} == {UsageState.LOCAL}
    assert all(a.verified_billing_units is None for a in report.cost.attempts)
    assert report.cost.attempts[-1].usage.state is UsageState.TIMEOUT
    assert len(report.anomalies) == len(RULES) == 6
    assert {s.facts.kind for s in report.anomalies} == set(RULES)
    assert all(not state.enabled and state.health.exported == 0 for state in report.integrations)
    assert report.workflow_cohort.sample_count == 1
    assert report.workflow_cohort.slo_met is None
    assert not report.workflow_cohort.sufficient_samples
    starts = [e for e in report.events if e.kind.value == "started"]
    root = next(e for e in starts if e.measurement is Measurement.WORKFLOW)
    actions = [e for e in starts if e.measurement is Measurement.ACTION]
    assert {e.step_index for e in actions} == {1, 2}
    assert all(e.parent_span_id == root.trace.span_id for e in actions)
    providers = [e for e in starts if e.measurement is Measurement.PROVIDER]
    assert len(providers) == 3
    assert all(e.parent_span_id in {a.trace.span_id for a in actions} for e in providers)
    assert len({e.trace.trace_id for e in report.events}) == 1
    before = report.model_dump_json()
    for _ in range(2):
        text = render_report(report)
        assert "insufficient_samples" in text
        assert "committed=120 outstanding=40 cap=160" in text
        assert "unavailable (local/uncertain)" in text
        assert "fixture" in text and "structured logs" in text
        assert SECRET not in text
        assert "Deterministic provider response." not in text
        assert json.loads(render_report(report, format="json"))["cost"]["cap_units"] == 160
    assert report.model_dump_json() == before
    assert (directory / "1" / "cost.sqlite").exists()
    with pytest.raises(FileExistsError):
        run_observability_lab(directory)


def test_twenty_whole_workflows_have_a_real_bounded_cohort(tmp_path: Path) -> None:
    report = run_observability_lab(tmp_path / "twenty", LabConfig(samples=20))
    cohort = report.workflow_cohort
    assert cohort.sample_count == 20 and cohort.sufficient_samples
    assert cohort.cohort.outcome is Outcome.SUCCEEDED
    assert cohort.slo_met == (cohort.p95_seconds <= 5.0)
    assert len(tuple((tmp_path / "twenty").glob("*/cost.sqlite"))) == 20
    assert len(report.events) <= 512 and len(report.usage) == 3
    assert len(report.latency) <= 36


def test_semantic_fixture_results_repeat_without_fixing_runtime_ids(tmp_path: Path) -> None:
    left = run_observability_lab(tmp_path / "left")
    right = run_observability_lab(tmp_path / "right")
    assert left.identity != right.identity
    for report in (left, right):
        assert (report.cost.committed_units, report.cost.outstanding_units) == (120, 40)
        assert report.cost.warnings == (80, 100)
        assert report.workflow_cohort.sample_count == 1
        assert {s.facts.kind for s in report.anomalies} == set(RULES)


@pytest.mark.parametrize("changes", [
    {"samples": True}, {"samples": 0}, {"samples": 21}, {"samples": 1.0},
    {"offline_sdk": "true"}, {"evidence": "deployment"}, {"prompt": SECRET},
    {"api_key": SECRET}, {"retry_budget": 99}, {"permissions": ["all"]},
    {"hitl": False}, {"off_switch": False}, {"max_cost_usd": 999},
])
def test_invalid_lab_configuration_has_no_effects(tmp_path: Path, changes: dict) -> None:
    config = LabConfig().model_copy(update=changes)
    with pytest.raises(ValidationError) as caught:
        run_observability_lab(tmp_path / "absent", config)
    assert SECRET not in str(caught.value)
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("change", [
    {"evidence": EvidenceClass.DEPLOYMENT}, {"identity": {"workflow_id": uuid4()}},
    {"metadata": {"prompt": SECRET}}, {"routing": "admin"}, {"permissions": ["all"]},
])
def test_presentation_rejects_forgery_without_authority_effect(
    tmp_path: Path, change: dict,
) -> None:
    report = run_observability_lab(tmp_path / "lab")
    before = report.model_dump_json()
    with pytest.raises(PresentationError) as caught:
        render_report(report.model_copy(update=change))
    assert SECRET not in str(caught.value)
    assert report.model_dump_json() == before
    for value in (report, report.cost, report.helicone, report.anomalies, report.integrations,
                  report.usage, {"approved": True, "credential": SECRET}, TraceContext(
                      trace_id="1" * 32, span_id="2" * 16)):
        with pytest.raises(AuthorityViolationError):
            require_real_monetary_admission(live_enabled=True, approved_tariff=value)


def test_sink_and_anomaly_projection_failure_preserves_durable_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise ValueError(SECRET)

    monkeypatch.setattr(LocalTelemetrySink, "emit", fail)
    report = run_observability_lab(tmp_path / "sink")
    assert not report.events and report.telemetry_failures > 0
    assert report.cost.committed_units == 120 and report.cost.outstanding_units == 40
    assert len(report.anomalies) == 6
    monkeypatch.setattr(TelemetrySession, "record_governance", fail)
    report = run_observability_lab(tmp_path / "anomaly")
    assert report.advisory_failures > 0
    assert len(report.anomalies) == 6
    assert report.cost.warnings == (80, 100)
    assert SECRET not in render_report(report)


@pytest.mark.parametrize("failure", ["unavailable", "construction", "timeout"])
def test_exporter_outage_cannot_change_integrated_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    calls = []

    def run(*args: object, **kwargs: object) -> object:
        calls.append(kwargs["timeout"])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(SECRET, 10)
        return SimpleNamespace(stdout=failure, returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    report = run_observability_lab(tmp_path / "lab", LabConfig(offline_sdk=True))
    assert calls == [10, 10]
    assert all(v.health.failure == failure and v.health.dropped > 0 for v in report.integrations)
    assert report.cost.committed_units == 120 and report.cost.outstanding_units == 40
    assert report.hard_cap_denied and report.recovery_preserved
    assert SECRET not in render_report(report)


def test_renderer_failure_does_not_rewrite_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = run_observability_lab(tmp_path / "lab")
    before = report.cost

    def fail(*args: object, **kwargs: object) -> None:
        raise ValueError(SECRET)

    monkeypatch.setattr(ObservabilityReport, "model_dump_json", fail)
    with pytest.raises(PresentationError) as caught:
        render_report(report)
    assert SECRET not in str(caught.value)
    assert report.cost == before


def test_duplicate_and_late_usage_cannot_refund_fixture_exposure(tmp_path: Path) -> None:
    report = run_observability_lab(tmp_path / "lab")
    # Reconstruct only from the actual durable header/policy, never the dashboard.
    import sqlite3

    from harness_engineering.cost_governance import LedgerPolicy

    path = tmp_path / "lab" / "1" / "cost.sqlite"
    with sqlite3.connect(path) as db:
        policy = LedgerPolicy.model_validate_json(db.execute(
            "SELECT payload FROM cost_header").fetchone()[0])
    ledger = FixtureLedger(path, policy)
    uncertain = ledger.snapshot().attempts[-1]
    capture = UsageCapture()
    assert capture.close(UsageState.TIMEOUT).state is UsageState.TIMEOUT
    capture.report(UsageFacts(state=UsageState.REPORTED, input_tokens=1, output_tokens=1))
    assert capture.late
    with pytest.raises(LedgerError):
        ledger.settle(uncertain.reservation,
                      UsageFacts(state=UsageState.REPORTED, input_tokens=1, output_tokens=1))
    assert ledger.snapshot() == report.cost


@pytest.mark.parametrize("before,after,signal", [
    (100, 10, True), (100, 11, False), (100, 100, False),
])
def test_compression_rule_uses_counts_not_content(before: int, after: int, signal: bool) -> None:
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC)
    detector.observe_compression(before, after)
    assert bool(detector.snapshot()) == signal


@pytest.mark.parametrize("before,after", [(True, 0), (1, -1), (12001, 1), (100, 1.0)])
def test_compression_rule_rejects_malformed_numeric_facts(before: object, after: object) -> None:
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC)
    with pytest.raises(ValueError):
        detector.observe_compression(before, after)
