"""Story 9.4 speech pipeline tests: transcription, synthesis, provider failures, and records."""

import asyncio
import io
import json
import wave
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from audio_builders import sine_wav
from pydantic import ValidationError

from multimodal_voice_platform.adapters.deterministic import FixtureCatalog, SessionContentStore
from multimodal_voice_platform.adapters.speech import (
    TONE_TTS_ID,
    SynthesisLimitError,
    ToneSequenceSynthesizer,
    plan_segments,
    planned_duration_ms,
    render_wav,
)
from multimodal_voice_platform.audio import AudioLimits, PcmEncoding, SignalContent
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import InputSource, Modality, TrustLevel
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    SpeechSynthesisRequest,
    SynthesizedAudio,
    TranscriptionRequest,
    TranscriptSegment,
)
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.speech import (
    LOCAL_AUDIO_PROCESSING,
    MAX_TRANSCRIPT_SEGMENTS,
    SpeechConfigurationError,
    SpeechOperation,
    SpeechProcessingKind,
    SpeechProviderUnavailableError,
    SpeechRecord,
    SpeechService,
    SpeechStage,
    SpeechStatus,
    SpeechToTextBinding,
    TextToSpeechBinding,
)

SESSION = SessionConfig(session_id="sess-speech")
TEST = EvidenceClass.AUTOMATED_TEST
TONE = sine_wav(440.0, 300)
DOUBLE = SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
STT_DOUBLE = ProviderDescriptor(
    provider_id="test-double-stt",
    port=ProviderPort.SPEECH_TO_TEXT,
    mode=ExecutionMode.DETERMINISTIC,
)
TTS_DOUBLE = ProviderDescriptor(
    provider_id="test-double-tts",
    port=ProviderPort.TEXT_TO_SPEECH,
    mode=ExecutionMode.DETERMINISTIC,
)


def _run(coro: Any) -> SpeechRecord:
    return asyncio.run(coro)


def _segment(text: str, *, final: bool, start: int = 0, end: int = 100, **extra: Any):
    fields = {"provider": STT_DOUBLE, "text": text, "is_final": final, "start_ms": start}
    fields.update({"end_ms": end, **extra})
    return TranscriptSegment(**fields)


class ScriptedSpeechToText:
    """Provider-contract test double that streams a fixed script or misbehaves on purpose."""

    def __init__(self, script: Callable[[TranscriptionRequest], AsyncIterator[Any]]) -> None:
        self.script = script
        self.requests: list[TranscriptionRequest] = []

    @property
    def descriptor(self) -> ProviderDescriptor:
        return STT_DOUBLE

    def transcribe(self, request: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
        self.requests.append(request)
        return self.script(request)


def _stt_service(script: Callable[[TranscriptionRequest], AsyncIterator[Any]]) -> SpeechService:
    double = ScriptedSpeechToText(script)
    return SpeechService(speech_to_text=SpeechToTextBinding(lambda _: double, DOUBLE))


async def _hello(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    yield _segment("hello", final=False, end=150)
    yield _segment("hello world", final=True, end=300)


def _transcribe(service: SpeechService, **overrides: Any) -> SpeechRecord:
    fields: dict[str, Any] = {
        "media_type": "audio/wav",
        "display_name": "tone.wav",
        "data": TONE,
        "evidence_class": TEST,
    }
    fields.update(overrides)
    session = fields.pop("session", SESSION)
    return _run(service.transcribe_upload(session, **fields))


def test_fixture_transcription_runs_real_audio_processing_then_fixture_playback() -> None:
    record = _run(SpeechService().transcribe_fixture(SESSION, "audio-tone", evidence_class=TEST))
    assert record.status is SpeechStatus.SUCCEEDED
    assert record.operation is SpeechOperation.TRANSCRIPTION
    assert record.processing == (*LOCAL_AUDIO_PROCESSING, SpeechProcessingKind.FIXTURE_PLAYBACK)
    assert (
        record.provider is not None and record.provider.provider_id == "deterministic-fixture-stt"
    )
    assert record.input is not None and record.input.source is InputSource.DETERMINISTIC_FIXTURE
    assert record.audio is not None and record.audio.encoding is PcmEncoding.PCM_U8
    assert record.audio.zero_crossing_rate_per_s == pytest.approx(798)
    transcript = record.transcript
    assert transcript is not None
    assert [segment.is_final for segment in transcript.segments] == [False, True]
    assert "No speech-to-text model ran." in transcript.text
    assert transcript.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    assert all(s.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT for s in transcript.segments)
    assert record.speech_recognition_performed is False
    assert record.model_inference_performed is False
    assert record.live_provider_called is False
    assert [t.stage for t in record.timings] == [
        SpeechStage.INGESTION,
        SpeechStage.AUDIO_PROCESSING,
        SpeechStage.SPEECH_TO_TEXT,
    ]
    assert record.evidence.story == "9.4"
    assert record.evidence.requirement_ids == ("SRC-003", "SRC-006", "ENG-006")
    assert "not speech recognition" in record.evidence.summary
    json.loads(record.model_dump_json())


def test_non_fixture_audio_is_processed_but_fixture_stt_rejects_it_honestly() -> None:
    record = _transcribe(SpeechService())
    assert record.status is SpeechStatus.REJECTED
    assert record.failed_stage is SpeechStage.SPEECH_TO_TEXT
    assert record.error is not None and record.error.code is ErrorCode.INPUT_REJECTED
    assert record.processing == LOCAL_AUDIO_PROCESSING
    assert record.audio is not None and record.audio.duration_ms == 300
    assert record.transcript is None
    assert record.provider_processing is SpeechProcessingKind.FIXTURE_PLAYBACK


def test_audio_analysis_reports_real_properties_without_any_speech_provider() -> None:
    record = _run(
        SpeechService().analyze_audio_upload(
            SESSION, media_type="audio/wav", display_name="t.wav", data=TONE, evidence_class=TEST
        )
    )
    assert record.status is SpeechStatus.SUCCEEDED
    assert record.provider is None and record.provider_processing is None
    assert record.processing == LOCAL_AUDIO_PROCESSING
    assert record.audio is not None and record.audio.content is SignalContent.SIGNAL
    assert record.audio.zero_crossing_rate_per_s == pytest.approx(880, rel=0.01)
    assert record.evidence.requirement_ids == ("SRC-003", "ENG-006")
    assert "no speech recognition" in record.evidence.summary


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"data": TONE[:-50]}, ErrorCode.INPUT_REJECTED),
        (
            {"data": b"ID3" + bytes(64), "media_type": "audio/mpeg", "display_name": "a.mp3"},
            ErrorCode.UNSUPPORTED_MODALITY,
        ),
        ({"data": b"not audio"}, ErrorCode.INPUT_REJECTED),
        ({"display_name": "../../etc/passwd.wav"}, ErrorCode.INPUT_REJECTED),
        (
            {
                "session": SessionConfig(
                    session_id="s", budget=ResourceBudget(max_audio_duration_ms=100)
                )
            },
            ErrorCode.LIMIT_EXCEEDED,
        ),
        (
            {"session": SessionConfig(session_id="s", budget=ResourceBudget(max_audio_bytes=1000))},
            ErrorCode.LIMIT_EXCEEDED,
        ),
        ({"language": "english; rm -rf /"}, ErrorCode.INPUT_REJECTED),
    ],
)
def test_invalid_audio_uploads_become_safe_ingestion_rejections(
    overrides: dict[str, Any], code: ErrorCode
) -> None:
    record = _transcribe(SpeechService(), **overrides)
    assert record.status is SpeechStatus.REJECTED
    assert record.failed_stage is SpeechStage.INGESTION
    assert record.error is not None and record.error.code is code
    assert record.error.retryable is False
    assert record.input is None and record.audio is None and record.processing == ()


def test_live_sessions_are_refused_for_every_operation() -> None:
    from multimodal_voice_platform.contracts.session import LiveCredential

    live = SessionConfig(
        session_id="sess-live",
        mode=ExecutionMode.LIVE,
        live_opt_in=True,
        credential=LiveCredential(provider_id="vendor", api_key="sk-test-secret-value"),
        allowed_live_providers=frozenset({"vendor"}),
    )
    service = SpeechService()
    records = [
        _transcribe(service, session=live),
        _run(
            service.analyze_audio_upload(
                live, media_type="audio/wav", display_name="a.wav", data=TONE
            )
        ),
        _run(service.synthesize_text(live, "hello")),
    ]
    for record in records:
        assert record.status is SpeechStatus.REJECTED
        assert record.error is not None
        assert record.error.code is ErrorCode.LIVE_MODE_NOT_AUTHORIZED
        assert record.evidence.execution_mode is ExecutionMode.DETERMINISTIC
        assert "sk-test-secret-value" not in record.model_dump_json()


def test_contract_double_transcript_flows_through_the_pipeline_with_language() -> None:
    record = _transcribe(_stt_service(_hello), language="en-US")
    assert record.status is SpeechStatus.SUCCEEDED
    assert record.transcript is not None and record.transcript.text == "hello world"
    assert record.transcript.language == "en-US"
    assert record.processing == (*LOCAL_AUDIO_PROCESSING, DOUBLE)
    assert "contract test double" in record.evidence.summary


def test_transcription_is_reproducible() -> None:
    first = _run(SpeechService().transcribe_fixture(SESSION, "audio-tone", evidence_class=TEST))
    second = _run(SpeechService().transcribe_fixture(SESSION, "audio-tone", evidence_class=TEST))
    assert first.transcript == second.transcript
    assert first.audio == second.audio
    assert first.input == second.input


async def _unavailable(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    raise SpeechProviderUnavailableError("speech-to-text provider is unavailable")
    yield  # pragma: no cover


async def _hangs(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    await asyncio.sleep(30)
    yield _segment("late", final=True)  # pragma: no cover


async def _endless(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    while True:
        yield _segment("again", final=False)


async def _foreign(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    other = STT_DOUBLE.model_copy(update={"provider_id": "someone-else"})
    yield _segment("spoofed", final=True, provider=other)


async def _beyond(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    yield _segment("too long", final=True, end=99_999)


async def _unordered(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    yield _segment("b", final=False, start=200, end=250)
    yield _segment("a", final=True, start=0, end=300)


async def _no_final(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    yield _segment("partial", final=False)


async def _silent(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
    return
    yield  # pragma: no cover


async def _not_a_segment(_: TranscriptionRequest) -> AsyncIterator[Any]:
    yield {"text": "raw provider payload", "is_final": True}


@pytest.mark.parametrize(
    ("script", "code", "retryable"),
    [
        (_unavailable, ErrorCode.PROVIDER_UNAVAILABLE, True),
        (_hangs, ErrorCode.PROVIDER_TIMEOUT, True),
        (_endless, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (_foreign, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (_beyond, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (_unordered, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (_no_final, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (_silent, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (_not_a_segment, ErrorCode.PROVIDER_UNAVAILABLE, False),
    ],
)
def test_provider_failures_and_contract_violations_become_safe_failed_records(
    script: Callable[[TranscriptionRequest], AsyncIterator[Any]], code: ErrorCode, retryable: bool
) -> None:
    fast = SessionConfig(session_id="sess-fast", budget=ResourceBudget(request_timeout_s=0.2))
    record = _transcribe(_stt_service(script), session=fast)
    assert record.status is SpeechStatus.FAILED
    assert record.failed_stage is SpeechStage.SPEECH_TO_TEXT
    assert record.error is not None
    assert (record.error.code, record.error.retryable) == (code, retryable)
    assert record.transcript is None
    assert record.audio is not None
    assert "raw provider payload" not in record.model_dump_json()


def test_endless_streams_are_cut_off_at_the_segment_limit() -> None:
    pulled: list[int] = []

    async def counting(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
        while True:
            pulled.append(1)
            yield _segment("again", final=False)

    record = _transcribe(_stt_service(counting))
    assert record.status is SpeechStatus.FAILED
    assert len(pulled) == MAX_TRANSCRIPT_SEGMENTS + 1


def test_unexpected_provider_exceptions_are_defects_not_swallowed() -> None:
    async def broken(_: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
        raise RuntimeError("adapter bug")
        yield  # pragma: no cover

    with pytest.raises(RuntimeError, match="adapter bug"):
        _transcribe(_stt_service(broken))


def test_content_is_released_after_every_run() -> None:
    stores: list[SessionContentStore] = []
    catalog = FixtureCatalog.load_default()

    def factory(store: SessionContentStore) -> Any:
        from multimodal_voice_platform.adapters.deterministic import (
            DeterministicSpeechToTextProvider,
        )

        stores.append(store)
        return DeterministicSpeechToTextProvider(catalog, store)

    binding = SpeechToTextBinding(factory, SpeechProcessingKind.FIXTURE_PLAYBACK)
    service = SpeechService(catalog, speech_to_text=binding)
    _run(service.transcribe_fixture(SESSION, "audio-tone", evidence_class=TEST))
    _transcribe(service)
    assert len(stores) == 2
    assert all(store.reference_count(SESSION.session_id) == 0 for store in stores)


def test_non_audio_fixtures_are_rejected_as_unsupported() -> None:
    record = _run(
        SpeechService().transcribe_fixture(SESSION, "image-quadrants", evidence_class=TEST)
    )
    assert record.status is SpeechStatus.REJECTED
    assert record.error is not None and record.error.code is ErrorCode.UNSUPPORTED_MODALITY


@pytest.mark.parametrize(
    "build",
    [
        lambda: SpeechToTextBinding(lambda _: None, SpeechProcessingKind.SPEECH_RECOGNITION),  # type: ignore[arg-type,return-value]
        lambda: SpeechToTextBinding(
            lambda _: None, SpeechProcessingKind.DETERMINISTIC_TONE_SYNTHESIS
        ),  # type: ignore[arg-type,return-value]
        lambda: TextToSpeechBinding(lambda *_: None, SpeechProcessingKind.SPEECH_SYNTHESIS),  # type: ignore[arg-type,return-value]
        lambda: TextToSpeechBinding(lambda *_: None, SpeechProcessingKind.FIXTURE_PLAYBACK),  # type: ignore[arg-type,return-value]
    ],
)
def test_bindings_cannot_claim_genuine_or_mismatched_speech_processing(
    build: Callable[[], object],
) -> None:
    with pytest.raises(SpeechConfigurationError):
        build()


def test_wiring_and_evidence_misuse_is_raised_not_recorded() -> None:
    with pytest.raises(SpeechConfigurationError):
        _transcribe(SpeechService(), evidence_class=EvidenceClass.LIVE_INTEGRATION)
    with pytest.raises(SpeechConfigurationError, match="automated_test"):
        _transcribe(_stt_service(_hello), evidence_class=EvidenceClass.DETERMINISTIC_DEMO)

    class LiveDouble(ScriptedSpeechToText):
        @property
        def descriptor(self) -> ProviderDescriptor:
            return STT_DOUBLE.model_copy(update={"mode": ExecutionMode.LIVE})

    live_double = LiveDouble(_hello)
    service = SpeechService(speech_to_text=SpeechToTextBinding(lambda _: live_double, DOUBLE))
    with pytest.raises(SpeechConfigurationError, match="deterministic"):
        _transcribe(service)
    assert live_double.requests == []


# Synthesis


def _wav_params(data: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as reader:
        return (
            reader.getnchannels(),
            reader.getsampwidth(),
            reader.getframerate(),
            reader.getnframes(),
        )


def test_default_synthesis_generates_valid_reproducible_tone_audio() -> None:
    text = "Hello, world 42."
    record = _run(SpeechService().synthesize_text(SESSION, text, evidence_class=TEST))
    assert record.status is SpeechStatus.SUCCEEDED
    assert record.processing == (
        SpeechProcessingKind.DETERMINISTIC_TONE_SYNTHESIS,
        *LOCAL_AUDIO_PROCESSING,
    )
    assert record.input is not None and record.input.modality is Modality.TEXT
    assert record.input.source is InputSource.USER_TEXT and record.input.text == text
    synthesis = record.synthesis
    assert synthesis is not None
    assert synthesis.audio.provider.provider_id == TONE_TTS_ID
    assert synthesis.audio.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    expected_ms = planned_duration_ms(plan_segments(text))
    assert synthesis.audio.duration_ms == expected_ms
    assert record.audio is not None and record.audio.duration_ms == expected_ms
    assert record.audio.encoding is PcmEncoding.PCM_S16LE
    assert record.audio.content is SignalContent.SIGNAL
    assert _wav_params(synthesis.wav_bytes) == (1, 2, 16000, expected_ms * 16)
    assert record.speech_synthesis_performed is False
    assert "not synthesized speech" in record.evidence.summary
    assert record.evidence.requirement_ids == ("SRC-007", "ENG-006")
    again = _run(SpeechService().synthesize_text(SESSION, text, evidence_class=TEST))
    assert again.synthesis is not None
    assert again.synthesis.audio_sha256 == synthesis.audio_sha256
    other = _run(SpeechService().synthesize_text(SESSION, "Different words", evidence_class=TEST))
    assert other.synthesis is not None and other.synthesis.audio_sha256 != synthesis.audio_sha256


def test_serialized_synthesis_records_carry_a_digest_not_the_audio_bytes() -> None:
    record = _run(SpeechService().synthesize_text(SESSION, "hello", evidence_class=TEST))
    assert record.synthesis is not None
    payload = json.loads(record.model_dump_json())
    assert "wav_bytes" not in payload["synthesis"]
    assert payload["synthesis"]["audio_sha256"] == record.synthesis.audio_sha256
    assert "wav_bytes" not in repr(record.synthesis)


@pytest.mark.parametrize(
    ("text", "voice", "stage", "code"),
    [
        ("   \n\t ", None, SpeechStage.INGESTION, ErrorCode.INPUT_REJECTED),
        ("bell\x07", None, SpeechStage.INGESTION, ErrorCode.INPUT_REJECTED),
        ("esc\x1b[31m", None, SpeechStage.INGESTION, ErrorCode.INPUT_REJECTED),
        ("lone \ud800 surrogate", None, SpeechStage.INGESTION, ErrorCode.INPUT_REJECTED),
        ("x" * 20_001, None, SpeechStage.INGESTION, ErrorCode.LIMIT_EXCEEDED),
        ("hello", "Not A Voice", SpeechStage.INGESTION, ErrorCode.INPUT_REJECTED),
        ("hello", "neural-voice", SpeechStage.TEXT_TO_SPEECH, ErrorCode.INPUT_REJECTED),
        ("a" * 3_000, None, SpeechStage.TEXT_TO_SPEECH, ErrorCode.LIMIT_EXCEEDED),
    ],
)
def test_invalid_synthesis_input_is_rejected_safely(
    text: str, voice: str | None, stage: SpeechStage, code: ErrorCode
) -> None:
    record = _run(SpeechService().synthesize_text(SESSION, text, voice=voice, evidence_class=TEST))
    assert record.status is SpeechStatus.REJECTED
    assert record.failed_stage is stage
    assert record.error is not None and record.error.code is code
    assert record.synthesis is None and record.audio is None


class ScriptedTextToSpeech:
    """Provider-contract test double for the text-to-speech port."""

    def __init__(
        self,
        store: SessionContentStore,
        behavior: Callable[[SessionContentStore, SpeechSynthesisRequest], Any],
    ) -> None:
        self.store = store
        self.behavior = behavior

    @property
    def descriptor(self) -> ProviderDescriptor:
        return TTS_DOUBLE

    async def synthesize(self, request: SpeechSynthesisRequest) -> SynthesizedAudio:
        return await self.behavior(self.store, request)


def _tts_service(behavior: Callable[[SessionContentStore, SpeechSynthesisRequest], Any]):
    binding = TextToSpeechBinding(lambda store, _: ScriptedTextToSpeech(store, behavior), DOUBLE)
    return SpeechService(text_to_speech=binding)


def _stored(
    data: bytes, *, duration_ms: int, media_type: str = "audio/wav", provider=TTS_DOUBLE
) -> Callable[[SessionContentStore, SpeechSynthesisRequest], Any]:
    async def behavior(store: SessionContentStore, request: SpeechSynthesisRequest) -> Any:
        ref = store.put(request.session_id, "generated", data)
        return SynthesizedAudio(
            provider=provider, audio_ref=ref, media_type=media_type, duration_ms=duration_ms
        )

    return behavior


async def _tts_unavailable(*_: Any) -> SynthesizedAudio:
    raise SpeechProviderUnavailableError("text-to-speech provider is unavailable")


async def _tts_hangs(*_: Any) -> SynthesizedAudio:
    await asyncio.sleep(30)
    raise AssertionError("unreachable")  # pragma: no cover


async def _tts_dangling(_: SessionContentStore, __: SpeechSynthesisRequest) -> SynthesizedAudio:
    return SynthesizedAudio(
        provider=TTS_DOUBLE, audio_ref="ref-missing", media_type="audio/wav", duration_ms=10
    )


async def _tts_wrong_type(*_: Any) -> Any:
    return {"audio_ref": "ref-x"}


@pytest.mark.parametrize(
    ("behavior", "stage", "code", "retryable"),
    [
        (_stored(TONE, duration_ms=300), None, None, None),
        (_tts_unavailable, SpeechStage.TEXT_TO_SPEECH, ErrorCode.PROVIDER_UNAVAILABLE, True),
        (_tts_hangs, SpeechStage.TEXT_TO_SPEECH, ErrorCode.PROVIDER_TIMEOUT, True),
        (_tts_wrong_type, SpeechStage.TEXT_TO_SPEECH, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (
            _stored(
                TONE, duration_ms=300, provider=TTS_DOUBLE.model_copy(update={"provider_id": "x"})
            ),
            SpeechStage.TEXT_TO_SPEECH,
            ErrorCode.PROVIDER_UNAVAILABLE,
            False,
        ),
        (_tts_dangling, SpeechStage.OUTPUT_VALIDATION, ErrorCode.PROVIDER_UNAVAILABLE, False),
        (
            _stored(TONE, duration_ms=900),
            SpeechStage.OUTPUT_VALIDATION,
            ErrorCode.PROVIDER_UNAVAILABLE,
            False,
        ),
        (
            _stored(TONE[:-40], duration_ms=300),
            SpeechStage.OUTPUT_VALIDATION,
            ErrorCode.PROVIDER_UNAVAILABLE,
            False,
        ),
        (
            _stored(b"ID3" + bytes(64), duration_ms=300, media_type="audio/mpeg"),
            SpeechStage.OUTPUT_VALIDATION,
            ErrorCode.PROVIDER_UNAVAILABLE,
            False,
        ),
    ],
)
def test_generated_audio_is_validated_before_it_is_recorded(
    behavior: Any, stage: SpeechStage | None, code: ErrorCode | None, retryable: bool | None
) -> None:
    fast = SessionConfig(session_id="sess-tts", budget=ResourceBudget(request_timeout_s=0.2))
    record = _run(_tts_service(behavior).synthesize_text(fast, "hello", evidence_class=TEST))
    if stage is None:
        assert record.status is SpeechStatus.SUCCEEDED
        assert record.processing == (DOUBLE, *LOCAL_AUDIO_PROCESSING)
        return
    assert record.status is SpeechStatus.FAILED
    assert record.failed_stage is stage
    assert record.error is not None
    assert (record.error.code, record.error.retryable) == (code, retryable)
    assert record.synthesis is None and record.audio is None


def test_tone_synthesizer_conforms_to_the_port_and_its_budgets() -> None:
    store = SessionContentStore()
    limits = AudioLimits(max_audio_bytes=1_000_000, max_audio_duration_ms=2_000, timeout_s=5)
    synthesizer = ToneSequenceSynthesizer(store, limits)
    assert synthesizer.descriptor.port is ProviderPort.TEXT_TO_SPEECH
    assert synthesizer.descriptor.mode is ExecutionMode.DETERMINISTIC
    request = SpeechSynthesisRequest(session_id="sess-tone", text="ab c!")
    audio = asyncio.run(synthesizer.synthesize(request))
    assert audio.duration_ms == 50 + 60 + 60 + 40 + 60 + 90 + 50
    data = store.read("sess-tone", audio.audio_ref)
    assert data == render_wav(plan_segments("ab c!"))
    too_long = SpeechSynthesisRequest(session_id="sess-tone", text="a" * 40)
    with pytest.raises(SynthesisLimitError):
        asyncio.run(synthesizer.synthesize(too_long))
    tiny = ToneSequenceSynthesizer(store, limits.model_copy(update={"max_audio_bytes": 100}))
    with pytest.raises(SynthesisLimitError, match="byte budget"):
        asyncio.run(tiny.synthesize(request))


# Record honesty


def _succeeded(**overrides: Any) -> dict[str, Any]:
    record = _run(SpeechService().transcribe_fixture(SESSION, "audio-tone", evidence_class=TEST))
    fields = {name: getattr(record, name) for name in SpeechRecord.model_fields}
    fields.update(overrides)
    return fields


def _evidence(**overrides: Any) -> EvidenceRecord:
    base = _succeeded()["evidence"]
    return base.model_copy(update=overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"speech_recognition_performed": True},
        {"live_provider_called": True},
        {"model_inference_performed": True},
        {"processing": (*LOCAL_AUDIO_PROCESSING, SpeechProcessingKind.SPEECH_RECOGNITION)},
        {"provider_processing": SpeechProcessingKind.SPEECH_RECOGNITION},
        {"processing": LOCAL_AUDIO_PROCESSING},
        {"transcript": None},
        {"audio": None},
        {"provider": None},
        {"operation": SpeechOperation.SYNTHESIS},
        {"evidence": _evidence(story="9.3")},
        {
            "evidence": _evidence(
                evidence_class=EvidenceClass.DESIGN_DOCUMENTATION,
                runtime_executed=False,
                execution_mode=None,
            )
        },
        {"status": SpeechStatus.FAILED},
    ],
)
def test_records_reject_claims_beyond_what_ran(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SpeechRecord(**_succeeded(**overrides))
