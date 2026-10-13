"""Tests for the application-owned internal policy capability."""

import pytest
from pydantic import ValidationError

from mcp_enterprise_integration.internal_system import (
    InternalPolicyService,
    PolicyDecision,
    PolicyRequest,
    RequestedAction,
)


def test_authorized_role_receives_allow_decision() -> None:
    """Allow an explicitly authorized enterprise role."""
    service = InternalPolicyService()
    request = PolicyRequest(
        customer_id="CUST-001",
        requester_role="account_manager",
        action=RequestedAction.ACCOUNT_CHANGE,
        account_status="active",
    )

    result = service.evaluate(request)

    assert result.decision is PolicyDecision.ALLOW
    assert result.rule_id == "POL-CHANGE-ROLE"


def test_unauthorized_role_is_denied() -> None:
    """Deny a role that lacks the required application authority."""
    service = InternalPolicyService()
    request = PolicyRequest(
        customer_id="CUST-001",
        requester_role="support_agent",
        action=RequestedAction.ACCOUNT_CHANGE,
        account_status="active",
    )

    result = service.evaluate(request)

    assert result.decision is PolicyDecision.DENY
    assert result.rule_id == "POL-CHANGE-ROLE"


def test_inactive_account_is_denied_before_role_authority() -> None:
    """Enforce account-state policy before role authorization."""
    service = InternalPolicyService()
    request = PolicyRequest(
        customer_id="CUST-003",
        requester_role="account_manager",
        action=RequestedAction.VIEW_ACCOUNT,
        account_status="review",
    )

    result = service.evaluate(request)

    assert result.decision is PolicyDecision.DENY
    assert result.rule_id == "POL-ACCOUNT-ACTIVE"


def test_untrusted_input_cannot_supply_a_decision() -> None:
    """Prevent callers or future agents from injecting authority."""
    with pytest.raises(ValidationError):
        PolicyRequest.model_validate(
            {
                "customer_id": "CUST-001",
                "requester_role": "support_agent",
                "action": "account_change",
                "account_status": "active",
                "decision": "allow",
            }
        )


def test_unknown_action_is_rejected() -> None:
    """Reject unsupported actions at the typed policy boundary."""
    with pytest.raises(ValidationError):
        PolicyRequest.model_validate(
            {
                "customer_id": "CUST-001",
                "requester_role": "account_manager",
                "action": "override_everything",
                "account_status": "active",
            }
        )


def test_policy_result_is_immutable() -> None:
    """Keep authoritative policy evidence immutable after evaluation."""
    service = InternalPolicyService()
    request = PolicyRequest(
        customer_id="CUST-001",
        requester_role="account_manager",
        action=RequestedAction.VIEW_ACCOUNT,
        account_status="active",
    )

    result = service.evaluate(request)

    with pytest.raises(ValidationError):
        result.reason = "agent supplied replacement"
