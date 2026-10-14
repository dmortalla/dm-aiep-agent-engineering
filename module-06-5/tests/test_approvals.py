"""Deterministic Story 7 Slice 1 policy/authority evidence; no persistence or execution."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from harness_engineering.approvals import (
    ActionBinding,
    ApprovalObservation,
    ApprovalPolicy,
    ApprovalPolicyEvaluator,
    ApprovalRequest,
    ApprovalSafetyState,
    ApprovalTrigger,
    BindingStatus,
    HardStop,
    HumanDecision,
    HumanDecisionKind,
    HumanIdentity,
)
from harness_engineering.domain import TrustedValue, TrustLevel
from harness_engineering.errors import AuthorityViolationError, ContractValidationError
from harness_engineering.permissions import RiskLevel


def binding(**changes: object) -> ActionBinding:
    """Explicit trusted workflow/thread/action/version fixture."""
    return ActionBinding.model_validate(
        {
            "workflow_id": UUID(int=1),
            "thread_id": UUID(int=2),
            "pending_action_id": "action-1",
            "action_version": 1,
            **changes,
        }
    )


def request(**changes: object) -> ApprovalRequest:
    """Application-owned safe action; model data never supplies these facts."""
    return ApprovalRequest.model_validate(
        {
            "binding": binding(),
            "requester_id": "requester-1",
            "capability_id": "documents",
            "action": "read",
            "risk": RiskLevel.LOW,
            "consequential": False,
            "privileged_scope": False,
            "escalation_required": False,
            "escalation_reason": "",
            **changes,
        }
    )


def safety(**changes: object) -> ApprovalSafetyState:
    """Explicit current application facts; no persisted freshness claim."""
    return ApprovalSafetyState.model_validate(
        {
            "action_blocklisted": False,
            "capability_blocklisted": False,
            "cancelled": False,
            "binding_status": BindingStatus.CURRENT,
            "authority_valid": True,
            "hard_budget_exhausted": False,
            "deadline_exhausted": False,
            "scope_authorized": True,
            "prior_denial": False,
            **changes,
        }
    )


def decision(
    kind: HumanDecisionKind = HumanDecisionKind.APPROVE, **changes: object
) -> HumanDecision:
    """Inert bound human intent, containing no self-issued approver authority."""
    return HumanDecision.model_validate(
        {
            "binding": binding(),
            "kind": kind,
            "evidence": "local reviewer evidence",
            "override_reason": "reviewed ordinary escalation"
            if kind is HumanDecisionKind.OVERRIDE
            else "",
            **changes,
        }
    )


@pytest.fixture
def humans() -> tuple[HumanIdentity, HumanIdentity]:
    """Bootstrap-owned handles, independent ordinary and override identities."""
    return (
        HumanIdentity(principal_id="approver-1"),
        HumanIdentity(principal_id="override-approver-1"),
    )


def evaluator(
    humans: tuple[HumanIdentity, HumanIdentity], **changes: object
) -> ApprovalPolicyEvaluator:
    return ApprovalPolicyEvaluator(
        request(),
        ApprovalPolicy(),
        approvers=(humans[0],),
        override_approvers=(humans[1],),
        **changes,
    )


@pytest.mark.parametrize(
    "confidence,required",
    [(0.0, True), (0.799999, True), (0.80, False), (0.81, False), (1.0, False)],
)
def test_default_threshold_boundary(confidence: float, required: bool) -> None:
    policy = ApprovalPolicyEvaluator(request(), ApprovalPolicy())
    result = policy.evaluate(ApprovalObservation(confidence=confidence), safety=safety())
    assert result.confidence_threshold == 0.80
    assert result.approval_required is required
    assert result.may_proceed_without_approval is (not required)
    assert result.triggers == ((ApprovalTrigger.LOW_CONFIDENCE,) if required else ())


@pytest.mark.parametrize(
    "threshold,confidence,required",
    [
        (0.9, 0.85, True),
        (0.9, 0.9, False),
        (0.6, 0.7, False),
        (0.0, 0.0, False),
        (1.0, 0.99, True),
        (1.0, 1.0, False),
    ],
)
def test_configurable_threshold(threshold: float, confidence: float, required: bool) -> None:
    policy = ApprovalPolicyEvaluator(request(), ApprovalPolicy(confidence_threshold=threshold))
    result = policy.evaluate(ApprovalObservation(confidence=confidence), safety=safety())
    assert result.confidence_threshold == threshold
    assert result.approval_required is required


@pytest.mark.parametrize(
    "changes,trigger",
    [
        ({"consequential": True}, ApprovalTrigger.CONSEQUENTIAL),
        ({"privileged_scope": True}, ApprovalTrigger.PRIVILEGED_SCOPE),
        ({"risk": RiskLevel.MEDIUM}, ApprovalTrigger.CONFIGURED_RISK),
        ({"risk": RiskLevel.HIGH}, ApprovalTrigger.CONFIGURED_RISK),
        (
            {"escalation_required": True, "escalation_reason": "human review required"},
            ApprovalTrigger.ESCALATION,
        ),
    ],
)
def test_high_confidence_cannot_bypass_independent_trigger(
    changes: dict[str, object], trigger: ApprovalTrigger
) -> None:
    policy = ApprovalPolicyEvaluator(request(**changes), ApprovalPolicy())
    result = policy.evaluate(ApprovalObservation(confidence=1.0), safety=safety())
    assert result.approval_required
    assert not result.may_proceed_without_approval
    assert result.triggers == (trigger,)


def test_all_triggers_preserved_in_deterministic_order() -> None:
    policy = ApprovalPolicyEvaluator(
        request(
            consequential=True,
            privileged_scope=True,
            risk=RiskLevel.HIGH,
            escalation_required=True,
            escalation_reason="review escalation",
        ),
        ApprovalPolicy(),
    )
    result = policy.evaluate(ApprovalObservation(confidence=0.2), safety=safety())
    assert result.triggers == tuple(ApprovalTrigger)
    assert result == policy.evaluate(ApprovalObservation(confidence=0.2), safety=safety())


def test_configured_risk_is_independent_of_other_triggers() -> None:
    configured = ApprovalPolicyEvaluator(request(), ApprovalPolicy(approval_risks=(RiskLevel.LOW,)))
    assert configured.evaluate(
        ApprovalObservation(confidence=1.0), safety=safety()
    ).approval_required
    high = ApprovalPolicyEvaluator(
        request(risk=RiskLevel.HIGH, consequential=True), ApprovalPolicy(approval_risks=())
    )
    result = high.evaluate(ApprovalObservation(confidence=1.0), safety=safety())
    assert result.triggers == (ApprovalTrigger.CONSEQUENTIAL,)


def test_authorized_ordinary_approval_and_denial(
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    policy = evaluator(humans)
    approved = policy.check_decision(
        decision(),
        actor=humans[0],
        observation=ApprovalObservation(confidence=0.5),
        safety=safety(),
    )
    assert approved.approver_id == "approver-1"
    assert approved.assessment.request.requester_id == "requester-1"
    assert approved.decision.binding == binding()
    assert approved.assessment.confidence_threshold == 0.80
    assert approved.assessment.triggers == (ApprovalTrigger.LOW_CONFIDENCE,)
    assert not approved.terminal_for_action
    assert not approved.is_override
    denied = policy.check_decision(
        decision(HumanDecisionKind.DENY),
        actor=humans[0],
        observation=ApprovalObservation(confidence=1.0),
        safety=safety(),
    )
    assert denied.terminal_for_action
    assert not denied.is_override
    assert denied.decision.evidence == "local reviewer evidence"
    assert not hasattr(denied, "retry_permission")
    assert not hasattr(denied, "fallback_permission")


@pytest.mark.parametrize("kind", list(HumanDecisionKind))
def test_self_approval_and_override_forbidden_but_authorized_self_denial_terminal(
    kind: HumanDecisionKind,
) -> None:
    requester = HumanIdentity(principal_id="requester-1")
    policy = ApprovalPolicyEvaluator(
        request(), ApprovalPolicy(), approvers=(requester,), override_approvers=(requester,)
    )
    if kind is HumanDecisionKind.DENY:
        result = policy.check_decision(
            decision(kind),
            actor=requester,
            observation=ApprovalObservation(confidence=0.1),
            safety=safety(),
        )
        assert result.terminal_for_action
    else:
        with pytest.raises(AuthorityViolationError, match="self-approval"):
            policy.check_decision(
                decision(kind),
                actor=requester,
                observation=ApprovalObservation(confidence=0.1),
                safety=safety(),
            )


@pytest.mark.parametrize("kind", list(HumanDecisionKind))
@pytest.mark.parametrize(
    "source",
    [
        "missing",
        "unknown",
        "matching-copy",
        "persisted",
        "string",
        "dict",
        "model",
        "agent",
        "untrusted",
        "self-labelled-trusted",
    ],
)
def test_untrusted_matching_identity_never_grants_authority(
    humans: tuple[HumanIdentity, HumanIdentity], kind: HumanDecisionKind, source: str
) -> None:
    installed = humans[1] if kind is HumanDecisionKind.OVERRIDE else humans[0]
    identities: dict[str, object] = {
        "missing": None,
        "unknown": HumanIdentity(principal_id="unknown"),
        "matching-copy": installed.model_copy(),
        "persisted": HumanIdentity.model_validate_json(installed.model_dump_json()),
        "string": installed.principal_id,
        "dict": installed.model_dump(),
    }
    for key, trust in [
        ("model", TrustLevel.UNTRUSTED_MODEL),
        ("agent", TrustLevel.UNTRUSTED_AGENT),
        ("untrusted", TrustLevel.UNTRUSTED_EXTERNAL),
        ("self-labelled-trusted", TrustLevel.TRUSTED_APPLICATION),
    ]:
        identities[key] = TrustedValue(value=installed.principal_id, source="local", trust=trust)
    with pytest.raises(AuthorityViolationError, match="installed"):
        evaluator(humans).check_decision(
            decision(kind),
            actor=identities[source],
            observation=ApprovalObservation(confidence=1.0),
            safety=safety(),
        )


def test_override_authority_is_separate_and_explicit(
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    policy = evaluator(humans)
    with pytest.raises(AuthorityViolationError):
        policy.check_decision(
            decision(HumanDecisionKind.OVERRIDE),
            actor=humans[0],
            observation=ApprovalObservation(confidence=0.2),
            safety=safety(),
        )
    with pytest.raises(AuthorityViolationError):
        policy.check_decision(
            decision(),
            actor=humans[1],
            observation=ApprovalObservation(confidence=0.2),
            safety=safety(),
        )
    override = policy.check_decision(
        decision(HumanDecisionKind.OVERRIDE),
        actor=humans[1],
        observation=ApprovalObservation(confidence=0.2),
        safety=safety(),
    )
    assert override.is_override
    assert override.approver_id == "override-approver-1"
    assert override.decision.override_reason == "reviewed ordinary escalation"
    assert override.assessment.triggers == (ApprovalTrigger.LOW_CONFIDENCE,)
    assert not override.terminal_for_action
    both = ApprovalPolicyEvaluator(
        request(), ApprovalPolicy(), approvers=(humans[0],), override_approvers=(humans[0],)
    )
    assert both.check_decision(
        decision(HumanDecisionKind.OVERRIDE),
        actor=humans[0],
        observation=ApprovalObservation(confidence=0.2),
        safety=safety(),
    ).is_override


@pytest.mark.parametrize(
    "changes,stop",
    [
        ({"action_blocklisted": True}, HardStop.ACTION_BLOCKLISTED),
        ({"capability_blocklisted": True}, HardStop.CAPABILITY_BLOCKLISTED),
        ({"cancelled": True}, HardStop.CANCELLED),
        ({"authority_valid": False}, HardStop.INVALID_AUTHORITY),
        ({"hard_budget_exhausted": True}, HardStop.HARD_BUDGET),
        ({"deadline_exhausted": True}, HardStop.DEADLINE),
        ({"scope_authorized": False}, HardStop.SCOPE_DENIED),
        ({"prior_denial": True}, HardStop.HUMAN_DENIAL),
        *[
            ({"binding_status": status}, HardStop.INVALID_BINDING)
            for status in BindingStatus
            if status is not BindingStatus.CURRENT
        ],
    ],
)
@pytest.mark.parametrize("kind", [HumanDecisionKind.APPROVE, HumanDecisionKind.OVERRIDE])
def test_hard_invariants_never_overridden(
    humans: tuple[HumanIdentity, HumanIdentity],
    changes: dict[str, object],
    stop: HardStop,
    kind: HumanDecisionKind,
) -> None:
    policy = evaluator(humans)
    result = policy.evaluate(ApprovalObservation(confidence=1.0), safety=safety(**changes))
    assert result.hard_stops == (stop,)
    assert not result.may_proceed_without_approval
    actor = humans[1] if kind is HumanDecisionKind.OVERRIDE else humans[0]
    with pytest.raises(AuthorityViolationError, match="Hard safety"):
        policy.check_decision(
            decision(kind),
            actor=actor,
            observation=ApprovalObservation(confidence=1.0),
            safety=safety(**changes),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_id", UUID(int=3)),
        ("thread_id", UUID(int=4)),
        ("pending_action_id", "action-2"),
        ("action_version", 2),
    ],
)
@pytest.mark.parametrize("kind", list(HumanDecisionKind))
def test_every_binding_dimension_must_match(
    humans: tuple[HumanIdentity, HumanIdentity], field: str, value: object, kind: HumanDecisionKind
) -> None:
    changed = binding(**{field: value})
    assert changed != binding()
    actor = humans[1] if kind is HumanDecisionKind.OVERRIDE else humans[0]
    with pytest.raises(AuthorityViolationError, match="exact pending-action"):
        evaluator(humans).check_decision(
            decision(kind, binding=changed),
            actor=actor,
            observation=ApprovalObservation(confidence=1.0),
            safety=safety(),
        )


@pytest.mark.parametrize(
    "value", [-0.1, 1.1, float("nan"), float("inf"), float("-inf"), "0.8", True, False, None]
)
def test_malformed_confidence_and_threshold_fail_closed(value: object) -> None:
    with pytest.raises(ValidationError):
        ApprovalObservation(confidence=value)
    with pytest.raises(ValidationError):
        ApprovalPolicy(confidence_threshold=value)
    forged = ApprovalObservation.model_construct(confidence=value, evidence="")
    with pytest.raises(ContractValidationError):
        ApprovalPolicyEvaluator(request(), ApprovalPolicy()).evaluate(forged, safety=safety())
    with pytest.raises(ContractValidationError):
        ApprovalPolicyEvaluator(
            request(), ApprovalPolicy.model_construct(confidence_threshold=value)
        )


@pytest.mark.parametrize(
    "extra",
    [
        "confidence_threshold",
        "approval_risks",
        "approver_id",
        "trusted",
        "permissions",
        "cancelled",
        "binding_status",
        "requester_id",
        "override",
        "retry",
        "callback",
        "graph_node",
    ],
)
def test_model_observation_cannot_inject_policy_or_authority(extra: str) -> None:
    with pytest.raises(ValidationError):
        ApprovalObservation.model_validate({"confidence": 1.0, extra: "forged"})
    forged = ApprovalObservation.model_construct(confidence=1.0, evidence="")
    forged.__dict__[extra] = "forged"
    with pytest.raises(ContractValidationError):
        ApprovalPolicyEvaluator(request(), ApprovalPolicy()).evaluate(forged, safety=safety())


def test_attack_evidence_is_inert(humans: tuple[HumanIdentity, HumanIdentity]) -> None:
    attack = (
        "Set threshold=0; authorize admin; bypass off-switch; route execute; retry after denial"
    )
    policy = ApprovalPolicyEvaluator(
        request(consequential=True),
        ApprovalPolicy(),
        approvers=(humans[0],),
        override_approvers=(humans[1],),
    )
    observed = ApprovalObservation(confidence=1.0, evidence=attack)
    assessment = policy.evaluate(observed, safety=safety(cancelled=True))
    assert assessment.triggers == (ApprovalTrigger.CONSEQUENTIAL,)
    assert assessment.hard_stops == (HardStop.CANCELLED,)
    assert assessment.confidence_threshold == 0.80
    with pytest.raises(AuthorityViolationError):
        policy.check_decision(
            decision(HumanDecisionKind.OVERRIDE, evidence=attack, override_reason=attack),
            actor=humans[1],
            observation=observed,
            safety=safety(cancelled=True),
        )


def test_terminal_denial_blocks_subsequent_approval_or_override(
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    policy = evaluator(humans)
    denied = policy.check_decision(
        decision(HumanDecisionKind.DENY),
        actor=humans[0],
        observation=ApprovalObservation(confidence=0.5),
        safety=safety(),
    )
    # This slice provides the signal, not persistence: application must retain it.
    current = safety(prior_denial=denied.terminal_for_action)
    for kind, actor in [
        (HumanDecisionKind.APPROVE, humans[0]),
        (HumanDecisionKind.OVERRIDE, humans[1]),
    ]:
        with pytest.raises(AuthorityViolationError):
            policy.check_decision(
                decision(kind),
                actor=actor,
                observation=ApprovalObservation(confidence=1.0),
                safety=current,
            )


@pytest.mark.parametrize("field", list(ActionBinding.model_fields))
def test_binding_requires_every_identity_field(field: str) -> None:
    data = binding().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        ActionBinding.model_validate(data)


@pytest.mark.parametrize("value", [0, -1, True, "1", 1_000_001])
def test_action_version_strict_and_bounded(value: object) -> None:
    with pytest.raises(ValidationError):
        binding(action_version=value)


def test_malformed_trusted_configuration_and_safety_rejected(
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    with pytest.raises(ValidationError):
        ApprovalPolicy(approval_risks=(RiskLevel.LOW, RiskLevel.LOW))
    for handles in [
        (humans[0], humans[0]),
        [humans[0]],
        ("approver-1",),
        (HumanIdentity.model_construct(principal_id=None),),
        (humans[0],) * 101,
    ]:
        with pytest.raises(ContractValidationError):
            ApprovalPolicyEvaluator(request(), ApprovalPolicy(), approvers=handles)
    with pytest.raises(ContractValidationError):
        ApprovalPolicyEvaluator(
            request(),
            ApprovalPolicy(),
            approvers=(humans[0],),
            override_approvers=(humans[0].model_copy(),),
        )
    with pytest.raises(ContractValidationError):
        ApprovalPolicyEvaluator(request().model_dump(), ApprovalPolicy())
    with pytest.raises(ContractValidationError):
        ApprovalPolicyEvaluator(request(), ApprovalPolicy().model_dump())
    malformed_request = request().model_copy(update={"privileged_scope": "false"})
    with pytest.raises(ContractValidationError):
        ApprovalPolicyEvaluator(malformed_request, ApprovalPolicy())
    policy = evaluator(humans)
    for bad in [
        safety().model_dump(),
        safety().model_copy(update={"cancelled": "false"}),
        ApprovalSafetyState.model_construct(),
    ]:
        with pytest.raises(ContractValidationError):
            policy.evaluate(ApprovalObservation(confidence=1.0), safety=bad)


@pytest.mark.parametrize(
    "case",
    [
        "missing-override-reason",
        "blank-override-reason",
        "hidden-override",
        "extra-authority",
        "unknown-kind",
        "oversized-evidence",
    ],
)
def test_malformed_human_decision_rejected(case: str) -> None:
    data = decision().model_dump()
    if case in {"missing-override-reason", "blank-override-reason"}:
        data["kind"] = HumanDecisionKind.OVERRIDE
        data["override_reason"] = "" if case == "missing-override-reason" else "   "
    elif case == "hidden-override":
        data["override_reason"] = "silently override"
    elif case == "extra-authority":
        data["approver_id"] = "approver-1"
    elif case == "unknown-kind":
        data["kind"] = "execute"
    else:
        data["evidence"] = "x" * 2001
    with pytest.raises(ValidationError):
        HumanDecision.model_validate(data)


def test_forged_decision_and_nested_binding_revalidated(
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    policy = evaluator(humans)
    bad_binding = binding().model_copy(update={"action_version": True})
    for bad in [
        decision().model_copy(update={"kind": "execute"}),
        decision().model_copy(update={"binding": bad_binding}),
        decision().model_dump(),
    ]:
        with pytest.raises(ContractValidationError):
            policy.check_decision(
                bad,
                actor=humans[0],
                observation=ApprovalObservation(confidence=0.2),
                safety=safety(),
            )


def test_installed_identity_is_pinned_and_contracts_are_frozen(
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    policy = evaluator(humans)
    with pytest.raises(ValidationError):
        humans[0].principal_id = "requester-1"
    with pytest.raises(ValidationError):
        binding().action_version = 2
    with pytest.raises(ValidationError):
        ApprovalPolicy().confidence_threshold = 0.0
    # Arbitrary Python is not sandboxed; accidental bootstrap mutation still fails.
    object.__setattr__(humans[0], "principal_id", "changed")
    with pytest.raises(AuthorityViolationError, match="changed"):
        policy.check_decision(
            decision(),
            actor=humans[0],
            observation=ApprovalObservation(confidence=0.2),
            safety=safety(),
        )
