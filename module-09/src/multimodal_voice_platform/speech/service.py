"""Audio and speech pipeline service (Story 9.4).

``SpeechService`` is the application-facing entry point for Story 9.4. It runs three operations
through the accepted provider ports and returns a ``SpeechRecord`` for every outcome:

- audio analysis: validated audio -> local PCM WAV decoding and signal measurement;
- transcription: validated audio -> audio processing -> ``SpeechToTextPort`` -> typed transcript;
- synthesis: validated text -> ``TextToSpeechPort`` -> generated audio -> audio validation.

The speech adapters are injected as bindings that declare what kind of processing they perform, so
the core logic is not coupled to any provider and every record names its processing honestly. The
defaults are the Story 9.2 fixture-playback speech-to-text adapter (not speech recognition) and the
Story 9.4 tone-sequence synthesizer (not speech synthesis). Both run in-process with no network,
key, or spend.

Every provider call is bounded by the session request timeout, and provider output is validated
against the port contract before it is recorded. Adapters must translate their own provider
failures into ``Module9Error`` subclasses (for example ``SpeechProviderUnavailableError``); the
service turns those into safe rejected or failed records. Anything else is a defect and propagates.

Story 9.8 adds explicit live operation: a service constructed with ``LiveSpeechBindings`` runs
an opted-in live session's speech stage through a live adapter (speech recognition or synthesis
by the real provider, or a contract test double), after the same local validation, and validates
the provider's output exactly as before. A live session without live bindings is refused, as it
was in Story 9.4; a deterministic session never reaches a live adapter.

Content is staged in a store that lives for one call and is released before the call returns
(SEC-022). Authority (mode, budget, limits, provider selection) comes only from application code
and the application-owned ``SessionConfig``; transcripts and other content never change it.
"""

import asyncio
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from pydantic import TypeAdapter, ValidationError

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.deterministic.errors import ContentNotFoundError
from multimodal_voice_platform.adapters.deterministic.fixtures import FixtureCatalog
from multimodal_voice_platform.adapters.deterministic.providers import (
    DeterministicSpeechToTextProvider,
)
from multimodal_voice_platform.adapters.speech.tone_synthesis import ToneSequenceSynthesizer
from multimodal_voice_platform.audio.analysis import AudioAnalysis, analyze_wav
from multimodal_voice_platform.audio.errors import AudioProcessingTimeoutError
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.audio.staging import stage_audio_content
from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.live import LiveCall, calls_of, live_evidence
from multimodal_voice_platform.contracts.modality import InputSource, ModalityInput
from multimodal_voice_platform.contracts.providers import (
    LanguageTag,
    ProviderDescriptor,
    ProviderPort,
    SpeechSynthesisRequest,
    SpeechToTextPort,
    SynthesizedAudio,
    TextToSpeechPort,
    TranscriptionRequest,
    TranscriptSegment,
)
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.ingestion.errors import IngestionError
from multimodal_voice_platform.live.bindings import LiveBinding, LiveSpeechBindings
from multimodal_voice_platform.live.credentials import session_credential
from multimodal_voice_platform.speech.errors import (
    LiveSpeechUnavailableError,
    SpeechConfigurationError,
    SpeechProviderOutputError,
    SpeechProviderTimeoutError,
    SpeechProviderUnavailableError,
)
from multimodal_voice_platform.speech.records import (
    LOCAL_AUDIO_PROCESSING,
    MAX_TRANSCRIPT_SEGMENTS,
    PROVIDER_KINDS,
    SPEECH_EVIDENCE_CLASSES,
    SpeechOperation,
    SpeechProcessingKind,
    SpeechRecord,
    SpeechStage,
    SpeechStatus,
    SpeechTiming,
    SynthesisResult,
    TranscriptResult,
)
from multimodal_voice_platform.speech.text_input import stage_text_input

_REQUIREMENTS: Final = {
    SpeechOperation.AUDIO_ANALYSIS: ("SRC-003", "ENG-006"),
    SpeechOperation.TRANSCRIPTION: ("SRC-003", "SRC-006", "ENG-006"),
    SpeechOperation.SYNTHESIS: ("SRC-007", "ENG-006"),
}
_NO_LIVE: Final = "No model inference, live provider, network, or credential was used."
_LIVE_KINDS: Final = {
    ProviderPort.SPEECH_TO_TEXT: SpeechProcessingKind.SPEECH_RECOGNITION,
    ProviderPort.TEXT_TO_SPEECH: SpeechProcessingKind.SPEECH_SYNTHESIS,
}
_KIND_NOTES: Final = {
    SpeechProcessingKind.SPEECH_RECOGNITION: (
        "The transcript was produced by a live speech recognition model and is untrusted."
    ),
    SpeechProcessingKind.SPEECH_SYNTHESIS: (
        "The audio was produced by a live speech synthesis model and validated locally."
    ),
    SpeechProcessingKind.FIXTURE_PLAYBACK: (
        "The transcript is a scripted fixture transcript replayed by digest match, "
        "not speech recognition."
    ),
    SpeechProcessingKind.DETERMINISTIC_TONE_SYNTHESIS: (
        "The audio is a deterministic tone sequence, not synthesized speech."
    ),
    SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE: (
        "The provider was a contract test double; no speech was recognized or synthesized."
    ),
}
_FAILED_CODES: Final = frozenset(
    {ErrorCode.PROVIDER_TIMEOUT, ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.INTERNAL_ERROR}
)
_RETRYABLE: Final = (
    AudioProcessingTimeoutError,
    SpeechProviderTimeoutError,
    SpeechProviderUnavailableError,
)
_LANGUAGE: Final = TypeAdapter(LanguageTag)
_DURATION_TOLERANCE_MS: Final = 1.0


@dataclass(frozen=True)
class SpeechToTextBinding:
    """A speech-to-text adapter factory and the processing kind its adapter performs.

    Attributes:
        factory: Builds the adapter over the run's session content store.
        processing: What the adapter does. Must be a Story 9.4 speech-to-text kind.
    """

    factory: Callable[[SessionContentStore], SpeechToTextPort]
    processing: SpeechProcessingKind

    def __post_init__(self) -> None:
        """Reject processing kinds a Story 9.4 speech-to-text adapter cannot honestly claim.

        Raises:
            SpeechConfigurationError: If the kind is not a Story 9.4 speech-to-text kind.
        """
        if self.processing not in PROVIDER_KINDS[ProviderPort.SPEECH_TO_TEXT]:
            raise SpeechConfigurationError("unsupported speech-to-text processing kind")


@dataclass(frozen=True)
class TextToSpeechBinding:
    """A text-to-speech adapter factory and the processing kind its adapter performs.

    Attributes:
        factory: Builds the adapter over the run's content store and audio limits.
        processing: What the adapter does. Must be a Story 9.4 text-to-speech kind.
    """

    factory: Callable[[SessionContentStore, AudioLimits], TextToSpeechPort]
    processing: SpeechProcessingKind

    def __post_init__(self) -> None:
        """Reject processing kinds a Story 9.4 text-to-speech adapter cannot honestly claim.

        Raises:
            SpeechConfigurationError: If the kind is not a Story 9.4 text-to-speech kind.
        """
        if self.processing not in PROVIDER_KINDS[ProviderPort.TEXT_TO_SPEECH]:
            raise SpeechConfigurationError("unsupported text-to-speech processing kind")


@dataclass(frozen=True)
class _Wiring:
    """The speech adapter chosen for one run, and whether the run is live."""

    provider: object | None
    descriptor: ProviderDescriptor | None
    kind: SpeechProcessingKind | None
    live: bool


@dataclass
class _Run:
    """Mutable progress of one run, so failures record exactly what completed."""

    operation: SpeechOperation
    stage: SpeechStage = SpeechStage.INGESTION
    input: ModalityInput | None = None
    audio: AudioAnalysis | None = None
    processing: list[SpeechProcessingKind] = field(default_factory=list)
    timings: list[SpeechTiming] = field(default_factory=list)
    started: float = 0.0

    def begin(self, stage: SpeechStage) -> None:
        self.stage = stage
        self.started = time.perf_counter()

    def finish(self) -> None:
        elapsed = round((time.perf_counter() - self.started) * 1000, 3)
        self.timings.append(SpeechTiming(stage=self.stage, duration_ms=elapsed))


class SpeechService:
    """Validates, processes, and records audio analysis, transcription, and synthesis."""

    def __init__(
        self,
        catalog: FixtureCatalog | None = None,
        *,
        speech_to_text: SpeechToTextBinding | None = None,
        text_to_speech: TextToSpeechBinding | None = None,
        live: LiveSpeechBindings | None = None,
    ) -> None:
        """Create the service.

        Args:
            catalog: Verified fixture catalog for ``transcribe_fixture`` and the default
                fixture-playback speech-to-text adapter. Defaults to the packaged fixtures.
            speech_to_text: Speech-to-text binding. Defaults to Story 9.2 fixture playback.
            text_to_speech: Text-to-speech binding. Defaults to the tone-sequence synthesizer.
            live: Live speech bindings (Story 9.8). Without them, live sessions are refused.

        Raises:
            FixtureIntegrityError: If the default catalog fails verification.
        """
        self.catalog = catalog if catalog is not None else FixtureCatalog.load_default()
        catalog_ref = self.catalog
        self._stt = speech_to_text or SpeechToTextBinding(
            factory=lambda store: DeterministicSpeechToTextProvider(catalog_ref, store),
            processing=SpeechProcessingKind.FIXTURE_PLAYBACK,
        )
        self._tts = text_to_speech or TextToSpeechBinding(
            factory=ToneSequenceSynthesizer,
            processing=SpeechProcessingKind.DETERMINISTIC_TONE_SYNTHESIS,
        )
        self._live = live
        self._runs = 0

    def _live_binding(
        self, session: SessionConfig, port: ProviderPort
    ) -> LiveBinding[object] | None:
        if session.mode is not ExecutionMode.LIVE or self._live is None:
            return None
        if port is ProviderPort.SPEECH_TO_TEXT:
            return self._live.speech_to_text
        return self._live.text_to_speech

    def _wire(
        self,
        session: SessionConfig,
        port: ProviderPort | None,
        evidence_class: EvidenceClass,
        *context: object,
    ) -> _Wiring:
        """Choose the deterministic or live adapter for one run. Never falls back silently."""
        live_ready = session.mode is ExecutionMode.LIVE and self._live is not None
        binding = self._live_binding(session, port) if port is not None else None
        if binding is not None:
            binding.check_requested(evidence_class)
            provider = binding.build(session_credential(session), *context)
            kind = (
                _LIVE_KINDS[port]
                if binding.real
                else SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
            )
            return _Wiring(provider, provider.descriptor, kind, True)
        if live_ready and port is None:
            if evidence_class not in {EvidenceClass.LIVE_INTEGRATION, EvidenceClass.AUTOMATED_TEST}:
                raise SpeechConfigurationError(
                    "live runs request live_integration or automated_test"
                )
            return _Wiring(None, None, None, True)
        if port is None:
            self._check_evidence_class(evidence_class, None)
            return _Wiring(None, None, None, False)
        deterministic = self._stt if port is ProviderPort.SPEECH_TO_TEXT else self._tts
        self._check_evidence_class(evidence_class, deterministic.processing)
        return _Wiring(None, None, deterministic.processing, False)

    async def analyze_audio_upload(
        self,
        session: SessionConfig,
        *,
        media_type: str,
        display_name: str,
        data: bytes,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> SpeechRecord:
        """Validate, decode, and measure one untrusted audio upload.

        Args:
            session: Application-owned session configuration.
            media_type: Declared media type. Verified against the content.
            display_name: Untrusted file name.
            data: Untrusted audio bytes.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            A succeeded, rejected, or failed audio analysis record.

        Raises:
            SpeechConfigurationError: If the evidence class is not a Story 9.4 class.
        """
        return await self._audio_run(
            session,
            SpeechOperation.AUDIO_ANALYSIS,
            media_type=media_type,
            display_name=display_name,
            data=data,
            source=InputSource.USER_UPLOAD,
            language=None,
            evidence_class=evidence_class,
        )

    async def transcribe_upload(
        self,
        session: SessionConfig,
        *,
        media_type: str,
        display_name: str,
        data: bytes,
        language: str | None = None,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> SpeechRecord:
        """Validate and process one untrusted audio upload, then transcribe it.

        Args:
            session: Application-owned session configuration.
            media_type: Declared media type. Verified against the content.
            display_name: Untrusted file name.
            data: Untrusted audio bytes.
            language: Optional language tag such as ``en`` or ``en-US``.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            A succeeded, rejected, or failed transcription record.

        Raises:
            SpeechConfigurationError: If the evidence class or adapter wiring is invalid.
        """
        return await self._audio_run(
            session,
            SpeechOperation.TRANSCRIPTION,
            media_type=media_type,
            display_name=display_name,
            data=data,
            source=InputSource.USER_UPLOAD,
            language=language,
            evidence_class=evidence_class,
        )

    async def transcribe_fixture(
        self,
        session: SessionConfig,
        fixture_id: str,
        *,
        language: str | None = None,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> SpeechRecord:
        """Run a committed fixture's bytes through the transcription pipeline.

        The audio is genuinely decoded and measured like an upload. With the default binding the
        transcript is fixture playback, which the record states.

        Args:
            session: Application-owned session configuration.
            fixture_id: Fixture ID from the committed catalog.
            language: Optional language tag.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            A succeeded, rejected, or failed transcription record.

        Raises:
            SpeechConfigurationError: If the evidence class or adapter wiring is invalid.
            UnknownFixtureError: If the fixture ID is not in the catalog. Fixture IDs come from
                application code, so an unknown ID is a defect rather than untrusted input.
        """
        spec = self.catalog.get(fixture_id)
        return await self._audio_run(
            session,
            SpeechOperation.TRANSCRIPTION,
            media_type=spec.media_type,
            display_name=spec.display_name,
            data=self.catalog.content(fixture_id),
            source=InputSource.DETERMINISTIC_FIXTURE,
            language=language,
            evidence_class=evidence_class,
        )

    async def synthesize_text(
        self,
        session: SessionConfig,
        text: str,
        *,
        voice: str | None = None,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> SpeechRecord:
        """Validate text, synthesize audio through the TTS port, and validate the audio.

        Args:
            session: Application-owned session configuration.
            text: Untrusted text to render.
            voice: Optional voice identifier understood by the configured adapter.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            A succeeded, rejected, or failed synthesis record.

        Raises:
            SpeechConfigurationError: If the evidence class or adapter wiring is invalid.
        """
        store = SessionContentStore()
        limits = AudioLimits.from_budget(session.budget)
        wiring = self._wire(session, ProviderPort.TEXT_TO_SPEECH, evidence_class, store, limits)
        if wiring.live:
            provider = wiring.provider
            kind = wiring.kind
        else:
            provider = self._tts.factory(store, limits)
            kind = self._tts.processing
        descriptor = _checked_descriptor(provider.descriptor, ProviderPort.TEXT_TO_SPEECH, wiring)
        run = _Run(SpeechOperation.SYNTHESIS)
        try:
            run.begin(SpeechStage.INGESTION)
            _require_mode(session, wiring)
            item = stage_text_input(session.session_id, text)
            run.input = item
            try:
                request = SpeechSynthesisRequest(
                    session_id=session.session_id, text=text, voice=voice
                )
            except ValidationError as exc:
                raise IngestionError("synthesis request failed validation") from exc
            run.finish()
            run.begin(SpeechStage.TEXT_TO_SPEECH)
            synthesized = await _synthesize(provider, request, limits.timeout_s)
            if not isinstance(synthesized, SynthesizedAudio) or synthesized.provider != descriptor:
                raise SpeechProviderOutputError(
                    "text-to-speech provider returned audio not attributed to it"
                )
            run.processing.append(kind)
            run.finish()
            run.begin(SpeechStage.OUTPUT_VALIDATION)
            wav, analysis = await _validate_generated(store, session, synthesized, limits)
            run.audio = analysis
            run.processing.extend(LOCAL_AUDIO_PROCESSING)
            run.finish()
        except Module9Error as exc:
            return self._unsuccessful(
                session, run, descriptor, kind, exc, evidence_class, wiring.live, calls_of(provider)
            )
        finally:
            store.release(session.session_id)
        synthesis = SynthesisResult(
            audio=synthesized,
            voice=voice,
            audio_sha256=hashlib.sha256(wav).hexdigest(),
            audio_size_bytes=len(wav),
            wav_bytes=wav,
        )
        summary = (
            f"Text input {item.input_id} rendered by {descriptor.provider_id} "
            f"({kind}) into {analysis.duration_ms} ms of {analysis.encoding} WAV "
            f"audio, then decoded and measured locally. {_KIND_NOTES[kind]} "
            f"{_mode_note(wiring.live, calls_of(provider))}"
        )
        return self._record(
            session,
            run,
            descriptor,
            kind,
            evidence_class,
            summary,
            synthesis=synthesis,
            live=wiring.live,
            calls=calls_of(provider),
        )

    async def _audio_run(
        self,
        session: SessionConfig,
        operation: SpeechOperation,
        *,
        media_type: str,
        display_name: str,
        data: bytes,
        source: InputSource,
        language: str | None,
        evidence_class: EvidenceClass,
    ) -> SpeechRecord:
        transcribing = operation is SpeechOperation.TRANSCRIPTION
        store = SessionContentStore()
        limits = AudioLimits.from_budget(session.budget)
        port = ProviderPort.SPEECH_TO_TEXT if transcribing else None
        wiring = self._wire(session, port, evidence_class, store)
        kind = wiring.kind
        provider: SpeechToTextPort | None = None
        descriptor: ProviderDescriptor | None = None
        if transcribing:
            provider = wiring.provider if wiring.live else self._stt.factory(store)  # type: ignore[assignment]
            descriptor = _checked_descriptor(
                provider.descriptor, ProviderPort.SPEECH_TO_TEXT, wiring
            )
        run = _Run(operation)
        transcript: TranscriptResult | None = None
        try:
            run.begin(SpeechStage.INGESTION)
            _require_mode(session, wiring)
            if language is not None:
                try:
                    _LANGUAGE.validate_python(language)
                except ValidationError as exc:
                    raise IngestionError("language must be a tag such as en or en-US") from exc
            item = stage_audio_content(
                store,
                session_id=session.session_id,
                limits=limits,
                media_type=media_type,
                display_name=display_name,
                data=data,
                source=source,
            )
            run.input = item
            run.finish()
            run.begin(SpeechStage.AUDIO_PROCESSING)
            stored = _read(store, item)
            run.audio = await _bounded(lambda: analyze_wav(stored, item.media_type, limits), limits)
            run.processing.extend(LOCAL_AUDIO_PROCESSING)
            run.finish()
            if provider is not None and descriptor is not None and kind is not None:
                run.begin(SpeechStage.SPEECH_TO_TEXT)
                request = TranscriptionRequest(audio=item, language=language)
                segments = await _collect_transcript(provider, request, limits.timeout_s)
                transcript = _validated_transcript(segments, descriptor, item, language)
                run.processing.append(kind)
                run.finish()
        except Module9Error as exc:
            return self._unsuccessful(
                session, run, descriptor, kind, exc, evidence_class, wiring.live, calls_of(provider)
            )
        finally:
            store.release(session.session_id)
        audio = run.audio
        summary = (
            f"Local PCM WAV decoding and signal measurement of audio input {item.input_id}"
            + (
                f" ({audio.encoding}, {audio.sample_rate_hz} Hz, {audio.duration_ms} ms)."
                if audio
                else "."
            )
        )
        if descriptor is not None and kind is not None:
            summary += f" Transcript by {descriptor.provider_id} ({kind}). {_KIND_NOTES[kind]}"
        else:
            summary += " Audio processing only; no speech recognition."
        calls = calls_of(provider)
        return self._record(
            session,
            run,
            descriptor,
            kind,
            evidence_class,
            f"{summary} {_mode_note(wiring.live, calls)}",
            transcript=transcript,
            live=wiring.live,
            calls=calls,
        )

    @staticmethod
    def _check_evidence_class(
        evidence_class: EvidenceClass, kind: SpeechProcessingKind | None
    ) -> None:
        if evidence_class not in SPEECH_EVIDENCE_CLASSES:
            raise SpeechConfigurationError(
                "speech pipeline runs produce only deterministic evidence"
            )
        if (
            kind is SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
            and evidence_class is not EvidenceClass.AUTOMATED_TEST
        ):
            raise SpeechConfigurationError(
                "test-double providers produce automated_test evidence only"
            )

    def _record(
        self,
        session: SessionConfig,
        run: _Run,
        descriptor: ProviderDescriptor | None,
        kind: SpeechProcessingKind | None,
        evidence_class: EvidenceClass,
        summary: str,
        *,
        transcript: TranscriptResult | None = None,
        synthesis: SynthesisResult | None = None,
        live: bool = False,
        calls: tuple[LiveCall, ...] = (),
    ) -> SpeechRecord:
        record_id = self._next_id()
        processing = tuple(run.processing)
        return SpeechRecord(
            record_id=record_id,
            session_id=session.session_id,
            operation=run.operation,
            status=SpeechStatus.SUCCEEDED,
            input=run.input,
            provider=descriptor,
            provider_processing=kind,
            processing=processing,
            audio=run.audio,
            transcript=transcript,
            synthesis=synthesis,
            timings=tuple(run.timings),
            **_flags(processing, calls),
            evidence=_evidence(record_id, run.operation, evidence_class, summary, live, calls),
        )

    def _unsuccessful(
        self,
        session: SessionConfig,
        run: _Run,
        descriptor: ProviderDescriptor | None,
        kind: SpeechProcessingKind | None,
        error: Module9Error,
        evidence_class: EvidenceClass,
        live: bool = False,
        calls: tuple[LiveCall, ...] = (),
    ) -> SpeechRecord:
        status = SpeechStatus.FAILED if error.code in _FAILED_CODES else SpeechStatus.REJECTED
        safe = error.to_safe_error(retryable=isinstance(error, _RETRYABLE))
        record_id = self._next_id()
        processing = tuple(run.processing)
        return SpeechRecord(
            record_id=record_id,
            session_id=session.session_id,
            operation=run.operation,
            status=status,
            input=run.input,
            provider=descriptor,
            provider_processing=kind,
            processing=processing,
            audio=run.audio,
            timings=tuple(run.timings),
            failed_stage=run.stage,
            error=safe,
            **_flags(processing, calls),
            evidence=_evidence(
                record_id,
                run.operation,
                evidence_class,
                f"{run.operation} {status} safely at the {run.stage} stage with code "
                f"{safe.code}. {_mode_note(live, calls)}",
                live,
                calls,
            ),
        )

    def _next_id(self) -> str:
        self._runs += 1
        return f"spc-{self._runs:06d}"


def _require_mode(session: SessionConfig, wiring: _Wiring) -> None:
    if session.mode is not ExecutionMode.DETERMINISTIC and not wiring.live:
        raise LiveSpeechUnavailableError(
            "live speech providers are not available; use deterministic mode"
        )


def _checked_descriptor(
    descriptor: ProviderDescriptor, port: ProviderPort, wiring: _Wiring
) -> ProviderDescriptor:
    expected = ExecutionMode.LIVE if wiring.live else ExecutionMode.DETERMINISTIC
    if descriptor.port is not port or descriptor.mode is not expected:
        raise SpeechConfigurationError(f"the configured {port} adapter must be {expected}")
    return descriptor


def _flags(
    processing: tuple[SpeechProcessingKind, ...], calls: tuple[LiveCall, ...]
) -> dict[str, bool]:
    recognized = SpeechProcessingKind.SPEECH_RECOGNITION in processing
    synthesized = SpeechProcessingKind.SPEECH_SYNTHESIS in processing
    return {
        "speech_recognition_performed": recognized,
        "speech_synthesis_performed": synthesized,
        "model_inference_performed": recognized or synthesized,
        "live_provider_called": any(call.real_endpoint for call in calls),
        "live_calls": calls,
    }


def _mode_note(live: bool, calls: tuple[LiveCall, ...]) -> str:
    if not live:
        return _NO_LIVE
    real = sum(call.real_endpoint for call in calls)
    if real:
        return f"Live mode: {real} call(s) to the real provider endpoint; no credential recorded."
    if calls:
        return "Live mode over a provider contract test double; no real provider was called."
    return "Live mode, but no provider call was made; only local processing ran."


def _read(store: SessionContentStore, item: ModalityInput) -> bytes:
    if item.content_ref is None:
        raise IngestionError("audio input requires a content reference")
    return store.read(item.session_id, item.content_ref)


async def _bounded(work: Callable[[], AudioAnalysis], limits: AudioLimits) -> AudioAnalysis:
    try:
        return await asyncio.wait_for(asyncio.to_thread(work), timeout=limits.timeout_s)
    except TimeoutError as exc:
        raise AudioProcessingTimeoutError(
            "local audio processing exceeded the request timeout"
        ) from exc


async def _collect_transcript(
    provider: SpeechToTextPort, request: TranscriptionRequest, timeout_s: float
) -> list[TranscriptSegment]:
    stream = provider.transcribe(request)
    segments: list[TranscriptSegment] = []
    try:
        async with asyncio.timeout(timeout_s):
            async for segment in stream:
                if len(segments) >= MAX_TRANSCRIPT_SEGMENTS:
                    raise SpeechProviderOutputError(
                        "speech-to-text provider returned too many segments"
                    )
                segments.append(segment)
    except TimeoutError as exc:
        raise SpeechProviderTimeoutError(
            "speech-to-text provider exceeded the request timeout"
        ) from exc
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()
    return segments


def _validated_transcript(
    segments: list[TranscriptSegment],
    descriptor: ProviderDescriptor,
    item: ModalityInput,
    language: str | None,
) -> TranscriptResult:
    if not segments:
        raise SpeechProviderOutputError("speech-to-text provider returned no transcript")
    duration_ms = item.duration_ms or 0
    previous_start = 0
    for segment in segments:
        if not isinstance(segment, TranscriptSegment) or segment.provider != descriptor:
            raise SpeechProviderOutputError(
                "speech-to-text provider returned a segment not attributed to it"
            )
        if segment.start_ms < previous_start or segment.end_ms > duration_ms:
            raise SpeechProviderOutputError(
                "speech-to-text provider returned segments outside the audio timeline"
            )
        previous_start = segment.start_ms
    try:
        return TranscriptResult(segments=tuple(segments), text=segments[-1].text, language=language)
    except ValidationError as exc:
        raise SpeechProviderOutputError(
            "speech-to-text provider returned an invalid transcript stream"
        ) from exc


async def _synthesize(
    provider: TextToSpeechPort, request: SpeechSynthesisRequest, timeout_s: float
) -> SynthesizedAudio:
    try:
        async with asyncio.timeout(timeout_s):
            return await provider.synthesize(request)
    except TimeoutError as exc:
        raise SpeechProviderTimeoutError(
            "text-to-speech provider exceeded the request timeout"
        ) from exc


async def _validate_generated(
    store: SessionContentStore,
    session: SessionConfig,
    synthesized: SynthesizedAudio,
    limits: AudioLimits,
) -> tuple[bytes, AudioAnalysis]:
    try:
        wav = store.read(session.session_id, synthesized.audio_ref)
        analysis = await _bounded(lambda: analyze_wav(wav, synthesized.media_type, limits), limits)
    except AudioProcessingTimeoutError:
        raise
    except (IngestionError, ContentNotFoundError) as exc:
        raise SpeechProviderOutputError(
            "text-to-speech provider returned audio that failed validation"
        ) from exc
    if abs(analysis.duration_ms - synthesized.duration_ms) > _DURATION_TOLERANCE_MS:
        raise SpeechProviderOutputError(
            "text-to-speech provider misreported the generated audio duration"
        )
    return wav, analysis


def _evidence(
    record_id: str,
    operation: SpeechOperation,
    evidence_class: EvidenceClass,
    summary: str,
    live: bool = False,
    calls: tuple[LiveCall, ...] = (),
) -> EvidenceRecord:
    if live:
        return live_evidence(
            evidence_id=f"ev-9-8-{record_id}",
            requested=evidence_class,
            calls=calls,
            requirement_ids=_REQUIREMENTS[operation],
            summary=summary,
        )
    return EvidenceRecord(
        evidence_id=f"ev-9-4-{record_id}",
        evidence_class=evidence_class,
        story="9.4",
        requirement_ids=_REQUIREMENTS[operation],
        summary=summary[:1000],
        runtime_executed=True,
        live_provider_executed=False,
        execution_mode=ExecutionMode.DETERMINISTIC,
    )
