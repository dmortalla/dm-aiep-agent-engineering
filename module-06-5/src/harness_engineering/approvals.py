"""Story 7 Slice 1: deterministic approval domain, without lifecycle or storage.

Trusted bootstrap installs policy, request metadata, and local human handles.
Only confidence/evidence and decision-shaped data are untrusted inputs. Current
safety facts must come from the application, never a model or persisted record.
Local handle identity demonstrates authorization, not human authentication or
isolation from arbitrary trusted Python code. Results are inert assessments;
they are not execution tokens, durable decisions, or permission grants.
"""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness_engineering.domain import Identifier
from harness_engineering.errors import AuthorityViolationError, ContractValidationError
from harness_engineering.permissions import RiskLevel

Confidence = Annotated[float, Field(ge=0, le=1, strict=True, allow_inf_nan=False)]
Evidence = Annotated[str, Field(max_length=2000, strict=True)]


class ApprovalContract(BaseModel):
    """Immutable, recursively revalidated domain objects with no undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class ActionBinding(ApprovalContract):
    """Exact action identity; trusted application increments version on action changes.

    No generated identity defaults or partial bindings are permitted. These
    references never select executable callbacks or graph nodes.
    """

    workflow_id: UUID
    thread_id: UUID
    pending_action_id: Identifier
    action_version: int = Field(ge=1, le=1_000_000, strict=True)


class HumanIdentity(ApprovalContract):
    """Local demonstration handle, authoritative only when installed by bootstrap.

    A separately constructed or deserialized matching identifier is not the
    installed handle. There is deliberately no self-asserted provenance field.
    """

    principal_id: Identifier


class ApprovalRequest(ApprovalContract):
    """Trusted pending-action metadata, separate from model confidence/evidence.

    Risk, scope privilege, consequential status, and escalation state are
    application facts. Never derive this object from contextual authority claims.
    """

    binding: ActionBinding
    requester_id: Identifier
    capability_id: Identifier
    action: Identifier
    risk: RiskLevel
    consequential: bool = Field(strict=True)
    privileged_scope: bool = Field(strict=True)
    escalation_required: bool = Field(strict=True)
    escalation_reason: Evidence

    @model_validator(mode="after")
    def validate_escalation(self) -> Self:
        """Require an explicit reason exactly when application escalation is active."""
        if self.escalation_required != bool(self.escalation_reason.strip()):
            raise ValueError("Escalation requires a nonblank reason; inactive escalation has none.")
        return self


class ApprovalObservation(ApprovalContract):
    """Untrusted finite confidence and bounded evidence, containing no authority."""

    confidence: Confidence
    evidence: Evidence = ""


class ApprovalPolicy(ApprovalContract):
    """Trusted application configuration; never selected or changed by model output."""

    confidence_threshold: Confidence = 0.80
    approval_risks: tuple[RiskLevel, ...] = Field(
        default=(RiskLevel.MEDIUM, RiskLevel.HIGH), max_length=3
    )

    @model_validator(mode="after")
    def validate_unique_risks(self) -> Self:
        """Reject ambiguous duplicate configured approval risks."""
        if len(set(self.approval_risks)) != len(self.approval_risks):
            raise ValueError("Approval risks must be unique.")
        return self


class BindingStatus(StrEnum):
    """Current application binding classification; this slice does not derive it."""

    CURRENT = "current"
    INVALID = "invalid"
    STALE = "stale"
    FORGED = "forged"
    REPLAYED = "replayed"
    CONSUMED = "consumed"
    MISMATCHED = "mismatched"


class ApprovalSafetyState(ApprovalContract):
    """Required current trusted facts; no default assumes a safe or fresh action.

    Later lifecycle/storage code must derive these facts and latch human denial.
    A caller declaring CURRENT does not prove durable freshness or consumption.
    """

    action_blocklisted: bool = Field(strict=True)
    capability_blocklisted: bool = Field(strict=True)
    cancelled: bool = Field(strict=True)
    binding_status: BindingStatus
    authority_valid: bool = Field(strict=True)
    hard_budget_exhausted: bool = Field(strict=True)
    deadline_exhausted: bool = Field(strict=True)
    scope_authorized: bool = Field(strict=True)
    prior_denial: bool = Field(strict=True)


class ApprovalTrigger(StrEnum):
    """Independent deterministic reasons for requiring human approval."""

    LOW_CONFIDENCE = "low_confidence"
    CONSEQUENTIAL = "consequential"
    PRIVILEGED_SCOPE = "privileged_scope"
    CONFIGURED_RISK = "configured_risk"
    ESCALATION = "escalation"


class HardStop(StrEnum):
    """Non-overridable reasons to reject the pending action."""

    ACTION_BLOCKLISTED = "action_blocklisted"
    CAPABILITY_BLOCKLISTED = "capability_blocklisted"
    CANCELLED = "cancelled"
    INVALID_BINDING = "invalid_binding"
    INVALID_AUTHORITY = "invalid_authority"
    HARD_BUDGET = "hard_budget_exhausted"
    DEADLINE = "deadline_exhausted"
    SCOPE_DENIED = "scope_denied"
    HUMAN_DENIAL = "human_denial"


class ApprovalAssessment(ApprovalContract):
    """Deterministic requirement assessment, never a transferable execution token."""

    request: ApprovalRequest
    observation: ApprovalObservation
    confidence_threshold: Confidence
    triggers: tuple[ApprovalTrigger, ...]
    hard_stops: tuple[HardStop, ...]

    @property
    def approval_required(self) -> bool:
        """Report independent approval triggers even when a hard stop also applies."""
        return bool(self.triggers)

    @property
    def may_proceed_without_approval(self) -> bool:
        """Report only approval-policy eligibility; tool permission remains separate."""
        return not self.triggers and not self.hard_stops


class HumanDecisionKind(StrEnum):
    """Finite decisions; override is explicit and distinct from ordinary approval."""

    APPROVE = "approve"
    DENY = "deny"
    OVERRIDE = "override"


class HumanDecision(ApprovalContract):
    """Untrusted decision data with exact binding and explicit override rationale.

    No approver identifier, trust label, policy, or safety configuration is
    accepted here. Approver authority is a separate installed local handle.
    """

    binding: ActionBinding
    kind: HumanDecisionKind
    evidence: Evidence = ""
    override_reason: Evidence = ""

    @model_validator(mode="after")
    def validate_override(self) -> Self:
        """Require a nonblank reason for override and reject hidden ordinary overrides."""
        if (self.kind is HumanDecisionKind.OVERRIDE) != bool(self.override_reason.strip()):
            raise ValueError("Override needs an explicit reason; ordinary decisions have none.")
        return self


class DecisionAssessment(ApprovalContract):
    """Inert decision evaluation carrying bounded evidence for later audit storage."""

    assessment: ApprovalAssessment
    approver_id: Identifier
    decision: HumanDecision

    @property
    def terminal_for_action(self) -> bool:
        """A valid denial terminates this pending action; it is not retry permission."""
        return self.decision.kind is HumanDecisionKind.DENY

    @property
    def is_override(self) -> bool:
        """Identify every override explicitly for later audit persistence."""
        return self.decision.kind is HumanDecisionKind.OVERRIDE


def _checked[Contract: ApprovalContract](
    value: Contract, contract: type[Contract], description: str
) -> Contract:
    if type(value) is not contract:
        raise ContractValidationError(f"{description} requires an explicit {contract.__name__}.")
    try:
        return contract.model_validate(value)
    except ValidationError as exc:
        raise ContractValidationError(f"Malformed {description}.") from exc


class ApprovalPolicyEvaluator:
    """One pending action's deterministic policy, with explicit bootstrap authority.

    Only trusted application code constructs this evaluator and supplies current
    safety facts. Matching identity text is insufficient: decisions require a
    handle object actually installed in the relevant allowlist. No persistence,
    decision consumption, off-switch reset, retry, fallback, or execution occurs.
    """

    def __init__(
        self,
        request: ApprovalRequest,
        policy: ApprovalPolicy,
        *,
        approvers: tuple[HumanIdentity, ...] = (),
        override_approvers: tuple[HumanIdentity, ...] = (),
    ) -> None:
        """Freeze application metadata and install separate human allowlists.

        Args:
            request: Trusted exact pending-action metadata.
            policy: Trusted threshold and configured risks.
            approvers: Local handles allowed to approve or deny.
            override_approvers: Independently installed handles allowed to override.

        Raises:
            ContractValidationError: For malformed or ambiguous trusted configuration.
        """
        self._request = _checked(request, ApprovalRequest, "approval request")
        self._policy = _checked(policy, ApprovalPolicy, "approval policy")
        self._approvers = self._allowlist(approvers)
        self._overrides = self._allowlist(override_approvers)
        ordinary = {principal: handle for handle, principal in self._approvers}
        for handle, principal in self._overrides:
            if principal in ordinary and ordinary[principal] is not handle:
                raise ContractValidationError("Shared authority must use the same local handle.")

    @staticmethod
    def _allowlist(handles: tuple[HumanIdentity, ...]) -> tuple[tuple[HumanIdentity, str], ...]:
        if type(handles) is not tuple or len(handles) > 100:
            raise ContractValidationError(
                "Allowlist must be an explicit tuple of at most 100 humans."
            )
        result = tuple(
            (handle, _checked(handle, HumanIdentity, "human identity").principal_id)
            for handle in handles
        )
        if len({principal for _, principal in result}) != len(result):
            raise ContractValidationError("Allowlist identities must be unique.")
        return result

    def evaluate(
        self, observation: ApprovalObservation, *, safety: ApprovalSafetyState
    ) -> ApprovalAssessment:
        """Compute all independent triggers and non-overridable stops in stable order.

        Args:
            observation: Untrusted confidence/evidence, never policy configuration.
            safety: Current application-owned safety facts, not persisted claims.

        Returns:
            Inert requirement assessment for this evaluator's exact pending action.

        Raises:
            ContractValidationError: For malformed observation or safety facts.
        """
        observed = _checked(observation, ApprovalObservation, "confidence observation")
        current = _checked(safety, ApprovalSafetyState, "current approval safety")
        request = self._request
        triggers = (
            (
                ApprovalTrigger.LOW_CONFIDENCE,
                observed.confidence < self._policy.confidence_threshold,
            ),
            (ApprovalTrigger.CONSEQUENTIAL, request.consequential),
            (ApprovalTrigger.PRIVILEGED_SCOPE, request.privileged_scope),
            (ApprovalTrigger.CONFIGURED_RISK, request.risk in self._policy.approval_risks),
            (ApprovalTrigger.ESCALATION, request.escalation_required),
        )
        hard_stops = (
            (HardStop.ACTION_BLOCKLISTED, current.action_blocklisted),
            (HardStop.CAPABILITY_BLOCKLISTED, current.capability_blocklisted),
            (HardStop.CANCELLED, current.cancelled),
            (HardStop.INVALID_BINDING, current.binding_status is not BindingStatus.CURRENT),
            (HardStop.INVALID_AUTHORITY, not current.authority_valid),
            (HardStop.HARD_BUDGET, current.hard_budget_exhausted),
            (HardStop.DEADLINE, current.deadline_exhausted),
            (HardStop.SCOPE_DENIED, not current.scope_authorized),
            (HardStop.HUMAN_DENIAL, current.prior_denial),
        )
        return ApprovalAssessment(
            request=request,
            observation=observed,
            confidence_threshold=self._policy.confidence_threshold,
            triggers=tuple(trigger for trigger, active in triggers if active),
            hard_stops=tuple(stop for stop, active in hard_stops if active),
        )

    def check_decision(
        self,
        decision: HumanDecision,
        *,
        actor: HumanIdentity | None,
        observation: ApprovalObservation,
        safety: ApprovalSafetyState,
    ) -> DecisionAssessment:
        """Check current human authority, exact binding, and hard safety before assessment.

        Args:
            decision: Untrusted bound decision data.
            actor: Original installed local human handle; None fails closed.
            observation: Confidence/evidence used in this policy evaluation.
            safety: Current trusted safety facts, including prior denial/binding status.

        Returns:
            Data-only checked decision with requester, binding, reasons, and evidence.

        Raises:
            ContractValidationError: For malformed input.
            AuthorityViolationError: For missing/unauthorized/self authority, mismatched
                binding, or any hard stop. No retry/fallback authority is returned.
        """
        checked = _checked(decision, HumanDecision, "human decision")
        allowlist = (
            self._overrides if checked.kind is HumanDecisionKind.OVERRIDE else self._approvers
        )
        principal = next((name for handle, name in allowlist if actor is handle), None)
        if principal is None:
            raise AuthorityViolationError("Decision requires an installed authorized human handle.")
        if _checked(actor, HumanIdentity, "approver identity").principal_id != principal:
            raise AuthorityViolationError("Installed human identity changed after bootstrap.")
        if principal == self._request.requester_id and checked.kind is not HumanDecisionKind.DENY:
            raise AuthorityViolationError("Requester self-approval or override is forbidden.")
        if checked.binding != self._request.binding:
            raise AuthorityViolationError(
                "Decision does not match the exact pending-action binding."
            )
        assessment = self.evaluate(observation, safety=safety)
        if assessment.hard_stops:
            raise AuthorityViolationError("Hard safety stop forbids approval or override.")
        return DecisionAssessment(assessment=assessment, approver_id=principal, decision=checked)
