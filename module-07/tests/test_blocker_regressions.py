"""Regression tests for independently reviewed Story 1 blockers."""

import json
import logging
from math import inf

import pytest
from pydantic import SecretStr, ValidationError

from reliability_safety_observability import (
    BudgetState,
    ConfigurationError,
    ExecutionMode,
    ReliabilityResult,
    RuntimeSettings,
    TelemetryRecord,
    TerminalStatus,
    UsageRecord,
    WorkflowIdentity,
    WorkflowState,
)
from reliability_safety_observability.domain import MAX_COUNTER
from reliability_safety_observability.logging import log_event


def test_provider_api_key_and_bearer_secret_do_not_leak(caplog) -> None:
    """Redact the exact credential shapes reproduced by independent review."""
    identity = WorkflowIdentity()
    logger = logging.getLogger("module7.test.blocker.secret")
    secret = "SYNTHETIC_REVIEW_SECRET"

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            event="credential_probe",
            workflow_id=identity.workflow_id,
            trace_id=identity.trace_id,
            fields={
                "provider_api_key": secret,
                "message": f"Bearer {secret}",
                "secret_object": SecretStr(secret),
            },
        )

    message = caplog.records[-1].message
    payload = json.loads(message)

    assert secret not in message
    assert payload["fields"]["provider_api_key"] == "[REDACTED]"
    assert payload["fields"]["message"] == "Bearer [REDACTED]"
    assert payload["fields"]["secret_object"] == "[REDACTED]"


def test_arbitrary_object_repr_cannot_cross_logging_boundary(caplog) -> None:
    """Avoid leaking secrets through arbitrary object string representations."""

    class SecretBearingObject:
        def __str__(self) -> str:
            return "SYNTHETIC_OBJECT_SECRET"

    identity = WorkflowIdentity()
    logger = logging.getLogger("module7.test.blocker.object")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            event="object_probe",
            workflow_id=identity.workflow_id,
            trace_id=identity.trace_id,
            fields={"payload": SecretBearingObject()},
        )

    message = caplog.records[-1].message
    assert "SYNTHETIC_OBJECT_SECRET" not in message
    assert json.loads(message)["fields"]["payload"] == "[UNSUPPORTED_TYPE]"


def test_validated_runtime_settings_are_immutable() -> None:
    """Prevent post-validation mutation from bypassing live invariants."""
    settings = RuntimeSettings(_env_file=None)

    with pytest.raises(ValidationError):
        settings.mode = ExecutionMode.LIVE


@pytest.mark.parametrize("credential", ["", "   ", "\t"])
def test_live_mode_rejects_blank_credentials(credential: str) -> None:
    """Reject blank credentials at the trusted configuration boundary."""
    with pytest.raises(ConfigurationError, match="non-blank"):
        RuntimeSettings(
            mode=ExecutionMode.LIVE,
            live_integrations_enabled=True,
            provider_api_key=credential,
            _env_file=None,
        )


def test_workflow_attempt_counter_has_finite_structural_bound() -> None:
    """Reject counters outside the normalized structural representation."""
    identity = WorkflowIdentity()

    state = WorkflowState(
        identity=identity,
        operation="probe",
        retry_attempt=MAX_COUNTER,
    )
    assert state.retry_attempt == MAX_COUNTER

    with pytest.raises(ValidationError):
        WorkflowState(
            identity=identity,
            operation="probe",
            retry_attempt=MAX_COUNTER + 1,
        )

    with pytest.raises(ValidationError):
        ReliabilityResult(attempts=MAX_COUNTER + 1)


@pytest.mark.parametrize("field", ["cost_usd", "duration_ms"])
def test_normalized_float_evidence_rejects_infinity(field: str) -> None:
    """Reject non-finite normalized cost and duration evidence."""
    if field == "cost_usd":
        with pytest.raises(ValidationError):
            UsageRecord(cost_usd=inf)
        return

    identity = WorkflowIdentity()
    with pytest.raises(ValidationError):
        TelemetryRecord(
            workflow_id=identity.workflow_id,
            trace_id=identity.trace_id,
            operation="probe",
            status="failed",
            duration_ms=inf,
        )


def test_workflow_state_represents_frozen_minimum_state_families() -> None:
    """Represent architecture-required state without implementing later behavior."""
    state = WorkflowState(identity=WorkflowIdentity(), operation="probe")

    assert state.idempotency_key is not None
    assert state.budget == BudgetState()
    assert state.usage == UsageRecord()
    assert state.terminal_status is None

    terminal = state.validated_update(terminal_status=TerminalStatus.SUCCEEDED)
    assert terminal.terminal_status is TerminalStatus.SUCCEEDED


def test_budget_state_rejects_nonfinite_and_contradictory_cost() -> None:
    """Reject malformed normalized budget state before later enforcement."""
    with pytest.raises(ValidationError):
        BudgetState(cost_limit_usd=inf)

    with pytest.raises(ValidationError, match="cannot exceed"):
        BudgetState(cost_limit_usd=1.0, cost_used_usd=1.01)


def test_malformed_telemetry_identity_is_rejected() -> None:
    """Reject malformed correlation identity at the telemetry boundary."""
    identity = WorkflowIdentity()

    with pytest.raises(ValidationError):
        TelemetryRecord(
            workflow_id="not-a-uuid",
            trace_id=identity.trace_id,
            operation="probe",
            status="failed",
            duration_ms=1.0,
        )
