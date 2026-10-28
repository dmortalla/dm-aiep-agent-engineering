"""Typed domain contracts for the governed agent harness.

These contracts establish fail-closed primitives shared by later planning,
execution, recovery, approval, observability, and evaluation components.
"""

from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class TrustLevel(StrEnum):
    """Classify whether information may be trusted by application policy."""

    TRUSTED_APPLICATION = "trusted_application"
    UNTRUSTED_EXTERNAL = "untrusted_external"
    UNTRUSTED_MODEL = "untrusted_model"
    UNTRUSTED_TOOL = "untrusted_tool"
    UNTRUSTED_MCP = "untrusted_mcp"
    UNTRUSTED_MEMORY = "untrusted_memory"
    UNTRUSTED_RETRIEVED = "untrusted_retrieved"
    UNTRUSTED_AGENT = "untrusted_agent"


class ExecutionStatus(StrEnum):
    """Represent finite workflow lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


class EvidenceClass(StrEnum):
    """Identify the strength and environment of implementation evidence."""

    DETERMINISTIC = "deterministic"
    MOCKED = "mocked"
    ADAPTER = "adapter"
    LOCAL_INTEGRATION = "local_integration"
    LIVE_PROVIDER = "live_provider"
    DEPLOYMENT = "deployment"


class RuntimeBudget(BaseModel):
    """Bound resource consumption for one workflow.

    All limits are explicit positive values. Later runtime components may
    consume less than these limits but may not silently exceed them.

    Units are distinct. ``max_context_tokens`` and ``max_output_tokens`` are
    provider-token counts: the output value is the cap sent to the vendor SDK
    and validated against reported usage. ``max_output_bytes`` is a separate
    local ceiling on returned text, counted in UTF-8 bytes. When it is unset,
    the legacy conservative rule applies and the byte ceiling equals
    ``max_output_tokens``; the live-provider policy requires it to be explicit.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_plan_steps: int = Field(default=12, ge=1, le=100)
    max_retries_per_action: int = Field(default=2, ge=0, le=10)
    max_provider_attempts: int = Field(default=8, ge=0, le=100)
    max_tool_calls: int = Field(default=12, ge=0, le=100)
    max_context_tokens: int = Field(default=12_000, ge=1)
    max_output_tokens: int = Field(default=2_000, ge=1)
    max_output_bytes: int | None = Field(default=None, ge=1, le=16_384)
    action_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    workflow_deadline_seconds: float = Field(default=180.0, gt=0, le=3600)
    latency_slo_p95_seconds: float = Field(default=5.0, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_latency_bound(self) -> "RuntimeBudget":
        """Require the performance SLO to fit inside the hard deadline.

        Returns:
            The validated immutable budget.

        Raises:
            ValueError: If the latency SLO exceeds the workflow deadline.
        """
        if self.latency_slo_p95_seconds > self.workflow_deadline_seconds:
            raise ValueError("latency SLO cannot exceed workflow deadline")
        return self

    @property
    def output_byte_limit(self) -> int:
        """Return the local UTF-8 byte ceiling for returned provider text.

        Returns:
            The explicit ``max_output_bytes`` when set; otherwise the legacy
            conservative ceiling equal to ``max_output_tokens``.
        """
        return self.max_output_tokens if self.max_output_bytes is None else self.max_output_bytes


class WorkflowIdentity(BaseModel):
    """Provide stable identity for execution, persistence, and audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: UUID = Field(default_factory=uuid4)
    thread_id: UUID = Field(default_factory=uuid4)


class TrustedValue(BaseModel):
    """Carry data together with explicit provenance and trust classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str = Field(min_length=1, max_length=20_000)
    source: Identifier
    trust: TrustLevel

    @property
    def grants_authority(self) -> bool:
        """Return whether this value may itself grant application authority.

        Returns:
            False. Authority is always granted by deterministic application
            policy rather than contextual or generated content.
        """
        return False


class WorkflowState(BaseModel):
    """Represent the minimal typed state shared across harness lifecycle steps."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    identity: WorkflowIdentity = Field(default_factory=WorkflowIdentity)
    status: ExecutionStatus = ExecutionStatus.PENDING
    budget: RuntimeBudget = Field(default_factory=RuntimeBudget)
    current_step: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    provider_attempt_count: int = Field(default=0, ge=0)
    cancelled: bool = False

    @model_validator(mode="after")
    def validate_counters(self) -> "WorkflowState":
        """Reject state that already exceeds immutable workflow budgets.

        Returns:
            The validated workflow state.

        Raises:
            ValueError: If a bounded execution counter exceeds its budget.
        """
        if self.current_step > self.budget.max_plan_steps:
            raise ValueError("current step exceeds plan-step budget")
        if self.retry_count > self.budget.max_retries_per_action:
            raise ValueError("retry count exceeds per-action budget")
        if self.tool_call_count > self.budget.max_tool_calls:
            raise ValueError("tool-call count exceeds workflow budget")
        if self.provider_attempt_count > self.budget.max_provider_attempts:
            raise ValueError("provider-attempt count exceeds workflow budget")
        return self
