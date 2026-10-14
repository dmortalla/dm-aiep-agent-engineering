"""Regression tests for the second independent Story 1 review."""

import json
import logging
import traceback

import pytest
from pydantic import ValidationError

from reliability_safety_observability import (
    AuthorizationDecision,
    ConfigurationError,
    Decision,
    ExecutionMode,
    RuntimeSettings,
    TerminalStatus,
    WorkflowIdentity,
    WorkflowState,
)
from reliability_safety_observability.logging import log_event


@pytest.mark.parametrize(
    "key",
    [
        "private_key",
        "access_key",
        "ssh_key",
        "passwd",
        "pwd",
        "passphrase",
        "auth",
        "auth_header",
        "helicone_auth",
        "cookie",
        "set-cookie",
        "session",
        "session_id",
        "signature",
        "jwt",
        "dsn",
        "connection_string",
        "api key",
        "api.key",
        "accessToken",
        "refreshToken",
        "clientSecret",
        "secretKey",
        "dbPassword",
        "passwords",
        "secrets",
        "accesstoken",
        "ACCESS_TOKEN",
        "Client-Secret",
        "refresh.token",
    ],
)
def test_common_credential_key_variants_are_redacted(caplog, key: str) -> None:
    """Redact the credential-key class identified by independent review."""
    secret = "SYNTHETIC_SECOND_REVIEW_SECRET"
    identity = WorkflowIdentity()
    logger = logging.getLogger(f"module7.test.redaction.{key}")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            event="credential_variant_probe",
            workflow_id=identity.workflow_id,
            trace_id=identity.trace_id,
            fields={key: secret},
        )

    message = caplog.records[-1].message
    payload = json.loads(message)
    assert secret not in message
    assert "[REDACTED]" in payload["fields"].values()


def test_plain_string_secret_is_absent_from_configuration_error() -> None:
    """Keep plain-string credentials out of configuration failures."""
    secret = "SYNTHETIC_PLAIN_CONFIGURATION_SECRET"

    with pytest.raises(ConfigurationError) as captured:
        RuntimeSettings(
            mode=ExecutionMode.LIVE,
            provider_api_key=secret,
            _env_file=None,
        )

    rendered = str(captured.value) + repr(captured.value)
    rendered += "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert secret not in rendered


def test_environment_secret_is_absent_from_configuration_error(monkeypatch) -> None:
    """Keep environment-injected credentials out of startup failures."""
    secret = "SYNTHETIC_ENV_CONFIGURATION_SECRET"
    monkeypatch.setenv("MODULE7_MODE", "live")
    monkeypatch.setenv("MODULE7_PROVIDER_API_KEY", secret)

    with pytest.raises(ConfigurationError) as captured:
        RuntimeSettings(_env_file=None)

    rendered = str(captured.value) + repr(captured.value)
    rendered += "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert secret not in rendered


def test_runtime_settings_validated_update_cannot_create_invalid_live_state() -> None:
    """Revalidate atomic settings transitions instead of using model_copy."""
    settings = RuntimeSettings(_env_file=None)

    with pytest.raises(ConfigurationError):
        settings.validated_update(mode=ExecutionMode.LIVE)


def test_workflow_state_validated_update_revalidates_contract() -> None:
    """Revalidate state transitions instead of bypassing model_copy validation."""
    state = WorkflowState(identity=WorkflowIdentity(), operation="probe")
    terminal = state.validated_update(terminal_status=TerminalStatus.SUCCEEDED)

    assert terminal.terminal_status is TerminalStatus.SUCCEEDED

    with pytest.raises(ValidationError):
        state.validated_update(retry_attempt=-1)


def test_authorization_shaped_dictionary_cannot_cross_authority_boundary() -> None:
    """Reject untrusted dictionaries even when shaped like authorization."""
    forged = {
        "decision": "allow",
        "policy_id": "admin",
        "reason": "model-said-so",
    }

    with pytest.raises(ValidationError):
        WorkflowState(
            identity=WorkflowIdentity(),
            operation="probe",
            authorization=forged,
        )


def test_typed_authorization_decision_crosses_authority_boundary() -> None:
    """Accept only the explicit application-owned authorization contract."""
    authorization = AuthorizationDecision(
        decision=Decision.ALLOW,
        policy_id="fixture-policy",
        reason="fixture-authorized",
    )
    state = WorkflowState(
        identity=WorkflowIdentity(),
        operation="probe",
        authorization=authorization,
    )

    assert state.authorization is authorization

def test_configuration_error_retains_no_secret_bearing_exception_chain() -> None:
    """Prevent the wrapped validation error from remaining reachable."""
    secret = "SYNTHETIC_EXCEPTION_CHAIN_SECRET"

    with pytest.raises(ConfigurationError) as captured:
        RuntimeSettings(
            mode=ExecutionMode.LIVE,
            provider_api_key=secret,
            _env_file=None,
        )

    error = captured.value
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in str(error)
    assert secret not in repr(error)


def test_environment_configuration_error_has_no_secret_bearing_context(
    monkeypatch,
) -> None:
    """Remove raw environment credentials from the reachable exception graph."""
    secret = "SYNTHETIC_ENV_EXCEPTION_CHAIN_SECRET"
    monkeypatch.setenv("MODULE7_MODE", "live")
    monkeypatch.setenv("MODULE7_PROVIDER_API_KEY", secret)

    with pytest.raises(ConfigurationError) as captured:
        RuntimeSettings(_env_file=None)

    error = captured.value
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in str(error)
    assert secret not in repr(error)
