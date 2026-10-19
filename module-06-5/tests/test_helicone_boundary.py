"""Non-executable Helicone header plan; no provider or gateway requests."""

import json
import socket

import pytest
from pydantic import ValidationError

from harness_engineering.cost_governance import require_real_monetary_admission
from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.errors import AuthorityViolationError
from harness_engineering.helicone_boundary import HeliconeOfflineConfig
from harness_engineering.observability import TelemetrySession

SECRET = "SECRET-HEADER-CREDENTIAL-SENTINEL"


def test_disabled_non_secret_deterministic_plan_has_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Helicone boundary attempted network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setenv("HELICONE_API_KEY", SECRET)
    telemetry = TelemetrySession(WorkflowIdentity(), evidence=EvidenceClass.MOCKED)
    config = HeliconeOfflineConfig()
    before = telemetry.sink.snapshot()
    document = config.describe(telemetry)
    assert document == config.describe(telemetry)
    assert SECRET not in document + str(config) + repr(config)
    parsed = json.loads(document)
    assert parsed["enabled"] is False
    assert parsed["source_evidence"] == "mocked"
    assert parsed["boundary_evidence"] == "deterministic"
    assert parsed["headers"] == {
        "Helicone-Session-Id": str(telemetry.identity.thread_id),
        "Helicone-Property-Workflow": str(telemetry.identity.workflow_id),
        "Helicone-Property-Evidence": "mocked",
        "Helicone-Omit-Request": "true", "Helicone-Omit-Response": "true",
        "Helicone-Retry-Enabled": "false", "Helicone-Cache-Enabled": "false",
    }
    assert telemetry.sink.snapshot() == before
    with pytest.raises(AuthorityViolationError):
        require_real_monetary_admission(approved_tariff=config, live_enabled=True)


@pytest.mark.parametrize("changes", [
    {"enabled": True}, {"enabled": 0}, {"enabled": "false"},
    {"headers": {"Authorization": SECRET}},
    {"headers": {"Helicone-Auth": SECRET}}, {"api_key": SECRET},
    {"provider_key": SECRET}, {"Authorization": SECRET},
    {"endpoint": "https://evil.invalid/" + SECRET}, {"endpoint": "not a URL"},
    {"endpoint": "http://gateway.helicone.ai/v1"},
    {"endpoint": "https://gateway.helicone.ai/v1?key=" + SECRET},
    {"retry_count": 9}, {"max_cost_usd": 999}, {"token_budget": 999},
    {"permissions": ["all"]}, {"hitl": False}, {"off_switch": False},
    {"evidence": EvidenceClass.LIVE_PROVIDER}, {"target_url": "https://api.openai.com"},
])
def test_closed_contract_rejects_injection_without_diagnostic_secrets(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as caught:
        HeliconeOfflineConfig(**changes)
    assert SECRET not in str(caught.value)


def test_unvalidated_copies_cannot_enable_gateway_or_promote_evidence() -> None:
    telemetry = TelemetrySession(WorkflowIdentity(), evidence=EvidenceClass.DETERMINISTIC)
    with pytest.raises(ValidationError):
        HeliconeOfflineConfig().model_copy(update={"enabled": True}).describe(telemetry)
    live = TelemetrySession(WorkflowIdentity(), evidence=EvidenceClass.LIVE_PROVIDER)
    with pytest.raises(ValueError):
        HeliconeOfflineConfig().describe(live)
