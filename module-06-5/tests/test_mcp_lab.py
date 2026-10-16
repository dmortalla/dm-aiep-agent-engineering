"""Integrated reviewer evidence and fail-closed reporting, using the real SDK."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError

from harness_engineering import mcp_lab as lab
from harness_engineering.errors import ToolExecutionError
from harness_engineering.mcp_binding import MCPBoundRuntime


@pytest.fixture(scope="module")
def evidence() -> lab.MCPLabEvidence:
    """Run genuine protocol scenarios once for report-contract assertions."""
    return lab.run_mcp_lab()


def test_integrated_report_measures_complete_bounded_coverage(
    evidence: lab.MCPLabEvidence,
) -> None:
    assert tuple(item.scenario for item in evidence.scenarios) == tuple(lab.ScenarioID)
    assert evidence.total_checks == 32
    assert evidence.total_protocol_tool_calls == 9
    assert sum(item.sdk_sessions_established for item in evidence.scenarios) == 11
    assert sum(item.discovery_requests for item in evidence.scenarios) == 13
    assert all(item.resources_closed for item in evidence.scenarios)
    assert all(item.unbound_tool_calls == 0 for item in evidence.scenarios)
    assert all(check.actual is check.expected for s in evidence.scenarios for check in s.checks)


def test_serialized_report_contains_only_sanitized_evidence(
    evidence: lab.MCPLabEvidence,
) -> None:
    serialized = evidence.model_dump_json()
    assert len(serialized.encode()) < 24_000
    for excluded in (lab._ATTACK, "UNTRUSTED_MCP_PAYLOAD", "traceback", "operation_id"):
        assert excluded not in serialized
    assert lab.MCPLabEvidence.model_validate_json(serialized) == evidence
    assert evidence.classification == ("deterministic_fixture", "local_integration")
    assert evidence.limitations == lab.NONCLAIMS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_checks", 31),
        ("total_protocol_tool_calls", 10),
        ("passed", False),
        ("provider_calls", 1),
        ("transport", "http"),
        ("classification", ["production"]),
        ("limitations", []),
        ("authority", True),
    ],
)
def test_report_rejects_contradictions_and_claim_escalation(
    evidence: lab.MCPLabEvidence, field: str, value: Any
) -> None:
    data = json.loads(evidence.model_dump_json())
    data[field] = value
    with pytest.raises(ValidationError):
        lab.MCPLabEvidence.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("mutation", ["outcome", "count", "cleanup", "missing", "order"])
def test_nested_measurements_cannot_claim_false_success(
    evidence: lab.MCPLabEvidence, mutation: str
) -> None:
    data = json.loads(evidence.model_dump_json())
    scenarios = data["scenarios"]
    if mutation == "outcome":
        scenarios[0]["checks"][0]["actual"] = "validated_result"
    elif mutation == "count":
        scenarios[0]["checks"][0]["tool_calls_after"] = 1
    elif mutation == "cleanup":
        scenarios[0]["resources_closed"] = False
    elif mutation == "missing":
        scenarios.pop()
    else:
        scenarios.reverse()
    with pytest.raises(ValidationError):
        lab.MCPLabEvidence.model_validate_json(json.dumps(data))


def test_copied_models_are_revalidated_when_nested(evidence: lab.MCPLabEvidence) -> None:
    forged = evidence.scenarios[0].model_copy(update={"resources_closed": False})
    data = evidence.model_dump()
    data["scenarios"] = (forged, *evidence.scenarios[1:])
    with pytest.raises(ValidationError):
        lab.MCPLabEvidence.model_validate(data)


@pytest.fixture
def observed_fixtures(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[lab._Fixture]]:
    created: list[lab._Fixture] = []
    original = lab._Fixture

    def create() -> lab._Fixture:
        fixture = original()
        created.append(fixture)
        return fixture

    monkeypatch.setattr(lab, "_Fixture", create)
    yield created
    for fixture in created:
        fixture.verify_closed()


def test_unexpected_denial_success_fails_closed_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, observed_fixtures: list[lab._Fixture]
) -> None:
    monkeypatch.setattr(
        MCPBoundRuntime,
        "execute",
        lambda *args, **kwargs: lab.TicketSummary(summary=lab._SUMMARY),
    )
    with pytest.raises(lab.MCPLabFailure, match="description-no-authority"):
        lab.run_mcp_lab()
    assert len(observed_fixtures) == 1
    assert observed_fixtures[0].calls == 0
    assert not lab._LAB_SLOT.locked()


def test_programming_defect_propagates_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, observed_fixtures: list[lab._Fixture]
) -> None:
    def broken_discovery(self: lab.LocalMCPIntegration) -> None:
        raise RuntimeError("intentional programming defect")

    monkeypatch.setattr(lab.LocalMCPIntegration, "discover", broken_discovery)
    with pytest.raises(RuntimeError, match="intentional programming defect"):
        lab.run_mcp_lab()
    assert len(observed_fixtures) == 1
    assert not lab._LAB_SLOT.locked()


def test_unknown_execution_defect_is_not_mislabeled_remote_failure() -> None:
    error = ToolExecutionError("sanitized wrapper")
    error.__cause__ = RuntimeError("programming defect")
    with pytest.raises(ToolExecutionError) as caught:
        lab._failure(error)
    assert caught.value is error


def test_concurrent_lab_is_rejected_before_resource_creation(
    observed_fixtures: list[lab._Fixture],
) -> None:
    assert lab._LAB_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(lab.MCPLabFailure, match="already running"):
            lab.run_mcp_lab()
    finally:
        lab._LAB_SLOT.release()
    assert observed_fixtures == []


def test_cli_prints_typed_report(
    evidence: lab.MCPLabEvidence,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(lab, "run_mcp_lab", lambda: evidence)
    lab.main()
    captured = capsys.readouterr()
    assert not captured.err
    assert lab.MCPLabEvidence.model_validate_json(captured.out) == evidence


def test_cli_known_failure_is_sanitized_and_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail() -> lab.MCPLabEvidence:
        raise lab.MCPLabFailure(lab._ATTACK)

    monkeypatch.setattr(lab, "run_mcp_lab", fail)
    with pytest.raises(SystemExit) as caught:
        lab.main()
    captured = capsys.readouterr()
    assert caught.value.code == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {"passed": False, "error": "mcp_lab_failed"}
    assert lab._ATTACK not in captured.err
