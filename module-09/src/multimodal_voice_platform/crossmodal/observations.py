"""Normalize processed modality results into typed, bounded observations (ADR-009-006).

Each successful text, image, document, or audio result becomes a ``ModalityObservation``:

- ``view`` is the ``ObservationView`` the reasoning port sees: modality, input identity, trust,
  locally measured or extracted facts, and bounded statements, each labeled with its origin.
- ``provenance`` is what the reviewer additionally sees: media type, processing path, processor,
  processing kinds reported by the Story 9.3 or 9.4 record, that record's ID, and timing.

Raw binary content never enters an observation. Statement text is untrusted data.
"""

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.contracts.modality import Identifier, ModalityInput, TrustLevel
from multimodal_voice_platform.contracts.providers import ProviderDescriptor
from multimodal_voice_platform.contracts.reasoning import (
    MAX_FACTS_PER_OBSERVATION,
    FactOrigin,
    ObservationView,
    ObservedFact,
    Statement,
)
from multimodal_voice_platform.crossmodal.limits import CrossModalLimits
from multimodal_voice_platform.speech.records import (
    SpeechProcessingKind,
    SpeechRecord,
    SpeechTiming,
)
from multimodal_voice_platform.understanding.records import StageTiming, UnderstandingRecord

_SENTENCE_SPLIT: Final = re.compile(r"(?<=[.!?])\s+|\n+")
_TRANSCRIPT_ORIGIN: Final = {
    SpeechProcessingKind.FIXTURE_PLAYBACK: FactOrigin.FIXTURE_PLAYBACK,
    SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE: FactOrigin.PROVIDER_CONTRACT_TEST_DOUBLE,
}


class ObservationPath(StrEnum):
    """The processing path that produced an observation."""

    TEXT_PASSTHROUGH = "text_passthrough"
    LOCAL_IMAGE_ANALYSIS = "local_image_analysis"
    LOCAL_DOCUMENT_EXTRACTION = "local_document_extraction"
    LOCAL_AUDIO_ANALYSIS = "local_audio_analysis"
    LOCAL_AUDIO_TRANSCRIPTION = "local_audio_transcription"


class ObservationProvenance(BaseModel):
    """How an observation was produced. Shown to reviewers; not sent to the reasoning port."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    media_type: str
    display_name: str | None = None
    processing_path: ObservationPath
    processor: ProviderDescriptor | None = None
    processing: tuple[str, ...] = ()
    source_record_id: Identifier | None = None
    processing_ms: float = Field(ge=0)


class ModalityObservation(BaseModel):
    """One normalized observation: what reasoning sees, and how it was produced."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    view: ObservationView
    provenance: ObservationProvenance


class _Builder:
    """Accumulates bounded facts and statements for one observation."""

    def __init__(self, observation_id: str, limits: CrossModalLimits) -> None:
        self.observation_id = observation_id
        self.limits = limits
        self.facts: list[ObservedFact] = []
        self.statements: list[Statement] = []
        self.chars = 0
        self.truncated = False

    def fact(
        self,
        prop: str,
        value: str,
        *,
        origin: FactOrigin = FactOrigin.LOCAL_MEASUREMENT,
        numeric: float | None = None,
        share: float | None = None,
    ) -> None:
        if len(self.facts) >= MAX_FACTS_PER_OBSERVATION:
            self.truncated = True
            return
        self.facts.append(
            ObservedFact(
                fact_id=f"{self.observation_id}-f{len(self.facts) + 1}",
                property=prop,
                value=value[:120],
                numeric=numeric,
                share=share,
                origin=origin,
            )
        )

    def text(self, text: str, origin: FactOrigin) -> None:
        for raw in _SENTENCE_SPLIT.split(text):
            sentence = " ".join(raw.split())
            if not sentence:
                continue
            if len(self.statements) >= self.limits.max_statements_per_observation:
                self.truncated = True
                return
            if len(sentence) > self.limits.max_statement_chars:
                sentence = sentence[: self.limits.max_statement_chars].rstrip()
                self.truncated = True
            room = self.limits.max_observation_chars - self.chars
            if room <= 0:
                self.truncated = True
                return
            if len(sentence) > room:
                sentence = sentence[:room].rstrip()
                self.truncated = True
            if not sentence:
                return
            self.statements.append(
                Statement(
                    statement_id=f"{self.observation_id}-s{len(self.statements) + 1}",
                    text=sentence,
                    origin=origin,
                )
            )
            self.chars += len(sentence)

    def build(self, item: ModalityInput, trust: TrustLevel) -> ObservationView:
        return ObservationView(
            observation_id=self.observation_id,
            modality=item.modality,
            input_id=item.input_id,
            source=item.source,
            trust=trust,
            facts=tuple(self.facts),
            statements=tuple(self.statements),
            truncated=self.truncated,
        )


def observe_text(
    observation_id: str, item: ModalityInput, limits: CrossModalLimits, processing_ms: float
) -> ModalityObservation:
    """Normalize a validated text input. Its sentences are user-provided statements.

    Args:
        observation_id: Canonical observation ID assigned by the workflow.
        item: Validated, untrusted text input.
        limits: Workflow bounds.
        processing_ms: Time spent validating the text.

    Returns:
        The observation.
    """
    builder = _Builder(observation_id, limits)
    builder.text(item.text or "", FactOrigin.USER_PROVIDED)
    return ModalityObservation(
        view=builder.build(item, TrustLevel.UNTRUSTED_EXTERNAL),
        provenance=ObservationProvenance(
            media_type=item.media_type,
            display_name=item.display_name,
            processing_path=ObservationPath.TEXT_PASSTHROUGH,
            processing_ms=processing_ms,
        ),
    )


def observe_understanding(
    observation_id: str, record: UnderstandingRecord, limits: CrossModalLimits
) -> ModalityObservation:
    """Normalize a successful Story 9.3 image or document record.

    Args:
        observation_id: Canonical observation ID assigned by the workflow.
        record: Successful understanding record.
        limits: Workflow bounds.

    Returns:
        The observation.

    Raises:
        ValueError: If the record is not a successful image or document record. Callers pass only
            successful records, so this indicates a defect.
    """
    item = record.input
    if item is None or record.path is None:
        raise ValueError("only successful understanding records can be observed")
    builder = _Builder(observation_id, limits)
    if record.image_analysis is not None:
        image = record.image_analysis
        for region in image.regions:
            builder.fact(f"image.region.{region.region}", region.color, share=region.share)
        for color in image.dominant_colors:
            builder.fact("image.color", color.color, share=color.share)
        builder.fact("image.brightness", image.brightness, numeric=image.mean_luma)
        builder.fact("image.orientation", image.orientation.value)
        builder.fact("image.size", f"{image.width} x {image.height} pixels")
    elif record.document is not None and record.document_analysis is not None:
        analysis = record.document_analysis
        extraction = FactOrigin.LOCAL_EXTRACTION
        builder.fact("document.format", analysis.format.value, origin=extraction)
        if analysis.title:
            builder.fact("document.title", analysis.title, origin=extraction)
        builder.fact(
            "document.section_count",
            str(analysis.section_count),
            origin=extraction,
            numeric=analysis.section_count,
        )
        builder.fact(
            "document.word_count",
            str(analysis.word_count),
            origin=extraction,
            numeric=analysis.word_count,
        )
        for section in record.document.sections:
            if section.heading:
                builder.text(section.heading, extraction)
            builder.text(section.text, extraction)
    else:
        raise ValueError("understanding record carries no outputs")
    return ModalityObservation(
        view=builder.build(item, TrustLevel.UNTRUSTED_MODEL_OUTPUT),
        provenance=ObservationProvenance(
            media_type=item.media_type,
            display_name=item.display_name,
            processing_path=ObservationPath(record.path.value),
            processor=record.provider,
            processing=tuple(kind.value for kind in record.processing),
            source_record_id=record.record_id,
            processing_ms=_total_ms(record.timings),
        ),
    )


def observe_speech(
    observation_id: str, record: SpeechRecord, limits: CrossModalLimits
) -> ModalityObservation:
    """Normalize a successful Story 9.4 audio analysis or transcription record.

    Signal measurements become facts. A transcript, if present, becomes statements labeled with
    the speech-to-text adapter's processing kind (fixture playback or a test double), never as
    speech recognition.

    Args:
        observation_id: Canonical observation ID assigned by the workflow.
        record: Successful audio analysis or transcription record.
        limits: Workflow bounds.

    Returns:
        The observation.

    Raises:
        ValueError: If the record is not a successful audio record. Callers pass only successful
            records, so this indicates a defect.
    """
    item, audio = record.input, record.audio
    if item is None or audio is None:
        raise ValueError("only successful audio records can be observed")
    builder = _Builder(observation_id, limits)
    builder.fact("audio.content", audio.content.value, numeric=audio.peak_level)
    builder.fact("audio.duration_ms", f"{audio.duration_ms:g} ms", numeric=audio.duration_ms)
    builder.fact("audio.sample_rate_hz", f"{audio.sample_rate_hz} Hz", numeric=audio.sample_rate_hz)
    builder.fact("audio.channels", str(audio.channels), numeric=audio.channels)
    if audio.content.value == "signal" and audio.zero_crossing_rate_per_s > 0:
        estimate = round(audio.zero_crossing_rate_per_s / 2, 1)
        builder.fact(
            "audio.tone_hz",
            f"{estimate:g} Hz zero-crossing estimate (valid for single tones only)",
            numeric=estimate,
        )
    if record.transcript is not None and record.provider_processing is not None:
        builder.text(record.transcript.text, _TRANSCRIPT_ORIGIN[record.provider_processing])
        path = ObservationPath.LOCAL_AUDIO_TRANSCRIPTION
    else:
        path = ObservationPath.LOCAL_AUDIO_ANALYSIS
    return ModalityObservation(
        view=builder.build(item, TrustLevel.UNTRUSTED_MODEL_OUTPUT),
        provenance=ObservationProvenance(
            media_type=item.media_type,
            display_name=item.display_name,
            processing_path=path,
            processor=record.provider,
            processing=tuple(kind.value for kind in record.processing),
            source_record_id=record.record_id,
            processing_ms=_total_ms(record.timings),
        ),
    )


def _total_ms(timings: Iterable[StageTiming | SpeechTiming]) -> float:
    return round(sum(timing.duration_ms for timing in timings), 3)
