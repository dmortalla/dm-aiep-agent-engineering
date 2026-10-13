"""Application-owned permission policy, separate from capability discovery.

Construct the authorizer only from trusted application configuration and state.
Validation or a TrustLevel label cannot establish provenance. Never deserialize
policy or grants from model, tool, MCP, memory, or other contextual output.
Resource identifiers are logical exact-match names, not paths or isolation.
"""

from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from harness_engineering.capabilities import CapabilityRegistry
from harness_engineering.domain import Identifier, WorkflowIdentity
from harness_engineering.errors import ContractValidationError


class PolicyContract(BaseModel):
    """Frozen, revalidated contracts rejecting undeclared authority fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class RiskLevel(StrEnum):
    """Application-declared risk classification, never inferred from tool tags."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutionScope(PolicyContract):
    """Finite set of exact logical resource identifiers; no wildcard semantics."""

    resources: tuple[Identifier, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_resources(self) -> Self:
        """Reject duplicate resource declarations.

        Returns:
            The validated scope.

        Raises:
            ValueError: If resources are duplicated after normalization.
        """
        if len(self.resources) != len(set(self.resources)):
            raise ValueError("execution scope resources must be unique")
        return self


class CapabilityPermissionPolicy(PolicyContract):
    """Trusted configuration for one capability/action pair."""

    capability_id: Identifier
    action: Identifier
    scope: ExecutionScope
    risk: RiskLevel
    approval_required: bool = Field(default=True, strict=True)


class PermissionGrant(PolicyContract):
    """Application-issued scope grant bound to a principal and workflow.

    This data contract has no credential or self-asserted trust field. Its
    authority depends on being installed by the trusted application bootstrap.
    """

    principal_id: Identifier
    identity: WorkflowIdentity
    capability_id: Identifier
    action: Identifier
    scope: ExecutionScope

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, identity: WorkflowIdentity) -> WorkflowIdentity:
        """Revalidate workflow binding even for constructed identity instances.

        Args:
            identity: Application-issued workflow identity.

        Returns:
            A validated identity snapshot.

        Raises:
            ValidationError: If a constructed identity contains invalid values.
        """
        return WorkflowIdentity.model_validate(identity.model_dump())


class AuthorizationPolicy(PolicyContract):
    """Application-owned rules with deny-by-default and deny-overrides behavior."""

    capabilities: tuple[CapabilityPermissionPolicy, ...] = Field(default=(), max_length=100)
    blocked_actions: tuple[Identifier, ...] = Field(default=(), max_length=100)
    approval_risks: tuple[RiskLevel, ...] = (RiskLevel.MEDIUM, RiskLevel.HIGH)

    @model_validator(mode="after")
    def validate_unique_rules(self) -> Self:
        """Reject ambiguous rules or repeated blocklist/risk declarations.

        Returns:
            The validated policy.

        Raises:
            ValueError: If any policy declarations are duplicated.
        """
        keys = [(rule.capability_id, rule.action) for rule in self.capabilities]
        if len(keys) != len(set(keys)):
            raise ValueError("capability/action policy rules must be unique")
        if len(self.blocked_actions) != len(set(self.blocked_actions)):
            raise ValueError("blocked actions must be unique")
        if len(self.approval_risks) != len(set(self.approval_risks)):
            raise ValueError("approval risks must be unique")
        return self


class ActionProposal(PolicyContract):
    """Untrusted requested action; contains no permissions or approval claims."""

    capability_id: Identifier
    action: Identifier
    resource_id: Identifier


class ApprovalRequirement(PolicyContract):
    """Pending approval metadata; cannot serve as an approved decision.

    A later human-approval service must bind approval to exact inputs as well
    as this action and identity before execution. Slice 2 accepts no approvals.
    """

    principal_id: Identifier
    identity: WorkflowIdentity
    proposal: ActionProposal
    risk: RiskLevel


class AuthorizationOutcome(StrEnum):
    """Finite outcomes consumed by later application orchestration."""

    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class AuthorizationDecision(PolicyContract):
    """Policy result, not a transferable execution token.

    Consumers must call the authorizer at their execution boundary rather than
    accept serialized decisions from contextual or generated data.
    """

    outcome: AuthorizationOutcome
    reason: str
    approval: ApprovalRequirement | None = None

    @property
    def allowed(self) -> bool:
        """Return whether this policy evaluation allowed the proposed action."""
        return self.outcome is AuthorizationOutcome.ALLOW


class CapabilityAuthorizer:
    """Evaluate proposals against trusted, immutable application authority.

    Registry membership, tags, credentials, and provenance labels grant no
    access. Application code owns construction and principal/workflow binding.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        policy: AuthorizationPolicy,
        principal_id: str,
        identity: WorkflowIdentity,
        grants: tuple[PermissionGrant, ...] = (),
    ) -> None:
        """Snapshot validated authority from trusted application bootstrap.

        Args:
            registry: Accepted Slice 1 application capability registry.
            policy: Trusted application policy, never a generated proposal.
            principal_id: Principal resolved by trusted application state.
            identity: Workflow binding resolved by trusted application state.
            grants: At most 100 application-issued grants, never caller metadata.

        Raises:
            ContractValidationError: If configuration is malformed or references
                an unknown capability.
        """
        if len(grants) > 100:
            raise ContractValidationError(
                "Authorization configuration exceeds 100 permission grants."
            )
        try:
            self._policy = AuthorizationPolicy.model_validate(policy)
            self._grants = tuple(PermissionGrant.model_validate(grant) for grant in grants)
            # Reconstruct because the existing identity contract does not revalidate instances.
            self._identity = WorkflowIdentity.model_validate(identity.model_dump())
            self._principal = TypeAdapter(Identifier).validate_python(principal_id)
        except (ValidationError, AttributeError) as exc:
            raise ContractValidationError(
                "Invalid application authorization configuration."
            ) from exc
        for rule in self._policy.capabilities:
            registry.lookup(rule.capability_id)
        for grant in self._grants:
            registry.lookup(grant.capability_id)
        self._registry = registry

    def authorize(self, proposal: ActionProposal) -> AuthorizationDecision:
        """Evaluate an untrusted proposal; never invoke tools or accept approvals.

        Args:
            proposal: Requested action and exact logical target resource.

        Returns:
            Deterministic allow, deny, or non-authorized pending approval result.
            Invalid proposals fail closed as denials.
        """
        try:
            requested = ActionProposal.model_validate(proposal)
        except ValidationError:
            return AuthorizationDecision(
                outcome=AuthorizationOutcome.DENY, reason="invalid proposal"
            )
        if requested.action in self._policy.blocked_actions:
            return AuthorizationDecision(outcome=AuthorizationOutcome.DENY, reason="action blocked")
        try:
            self._registry.lookup(requested.capability_id)
        except ContractValidationError:
            return AuthorizationDecision(
                outcome=AuthorizationOutcome.DENY, reason="unknown capability"
            )
        rule = next(
            (
                rule
                for rule in self._policy.capabilities
                if (rule.capability_id, rule.action) == (requested.capability_id, requested.action)
            ),
            None,
        )
        if rule is None:
            return AuthorizationDecision(
                outcome=AuthorizationOutcome.DENY, reason="no action policy"
            )
        if requested.resource_id not in rule.scope.resources:
            return AuthorizationDecision(
                outcome=AuthorizationOutcome.DENY, reason="outside policy scope"
            )
        matching_grant = any(
            grant.principal_id == self._principal
            and grant.identity == self._identity
            and grant.capability_id == requested.capability_id
            and grant.action == requested.action
            and requested.resource_id in grant.scope.resources
            for grant in self._grants
        )
        if not matching_grant:
            return AuthorizationDecision(
                outcome=AuthorizationOutcome.DENY, reason="no matching permission"
            )
        if rule.approval_required or rule.risk in self._policy.approval_risks:
            return AuthorizationDecision(
                outcome=AuthorizationOutcome.APPROVAL_REQUIRED,
                reason="human approval required",
                approval=ApprovalRequirement(
                    principal_id=self._principal,
                    identity=self._identity,
                    proposal=requested,
                    risk=rule.risk,
                ),
            )
        return AuthorizationDecision(
            outcome=AuthorizationOutcome.ALLOW, reason="explicit permission matched"
        )
