"""Tests for Story 1 correlation-aware structured logging."""

import json
import logging

from reliability_safety_observability import WorkflowIdentity
from reliability_safety_observability.logging import log_event


def test_structured_log_contains_correlation_identity(caplog) -> None:
    """Include workflow and trace identity in local structured logs."""
    identity = WorkflowIdentity()
    logger = logging.getLogger("module7.test.correlation")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            event="fixture_started",
            workflow_id=identity.workflow_id,
            trace_id=identity.trace_id,
            fields={"status": "ok"},
        )

    payload = json.loads(caplog.records[-1].message)
    assert payload["workflow_id"] == str(identity.workflow_id)
    assert payload["trace_id"] == str(identity.trace_id)
    assert payload["event"] == "fixture_started"


def test_structured_log_redacts_sensitive_keys_recursively(caplog) -> None:
    """Prevent ordinary structured logging from exposing keyed secrets."""
    identity = WorkflowIdentity()
    logger = logging.getLogger("module7.test.redaction")
    secret = "fixture-secret-must-not-leak"

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            event="fixture_secret_test",
            workflow_id=identity.workflow_id,
            trace_id=identity.trace_id,
            fields={
                "api_key": secret,
                "nested": {"token": secret},
                "safe": "visible",
            },
        )

    message = caplog.records[-1].message
    payload = json.loads(message)

    assert secret not in message
    assert payload["fields"]["api_key"] == "[REDACTED]"
    assert payload["fields"]["nested"]["token"] == "[REDACTED]"
    assert payload["fields"]["safe"] == "visible"
