"""Reviewer-displayable, evidence-classified record of one cross-modal workflow run (Story 9.5).

A ``CrossModalRecord`` shows what was supplied and how each input was processed (with the embedded
Story 9.3 or 9.4 record), the normalized observations, the bounded context, which reasoning adapter
ran and what kind of reasoning it performs, every finding with its citations, the derived
conclusion, stage timings, and the safe failure, with an ``EvidenceRecord``. Reasoning kinds are
explicit so that deterministic rule-based inference is never mistaken for model inference.
``model_inference_performed`` and ``live_provider_called`` are ``False`` for deterministic runs.
Story 9.8 live runs may use a live reasoning model (``model_inference``) or a contract test double
over a test transport; they report every provider call made by the reasoning adapter in
``live_calls`` (embedded Story 9.3 and 9.4 records report their own), and their evidence follows
the live evidence ladder in ``contracts.live``.
"""

from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.contracts.errors import SafeError
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.live import (
    LIVE_STORY,
    MAX_LIVE_CALLS,
    LiveCall,
    check_live_evidence,
    real_call_made,
)
from multimodal_voice_platform.contracts.modality import Identifier, Modality, ModalityInput
from multimodal_voice_platform.contracts.providers import ProviderDescriptor, ProviderPort
from multimodal_voice_platform.contracts.reasoning import CrossModalFinding
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.crossmodal.context import ContextStats
from multimodal_voice_platform.crossmodal.findings import CrossModalConclusion
from multimodal_voice_platform.crossmodal.limits import MAX_WORKFLOW_ITEMS
from multimodal_voice_platform.crossmodal.observations import ModalityObservation
from multimodal_voice_platform.speech.records import SpeechRecord
from multimodal_voice_platform.understanding.records import UnderstandingRecord

CROSS_MODAL_EVIDENCE_CLASSES: Final = frozenset(
    {EvidenceClass.AUTOMATED_TEST, EvidenceClass.DETERMINISTIC_DEMO}
)
"""The only evidence classes Story 9.5 workflow runs may produce."""


class ReasoningKind(StrEnum):
    """What kind of reasoning an adapter performs. Kept distinct for honest evidence."""

    DETERMINISTIC_RULE_INFERENCE = "deterministic_rule_inference"
    PROVIDER_CONTRACT_TEST_DOUBLE = "provider_contract_test_double"
    MODEL_INFERENCE = "model_inference"


RESERVED_REASONING_KINDS: Final = frozenset({ReasoningKind.MODEL_INFERENCE})
"""Model-based reasoning. Deterministic bindings refuse it; only a 9.8 live binding runs it."""
LIVE_REASONING_KINDS: Final = frozenset(
    {ReasoningKind.MODEL_INFERENCE, ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE}
)
"""What a live reasoning adapter may be recorded as: a real model, or a contract test double."""


class CrossModalStage(StrEnum):
    """Workflow stages, in the order they run."""

    VALIDATION = "validation"
    MODALITY_PROCESSING = "modality_processing"
    CONTEXT_CONSTRUCTION = "context_construction"
    REASONING = "reasoning"
    OUTPUT_VALIDATION = "output_validation"
    END_TO_END = "end_to_end"


class CrossModalStatus(StrEnum):
    """Outcome of one workflow run."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    REJECTED = "rejected"
    FAILED = "failed"


class OutcomeStatus(StrEnum):
    """Outcome of processing one supplied input."""

    PROCESSED = "processed"
    REJECTED = "rejected"
    FAILED = "failed"


class CrossModalTiming(BaseModel):
    """Measured wall-clock duration of one workflow stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: CrossModalStage
    duration_ms: float = Field(ge=0)


class ModalityOutcome(BaseModel):
    """How one supplied input was processed, with the record of the path that processed it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=0, lt=MAX_WORKFLOW_ITEMS)
    modality: Modality
    status: OutcomeStatus
    observation_id: str | None = None
    text_input: ModalityInput | None = None
    understanding: UnderstandingRecord | None = None
    speech: SpeechRecord | None = None
    error: SafeError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Keep the outcome consistent with its modality and status.

        Returns:
            The validated outcome.

        Raises:
            ValueError: If the attached record does not fit the modality, or the status, error,
                and observation contradict each other.
        """
        attached = {
            Modality.TEXT: self.text_input,
            Modality.IMAGE: self.understanding,
            Modality.DOCUMENT: self.understanding,
            Modality.AUDIO: self.speech,
        }
        others = [r for r in (self.text_input, self.understanding, self.speech) if r is not None]
        if len(others) > 1 or (others and others[0] is not attached[self.modality]):
            raise ValueError(f"{self.modality} outcomes carry only their own path's record")
        processed = self.status is OutcomeStatus.PROCESSED
        if processed != (self.observation_id is not None) or processed == (self.error is not None):
            raise ValueError("processed outcomes have an observation; others have an error")
        if processed and attached[self.modality] is None:
            raise ValueError("processed outcomes carry their processing record")
        return self


class CrossModalRecord(BaseModel):
    """Typed record of one cross-modal workflow run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: Identifier
    session_id: Identifier
    status: CrossModalStatus
    outcomes: tuple[ModalityOutcome, ...] = Field(default=(), max_length=MAX_WORKFLOW_ITEMS)
    observations: tuple[ModalityObservation, ...] = Field(
        default=(), max_length=MAX_WORKFLOW_ITEMS
    )
    context: ContextStats | None = None
    reasoning_provider: ProviderDescriptor | None = None
    reasoning_kind: ReasoningKind | None = None
    model_inference_performed: bool = False
    live_provider_called: bool = False
    live_calls: tuple[LiveCall, ...] = Field(default=(), max_length=MAX_LIVE_CALLS)
    findings: tuple[CrossModalFinding, ...] = ()
    conclusion: CrossModalConclusion | None = None
    timings: tuple[CrossModalTiming, ...] = Field(default=(), max_length=len(CrossModalStage))
    failed_stage: CrossModalStage | None = None
    error: SafeError | None = None
    evidence: EvidenceRecord

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        """Keep the record internally consistent and its evidence honest.

        Returns:
            The validated record.

        Raises:
            ValueError: If status, outcomes, observations, provider, reasoning kind, findings, or
                evidence contradict each other or claim more than deterministic, non-live,
                non-model reasoning.
        """
        self._validate_reasoning()
        ids = [obs.view.observation_id for obs in self.observations]
        if len(set(ids)) != len(ids):
            raise ValueError("observation IDs must be unique")
        linked = sorted(o.observation_id for o in self.outcomes if o.observation_id is not None)
        if self.outcomes and linked != sorted(ids):
            raise ValueError("every observation comes from exactly one processed outcome")
        if self.status in {CrossModalStatus.SUCCEEDED, CrossModalStatus.PARTIAL}:
            self._validate_success(set(ids))
        else:
            if self.error is None or self.failed_stage is None:
                raise ValueError("unsuccessful records carry an error and the failed stage")
            if self.findings or self.conclusion is not None:
                raise ValueError("unsuccessful records carry no findings or conclusion")
        self._validate_evidence()
        return self

    def all_live_calls(self) -> tuple[LiveCall, ...]:
        """Every provider call of the run: the reasoning adapter's and the embedded records'.

        Returns:
            The calls, reasoning calls first.
        """
        embedded = [
            call
            for outcome in self.outcomes
            for record in (outcome.understanding, outcome.speech)
            if record is not None
            for call in record.live_calls
        ]
        return (*self.live_calls, *embedded)

    def _validate_reasoning(self) -> None:
        if (self.reasoning_provider is None) != (self.reasoning_kind is None):
            raise ValueError("records name their reasoning provider and its reasoning kind")
        live = self.evidence.story == LIVE_STORY
        if self.live_calls and not live:
            raise ValueError("only live runs report provider calls")
        if self.live_provider_called != real_call_made(self.all_live_calls()):
            raise ValueError("live_provider_called must match the reported provider calls")
        if self.model_inference_performed != (
            self.reasoning_kind is ReasoningKind.MODEL_INFERENCE
        ):
            raise ValueError("model_inference_performed must match the reasoning kind")
        provider = self.reasoning_provider
        if provider is None:
            return
        if provider.port is not ProviderPort.REASONING:
            raise ValueError("records name a reasoning adapter")
        if provider.mode is ExecutionMode.LIVE:
            if not live or self.reasoning_kind not in LIVE_REASONING_KINDS:
                raise ValueError("live reasoning adapters run in live Story 9.8 runs only")
        elif live:
            raise ValueError("live Story 9.8 runs reason through a live reasoning adapter")
        elif self.reasoning_kind in RESERVED_REASONING_KINDS:
            raise ValueError("model-based reasoning needs a live reasoning adapter")
        model = self.reasoning_kind is ReasoningKind.MODEL_INFERENCE
        if any(call.real_endpoint != model for call in self.live_calls):
            raise ValueError("real reasoning calls are exactly the model-backed reasoning calls")

    def _validate_success(self, ids: set[str]) -> None:
        if self.error is not None or self.failed_stage is not None:
            raise ValueError("successful records carry no error")
        if self.reasoning_provider is None or self.conclusion is None or self.context is None:
            raise ValueError("successful records name their reasoner, context, and conclusion")
        if len({obs.view.modality for obs in self.observations}) < 2:
            raise ValueError("successful records relate at least two modalities")
        unprocessed = [o for o in self.outcomes if o.status is not OutcomeStatus.PROCESSED]
        if (self.status is CrossModalStatus.PARTIAL) != bool(unprocessed):
            raise ValueError("partial records, and only partial records, have unprocessed inputs")
        if any(oid not in ids for f in self.findings for oid in f.observation_ids):
            raise ValueError("findings may cite only the record's observations")

    def _validate_evidence(self) -> None:
        evidence = self.evidence
        if evidence.story == LIVE_STORY:
            check_live_evidence(evidence, self.all_live_calls())
            return
        if evidence.evidence_class not in CROSS_MODAL_EVIDENCE_CLASSES:
            raise ValueError("cross-modal records allow only deterministic evidence classes")
        if evidence.execution_mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("cross-modal records require deterministic execution mode")
        if evidence.live_provider_executed or evidence.story != "9.5":
            raise ValueError("cross-modal records are Story 9.5 evidence with no live execution")
        if self.reasoning_kind is ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE and (
            evidence.evidence_class is not EvidenceClass.AUTOMATED_TEST
        ):
            raise ValueError("test-double reasoning runs are automated_test evidence only")
