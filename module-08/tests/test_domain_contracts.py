"""Tests for foundational domain contracts."""

import pytest
from pydantic import ValidationError

from mcp_enterprise_integration.domain import (
    AuthorizationDecision,
    AuthorizationResult,
    CapabilityDescriptor,
    ClientFramework,
    InvocationContext,
    InvocationResult,
    InvocationStatus,
    TransportKind,
    ValidationStatus,
)


def test_capability_descriptor_is_validated_and_immutable() -> None:
    """Validate capability identity without implying authorization."""
    capability = CapabilityDescriptor(
        capability_id="customer_lookup",
        name="customer_lookup",
        description="Read sanitized customer records.",
    )

    assert capability.capability_id == "customer_lookup"

    with pytest.raises(ValidationError):
        capability.name = "changed"


def test_capability_rejects_blank_identity_and_unknown_fields() -> None:
    """Reject malformed or unexpected untrusted capability data."""
    with pytest.raises(ValidationError):
        CapabilityDescriptor(
            capability_id="   ",
            name="lookup",
            description="Valid description.",
        )

    with pytest.raises(ValidationError):
        CapabilityDescriptor(
            capability_id="lookup",
            name="lookup",
            description="Valid description.",
            authority="self_granted",
        )


def test_discovery_context_contains_no_authorization_decision() -> None:
    """Keep client discovery/invocation identity separate from authority."""
    context = InvocationContext(
        invocation_id="inv-001",
        client_id="reviewer-client",
        client_framework=ClientFramework.OPENAI,
        capability_id="customer_lookup",
        transport=TransportKind.STREAMABLE_HTTP,
    )

    assert context.client_framework is ClientFramework.OPENAI
    assert "authorization" not in context.model_dump()


def test_authorization_result_requires_explicit_decision_and_reason() -> None:
    """Represent authority as an explicit application-owned decision."""
    result = AuthorizationResult(
        decision=AuthorizationDecision.DENY,
        reason="Client lacks the required capability permission.",
    )

    assert result.decision is AuthorizationDecision.DENY

    with pytest.raises(ValidationError):
        AuthorizationResult(decision=AuthorizationDecision.ALLOW, reason=" ")


def test_invocation_result_validates_latency_and_structure() -> None:
    """Reject impossible execution metadata at the evidence boundary."""
    result = InvocationResult(
        invocation_id="inv-002",
        capability_id="policy_check",
        status=InvocationStatus.SUCCEEDED,
        validation_status=ValidationStatus.VALID,
        latency_ms=12.5,
        summary="Policy evaluation completed.",
    )

    assert result.latency_ms == 12.5

    with pytest.raises(ValidationError):
        InvocationResult(
            invocation_id="inv-003",
            capability_id="policy_check",
            status=InvocationStatus.FAILED,
            validation_status=ValidationStatus.INVALID,
            latency_ms=-1,
            summary="Invalid latency.",
        )
