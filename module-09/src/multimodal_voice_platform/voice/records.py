"""Reviewer-displayable, evidence-classified record of one voice-assistant turn (Story 9.6).

A ``VoiceTurnRecord`` shows the whole turn: the embedded Story 9.4 transcription record (input
audio metadata, local audio processing, and the transcript with its processing kind), the bounded
conversation context the reasoning call saw, which reasoning adapter ran and what kind of reasoning
it performs, the validated reply with its citations, the embedded Story 9.4 synthesis record (the
generated, validated output audio), the conversation snapshot, per-stage and end-to-end timings,
whether the turn committed, and the safe failure, with an ``EvidenceRecord``.

``speech_recognition_performed``, ``speech_synthesis_performed``, ``model_inference_performed``,
and ``live_provider_called`` are ``False`` for deterministic turns. ``streaming_performed`` is
``False`` for Story 9.6 synchronous turns; only a turn run by the Story 9.7 streaming coordinator
sets it, and such a record must be Story 9.7 evidence.

Story 9.8 live turns (synchronous or streamed) are Story 9.8 evidence. Their flags are derived
from what actually ran: speech recognition and synthesis from the embedded speech records, model
inference from the reasoning kind, and ``live_provider_called`` from the reported provider calls.
``live_calls`` holds the reasoning adapter's calls; the embedded speech records hold their own.
"""

from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.contracts.conversation import AssistantReply
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
from multimodal_voice_platform.contracts.modality import Identifier, ModalityInput, TrustLevel
from multimodal_voice_platform.contracts.providers import ProviderDescriptor, ProviderPort
from multimodal_voice_platform.contracts.reasoning import ObservationId
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.crossmodal.records import (
    LIVE_REASONING_KINDS,
    RESERVED_REASONING_KINDS,
    ReasoningKind,
)
from multimodal_voice_platform.speech.records import (
    SpeechOperation,
    SpeechProcessingKind,
    SpeechRecord,
    SpeechStatus,
    SynthesisResult,
)
from multimodal_voice_platform.voice.state import ConversationSnapshot

VOICE_EVIDENCE_CLASSES: Final = frozenset(
    {EvidenceClass.AUTOMATED_TEST, EvidenceClass.DETERMINISTIC_DEMO}
)
"""The only evidence classes Story 9.6 voice turns may produce."""


class VoiceStage(StrEnum):
    """Turn stages, in the order they run. ``end_to_end`` is a timing, never a failed stage."""

    ADMISSION = "admission"
    AUDIO_VALIDATION = "audio_validation"
    AUDIO_PROCESSING = "audio_processing"
    SPEECH_TO_TEXT = "speech_to_text"
    TRANSCRIPT_VALIDATION = "transcript_validation"
    CONTEXT_CONSTRUCTION = "context_construction"
    REASONING = "reasoning"
    REPLY_VALIDATION = "reply_validation"
    TEXT_TO_SPEECH = "text_to_speech"
    OUTPUT_AUDIO_VALIDATION = "output_audio_validation"
    STATE_COMMIT = "state_commit"
    END_TO_END = "end_to_end"


LATENCY_STAGES: Final = {
    VoiceStage.AUDIO_VALIDATION: LatencyStage.INGESTION,
    VoiceStage.SPEECH_TO_TEXT: LatencyStage.SPEECH_TO_TEXT,
    VoiceStage.REASONING: LatencyStage.REASONING,
    VoiceStage.TEXT_TO_SPEECH: LatencyStage.TEXT_TO_SPEECH,
    VoiceStage.END_TO_END: LatencyStage.END_TO_END,
}
"""Voice stages that map onto the contract's reviewer-visible latency stages."""


class TurnStatus(StrEnum):
    """Outcome of one turn."""

    COMMITTED = "committed"
    REJECTED = "rejected"
    FAILED = "failed"


class VoiceTiming(BaseModel):
    """Measured wall-clock duration of one turn stage. Local measurement, not an SLA."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: VoiceStage
    duration_ms: float = Field(ge=0, allow_inf_nan=False)


class TranscriptView(BaseModel):
    """The validated transcript the turn reasoned over. Untrusted data, never instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    trust: Literal[TrustLevel.UNTRUSTED_MODEL_OUTPUT] = TrustLevel.UNTRUSTED_MODEL_OUTPUT
    processing: SpeechProcessingKind
    chars: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        """Bind the length to the text and the processing kind to a speech-to-text kind.

        Returns:
            The validated view.

        Raises:
            ValueError: If the length is wrong or the kind claims speech recognition.
        """
        if self.chars != len(self.text):
            raise ValueError("chars must match the transcript text")
        if self.processing not in {
            SpeechProcessingKind.FIXTURE_PLAYBACK,
            SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE,
            SpeechProcessingKind.SPEECH_RECOGNITION,
        }:
            raise ValueError("transcripts are fixture playback, a test double, or live recognition")
        return self


class ConversationContext(BaseModel):
    """What the reasoning call saw: the current observation and the bounded history window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: ObservationId
    statement_count: int = Field(ge=1)
    fact_count: int = Field(ge=0)
    history_entries: int = Field(ge=0)
    history_exchanges: int = Field(ge=0)
    history_chars: int = Field(ge=0)
    retained_exchanges: int = Field(ge=0)
    max_context_turns: int = Field(ge=1)
    max_context_chars: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        """Keep the window within its bounds and made of whole exchanges.

        Returns:
            The validated context.

        Raises:
            ValueError: If the window is not whole exchanges or exceeds a bound.
        """
        if self.history_entries != 2 * self.history_exchanges:
            raise ValueError("the history window holds whole exchanges")
        if self.history_exchanges > min(self.max_context_turns, self.retained_exchanges):
            raise ValueError("the history window exceeds its turn bound")
        if self.history_chars > self.max_context_chars:
            raise ValueError("the history window exceeds its character bound")
        return self


class VoiceTurnRecord(BaseModel):
    """Typed record of one voice-assistant turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: Identifier
    session_id: Identifier
    turn_id: Identifier
    status: TurnStatus
    committed: bool
    sequence: int | None = Field(default=None, ge=1)
    transcription: SpeechRecord | None = None
    transcript: TranscriptView | None = None
    context: ConversationContext | None = None
    reasoning_provider: ProviderDescriptor | None = None
    reasoning_kind: ReasoningKind | None = None
    reply: AssistantReply | None = None
    synthesis: SpeechRecord | None = None
    conversation: ConversationSnapshot | None = None
    speech_recognition_performed: bool = False
    speech_synthesis_performed: bool = False
    model_inference_performed: bool = False
    live_provider_called: bool = False
    live_calls: tuple[LiveCall, ...] = Field(default=(), max_length=MAX_LIVE_CALLS)
    streaming_performed: bool = False
    timings: tuple[VoiceTiming, ...] = Field(min_length=1, max_length=len(VoiceStage))
    failed_stage: VoiceStage | None = None
    error: SafeError | None = None
    evidence: EvidenceRecord

    @property
    def input_audio(self) -> ModalityInput | None:
        """The validated input audio's metadata, if the audio passed validation."""
        return self.transcription.input if self.transcription is not None else None

    @property
    def output_audio(self) -> SynthesisResult | None:
        """The generated, validated output audio, if the turn produced it."""
        return self.synthesis.synthesis if self.synthesis is not None else None

    @property
    def end_to_end_ms(self) -> float:
        """Measured wall-clock duration of the whole turn."""
        return next(t.duration_ms for t in self.timings if t.stage is VoiceStage.END_TO_END)

    def all_live_calls(self) -> tuple[LiveCall, ...]:
        """Every provider call of the turn: speech-to-text, reasoning, and text-to-speech.

        Returns:
            The calls in turn order.
        """
        before = self.transcription.live_calls if self.transcription is not None else ()
        after = self.synthesis.live_calls if self.synthesis is not None else ()
        return (*before, *self.live_calls, *after)

    def latency_metrics(self) -> tuple[tuple[LatencyStage, float], ...]:
        """Return measured durations keyed by the contract's latency stages.

        Returns:
            ``(stage, milliseconds)`` pairs for the stages that ran, in turn order.
        """
        return tuple(
            (LATENCY_STAGES[timing.stage], timing.duration_ms)
            for timing in self.timings
            if timing.stage in LATENCY_STAGES
        )

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        """Keep the record internally consistent and its evidence honest.

        Returns:
            The validated record.

        Raises:
            ValueError: If status, commit state, outputs, providers, timings, or evidence
                contradict each other or claim more than deterministic, non-live processing.
        """
        if self.committed != (self.status is TurnStatus.COMMITTED):
            raise ValueError("a turn is committed exactly when its status is committed")
        stages = [timing.stage for timing in self.timings]
        if stages.count(VoiceStage.END_TO_END) != 1 or stages[-1] is not VoiceStage.END_TO_END:
            raise ValueError("timings end with exactly one end_to_end measurement")
        self._validate_speech()
        self._validate_reasoning()
        self._validate_flags()
        if self.committed:
            self._validate_committed()
        else:
            self._validate_uncommitted()
        self._validate_evidence()
        return self

    def _validate_speech(self) -> None:
        transcription, synthesis = self.transcription, self.synthesis
        if (
            transcription is not None
            and transcription.operation is not SpeechOperation.TRANSCRIPTION
        ):
            raise ValueError("the transcription record must be a transcription run")
        if synthesis is not None and synthesis.operation is not SpeechOperation.SYNTHESIS:
            raise ValueError("the synthesis record must be a synthesis run")
        for record in (transcription, synthesis):
            if record is not None and record.session_id != self.session_id:
                raise ValueError("embedded speech records belong to the turn's session")
        if self.transcript is not None:
            if transcription is None or transcription.transcript is None:
                raise ValueError("a transcript comes from a successful transcription")
            if transcription.provider_processing is not self.transcript.processing:
                raise ValueError("the transcript names its speech-to-text processing kind")

    def _validate_flags(self) -> None:
        transcription, synthesis = self.transcription, self.synthesis
        recognized = transcription is not None and transcription.speech_recognition_performed
        synthesized = synthesis is not None and synthesis.speech_synthesis_performed
        if self.speech_recognition_performed != recognized:
            raise ValueError("speech_recognition_performed must match the transcription record")
        if self.speech_synthesis_performed != synthesized:
            raise ValueError("speech_synthesis_performed must match the synthesis record")
        if self.model_inference_performed != (self.reasoning_kind is ReasoningKind.MODEL_INFERENCE):
            raise ValueError("model_inference_performed must match the reasoning kind")
        if self.live_provider_called != real_call_made(self.all_live_calls()):
            raise ValueError("live_provider_called must match the reported provider calls")
        if self.live_calls and self.evidence.story != LIVE_STORY:
            raise ValueError("only live turns report provider calls")
        model = self.reasoning_kind is ReasoningKind.MODEL_INFERENCE
        if any(call.real_endpoint != model for call in self.live_calls):
            raise ValueError("real reasoning calls are exactly the model-backed reasoning calls")

    def _validate_reasoning(self) -> None:
        provider, kind = self.reasoning_provider, self.reasoning_kind
        if (provider is None) != (kind is None):
            raise ValueError("the reasoning provider and its kind are recorded together")
        live = self.evidence.story == LIVE_STORY
        if provider is not None and provider.port is not ProviderPort.REASONING:
            raise ValueError("the reasoning provider must be a reasoning adapter")
        if provider is not None and provider.mode is ExecutionMode.LIVE:
            if not live or kind not in LIVE_REASONING_KINDS:
                raise ValueError("live reasoning adapters run in live Story 9.8 turns only")
            return
        if kind in RESERVED_REASONING_KINDS:
            raise ValueError("model inference needs a live reasoning adapter")
        if provider is not None and live:
            raise ValueError("live turns reason through a live reasoning adapter")
        if self.reply is not None and provider is None:
            raise ValueError("a reply names the reasoning provider that produced it")

    def _validate_committed(self) -> None:
        transcription, synthesis = self.transcription, self.synthesis
        if self.error is not None or self.failed_stage is not None or self.sequence is None:
            raise ValueError("committed turns have a sequence number and no error")
        if transcription is None or transcription.status is not SpeechStatus.SUCCEEDED:
            raise ValueError("committed turns carry a successful transcription")
        if synthesis is None or synthesis.status is not SpeechStatus.SUCCEEDED:
            raise ValueError("committed turns carry successfully generated output audio")
        if self.transcript is None or self.context is None or self.reply is None:
            raise ValueError("committed turns carry the transcript, context, and reply")
        if synthesis.input is None or synthesis.input.text != self.reply.reply:
            raise ValueError("the output audio renders exactly the reply text")
        conversation = self.conversation
        if conversation is None or conversation.committed_turns < self.sequence:
            raise ValueError("committed turns show the conversation that includes them")

    def _validate_uncommitted(self) -> None:
        if self.error is None or self.failed_stage is None:
            raise ValueError("uncommitted turns carry an error and the failed stage")
        if self.failed_stage is VoiceStage.END_TO_END or self.sequence is not None:
            raise ValueError("uncommitted turns name a real failed stage and no sequence")
        if (
            self.synthesis is not None
            and self.synthesis.status is SpeechStatus.SUCCEEDED
            and (self.failed_stage is not VoiceStage.STATE_COMMIT)
        ):
            raise ValueError("only a state-commit failure follows successful output audio")

    def _validate_evidence(self) -> None:
        evidence = self.evidence
        if evidence.story == LIVE_STORY:
            check_live_evidence(evidence, self.all_live_calls())
            for record in (self.transcription, self.synthesis):
                if record is not None and record.evidence.story != LIVE_STORY:
                    raise ValueError("embedded speech records of a live turn are live runs")
            return
        if evidence.evidence_class not in VOICE_EVIDENCE_CLASSES:
            raise ValueError("voice turns allow only deterministic evidence classes")
        if evidence.execution_mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("voice turns require deterministic execution mode")
        story = "9.7" if self.streaming_performed else "9.6"
        if evidence.live_provider_executed or evidence.story != story:
            raise ValueError(
                "synchronous turns are Story 9.6 evidence and streamed turns Story 9.7 evidence, "
                "with no live execution"
            )
        test_double = SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
        doubles = [
            record.provider_processing is test_double
            for record in (self.transcription, self.synthesis)
            if record is not None
        ]
        if (
            any(doubles) or self.reasoning_kind is ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
        ) and (evidence.evidence_class is not EvidenceClass.AUTOMATED_TEST):
            raise ValueError("turns with any test-double provider are automated_test evidence")
        for record in (self.transcription, self.synthesis):
            if record is not None and record.evidence.evidence_class is not evidence.evidence_class:
                raise ValueError("embedded speech records share the turn's evidence class")
