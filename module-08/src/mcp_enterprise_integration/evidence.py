"""Structured evidence contracts for defensible Module 8 claims."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from mcp_enterprise_integration.domain import Identifier


class EvidenceClass(StrEnum):
    """Approved strength/classification vocabulary for execution evidence."""

    DETERMINISTIC = "deterministic"
    MOCKED = "mocked"
    ADAPTER = "adapter"
    LOCAL_INTEGRATION = "local-integration"
    LIVE_PROVIDER = "live-provider"
    DEPLOYMENT = "deployment"


class ExecutionEvidence(BaseModel):
    """Record accurately classified, sanitized execution evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: Identifier
    evidence_class: EvidenceClass
    capability_id: Identifier
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ]
    live_provider_executed: bool = False
    deployment_executed: bool = False

    @model_validator(mode="after")
    def validate_evidence_strength(self) -> Self:
        """Prevent weaker execution from claiming stronger evidence.

        Returns:
            The validated evidence instance.

        Raises:
            ValueError: If execution flags contradict the evidence class.
        """
        if self.evidence_class == EvidenceClass.LIVE_PROVIDER and not self.live_provider_executed:
            raise ValueError("live-provider evidence requires actual live-provider execution")
        if self.evidence_class == EvidenceClass.DEPLOYMENT and not self.deployment_executed:
            raise ValueError("deployment evidence requires actual deployment execution")
        if self.live_provider_executed and self.evidence_class != EvidenceClass.LIVE_PROVIDER:
            raise ValueError("live-provider execution must be classified as live-provider evidence")
        if self.deployment_executed and self.evidence_class != EvidenceClass.DEPLOYMENT:
            raise ValueError("deployment execution must be classified as deployment evidence")
        return self
