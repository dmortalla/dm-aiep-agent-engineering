"""Slice 3: genuine SDKs over offline boundaries, never hosted evidence."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from harness_engineering import observability_adapters as adapters
from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.governance_facts import GovernanceFacts, GovernanceKind
from harness_engineering.latency import Measurement
from harness_engineering.observability import TelemetrySession, current_trace
from harness_engineering.observability_adapters import OfflineObservabilityAdapter, Vendor

SECRET = "SECRET-PROMPT-OUTPUT-CREDENTIAL-EXCEPTION-SENTINEL"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith(("LANGSMITH", "LANGCHAIN", "LANGFUSE", "OTEL")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("LANGSMITH_CONFIG_FILE", os.devnull)
    monkeypatch.setenv("LANGFUSE_MEDIA_UPLOAD_ENABLED", "false")

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network attempted by offline SDK test")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def source() -> TelemetrySession:
    result = TelemetrySession(WorkflowIdentity(), evidence=EvidenceClass.DETERMINISTIC)
    assert result.call(Measurement.WORKFLOW, lambda: SECRET) == SECRET
    result.record_governance(GovernanceFacts(kind=GovernanceKind.EXPOSURE,
                                           exposure_units=80, cap_units=100))
    return result


def sdk_probe(vendor: Vendor, events: tuple, phase: str = "serialize") -> dict:
    """Run each SDK lifecycle in a fresh process, just like production flush."""
    pytest.importorskip(vendor.value)
    environment = {"LANGSMITH_CONFIG_FILE": os.devnull,
                   "LANGFUSE_MEDIA_UPLOAD_ENABLED": "false"}
    if "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).with_name("observability_sdk_probe.py")),
         vendor.value, phase], input=json.dumps([e.model_dump(mode="json") for e in events]),
        text=True, capture_output=True, timeout=10, check=True, env=environment,
    )
    parsed = json.loads(result.stdout)
    assert parsed["network_attempts"] == 0
    return parsed


@pytest.mark.parametrize("vendor", list(Vendor))
def test_genuine_sdk_serialization_privacy_and_correlation(vendor: Vendor) -> None:
    pytest.importorskip(vendor.value)
    telemetry = source()
    events = telemetry.sink.snapshot()
    records = sdk_probe(vendor, events)["records"]
    encoded = json.dumps(records)
    assert SECRET not in encoded
    assert str(telemetry.identity.workflow_id) in encoded
    assert str(telemetry.identity.thread_id) in encoded
    assert "deterministic" in encoded
    assert "exposure_units" in encoded
    for event in events:
        assert event.trace.trace_id in encoded.replace("-", "")
        assert event.trace.span_id in encoded
        assert str(event.event_id) in encoded
    assert current_trace() is None
    if vendor is Vendor.LANGSMITH:
        assert len(records) == 2 * len(events)
        for item in records:
            body = item["body"]
            assert body.get("inputs", {}) == {}
            assert body.get("outputs", {}) == {}
            assert not body.get("error")
            if item["method"] == "POST":
                assert body["extra"] == {
                    "metadata": next(e.model_dump(mode="json", exclude_none=True)
                                     for e in events if str(e.event_id) == body["id"])
                }
    else:
        assert len(records) == len(events)
        for record, event in zip(records, events, strict=True):
            assert record["trace_id"] == event.trace.trace_id
            assert record["parent_span_id"] == event.trace.span_id
            assert not any("input" in k or "output" in k for k in record["attributes"])


@pytest.mark.parametrize("vendor", list(Vendor))
def test_real_isolated_worker_ignores_hostile_environment(
    vendor: Vendor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip(vendor.value)
    for key in ("LANGSMITH_API_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_RELEASE",
                "LANGSMITH_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.setenv(key, SECRET)
    telemetry = source()
    adapter = OfflineObservabilityAdapter(telemetry, vendor, enabled=True)
    for event in telemetry.sink.snapshot():
        assert adapter.enqueue(event)
    adapter.flush()
    assert adapter.health().exported == 3
    assert adapter.health().pending == 0
    assert adapter.health().failure is None
    adapter.close()
    assert adapter.health().closed


@pytest.mark.parametrize("category", ["unavailable", "construction", "create", "update",
                                     "flush", "close", "unexpected-" + SECRET])
@pytest.mark.parametrize("vendor", list(Vendor))
def test_failure_categories_never_propagate_or_retain_external_payload(
    category: str, vendor: Vendor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry = source()
    before = telemetry.sink.snapshot(), telemetry.reports(), telemetry.failures
    adapter = OfflineObservabilityAdapter(telemetry, vendor, enabled=True)
    for event in telemetry.sink.snapshot():
        adapter.enqueue(event)

    def run(*args: object, **kwargs: object) -> object:
        assert SECRET not in kwargs["input"]
        assert kwargs["timeout"] == 10
        assert set(kwargs["env"]) <= {
            "SYSTEMROOT", "LANGSMITH_CONFIG_FILE", "LANGFUSE_MEDIA_UPLOAD_ENABLED"
        }
        return SimpleNamespace(stdout=category, returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    adapter.flush()
    adapter.flush()  # No retry of a failed batch.
    assert adapter.health().dropped == 3
    assert adapter.health().exported == 0
    assert SECRET not in str(adapter.health())
    assert before == (telemetry.sink.snapshot(), telemetry.reports(), telemetry.failures)


@pytest.mark.parametrize("failure", [OSError(SECRET), subprocess.TimeoutExpired(SECRET, 10)])
def test_process_failure_is_bounded(failure: Exception, monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = source()
    adapter = OfflineObservabilityAdapter(telemetry, Vendor.LANGSMITH, enabled=True)
    adapter.enqueue(telemetry.sink.snapshot()[0])

    def fail(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    adapter.flush()
    assert adapter.health().dropped == 1
    assert adapter.health().failure in ("timeout", "unavailable")
    assert SECRET not in str(adapter.health())


def test_disabled_missing_configuration_and_close_do_not_construct_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Disabled/closed/busy exporter invoked a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    telemetry = source()
    adapter = OfflineObservabilityAdapter(telemetry, Vendor.LANGSMITH)
    assert not adapter.enqueue(telemetry.sink.snapshot()[0])
    adapter.flush()
    adapter.close()
    adapter.close()
    adapter.flush()
    assert adapter.health().dropped == 1
    active = OfflineObservabilityAdapter(telemetry, Vendor.LANGFUSE, enabled=True)
    active.enqueue(telemetry.sink.snapshot()[0])
    assert adapters._DRAIN.acquire(blocking=False)
    try:
        active.flush()
        assert active.health().pending == 1
        active.close()
        assert active.health().dropped == 1
    finally:
        adapters._DRAIN.release()


@pytest.mark.parametrize("change", [
    {"workflow_id": uuid4()}, {"thread_id": uuid4()},
    {"evidence": EvidenceClass.LIVE_PROVIDER}, {"segment_id": uuid4()},
    {"trace": {"trace_id": "1" * 32, "span_id": "2" * 16}},
    {"prompt": SECRET}, {"metadata": {"credential": SECRET}}, {"sequence": True},
])
def test_forged_or_malformed_projection_is_rejected(change: dict[str, object]) -> None:
    telemetry = source()
    adapter = OfflineObservabilityAdapter(telemetry, Vendor.LANGSMITH, enabled=True)
    event = telemetry.sink.snapshot()[0].model_copy(update=change)
    assert not adapter.enqueue(event)
    assert adapter.health().failure == "projection"
    assert SECRET not in str(adapter.health())


def test_capacity_replay_drop_counters_and_no_unbounded_registry() -> None:
    telemetry = source()
    for _ in range(40):
        telemetry.call(Measurement.ACTION, lambda: None)
    adapter = OfflineObservabilityAdapter(telemetry, Vendor.LANGSMITH, enabled=True)
    events = telemetry.sink.snapshot()
    assert sum(adapter.enqueue(e) for e in events) == 64
    assert adapter.health().pending == 64
    assert adapter.health().dropped == len(events) - 64
    assert not adapter.enqueue(events[-1])
    adapter._dropped = 1_000_000
    adapter.enqueue(events[-1])
    assert adapter.health().dropped == 1_000_000
    adapter.close()
    assert adapter.health().pending == 0


@pytest.mark.parametrize("evidence", [EvidenceClass.LIVE_PROVIDER, EvidenceClass.DEPLOYMENT])
def test_fixture_boundary_rejects_live_evidence(evidence: EvidenceClass) -> None:
    telemetry = TelemetrySession(WorkflowIdentity(), evidence=evidence)
    with pytest.raises(ValueError):
        OfflineObservabilityAdapter(telemetry, Vendor.LANGSMITH, enabled=True)


@pytest.mark.parametrize("vendor", list(Vendor))
@pytest.mark.parametrize("phase", ["construction", "create", "update", "flush", "close"])
def test_actual_sdk_method_failures_are_normalized(
    phase: str, vendor: Vendor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = sdk_probe(vendor, source().sink.snapshot(), phase)
    assert result["failure"] == phase
    assert SECRET not in json.dumps(result)


def test_langfuse_lifecycle_limitation_and_repeatable_fresh_processes() -> None:
    events = source().sink.snapshot()
    assert sdk_probe(Vendor.LANGFUSE, events, "repeat")["repeat_failure"] == "flush"
    for _ in range(2):
        assert len(sdk_probe(Vendor.LANGFUSE, events)["records"]) == len(events)


@pytest.mark.parametrize("vendor", list(Vendor))
def test_export_failure_cannot_change_accounting_or_anomalies(
    tmp_path: Path, vendor: Vendor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness_engineering.anomaly_signals import AnomalyDetector
    from harness_engineering.cost_governance import FixtureLedger
    from tests.test_cost_governance import policy

    bound_policy = policy(cap=10)
    telemetry = TelemetrySession(WorkflowIdentity(workflow_id=bound_policy.workflow_id,
                                                thread_id=bound_policy.thread_id),
                                 evidence=EvidenceClass.DETERMINISTIC)
    anomalies = AnomalyDetector(evidence=telemetry.evidence, telemetry=telemetry)
    ledger = FixtureLedger(tmp_path / "cost.sqlite", bound_policy, create=True,
                           telemetry=telemetry, anomalies=anomalies)
    reservation = ledger.reserve(1)
    before = ledger.snapshot(), anomalies.snapshot()
    assert reservation is not None
    assert before[0].outstanding_units == 10
    assert before[1]
    telemetry.call(Measurement.WORKFLOW, lambda: SECRET)
    adapter = OfflineObservabilityAdapter(telemetry, vendor, enabled=True)
    for event in telemetry.sink.snapshot():
        adapter.enqueue(event)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout="create", returncode=0))
    adapter.flush()
    assert before == (ledger.snapshot(), anomalies.snapshot())
