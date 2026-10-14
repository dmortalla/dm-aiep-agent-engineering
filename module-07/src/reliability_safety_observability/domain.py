"""Typed application-owned contracts for Module 7."""

from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
OperationName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]

# Structural interoperability bound only. Operational retry policy belongs to Story 3.
MAX_COUNTER = 2_147_483_647


class EvidenceClass(StrEnum):
    """Permitted evidence classifications for implementation claims."""

    DETERMINISTIC_FIXTURE = "deterministic_fixture"
    SIMULATED_FAILURE = "simulated_failure"
    MOCKED_PROVIDER_CONTRACT = "mocked_provider_contract"
    LIVE_VENDOR = "live_vendor"
    LIVE_MODEL = "live_model"


class ExecutionMode(StrEnum):
    """Supported execution modes."""

    DETERMINISTIC = "deterministic"
    LIVE = "live"


class Decision(StrEnum):
    """Generic bounded decision outcome."""

    ALLOW = "allow"
    DENY = "deny"


class TerminalStatus(StrEnum):
    """Terminal workflow outcomes recorded by later execution stories."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


class WorkflowIdentity(BaseModel):
    """Immutable correlation identity for one workflow execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)


class UntrustedContent(BaseModel):
    """Content that has not crossed an application trust boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Annotated[str, StringConstraints(max_length=20_000)]
    source: Identifier = "user"


class AuthorizationDecision(BaseModel):
    """Application-owned authorization result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    policy_id: Identifier
    reason: Identifier


class SafetyDecision(BaseModel):
    """Safety validation result that carries no authorization authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    validator: Identifier
    reason: Identifier


class UsageRecord(BaseModel):
    """Bounded usage and finite normalized cost information."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(default=0, ge=0, le=MAX_COUNTER)
    output_tokens: int = Field(default=0, ge=0, le=MAX_COUNTER)
    cost_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)


class BudgetState(BaseModel):
    """Typed budget state without implementing budget enforcement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_limit_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    cost_used_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_cost_usage(self) -> "BudgetState":
        """Reject internally contradictory budget state.

        Returns:
            The validated budget state.

        Raises:
            ValueError: If recorded cost exceeds the represented budget.
        """
        if self.cost_used_usd > self.cost_limit_usd:
            raise ValueError("Recorded cost cannot exceed the represented budget.")
        return self


class TelemetryRecord(BaseModel):
    """Normalized telemetry independent of any vendor exporter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID
    trace_id: UUID
    span_id: UUID = Field(default_factory=uuid4)
    operation: OperationName
    status: Identifier
    duration_ms: float = Field(ge=0.0, allow_inf_nan=False)
    retry_attempt: int = Field(default=0, ge=0, le=MAX_COUNTER)
    fallback_used: bool = False
    safety_decision: Decision | None = None
    authorization_decision: Decision | None = None
    usage: UsageRecord = Field(default_factory=UsageRecord)
    error_classification: Identifier | None = None
    evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_FIXTURE


class EvaluationResult(BaseModel):
    """Provider-neutral evaluation result contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluator: Identifier
    metric: Identifier
    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    passed: bool
    evidence_class: EvidenceClass


class ReliabilityResult(BaseModel):
    """Result metadata for later resilience execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempts: int = Field(ge=1, le=MAX_COUNTER)
    fallback_used: bool = False
    recovered: bool = False


class ProviderResult(BaseModel):
    """Provider-neutral result whose payload remains untrusted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Identifier
    payload: Any
    evidence_class: EvidenceClass


class WorkflowState(BaseModel):
    """Bounded immutable workflow state for deterministic foundations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: WorkflowIdentity
    idempotency_key: UUID = Field(default_factory=uuid4)
    operation: OperationName
    evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_FIXTURE
    authorization: AuthorizationDecision | None = None
    safety: SafetyDecision | None = None
    retry_attempt: int = Field(default=0, ge=0, le=MAX_COUNTER)
    fallback_used: bool = False
    budget: BudgetState = Field(default_factory=BudgetState)
    usage: UsageRecord = Field(default_factory=UsageRecord)
    terminal_status: TerminalStatus | None = None

    @field_validator("authorization", mode="before")
    @classmethod
    def require_typed_authorization(
        cls, value: object
    ) -> AuthorizationDecision | None:
        """Reject authorization-shaped data that lacks application authority.

        Args:
            value: Candidate authorization value.

        Returns:
            An application-owned authorization decision or None.

        Raises:
            ValueError: If untrusted data attempts to cross the authority boundary.
        """
        if value is not None and not isinstance(value, AuthorizationDecision):
            raise ValueError(
                "Authorization requires an application-owned AuthorizationDecision."
            )
        return value

    @field_validator("safety", mode="before")
    @classmethod
    def require_typed_safety(cls, value: object) -> SafetyDecision | None:
        """Reject safety-shaped data that lacks a validated safety decision.

        Args:
            value: Candidate safety value.

        Returns:
            A typed safety decision or None.

        Raises:
            ValueError: If untrusted data attempts to cross the safety boundary.
        """
        if value is not None and not isinstance(value, SafetyDecision):
            raise ValueError("Safety requires an application-owned SafetyDecision.")
        return value

    def validated_update(self, **changes: object) -> "WorkflowState":
        """Return a new workflow state after complete validation.

        Args:
            **changes: State fields to replace atomically.

        Returns:
            A newly validated immutable workflow state.
        """
        values = {name: getattr(self, name) for name in type(self).model_fields}
        values.update(changes)
        return type(self).model_validate(values)
