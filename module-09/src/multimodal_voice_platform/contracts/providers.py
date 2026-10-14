"""Provider port contracts for STT, TTS, vision, documents, and reasoning (ADR-009-003).

Ports are ``typing.Protocol`` definitions. Deterministic and live adapters implement them in later
stories. Every provider result is untrusted model output (ADR-009-007).
"""

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Annotated, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from multimodal_voice_platform.contracts.limits import (
    MAX_AUDIO_DURATION_MS,
    MAX_DELTA_CHARS,
    MAX_HISTORY_TURNS,
    MAX_OUTPUT_TOKENS,
    MAX_REASONING_PARTS,
    MAX_TEXT_CHARS,
    MAX_TRANSCRIPT_CHARS,
)
from multimodal_voice_platform.contracts.modality import (
    MEDIA_TYPES,
    UNTRUSTED_LEVELS,
    Identifier,
    Modality,
    ModalityInput,
    TrustLevel,
)
from multimodal_voice_platform.contracts.session import ConversationTurn, ExecutionMode

BoundedText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_TEXT_CHARS)]
LanguageTag = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")]


class ProviderPort(StrEnum):
    """The five provider capabilities behind explicit ports."""

    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    VISION = "vision"
    DOCUMENT_UNDERSTANDING = "document_understanding"
    REASONING = "reasoning"


class ProviderDescriptor(BaseModel):
    """Identifies which adapter produced a result and in which execution mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: Identifier
    port: ProviderPort
    mode: ExecutionMode


class ProviderResult(BaseModel):
    """Base for every provider result. Always untrusted model output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderDescriptor
    trust: TrustLevel = TrustLevel.UNTRUSTED_MODEL_OUTPUT

    @model_validator(mode="after")
    def validate_untrusted(self) -> Self:
        """Prevent provider output from claiming trusted status.

        Returns:
            The validated result.

        Raises:
            ValueError: If the result is not classified as untrusted model output.
        """
        if self.trust is not TrustLevel.UNTRUSTED_MODEL_OUTPUT:
            raise ValueError("provider results must be classified untrusted_model_output")
        return self


def _require_modality(item: ModalityInput, modality: Modality) -> None:
    if item.modality is not modality:
        raise ValueError(f"expected {modality} input, received {item.modality}")


class TranscriptionRequest(BaseModel):
    """Speech-to-text request for one validated audio input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audio: ModalityInput
    language: LanguageTag | None = None

    @model_validator(mode="after")
    def validate_audio(self) -> Self:
        """Require an audio input.

        Returns:
            The validated request.

        Raises:
            ValueError: If the input is not audio.
        """
        _require_modality(self.audio, Modality.AUDIO)
        return self


class TranscriptSegment(ProviderResult):
    """Partial or final transcript text."""

    text: str = Field(max_length=MAX_TRANSCRIPT_CHARS)
    is_final: bool
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Require an ordered time span.

        Returns:
            The validated segment.

        Raises:
            ValueError: If the segment ends before it starts.
        """
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must not precede start_ms")
        return self


class SpeechSynthesisRequest(BaseModel):
    """Text-to-speech request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: Identifier
    text: BoundedText
    voice: Identifier | None = None


class SynthesizedAudio(ProviderResult):
    """Synthesized speech held by opaque reference."""

    audio_ref: Identifier
    media_type: str
    duration_ms: int = Field(gt=0, le=MAX_AUDIO_DURATION_MS)

    @model_validator(mode="after")
    def validate_media_type(self) -> Self:
        """Require an allowlisted audio media type.

        Returns:
            The validated audio.

        Raises:
            ValueError: If the media type is not an allowed audio type.
        """
        if self.media_type not in MEDIA_TYPES[Modality.AUDIO]:
            raise ValueError("synthesized audio media type is not allowed")
        return self


class VisionRequest(BaseModel):
    """Vision request for one validated image input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: ModalityInput
    question: BoundedText | None = None

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        """Require an image input.

        Returns:
            The validated request.

        Raises:
            ValueError: If the input is not an image.
        """
        _require_modality(self.image, Modality.IMAGE)
        return self


class VisionResult(ProviderResult):
    """Structured image understanding."""

    description: BoundedText
    observations: tuple[BoundedText, ...] = Field(default=(), max_length=20)


class DocumentRequest(BaseModel):
    """Document understanding request for one validated document input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document: ModalityInput

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        """Require a document input.

        Returns:
            The validated request.

        Raises:
            ValueError: If the input is not a document.
        """
        _require_modality(self.document, Modality.DOCUMENT)
        return self


class DocumentSection(BaseModel):
    """One extracted document section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    heading: str | None = Field(default=None, max_length=300)
    text: BoundedText


class DocumentResult(ProviderResult):
    """Structured document understanding."""

    title: str | None = Field(default=None, max_length=300)
    sections: tuple[DocumentSection, ...] = Field(min_length=1, max_length=200)


class ReasoningPart(BaseModel):
    """Processed modality content entering the reasoning context. Always untrusted data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    modality: Modality
    source_input_id: Identifier
    content: BoundedText
    trust: TrustLevel

    @model_validator(mode="after")
    def validate_untrusted(self) -> Self:
        """Keep content parts out of the trusted zone.

        Returns:
            The validated part.

        Raises:
            ValueError: If the part claims application trust.
        """
        if self.trust not in UNTRUSTED_LEVELS:
            raise ValueError("reasoning parts must be untrusted")
        return self


class ReasoningRequest(BaseModel):
    """Cross-modal reasoning request.

    ``task`` is authored by application code only and is never derived from content or model
    output. ``parts`` and ``history`` are untrusted data, never instructions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: Identifier
    task: BoundedText
    parts: tuple[ReasoningPart, ...] = Field(min_length=1, max_length=MAX_REASONING_PARTS)
    history: tuple[ConversationTurn, ...] = Field(default=(), max_length=MAX_HISTORY_TURNS)
    max_output_tokens: int = Field(gt=0, le=MAX_OUTPUT_TOKENS)


class ReasoningChunk(ProviderResult):
    """One streamed piece of reasoning output."""

    text: str = Field(max_length=MAX_DELTA_CHARS)
    is_final: bool


class SpeechToTextPort(Protocol):
    """Speech-to-text capability."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter."""
        ...

    def transcribe(self, request: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
        """Stream partial then final transcript segments.

        Args:
            request: Validated transcription request.

        Returns:
            Async iterator of transcript segments, ending with a final segment.
        """
        ...


class TextToSpeechPort(Protocol):
    """Text-to-speech capability."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter."""
        ...

    async def synthesize(self, request: SpeechSynthesisRequest) -> SynthesizedAudio:
        """Synthesize speech.

        Args:
            request: Validated synthesis request.

        Returns:
            Synthesized audio held by reference.
        """
        ...


class VisionPort(Protocol):
    """Vision understanding capability."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter."""
        ...

    async def analyze(self, request: VisionRequest) -> VisionResult:
        """Analyze an image.

        Args:
            request: Validated vision request.

        Returns:
            Structured image understanding.
        """
        ...


class DocumentUnderstandingPort(Protocol):
    """Document understanding capability."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter."""
        ...

    async def understand(self, request: DocumentRequest) -> DocumentResult:
        """Extract structured understanding from a document.

        Args:
            request: Validated document request.

        Returns:
            Structured document understanding.
        """
        ...


class ReasoningPort(Protocol):
    """Cross-modal reasoning capability."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter."""
        ...

    def stream_reason(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Stream reasoning output.

        Args:
            request: Validated reasoning request.

        Returns:
            Async iterator of reasoning chunks, ending with a final chunk.
        """
        ...
