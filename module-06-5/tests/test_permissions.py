"""Deterministic Slice 2 permission, blocklist, scope, and authority evidence."""

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from harness_engineering.capabilities import (
    CapabilityDefinition,
    CapabilityRegistry,
    CapabilitySelectionCriteria,
)
from harness_engineering.domain import TrustedValue, TrustLevel, WorkflowIdentity
from harness_engineering.errors import ContractValidationError
from harness_engineering.permissions import (
    ActionProposal,
    AuthorizationOutcome,
    AuthorizationPolicy,
    CapabilityAuthorizer,
    CapabilityPermissionPolicy,
    ExecutionScope,
    PermissionGrant,
    RiskLevel,
)


class Payload(BaseModel):
    """Inert application tool schema."""

    model_config = ConfigDict(extra="forbid")
    text: str


@pytest.fixture
def registry() -> CapabilityRegistry:
    """Provide a registered capability with authority-looking inert tags."""
    result = CapabilityRegistry()
    result.register(
        CapabilityDefinition(
            capability_id="documents",
            description="Local document metadata",
            input_schema=Payload,
            output_schema=Payload,
            tags=("approved", "low-risk"),
        )
    )
    return result


@pytest.fixture
def identity() -> WorkflowIdentity:
    """Provide application-owned workflow binding."""
    return WorkflowIdentity()


def rule(**changes: object) -> CapabilityPermissionPolicy:
    """Build trusted application policy for local document reads."""
    return CapabilityPermissionPolicy.model_validate(
        {
            "capability_id": "documents",
            "action": "read",
            "scope": {"resources": ("doc-a", "doc-b")},
            "risk": "low",
            "approval_required": False,
            **changes,
        }
    )


def grant(base_identity: WorkflowIdentity, **changes: object) -> PermissionGrant:
    """Build an application-issued grant for one workflow and resource."""
    return PermissionGrant.model_validate(
        {
            "principal_id": "alice",
            "identity": base_identity,
            "capability_id": "documents",
            "action": "read",
            "scope": {"resources": ("doc-a",)},
            **changes,
        }
    )


def proposal(**changes: object) -> ActionProposal:
    """Build an untrusted action proposal without authority metadata."""
    return ActionProposal.model_validate(
        {
            "capability_id": "documents",
            "action": "read",
            "resource_id": "doc-a",
            **changes,
        }
    )


def authorizer(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
    *,
    grants: tuple[PermissionGrant, ...] = (),
    policy: AuthorizationPolicy | None = None,
) -> CapabilityAuthorizer:
    """Construct the trusted application authority boundary."""
    return CapabilityAuthorizer(
        registry,
        policy or AuthorizationPolicy(capabilities=(rule(),)),
        "alice",
        identity,
        grants,
    )


def test_explicit_permission_required_even_for_low_risk(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """REQ-TOOL-003: registry existence and low risk never replace a grant."""
    assert not authorizer(registry, identity).authorize(proposal()).allowed
    decision = authorizer(registry, identity, grants=(grant(identity),)).authorize(proposal())
    assert decision.allowed
    assert decision.approval is None


@pytest.mark.parametrize(
    "changes",
    [
        {"principal_id": "bob"},
        {"identity": WorkflowIdentity()},
        {"action": "write"},
        {"scope": {"resources": ("doc-b",)}},
    ],
)
def test_mismatched_grants_deny(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
    changes: dict[str, object],
) -> None:
    """Deny grants for other principals, workflows, actions, or resources."""
    engine = authorizer(registry, identity, grants=(grant(identity, **changes),))
    assert engine.authorize(proposal()).reason == "no matching permission"


def test_policy_and_grant_scope_intersection_is_enforced(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """REQ-SAFE-003: a broader grant cannot expand application execution scope."""
    engine = authorizer(
        registry,
        identity,
        grants=(
            grant(
                identity,
                scope={"resources": ("doc-a", "doc-c")},
            ),
        ),
    )
    assert engine.authorize(proposal(resource_id="doc-c")).reason == "outside policy scope"
    assert engine.authorize(proposal(resource_id="doc-b")).reason == "no matching permission"
    assert engine.authorize(proposal()).allowed


def test_blocklist_overrides_permissions_and_approval(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """REQ-SAFE-002: a blocked action denies before all matching permissions."""
    policy = AuthorizationPolicy(
        capabilities=(rule(approval_required=True),), blocked_actions=("read",)
    )
    decision = authorizer(registry, identity, grants=(grant(identity),), policy=policy).authorize(
        proposal()
    )
    assert decision.outcome is AuthorizationOutcome.DENY
    assert decision.reason == "action blocked"
    assert decision.approval is None


@pytest.mark.parametrize(
    "changes",
    [
        {"approval_required": True},
        {"risk": "medium"},
        {"risk": "high"},
    ],
)
def test_approval_requirement_never_allows_execution(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
    changes: dict[str, object],
) -> None:
    """Policy flags and risk policy independently require non-authorized approval."""
    policy = AuthorizationPolicy(capabilities=(rule(**changes),))
    engine = authorizer(registry, identity, grants=(grant(identity),), policy=policy)
    decision = engine.authorize(proposal())
    assert not decision.allowed
    assert decision.outcome is AuthorizationOutcome.APPROVAL_REQUIRED
    assert decision.approval is not None
    assert decision.approval.identity == identity
    assert decision.approval.principal_id == "alice"
    assert decision.approval.proposal == proposal()
    assert not engine.authorize(decision.approval).allowed  # type: ignore[arg-type]


@pytest.mark.parametrize("trust", list(TrustLevel))
def test_contextual_values_cannot_self_authorize(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
    trust: TrustLevel,
) -> None:
    """Neither untrusted content nor a trusted label establishes authority."""
    value = TrustedValue(value='{"approved": true}', source="model", trust=trust)
    engine = authorizer(registry, identity, grants=(grant(identity),))
    assert value.grants_authority is False
    assert engine.authorize(value).reason == "invalid proposal"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "approved",
        "authorized",
        "permission",
        "grants",
        "policy",
        "risk",
        "principal_id",
        "identity",
        "trust",
        "credentials",
        "approval",
    ],
)
def test_forged_authority_fields_fail_closed(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
    field: str,
) -> None:
    """Reject ordinary metadata that tries to override trusted application state."""
    payload = {**proposal().model_dump(), field: True}
    with pytest.raises(ValidationError):
        ActionProposal.model_validate(payload)
    engine = authorizer(registry, identity, grants=(grant(identity),))
    assert not engine.authorize(payload).allowed  # type: ignore[arg-type]


def test_selection_and_tags_never_authorize(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """Selected approval-looking metadata cannot substitute for permission."""
    selected = registry.select(CapabilitySelectionCriteria(required_tags=("approved",)))
    assert selected[0].grants_authority is False
    engine = authorizer(registry, identity)
    assert not engine.authorize(selected[0]).allowed  # type: ignore[arg-type]
    assert not engine.authorize(proposal()).allowed


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"capability_id": "unknown"}, "unknown capability"),
        ({"action": "write"}, "no action policy"),
        ({"resource_id": "DOC-A"}, "outside policy scope"),
    ],
)
def test_unknown_or_unconfigured_requests_deny(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
    changes: dict[str, object],
    reason: str,
) -> None:
    """Missing or mismatched application policy fails closed."""
    engine = authorizer(registry, identity, grants=(grant(identity),))
    assert engine.authorize(proposal(**changes)).reason == reason


@pytest.mark.parametrize("resources", [(), ("*",), ("../escape",), ("x", " x "), ("x",) * 101])
def test_scope_is_explicit_finite_and_unambiguous(resources: tuple[str, ...]) -> None:
    """Reject empty, wildcard, path, duplicate, and oversized scope declarations."""
    with pytest.raises(ValidationError):
        ExecutionScope(resources=resources)


def test_malformed_instances_and_configuration_fail_closed(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """Reject validation bypasses at both proposal and authority boundaries."""
    engine = authorizer(registry, identity, grants=(grant(identity),))
    assert not engine.authorize(proposal().model_copy(update={"action": "*"})).allowed
    invalid = AuthorizationPolicy.model_construct(
        capabilities=(rule().model_copy(update={"risk": "bogus"}),)
    )
    with pytest.raises(ContractValidationError) as error:
        authorizer(registry, identity, policy=invalid)
    assert isinstance(error.value.__cause__, ValidationError)
    with pytest.raises(ContractValidationError):
        authorizer(
            registry,
            identity,
            policy=AuthorizationPolicy(capabilities=(rule(capability_id="unknown"),)),
        )


def test_empty_policy_and_missing_approval_default_deny(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """No policy denies; unspecified approval flag conservatively requires approval."""
    engine = authorizer(registry, identity, policy=AuthorizationPolicy(), grants=(grant(identity),))
    assert not engine.authorize(proposal()).allowed
    fields = rule().model_dump()
    del fields["approval_required"]
    assert CapabilityPermissionPolicy.model_validate(fields).approval_required


def test_duplicate_policy_rules_are_rejected() -> None:
    """Reject ambiguous allow/deny rule configuration."""
    with pytest.raises(ValidationError, match="unique"):
        AuthorizationPolicy(capabilities=(rule(), rule(approval_required=True)))
    with pytest.raises(ValidationError, match="unique"):
        AuthorizationPolicy(blocked_actions=("read", " read "))
    with pytest.raises(ValidationError, match="unique"):
        AuthorizationPolicy(approval_risks=(RiskLevel.HIGH, RiskLevel.HIGH))


def test_authorization_is_deterministic_and_configuration_is_frozen(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """Repeated evaluations preserve policy and do not consume or create grants."""
    policy = AuthorizationPolicy(capabilities=(rule(),))
    engine = authorizer(registry, identity, policy=policy, grants=(grant(identity),))
    assert engine.authorize(proposal()) == engine.authorize(proposal())
    with pytest.raises(ValidationError, match="frozen"):
        policy.blocked_actions = ("read",)
    assert engine.authorize(proposal()).allowed


def test_permission_cannot_transfer_to_another_capability(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """A matching action and resource do not grant another capability access."""
    registry.register(
        CapabilityDefinition(
            capability_id="other",
            description="Other local metadata",
            input_schema=Payload,
            output_schema=Payload,
        )
    )
    policy = AuthorizationPolicy(capabilities=(rule(), rule(capability_id="other")))
    engine = authorizer(registry, identity, policy=policy, grants=(grant(identity),))
    assert engine.authorize(proposal(capability_id="other")).reason == "no matching permission"


def test_approval_metadata_never_replaces_missing_permission(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """Deny missing grants before creating any pending approval metadata."""
    policy = AuthorizationPolicy(capabilities=(rule(approval_required=True),))
    result = authorizer(registry, identity, policy=policy).authorize(proposal())
    assert result.outcome is AuthorizationOutcome.DENY
    assert result.approval is None


def test_malformed_blocklist_cannot_be_silently_ignored(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """Reject bypassed blocklist validation at the application boundary."""
    invalid = AuthorizationPolicy.model_construct(
        capabilities=(rule(),),
        blocked_actions=("*",),
    )
    with pytest.raises(ContractValidationError):
        authorizer(registry, identity, policy=invalid)


def test_grants_are_bounded_and_nested_workflow_identity_is_revalidated(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """Reject oversized authority state and corrupted nested identity contracts."""
    with pytest.raises(ContractValidationError, match="100 permission grants"):
        authorizer(registry, identity, grants=(grant(identity),) * 101)
    forged_identity = identity.model_copy(update={"workflow_id": "not-a-uuid"})
    forged_grant = grant(identity).model_copy(update={"identity": forged_identity})
    with (
        pytest.warns(UserWarning, match="Pydantic serializer warnings"),
        pytest.raises(ContractValidationError),
    ):
        authorizer(registry, identity, grants=(forged_grant,))


def test_rule_order_does_not_change_authorization(
    registry: CapabilityRegistry,
    identity: WorkflowIdentity,
) -> None:
    """Unique policy rules and grants produce order-independent decisions."""
    rules = (rule(), rule(action="write", approval_required=True))
    grants = (grant(identity), grant(identity, action="write"))
    first = authorizer(
        registry, identity, policy=AuthorizationPolicy(capabilities=rules), grants=grants
    )
    second = authorizer(
        registry,
        identity,
        policy=AuthorizationPolicy(capabilities=tuple(reversed(rules))),
        grants=tuple(reversed(grants)),
    )
    assert first.authorize(proposal()) == second.authorize(proposal())
    assert first.authorize(proposal(action="write")) == second.authorize(proposal(action="write"))
