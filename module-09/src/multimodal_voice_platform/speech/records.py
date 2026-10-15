"""Reviewer-displayable, evidence-classified records of audio and speech pipeline runs.

A ``SpeechRecord`` shows what came in, which stages ran and what kind of processing each was, the
audio properties, the transcript or generated audio, the provider that handled the speech stage,
stage timings, and the safe failure, with an ``EvidenceRecord``. Processing kinds are explicit so
that local audio decoding is never mistaken for speech recognition, fixture playback is never
mistaken for transcription, and deterministic tone generation is never mistaken for speech
synthesis. ``speech_recognition_performed``, ``speech_synthesis_performed``,
``model_inference_performed``, and ``live_provider_called`` are always ``False`` in Story 9.4.
"""

import hashlib
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.audio.analysis import AudioAnalysis
from multimodal_voice_platform.contracts.errors import SafeError
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.modality import (
    Identifier,
    Modality,
    ModalityInput,
    TrustLevel,
)
from multimodal_voice_platform.contracts.providers import (
    LanguageTag,
    ProviderDescriptor,
    ProviderPort,
    SynthesizedAudio,
    TranscriptSegment,
)
from multimodal_voice_platform.contracts.session import ExecutionMode

MAX_TRANSCRIPT_SEGMENTS: Final = 200
SPEECH_EVIDENCE_CLASSES: Final = frozenset(
    {EvidenceClass.AUTOMATED_TEST, EvidenceClass.DETERMINISTIC_DEMO}
)
"""The only evidence classes Story 9.4 speech pipeline runs may produce."""


class SpeechOperation(StrEnum):
    """Which speech pipeline operation ran."""

    AUDIO_ANALYSIS = "audio_analysis"
    TRANSCRIPTION = "transcription"
    SYNTHESIS = "synthesis"


class SpeechStage(StrEnum):
    """Pipeline stages, in the order they run for each operation."""

    INGESTION = "ingestion"
    AUDIO_PROCESSING = "audio_processing"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    OUTPUT_VALIDATION = "output_validation"


class SpeechProcessingKind(StrEnum):
    """What kind of processing a stage performed. Kept distinct for honest evidence."""

    LOCAL_AUDIO_DECODING = "local_audio_decoding"
    LOCAL_SIGNAL_ANALYSIS = "local_signal_analysis"
    FIXTURE_PLAYBACK = "fixture_playback"
    DETERMINISTIC_TONE_SYNTHESIS = "deterministic_tone_synthesis"
    PROVIDER_CONTRACT_TEST_DOUBLE = "provider_contract_test_double"
    SPEECH_RECOGNITION = "speech_recognition"
    SPEECH_SYNTHESIS = "speech_synthesis"


LOCAL_AUDIO_PROCESSING: Final = (
    SpeechProcessingKind.LOCAL_AUDIO_DECODING,
    SpeechProcessingKind.LOCAL_SIGNAL_ANALYSIS,
)
"""Processing performed whenever audio is decoded and measured."""

RESERVED_KINDS: Final = frozenset(
    {SpeechProcessingKind.SPEECH_RECOGNITION, SpeechProcessingKind.SPEECH_SYNTHESIS}
)
"""Genuine model-based speech kinds. Not implemented; reserved for the live-provider story."""

PROVIDER_KINDS: Final = {
    ProviderPort.SPEECH_TO_TEXT: frozenset(
        {
            SpeechProcessingKind.FIXTURE_PLAYBACK,
            SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE,
        }
    ),
    ProviderPort.TEXT_TO_SPEECH: frozenset(
        {
            SpeechProcessingKind.DETERMINISTIC_TONE_SYNTHESIS,
            SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE,
        }
    ),
}
"""Processing kinds a Story 9.4 speech provider may declare, per port."""

OPERATION_PORT: Final = {
    SpeechOperation.AUDIO_ANALYSIS: None,
    SpeechOperation.TRANSCRIPTION: ProviderPort.SPEECH_TO_TEXT,
    SpeechOperation.SYNTHESIS: ProviderPort.TEXT_TO_SPEECH,
}
OPERATION_STAGES: Final = {
    SpeechOperation.AUDIO_ANALYSIS: (SpeechStage.INGESTION, SpeechStage.AUDIO_PROCESSING),
    SpeechOperation.TRANSCRIPTION: (
        SpeechStage.INGESTION,
        SpeechStage.AUDIO_PROCESSING,
        SpeechStage.SPEECH_TO_TEXT,
    ),
    SpeechOperation.SYNTHESIS: (
        SpeechStage.INGESTION,
        SpeechStage.TEXT_TO_SPEECH,
        SpeechStage.OUTPUT_VALIDATION,
    ),
}
OPERATION_INPUT: Final = {
    SpeechOperation.AUDIO_ANALYSIS: Modality.AUDIO,
    SpeechOperation.TRANSCRIPTION: Modality.AUDIO,
    SpeechOperation.SYNTHESIS: Modality.TEXT,
}


def expected_processing(
    operation: SpeechOperation, provider_kind: SpeechProcessingKind | None
) -> tuple[SpeechProcessingKind, ...]:
    """Return the processing kinds a successful run of an operation performs.

    Args:
        operation: The pipeline operation.
        provider_kind: Processing kind declared by the speech provider, if the operation has one.

    Returns:
        Processing kinds in stage order.
    """
    if operation is SpeechOperation.AUDIO_ANALYSIS or provider_kind is None:
        return LOCAL_AUDIO_PROCESSING
    if operation is SpeechOperation.TRANSCRIPTION:
        return (*LOCAL_AUDIO_PROCESSING, provider_kind)
    return (provider_kind, *LOCAL_AUDIO_PROCESSING)


class SpeechStatus(StrEnum):
    """Outcome of one speech pipeline run."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class SpeechTiming(BaseModel):
    """Measured wall-clock duration of one pipeline stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: SpeechStage
    duration_ms: float = Field(ge=0)


class TranscriptResult(BaseModel):
    """Validated transcript stream from a speech-to-text provider. Always untrusted data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    segments: tuple[TranscriptSegment, ...] = Field(
        min_length=1, max_length=MAX_TRANSCRIPT_SEGMENTS
    )
    text: str
    language: LanguageTag | None = None
    trust: Literal[TrustLevel.UNTRUSTED_MODEL_OUTPUT] = TrustLevel.UNTRUSTED_MODEL_OUTPUT

    @model_validator(mode="after")
    def validate_transcript(self) -> Self:
        """Require one final segment, last, whose text is the transcript text.

        Returns:
            The validated transcript.

        Raises:
            ValueError: If the final segment is missing, repeated, misplaced, or mismatched.
        """
        finals = [segment.is_final for segment in self.segments]
        if finals.count(True) != 1 or not finals[-1]:
            raise ValueError("a transcript ends with exactly one final segment")
        if self.text != self.segments[-1].text:
            raise ValueError("transcript text must be the final segment's text")
        return self


class SynthesisResult(BaseModel):
    """Generated audio from a text-to-speech provider, with its validated bytes.

    ``wav_bytes`` is excluded from serialization and repr. In-process callers (such as the later
    reviewer UI) can play it; serialized records carry its digest and size instead.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    audio: SynthesizedAudio
    voice: Identifier | None = None
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_size_bytes: int = Field(gt=0)
    wav_bytes: bytes = Field(exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_bytes(self) -> Self:
        """Bind the digest and size to the carried bytes.

        Returns:
            The validated result.

        Raises:
            ValueError: If the digest or size does not match the bytes.
        """
        if len(self.wav_bytes) != self.audio_size_bytes:
            raise ValueError("audio_size_bytes must match the generated audio")
        if hashlib.sha256(self.wav_bytes).hexdigest() != self.audio_sha256:
            raise ValueError("audio_sha256 must match the generated audio")
        return self


class SpeechRecord(BaseModel):
    """Typed record of one audio analysis, transcription, or synthesis run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: Identifier
    session_id: Identifier
    operation: SpeechOperation
    status: SpeechStatus
    input: ModalityInput | None = None
    provider: ProviderDescriptor | None = None
    provider_processing: SpeechProcessingKind | None = None
    processing: tuple[SpeechProcessingKind, ...] = ()
    speech_recognition_performed: Literal[False] = False
    speech_synthesis_performed: Literal[False] = False
    model_inference_performed: Literal[False] = False
    live_provider_called: Literal[False] = False
    audio: AudioAnalysis | None = None
    transcript: TranscriptResult | None = None
    synthesis: SynthesisResult | None = None
    timings: tuple[SpeechTiming, ...] = Field(default=(), max_length=8)
    failed_stage: SpeechStage | None = None
    error: SafeError | None = None
    evidence: EvidenceRecord

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        """Keep the record internally consistent and its evidence honest.

        Returns:
            The validated record.

        Raises:
            ValueError: If status, stages, outputs, provider, processing kinds, or evidence
                contradict each other or claim more than deterministic, non-live processing.
        """
        self._validate_provider()
        if self.input is not None and self.input.modality is not OPERATION_INPUT[self.operation]:
            raise ValueError(
                f"{self.operation} records take {OPERATION_INPUT[self.operation]} input"
            )
        if RESERVED_KINDS.intersection(self.processing):
            raise ValueError("speech recognition and synthesis kinds are not implemented")
        expected = expected_processing(self.operation, self.provider_processing)
        if self.status is SpeechStatus.SUCCEEDED:
            self._validate_success(expected)
        else:
            self._validate_unsuccessful(expected)
        if (self.audio is not None) != (
            SpeechProcessingKind.LOCAL_SIGNAL_ANALYSIS in self.processing
        ):
            raise ValueError("audio properties are present exactly when audio was analyzed")
        self._validate_evidence()
        return self

    def _validate_provider(self) -> None:
        port = OPERATION_PORT[self.operation]
        provider, kind = self.provider, self.provider_processing
        if port is None:
            if provider is not None or kind is not None:
                raise ValueError("audio analysis records involve no speech provider")
            return
        if provider is None or kind is None:
            raise ValueError(f"{self.operation} records name their provider and its processing")
        if provider.port is not port:
            raise ValueError(f"{self.operation} records require a {port} provider")
        if kind not in PROVIDER_KINDS[port]:
            raise ValueError(f"{kind} is not a valid {port} processing kind in Story 9.4")
        if provider.mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("Story 9.4 speech providers run only in deterministic mode")

    def _validate_success(self, expected: tuple[SpeechProcessingKind, ...]) -> None:
        if self.error is not None or self.failed_stage is not None or self.input is None:
            raise ValueError("successful records require an input and no error")
        if self.processing != expected:
            raise ValueError(f"{self.operation} records claim exactly {expected}")
        wants_transcript = self.operation is SpeechOperation.TRANSCRIPTION
        wants_synthesis = self.operation is SpeechOperation.SYNTHESIS
        if (self.transcript is not None) != wants_transcript:
            raise ValueError("only successful transcription records carry a transcript")
        if (self.synthesis is not None) != wants_synthesis:
            raise ValueError("only successful synthesis records carry generated audio")
        results = []
        if self.transcript is not None:
            results.extend(self.transcript.segments)
        if self.synthesis is not None:
            results.append(self.synthesis.audio)
        if any(result.provider != self.provider for result in results):
            raise ValueError("every result must be attributed to the record's provider")

    def _validate_unsuccessful(self, expected: tuple[SpeechProcessingKind, ...]) -> None:
        if self.error is None or self.failed_stage is None:
            raise ValueError("unsuccessful records carry an error and the failed stage")
        if self.failed_stage not in OPERATION_STAGES[self.operation]:
            raise ValueError(f"{self.failed_stage} is not a stage of {self.operation}")
        if self.transcript is not None or self.synthesis is not None:
            raise ValueError("unsuccessful records carry no transcript or generated audio")
        if self.processing != expected[: len(self.processing)] or self.processing == expected:
            raise ValueError("unsuccessful records claim only the stages that completed")
        if self.input is None and self.failed_stage is not SpeechStage.INGESTION:
            raise ValueError("only ingestion failures may lack a validated input")

    def _validate_evidence(self) -> None:
        evidence = self.evidence
        if evidence.evidence_class not in SPEECH_EVIDENCE_CLASSES:
            raise ValueError("speech records allow only deterministic evidence classes")
        if evidence.execution_mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("speech records require deterministic execution mode")
        if evidence.live_provider_executed or evidence.story != "9.4":
            raise ValueError("speech records are Story 9.4 evidence with no live execution")
        test_double = SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
        if self.provider_processing is test_double and (
            evidence.evidence_class is not EvidenceClass.AUTOMATED_TEST
        ):
            raise ValueError("test-double provider runs are automated_test evidence only")
