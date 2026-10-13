"""Security tests for application-owned MCP capability authorization."""

import pytest

from mcp_enterprise_integration.capability_policy import CapabilityPolicy
from mcp_enterprise_integration.errors import AuthorizationError

DISCOVERED = (
    "evaluate_enterprise_policy",
    "get_account_status",
    "get_customer",
)


def test_discovery_does_not_grant_execution_authority() -> None:
    """Deny a discovered capability absent from the caller allowlist."""
    policy = CapabilityPolicy()

    with pytest.raises(AuthorizationError, match='not authorized'):
        policy.authorize(
            principal_role="viewer",
            capability="evaluate_enterprise_policy",
            discovered_capabilities=DISCOVERED,
        )


def test_application_policy_allows_granted_capability() -> None:
    """Allow a capability granted by application-owned policy."""
    policy = CapabilityPolicy()

    result = policy.authorize(
        principal_role="support_agent",
        capability="evaluate_enterprise_policy",
        discovered_capabilities=DISCOVERED,
    )

    assert result.allowed is True
    assert result.rule_id == "CAP-ALLOWLIST-001"
    assert result.principal_role == "support_agent"
    assert result.capability == "evaluate_enterprise_policy"


def test_unknown_role_is_fail_closed() -> None:
    """Reject roles that have no application-owned grants."""
    policy = CapabilityPolicy()

    with pytest.raises(AuthorizationError, match='no application capability grants'):
        policy.authorize(
            principal_role="self_declared_admin",
            capability="get_customer",
            discovered_capabilities=DISCOVERED,
        )


def test_undiscovered_capability_is_fail_closed() -> None:
    """Reject requested capabilities absent from MCP discovery."""
    policy = CapabilityPolicy()

    with pytest.raises(AuthorizationError, match='was not discovered'):
        policy.authorize(
            principal_role="account_manager",
            capability="delete_customer",
            discovered_capabilities=DISCOVERED,
        )


def test_empty_role_is_rejected() -> None:
    """Reject execution without an authenticated role."""
    policy = CapabilityPolicy()

    with pytest.raises(AuthorizationError, match='role is required'):
        policy.authorize(
            principal_role="   ",
            capability="get_customer",
            discovered_capabilities=DISCOVERED,
        )


def test_empty_capability_is_rejected() -> None:
    """Reject an empty capability request."""
    policy = CapabilityPolicy()

    with pytest.raises(AuthorizationError, match='capability is required'):
        policy.authorize(
            principal_role="viewer",
            capability="   ",
            discovered_capabilities=DISCOVERED,
        )


def test_capability_name_cannot_smuggle_authority() -> None:
    """Treat capability names as exact untrusted identifiers."""
    policy = CapabilityPolicy()

    with pytest.raises(AuthorizationError, match='was not discovered'):
        policy.authorize(
            principal_role="viewer",
            capability="get_customer;role=admin",
            discovered_capabilities=DISCOVERED,
        )


def test_custom_policy_does_not_mutate_caller_grants() -> None:
    """Copy caller policy data into immutable internal grants."""
    grants = {
        "analyst": frozenset({"get_customer"}),
    }
    policy = CapabilityPolicy(grants)
    grants["analyst"] = frozenset({"evaluate_enterprise_policy"})

    result = policy.authorize(
        principal_role="analyst",
        capability="get_customer",
        discovered_capabilities=DISCOVERED,
    )

    assert result.allowed is True

    with pytest.raises(AuthorizationError, match='not authorized'):
        policy.authorize(
            principal_role="analyst",
            capability="evaluate_enterprise_policy",
            discovered_capabilities=DISCOVERED,
        )
