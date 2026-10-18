"""Reviewer-displayable, evidence-classified records of image and document understanding.

An ``UnderstandingRecord`` shows what came in, which processing path ran, what kind of processing
it was, the typed structured result or the safe failure, stage timings, and an ``EvidenceRecord``.
It distinguishes processing kinds explicitly so that local extraction is never mistaken for model
inference, and fixture playback (Story 9.2) is never mistaken for either.

Story 9.8 adds live image understanding: the local analysis still runs and stays in ``vision`` and
``image_analysis``; a live vision model's interpretation is kept separately in ``model_vision``,
attributed to ``model_provider`` and labeled ``model_inference`` (real provider) or
``provider_contract_test_double`` (test transport). Every provider call is reported in
``live_calls`` and the evidence follows the live evidence ladder in ``contracts.live``.
"""

from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.adapters.local.document_parsing import DocumentAnalysis
from multimodal_voice_platform.adapters.local.image_analysis import ImageAnalysis
from multimodal_voice_platform.adapters.local.providers import LOCAL_DOCUMENT_ID, LOCAL_VISION_ID
from multimodal_voice_platform.contracts.errors import SafeError
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.limits import LatencyStage
from multimodal_voice_platform.contracts.live import (
    LIVE_STORY,
    MAX_LIVE_CALLS,
    LiveCall,
    check_live_evidence,
    real_call_made,
)
from multimodal_voice_platform.contracts.modality import Identifier, Modality, ModalityInput
from multimodal_voice_platform.contracts.providers import (
    DocumentResult,
    ProviderDescriptor,
    ProviderPort,
    VisionResult,
)
from multimodal_voice_platform.contracts.session import ExecutionMode

LOCAL_EVIDENCE_CLASSES: Final = frozenset(
    {EvidenceClass.AUTOMATED_TEST, EvidenceClass.DETERMINISTIC_DEMO}
)
"""The only evidence classes local, in-process processing may produce."""


class ProcessingKind(StrEnum):
    """What kind of processing produced a result. Kept distinct for honest evidence."""

    FIXTURE_PLAYBACK = "fixture_playback"
    LOCAL_EXTRACTION = "local_extraction"
    LOCAL_STRUCTURAL_ANALYSIS = "local_structural_analysis"
    MODEL_INFERENCE = "model_inference"
    PROVIDER_CONTRACT_TEST_DOUBLE = "provider_contract_test_double"


LIVE_VISION_KINDS: Final = frozenset(
    {ProcessingKind.MODEL_INFERENCE, ProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE}
)
"""What a Story 9.8 live vision adapter may declare: a real model, or a contract test double."""


LOCAL_PROCESSING: Final = (
    ProcessingKind.LOCAL_EXTRACTION,
    ProcessingKind.LOCAL_STRUCTURAL_ANALYSIS,
)
"""Processing performed by every successful Story 9.3 run."""


class ProcessingPath(StrEnum):
    """Which understanding path handled the input."""

    LOCAL_IMAGE_ANALYSIS = "local_image_analysis"
    LOCAL_DOCUMENT_EXTRACTION = "local_document_extraction"


PATH_FOR_MODALITY: Final = {
    Modality.IMAGE: (ProcessingPath.LOCAL_IMAGE_ANALYSIS, ProviderPort.VISION, LOCAL_VISION_ID),
    Modality.DOCUMENT: (
        ProcessingPath.LOCAL_DOCUMENT_EXTRACTION,
        ProviderPort.DOCUMENT_UNDERSTANDING,
        LOCAL_DOCUMENT_ID,
    ),
}


class UnderstandingStatus(StrEnum):
    """Outcome of one understanding run."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class StageTiming(BaseModel):
    """Measured wall-clock duration of one pipeline stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: LatencyStage
    duration_ms: float = Field(ge=0)


class UnderstandingRecord(BaseModel):
    """Typed record of one image or document understanding run.

    ``model_inference_performed`` and ``live_provider_called`` are ``False`` for local runs; a
    Story 9.8 live run sets them from what actually completed and what reached the real provider.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: Identifier
    session_id: Identifier
    status: UnderstandingStatus
    modality: Modality
    input: ModalityInput | None = None
    path: ProcessingPath | None = None
    provider: ProviderDescriptor | None = None
    processing: tuple[ProcessingKind, ...] = ()
    model_inference_performed: bool = False
    live_provider_called: bool = False
    live_calls: tuple[LiveCall, ...] = Field(default=(), max_length=MAX_LIVE_CALLS)
    model_provider: ProviderDescriptor | None = None
    model_vision: VisionResult | None = None
    vision: VisionResult | None = None
    image_analysis: ImageAnalysis | None = None
    document: DocumentResult | None = None
    document_analysis: DocumentAnalysis | None = None
    timings: tuple[StageTiming, ...] = Field(default=(), max_length=8)
    error: SafeError | None = None
    evidence: EvidenceRecord

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        """Keep the record internally consistent and its evidence honest.

        Returns:
            The validated record.

        Raises:
            ValueError: If status, outputs, provider, processing kinds, or evidence contradict
                each other or claim more than local, deterministic, non-live processing.
        """
        if self.input is not None and self.input.modality is not self.modality:
            raise ValueError("record modality must match its input")
        live = self.evidence.story == LIVE_STORY
        if self.model_inference_performed != (ProcessingKind.MODEL_INFERENCE in self.processing):
            raise ValueError("model_inference_performed must match the completed processing")
        if self.live_provider_called != real_call_made(self.live_calls):
            raise ValueError("live_provider_called must match the reported provider calls")
        if (self.live_calls or self.model_provider is not None) and not live:
            raise ValueError("only live runs involve a live provider")
        model_kind = ProcessingKind.MODEL_INFERENCE in self.processing
        if any(call.real_endpoint != model_kind for call in self.live_calls if self.model_vision):
            raise ValueError("real provider calls are exactly the model-backed vision calls")
        if self.status is UnderstandingStatus.SUCCEEDED:
            self._validate_success()
        else:
            outputs = (
                self.vision,
                self.image_analysis,
                self.document,
                self.document_analysis,
                self.model_vision,
            )
            if self.error is None or any(output is not None for output in outputs):
                raise ValueError("unsuccessful records carry an error and no outputs")
            if self.processing or self.provider is not None or self.path is not None:
                raise ValueError("unsuccessful records claim no processing")
        self._validate_evidence()
        return self

    def _validate_success(self) -> None:
        expected = PATH_FOR_MODALITY.get(self.modality)
        if expected is None or self.input is None or self.error is not None:
            raise ValueError("successful records require a supported input and no error")
        path, port, provider_id = expected
        provider = self.provider
        if self.path is not path or provider is None:
            raise ValueError(f"{self.modality} records require the {path} path")
        if provider.port is not port or provider.provider_id != provider_id:
            raise ValueError(f"{self.modality} records require the local {port} adapter")
        if provider.mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("local processing runs only in deterministic mode")
        self._validate_model_vision()
        is_image = self.modality is Modality.IMAGE
        image_outputs = (self.vision, self.image_analysis)
        document_outputs = (self.document, self.document_analysis)
        present, absent = (
            (image_outputs, document_outputs) if is_image else (document_outputs, image_outputs)
        )
        if any(item is None for item in present) or any(item is not None for item in absent):
            raise ValueError(f"{self.modality} record carries the wrong outputs")
        result = self.vision if is_image else self.document
        if result is None or result.provider != provider:
            raise ValueError("the result must be attributed to the record's provider")

    def _validate_model_vision(self) -> None:
        model, provider = self.model_vision, self.model_provider
        if model is None:
            if provider is not None or self.processing != LOCAL_PROCESSING:
                raise ValueError(
                    "local records claim only local extraction and structural analysis"
                )
            return
        if self.modality is not Modality.IMAGE or provider is None:
            raise ValueError("model interpretation applies to images and names its provider")
        if provider.port is not ProviderPort.VISION or provider.mode is not ExecutionMode.LIVE:
            raise ValueError("model interpretation comes from a live vision provider")
        if model.provider != provider:
            raise ValueError("the model interpretation must be attributed to its provider")
        kinds = self.processing[len(LOCAL_PROCESSING) :]
        if (
            self.processing[: len(LOCAL_PROCESSING)] != LOCAL_PROCESSING
            or len(kinds) != 1
            or kinds[0] not in LIVE_VISION_KINDS
        ):
            raise ValueError("live image records claim local processing then one model kind")

    def _validate_evidence(self) -> None:
        evidence = self.evidence
        if evidence.story == LIVE_STORY:
            check_live_evidence(evidence, self.live_calls)
            return
        if evidence.evidence_class not in LOCAL_EVIDENCE_CLASSES:
            raise ValueError("local records allow only deterministic evidence classes")
        if evidence.execution_mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("local records require deterministic execution mode")
        if evidence.live_provider_executed or evidence.story != "9.3":
            raise ValueError("local records are Story 9.3 evidence with no live execution")
