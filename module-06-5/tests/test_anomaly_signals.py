"""Deterministic bounded advisory rules and safe Slice 1 projections."""

from pathlib import Path

import pytest

from harness_engineering.anomaly_signals import RULES, AnomalyDetector
from harness_engineering.cost_governance import FixtureLedger, LedgerError
from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.errors import AuthorityViolationError, ContractValidationError
from harness_engineering.governance_facts import GovernanceFacts, GovernanceKind
from harness_engineering.lifecycle_controls import OffSwitch
from harness_engineering.observability import TelemetrySession
from harness_engineering.providers import ProviderRuntime
from tests.test_cost_governance import policy


@pytest.mark.parametrize("kind", list(RULES))
def test_threshold_window_deduplication_and_rearm(kind: GovernanceKind) -> None:
    now = [0.0]
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC, clock=lambda: now[0])
    for _ in range(RULES[kind] - 1):
        assert detector.observe(kind) is None
    assert detector.observe(kind).facts.kind is kind
    for _ in range(1000):
        assert detector.observe(kind) is None
    assert len(detector.snapshot()) == 1
    now[0] = 60.0
    for _ in range(RULES[kind] - 1):
        assert detector.observe(kind) is None
    assert detector.observe(kind) is not None


def test_signal_and_window_retention_are_bounded() -> None:
    now = [0.0]
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC, clock=lambda: now[0])
    for _ in range(100):
        detector.observe(GovernanceKind.BUDGET_SPIKE)
        now[0] += 60.0
    assert len(detector.snapshot()) == 64


def test_provider_denial_and_retry_failures_remain_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness_engineering.providers import FakeProvider, ProviderExecutionError

    telemetry = TelemetrySession(WorkflowIdentity(), evidence=EvidenceClass.DETERMINISTIC)
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC, telemetry=telemetry)
    switch = OffSwitch()
    runtime = ProviderRuntime(anomalies=detector, off_switch=switch, identity=telemetry.identity)

    def fail(*args: object) -> object:
        raise ProviderExecutionError("SECRET-RAW-FAILURE")

    monkeypatch.setattr(FakeProvider, "generate", fail)
    for _ in range(3):
        with pytest.raises(ProviderExecutionError):
            runtime.generate({"prompt": "SECRET-INPUT"})
    switch.activate()
    for _ in range(3):
        with pytest.raises(AuthorityViolationError):
            runtime.generate({"prompt": "SECRET-INPUT"})
    kinds = {signal.facts.kind for signal in detector.snapshot()}
    assert kinds == {
        GovernanceKind.RETRY_BURST,
        GovernanceKind.PROVIDER_FAILURE_BURST,
        GovernanceKind.DENIAL_BURST,
    }
    assert runtime.attempts == 3 and switch.is_active()
    encoded = "".join(event.model_dump_json() for event in telemetry.sink.snapshot())
    assert "SECRET" not in encoded
    assert not telemetry.reports()  # Governance facts create no latency samples.


def test_budget_spike_uses_reservation_not_telemetry_as_source(tmp_path: Path) -> None:
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC)
    cost = FixtureLedger(tmp_path / "cost.sqlite", policy(20), create=True, anomalies=detector)
    cost.reserve(1)
    assert detector.snapshot()[0].facts.kind is GovernanceKind.BUDGET_SPIKE
    assert cost.snapshot().outstanding_units == 10


def test_rule_failure_cannot_change_provider_result_or_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC)

    def fail(*args: object) -> None:
        raise RuntimeError("SECRET")

    monkeypatch.setattr(detector, "observe", fail)
    runtime = ProviderRuntime(anomalies=detector)
    runtime.generate({"prompt": "local"})
    runtime.generate({"prompt": "local"})
    assert runtime.attempts == 2
    assert runtime.advisory_failures == 1


def test_external_fields_cannot_create_governance_evidence() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GovernanceFacts(kind=GovernanceKind.DENIAL_BURST, metadata={"approved": True})
    with pytest.raises(ValidationError):
        GovernanceFacts(kind=GovernanceKind.EXPOSURE, exposure_units=True)


@pytest.mark.parametrize(
    "facts",
    [
        {"kind": GovernanceKind.WARNING_100, "exposure_units": 1, "cap_units": 100},
        {"kind": GovernanceKind.EXPOSURE, "exposure_units": 101, "cap_units": 100},
        {"kind": GovernanceKind.DENIAL_BURST, "observation_count": 1},
    ],
)
def test_contradictory_governance_claims_are_rejected(facts: dict[str, object]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GovernanceFacts.model_validate(facts)


def test_evidence_classification_cannot_escalate_via_projection() -> None:
    telemetry = TelemetrySession(WorkflowIdentity(), evidence=EvidenceClass.DEPLOYMENT)
    with pytest.raises(ValueError):
        AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC, telemetry=telemetry)


def test_telemetry_failure_does_not_skip_anomaly_source_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = policy(20)
    telemetry = TelemetrySession(
        WorkflowIdentity(workflow_id=p.workflow_id, thread_id=p.thread_id),
        evidence=EvidenceClass.DETERMINISTIC,
    )
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC, telemetry=telemetry)
    cost = FixtureLedger(
        tmp_path / "cost.sqlite", p, create=True, telemetry=telemetry, anomalies=detector
    )

    def fail(*args: object) -> None:
        raise RuntimeError("SECRET")

    monkeypatch.setattr(telemetry, "record_governance", fail)
    cost.reserve(1)
    assert detector.snapshot()[0].facts.kind is GovernanceKind.BUDGET_SPIKE
    assert cost.snapshot().outstanding_units == 10
    assert cost.projection_failures == 2


@pytest.mark.parametrize("evidence", [EvidenceClass.DEPLOYMENT, EvidenceClass.LIVE_PROVIDER])
@pytest.mark.parametrize("projected", [False, True])
def test_fixture_rejects_stronger_anomaly_evidence_before_authority_changes(
    tmp_path: Path,
    evidence: EvidenceClass,
    projected: bool,
) -> None:
    p = policy(20)
    identity = WorkflowIdentity(workflow_id=p.workflow_id, thread_id=p.thread_id)
    telemetry = TelemetrySession(identity, evidence=evidence) if projected else None
    detector = AnomalyDetector(evidence=evidence, telemetry=telemetry)
    path = tmp_path / "cost.sqlite"
    with pytest.raises(LedgerError, match="identity/evidence"):
        FixtureLedger(path, p, create=True, anomalies=detector)
    assert not path.exists()
    assert detector.snapshot() == ()
    if telemetry is not None:
        assert telemetry.sink.snapshot() == ()


@pytest.mark.parametrize("different_thread", [False, True])
def test_foreign_anomaly_workflow_rejected_without_changing_existing_ledger(
    tmp_path: Path,
    different_thread: bool,
) -> None:
    p = policy(20)
    identity = WorkflowIdentity(workflow_id=p.workflow_id, thread_id=p.thread_id)
    foreign = WorkflowIdentity()
    if different_thread:
        foreign = WorkflowIdentity(workflow_id=p.workflow_id, thread_id=foreign.thread_id)
    telemetry = TelemetrySession(foreign, evidence=EvidenceClass.DETERMINISTIC)
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC, telemetry=telemetry)
    path = tmp_path / "cost.sqlite"
    cost = FixtureLedger(path, p, create=True)
    cost.reserve(1)
    before = cost.snapshot()
    with pytest.raises(LedgerError, match="identity/evidence"):
        FixtureLedger(path, p, anomalies=detector)
    assert cost.snapshot() == before
    assert detector.snapshot() == ()
    assert telemetry.sink.snapshot() == ()
    assert identity != foreign


@pytest.mark.parametrize(
    "evidence",
    [
        EvidenceClass.DETERMINISTIC,
        EvidenceClass.MOCKED,
        EvidenceClass.ADAPTER,
        EvidenceClass.LOCAL_INTEGRATION,
    ],
)
def test_valid_fixture_anomaly_keeps_exact_accounting_identity_and_evidence(
    tmp_path: Path,
    evidence: EvidenceClass,
) -> None:
    p = policy(20)
    identity = WorkflowIdentity(workflow_id=p.workflow_id, thread_id=p.thread_id)
    telemetry = TelemetrySession(identity, evidence=evidence)
    detector = AnomalyDetector(evidence=evidence, telemetry=telemetry)
    cost = FixtureLedger(tmp_path / "cost.sqlite", p, create=True, anomalies=detector)
    cost.reserve(1)
    signal = detector.snapshot()[0]
    assert signal.identity == identity
    assert signal.evidence is evidence
    event = telemetry.sink.snapshot()[0]
    assert event.workflow_id == identity.workflow_id and event.thread_id == identity.thread_id
    assert event.evidence is evidence
    assert cost.snapshot().outstanding_units == 10


def test_detector_cannot_be_rebound_to_another_fixture_workflow(tmp_path: Path) -> None:
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC)
    p = policy(20)
    cost = FixtureLedger(tmp_path / "first.sqlite", p, create=True, anomalies=detector)
    cost.reserve(1)
    before = cost.snapshot()
    with pytest.raises(LedgerError):
        FixtureLedger(tmp_path / "second.sqlite", policy(20), create=True, anomalies=detector)
    assert not (tmp_path / "second.sqlite").exists()
    assert cost.snapshot() == before


@pytest.mark.parametrize("case", ["deployment", "live", "foreign"])
def test_provider_adjacent_anomaly_binding_rejects_without_invocation(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness_engineering.providers import FakeProvider

    owner = WorkflowIdentity()
    evidence = {
        "deployment": EvidenceClass.DEPLOYMENT,
        "live": EvidenceClass.LIVE_PROVIDER,
        "foreign": EvidenceClass.DETERMINISTIC,
    }[case]
    telemetry = TelemetrySession(
        WorkflowIdentity() if case == "foreign" else owner, evidence=evidence
    )
    detector = AnomalyDetector(evidence=evidence, telemetry=telemetry)
    calls = []
    monkeypatch.setattr(FakeProvider, "generate", lambda *_: calls.append(True))
    switch = OffSwitch()
    with pytest.raises(ContractValidationError, match="Anomaly projection"):
        ProviderRuntime(identity=owner, anomalies=detector, off_switch=switch)
    assert calls == [] and not switch.is_active()
    assert telemetry.sink.snapshot() == () and detector.snapshot() == ()


def test_unattributed_prior_observations_cannot_be_adopted_by_accounting(tmp_path: Path) -> None:
    detector = AnomalyDetector(evidence=EvidenceClass.DETERMINISTIC)
    detector.observe(GovernanceKind.BUDGET_SPIKE)
    with pytest.raises(LedgerError):
        FixtureLedger(tmp_path / "cost.sqlite", policy(), create=True, anomalies=detector)
    assert not (tmp_path / "cost.sqlite").exists()
