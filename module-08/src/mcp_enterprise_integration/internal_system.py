"""Application-owned internal enterprise policy capability."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RequestedAction(StrEnum):
    """Actions evaluated by the internal enterprise policy system."""

    VIEW_ACCOUNT = "view_account"
    PRIORITY_SUPPORT = "priority_support"
    ACCOUNT_CHANGE = "account_change"


class PolicyDecision(StrEnum):
    """Authoritative decisions produced by application-owned policy."""

    ALLOW = "allow"
    DENY = "deny"


class PolicyRequest(BaseModel):
    """Validated input to the internal policy system."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: str = Field(min_length=1, max_length=64)
    requester_role: str = Field(min_length=1, max_length=64)
    action: RequestedAction
    account_status: str = Field(min_length=1, max_length=32)


class PolicyResult(BaseModel):
    """Auditable result from the internal policy system."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: str
    action: RequestedAction
    decision: PolicyDecision
    rule_id: str
    reason: str


class InternalPolicyService:
    """Evaluate deterministic enterprise authorization policy."""

    _VIEW_ROLES = frozenset({
        "support_agent",
        "account_manager",
        "compliance_officer",
    })

    _PRIORITY_ROLES = frozenset({
        "account_manager",
        "support_manager",
    })

    _CHANGE_ROLES = frozenset({
        "account_manager",
    })

    def evaluate(self, request: PolicyRequest) -> PolicyResult:
        """Evaluate one request using application-owned rules.

        Args:
            request: Validated policy request.

        Returns:
            Deterministic auditable policy decision.
        """
        if request.account_status != "active":
            return PolicyResult(
                customer_id=request.customer_id,
                action=request.action,
                decision=PolicyDecision.DENY,
                rule_id="POL-ACCOUNT-ACTIVE",
                reason="Account must be active for enterprise actions.",
            )

        if request.action is RequestedAction.VIEW_ACCOUNT:
            allowed = request.requester_role in self._VIEW_ROLES
            return self._result(
                request,
                allowed,
                "POL-VIEW-ROLE",
                "Requester role is permitted to view the account.",
                "Requester role is not permitted to view the account.",
            )

        if request.action is RequestedAction.PRIORITY_SUPPORT:
            allowed = request.requester_role in self._PRIORITY_ROLES
            return self._result(
                request,
                allowed,
                "POL-PRIORITY-ROLE",
                "Requester role may initiate priority support.",
                "Requester role may not initiate priority support.",
            )

        allowed = request.requester_role in self._CHANGE_ROLES
        return self._result(
            request,
            allowed,
            "POL-CHANGE-ROLE",
            "Requester role may request an account change.",
            "Requester role may not request an account change.",
        )

    @staticmethod
    def _result(
        request: PolicyRequest,
        allowed: bool,
        rule_id: str,
        allow_reason: str,
        deny_reason: str,
    ) -> PolicyResult:
        """Build a consistent auditable policy result."""
        return PolicyResult(
            customer_id=request.customer_id,
            action=request.action,
            decision=PolicyDecision.ALLOW if allowed else PolicyDecision.DENY,
            rule_id=rule_id,
            reason=allow_reason if allowed else deny_reason,
        )
