"""Application-owned, least-privilege tool authorization.

Authority originates only from committed application policy. Tool requests,
model output, retrieved content, telemetry, moderation results, and Guardrails
results are never consulted when deciding whether an action is permitted.
"""

import logging
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from .domain import AuthorizationDecision, Decision, Identifier, WorkflowIdentity
from .errors import AuthorizationDeniedError, ConfigurationError
from .logging import log_event

_MAX_ISSUED_DECISIONS: Final = 4_096
_UNREGISTERED_TOOL: Final = "[UNREGISTERED_TOOL]"
_UNKNOWN_PRINCIPAL: Final = "[UNKNOWN_PRINCIPAL]"
_IDENTIFIER: Final = TypeAdapter(Identifier)


class ToolPermission(BaseModel):
    """One application-registered tool capability.

    Attributes:
        tool_name: Stable tool identifier used by the allowlist.
        privileged: Whether the tool performs a privileged action. Privileged and
            unprivileged tools both require an explicit grant; the flag is
            recorded so denials of privileged requests remain observable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: Identifier
    privileged: bool = False


class AuthorizationPolicy:
    """Deny-by-default allowlist of tool grants owned by the application.

    The policy is immutable after construction. It issues typed
    ``AuthorizationDecision`` objects and remembers exactly which decision
    objects it issued, so an externally constructed or copied decision can never
    be redeemed as authority.
    """

    def __init__(
        self,
        *,
        policy_id: str,
        tools: Iterable[ToolPermission],
        grants: Mapping[str, Iterable[str]],
        logger: logging.Logger | None = None,
    ) -> None:
        """Validate and freeze committed authorization policy.

        Args:
            policy_id: Stable identifier of the committed policy version.
            tools: Every tool the application exposes.
            grants: Trusted principal identifiers mapped to the tool names each
                principal may invoke.
            logger: Optional logger receiving redacted decision records.

        Raises:
            ConfigurationError: If the policy is empty, duplicated, or grants a
                tool that is not registered.
        """
        try:
            permissions = tuple(ToolPermission.model_validate(tool) for tool in tools)
            self._policy_id: str = _IDENTIFIER.validate_python(policy_id)
            principals = {
                _IDENTIFIER.validate_python(principal_id): tuple(tool_names)
                for principal_id, tool_names in grants.items()
            }
        except ValidationError as exc:
            raise ConfigurationError(
                "Authorization policy contains an invalid identifier or tool definition."
            ) from exc
        if len(principals) != len(grants):
            raise ConfigurationError("Authorization grants repeat a principal identifier.")

        names = [permission.tool_name for permission in permissions]
        if not names:
            raise ConfigurationError("Authorization policy must register at least one tool.")
        if len(set(names)) != len(names):
            raise ConfigurationError("Authorization policy registers a tool more than once.")

        self._tools: Mapping[str, ToolPermission] = MappingProxyType(
            {permission.tool_name: permission for permission in permissions}
        )

        frozen_grants: dict[str, frozenset[str]] = {}
        for principal, tool_names in principals.items():
            granted = frozenset(tool_names)
            unknown = granted - self._tools.keys()
            if unknown:
                raise ConfigurationError(
                    f"Authorization grants for principal {principal!r} reference "
                    f"{len(unknown)} unregistered tool(s); register the tool first."
                )
            frozen_grants[principal] = granted
        self._grants: Mapping[str, frozenset[str]] = MappingProxyType(frozen_grants)

        self._issued: OrderedDict[int, tuple[AuthorizationDecision, str, str]] = OrderedDict()
        self._logger = logger

    @property
    def policy_id(self) -> str:
        """Return the committed policy identifier."""
        return self._policy_id

    def allowed_tools(self, principal_id: str) -> frozenset[str]:
        """Return the tools explicitly granted to a trusted principal.

        Args:
            principal_id: Application-resolved principal identifier.

        Returns:
            The granted tool names, or an empty set for unknown principals.
        """
        return self._grants.get(principal_id, frozenset())

    def authorize(
        self,
        *,
        principal_id: str,
        tool_name: str,
        identity: WorkflowIdentity | None = None,
    ) -> AuthorizationDecision:
        """Decide whether a principal may invoke a tool.

        Only the committed tool registry and grants are consulted. The tool name
        may originate from untrusted model output; it is treated purely as a
        lookup key and cannot add itself to the allowlist.

        Args:
            principal_id: Principal identity resolved by trusted application code,
                never by model output or request content.
            tool_name: Requested tool identifier.
            identity: Optional workflow correlation for the decision record.

        Returns:
            An application-issued authorization decision.
        """
        if tool_name not in self._tools:
            decision = Decision.DENY
            reason = "tool_not_registered"
        elif principal_id not in self._grants:
            decision = Decision.DENY
            reason = "principal_not_recognized"
        elif tool_name not in self._grants[principal_id]:
            decision = Decision.DENY
            reason = "tool_not_allowlisted"
        else:
            decision = Decision.ALLOW
            reason = "tool_allowlisted"

        result = AuthorizationDecision(
            decision=decision, policy_id=self._policy_id, reason=reason
        )
        self._remember(result, principal_id, tool_name)
        self._record(result, principal_id, tool_name, identity)
        return result

    def is_issued(
        self, decision: object, *, principal_id: str, tool_name: str
    ) -> bool:
        """Return whether this policy issued the exact decision for the request.

        Args:
            decision: Candidate decision presented by a caller.
            principal_id: Principal the decision must have been issued to.
            tool_name: Tool the decision must have been issued for.

        Returns:
            True only for the identical decision object issued by this policy for
            the same principal and tool.
        """
        entry = self._issued.get(id(decision))
        return (
            entry is not None
            and entry[0] is decision
            and entry[1] == principal_id
            and entry[2] == tool_name
        )

    def enforce(
        self, decision: object, *, principal_id: str, tool_name: str
    ) -> AuthorizationDecision:
        """Require an issued allow decision before a tool may execute.

        Args:
            decision: Decision presented by the caller.
            principal_id: Principal attempting the action.
            tool_name: Tool about to execute.

        Returns:
            The verified application-issued allow decision.

        Raises:
            AuthorizationDeniedError: If the decision is forged, copied, issued
                for another request, or denies the action.
        """
        if not isinstance(decision, AuthorizationDecision):
            raise AuthorizationDeniedError(
                "Tool execution requires an application-issued AuthorizationDecision."
            )
        if not self.is_issued(decision, principal_id=principal_id, tool_name=tool_name):
            raise AuthorizationDeniedError(
                "Authorization decision was not issued by this policy for this request."
            )
        if decision.decision is not Decision.ALLOW:
            raise AuthorizationDeniedError(
                f"Authorization policy denied the request: {decision.reason}."
            )
        return decision

    def _remember(
        self, decision: AuthorizationDecision, principal_id: str, tool_name: str
    ) -> None:
        """Retain a bounded record of issued decisions for provenance checks.

        Args:
            decision: Newly issued decision.
            principal_id: Principal it was issued to.
            tool_name: Tool it was issued for.
        """
        self._issued[id(decision)] = (decision, principal_id, tool_name)
        while len(self._issued) > _MAX_ISSUED_DECISIONS:
            self._issued.popitem(last=False)

    def _record(
        self,
        decision: AuthorizationDecision,
        principal_id: str,
        tool_name: str,
        identity: WorkflowIdentity | None,
    ) -> None:
        """Emit an observable, redacted local decision record.

        Unregistered tool names and unknown principals may carry untrusted or
        sensitive text, so only placeholders are recorded for them.

        Args:
            decision: Issued decision.
            principal_id: Requesting principal.
            tool_name: Requested tool.
            identity: Optional workflow correlation.
        """
        if self._logger is None:
            return
        correlation = identity or WorkflowIdentity()
        tool = self._tools.get(tool_name)
        log_event(
            self._logger,
            event="authorization_decision",
            workflow_id=correlation.workflow_id,
            trace_id=correlation.trace_id,
            fields={
                "decision": decision.decision.value,
                "reason": decision.reason,
                "policy_id": decision.policy_id,
                "principal": principal_id if principal_id in self._grants else _UNKNOWN_PRINCIPAL,
                "tool": tool.tool_name if tool is not None else _UNREGISTERED_TOOL,
                "privileged": tool.privileged if tool is not None else None,
            },
        )
