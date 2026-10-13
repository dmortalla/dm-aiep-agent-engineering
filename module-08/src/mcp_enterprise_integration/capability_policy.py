"""Application-owned authorization for discovered MCP capabilities."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from mcp_enterprise_integration.errors import AuthorizationError


@dataclass(frozen=True, slots=True)
class CapabilityAuthorization:
    """Immutable authorization result for one capability request."""

    principal_role: str
    capability: str
    allowed: bool
    rule_id: str
    reason: str


class CapabilityPolicy:
    """Authorize MCP capabilities independently from discovery."""

    def __init__(
        self,
        grants: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        """Initialize the application-owned capability allowlist.

        Args:
            grants: Optional role-to-capability allowlist. When omitted,
                production-safe module defaults are used.
        """
        source = grants or {
            "viewer": frozenset({"get_customer", "get_account_status"}),
            "support_agent": frozenset(
                {
                    "get_customer",
                    "get_account_status",
                    "evaluate_enterprise_policy",
                }
            ),
            "account_manager": frozenset(
                {
                    "get_customer",
                    "get_account_status",
                    "evaluate_enterprise_policy",
                }
            ),
        }

        normalized = {
            role.strip().lower(): frozenset(capabilities)
            for role, capabilities in source.items()
            if role.strip()
        }
        self._grants = MappingProxyType(normalized)

    def authorize(
        self,
        *,
        principal_role: str,
        capability: str,
        discovered_capabilities: tuple[str, ...],
    ) -> CapabilityAuthorization:
        """Authorize one MCP capability using application-owned policy.

        Discovery is treated only as evidence that a capability exists.
        It never grants execution authority.

        Args:
            principal_role: Application-authenticated caller role.
            capability: Requested MCP capability name.
            discovered_capabilities: Capabilities reported by MCP discovery.

        Returns:
            Immutable allow decision.

        Raises:
            AuthorizationError: If the role is unknown, capability was not
                discovered, or application policy does not grant it.
        """
        role = principal_role.strip().lower()
        requested = capability.strip()

        if not role:
            raise AuthorizationError("Authenticated principal role is required.")

        if not requested:
            raise AuthorizationError("Requested capability is required.")

        if role not in self._grants:
            raise AuthorizationError(
                f"Role {role!r} has no application capability grants."
            )

        if requested not in discovered_capabilities:
            raise AuthorizationError(
                f"Capability {requested!r} was not discovered from the MCP server."
            )

        if requested not in self._grants[role]:
            raise AuthorizationError(
                f"Role {role!r} is not authorized for capability {requested!r}."
            )

        return CapabilityAuthorization(
            principal_role=role,
            capability=requested,
            allowed=True,
            rule_id="CAP-ALLOWLIST-001",
            reason="Application-owned role allowlist permits execution.",
        )
