"""Evidence classification contracts (ADR-009-009)."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from multimodal_voice_platform.contracts.modality import Identifier
from multimodal_voice_platform.contracts.session import ExecutionMode

RequirementId = Annotated[str, StringConstraints(pattern=r"^(SRC|ENG)-\d{3}$")]
StoryId = Annotated[str, StringConstraints(pattern=r"^9\.(10|[1-9])$")]


class EvidenceClass(StrEnum):
    """Evidence strength classes. Weaker evidence must never claim a stronger class."""

    DESIGN_DOCUMENTATION = "design_documentation"
    AUTOMATED_TEST = "automated_test"
    DETERMINISTIC_DEMO = "deterministic_demo"
    LIVE_INTEGRATION = "live_integration"
    DEPLOYMENT_RELEASE = "deployment_release"


_RUNTIME_CLASSES = frozenset(
    {
        EvidenceClass.AUTOMATED_TEST,
        EvidenceClass.DETERMINISTIC_DEMO,
        EvidenceClass.LIVE_INTEGRATION,
        EvidenceClass.DEPLOYMENT_RELEASE,
    }
)


class EvidenceRecord(BaseModel):
    """One accurately classified piece of evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: Identifier
    evidence_class: EvidenceClass
    story: StoryId
    requirement_ids: tuple[RequirementId, ...] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=1000)
    runtime_executed: bool = False
    live_provider_executed: bool = False
    execution_mode: ExecutionMode | None = None

    @model_validator(mode="after")
    def validate_strength(self) -> Self:
        """Prevent evidence from claiming more than actually happened.

        Returns:
            The validated record.

        Raises:
            ValueError: If execution flags or mode contradict the evidence class.
        """
        is_runtime = self.evidence_class in _RUNTIME_CLASSES
        if is_runtime != self.runtime_executed:
            raise ValueError(f"{self.evidence_class} runtime_executed must be {is_runtime}")
        is_live = self.evidence_class is EvidenceClass.LIVE_INTEGRATION
        if is_live != self.live_provider_executed:
            raise ValueError("only live_integration evidence may, and must, record live execution")
        if self.evidence_class is EvidenceClass.DESIGN_DOCUMENTATION:
            if self.execution_mode is not None:
                raise ValueError("design_documentation evidence has no execution mode")
        elif is_live and self.execution_mode is not ExecutionMode.LIVE:
            raise ValueError("live_integration evidence requires live execution mode")
        elif self.evidence_class is EvidenceClass.DETERMINISTIC_DEMO and (
            self.execution_mode is not ExecutionMode.DETERMINISTIC
        ):
            raise ValueError("deterministic_demo evidence requires deterministic execution mode")
        return self
