"""Typed safety-check contracts shared by the safety pipeline and providers.

None of these types carries authorization authority. They extend the Story 1
``SafetyDecision`` contract with per-check evidence.
"""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from .domain import Decision, EvidenceClass, Identifier, SafetyDecision


class SafetyStage(StrEnum):
    """Boundary at which content is assessed."""

    INPUT = "input"
    OUTPUT = "output"


class SafetyCheckResult(BaseModel):
    """Outcome of one safety check.

    Attributes:
        check: Stable check identifier.
        decision: Allow or deny for this check.
        reason: Stable reason identifier; never the inspected content.
        evidence_class: How this check's evidence was produced.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: Identifier
    decision: Decision
    reason: Identifier
    evidence_class: EvidenceClass


class SafetyAssessment(BaseModel):
    """Aggregated safety evidence for one piece of untrusted content.

    Attributes:
        stage: Boundary at which the content was assessed.
        decision: Story 1 safety decision derived from all checks.
        checks: Every check result that contributed to the decision.
        evidence_class: Weakest evidence class among the contributing checks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: SafetyStage
    decision: SafetyDecision
    checks: tuple[SafetyCheckResult, ...]
    evidence_class: EvidenceClass

    @property
    def allowed(self) -> bool:
        """Return whether every safety check allowed the content."""
        return self.decision.decision is Decision.ALLOW


@runtime_checkable
class SafetyProvider(Protocol):
    """Pluggable safety validator executed inside the safety boundary."""

    @property
    def name(self) -> str:
        """Return the provider's stable check identifier."""
        ...

    def check(self, text: str, stage: SafetyStage) -> SafetyCheckResult:
        """Validate untrusted text.

        Args:
            text: Untrusted text to validate.
            stage: Boundary at which the text is validated.

        Returns:
            The provider's safety check result.

        Raises:
            SafetyProviderError: If the provider cannot produce a trustworthy
                result.
        """
        ...
