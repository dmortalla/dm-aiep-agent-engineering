"""Builders for Story 9.6 voice-assistant tests. Every input is generated in-process or committed.

Committed conversation fixtures exercise the default, reviewer-facing path (fixture-playback STT,
rule-based reasoning, tone-sequence TTS). Provider-contract test doubles let tests script any
transcript, reasoning output, or synthesized audio, and inject failures at a precise stage.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from audio_builders import sine_wav

from multimodal_voice_platform.adapters.deterministic import FixtureCatalog
from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    ReasoningChunk,
    ReasoningRequest,
    SpeechSynthesisRequest,
    SynthesizedAudio,
    TranscriptionRequest,
    TranscriptSegment,
)
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.crossmodal import ReasoningBinding, ReasoningKind
from multimodal_voice_platform.speech import (
    SpeechProcessingKind,
    SpeechService,
    SpeechToTextBinding,
    TextToSpeechBinding,
)
from multimodal_voice_platform.voice import (
    VoiceAssistant,
    VoiceLimits,
    VoiceTurnRecord,
    VoiceTurnRequest,
    load_voice_catalog,
)

TEST = EvidenceClass.AUTOMATED_TEST
DOUBLE = SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
CATALOG: FixtureCatalog = load_voice_catalog()
TONE_WAV = sine_wav(440.0, 300)
"""300 ms, 16 kHz, 16-bit mono 440 Hz sine tone: valid audio for any scripted transcript."""
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
REASONER_DOUBLE = ProviderDescriptor(
    provider_id="test-double-reasoner",
    port=ProviderPort.REASONING,
    mode=ExecutionMode.DETERMINISTIC,
)


def session(session_id: str = "sess-voice", **options: Any) -> SessionConfig:
    """Return an application-owned deterministic session configuration."""
    return SessionConfig(session_id=session_id, **options)


def assistant(**options: Any) -> VoiceAssistant:
    """Return an assistant over the committed voice catalog."""
    options.setdefault("catalog", CATALOG)
    return VoiceAssistant(**options)


def started(
    session_config: SessionConfig | None = None, **options: Any
) -> tuple[VoiceAssistant, SessionConfig]:
    """Return an assistant with one open conversation, and its configuration."""
    config = session_config or session()
    voice = assistant(**options)
    voice.start_session(config)
    return voice, config


def request(
    turn_id: str,
    data: bytes = TONE_WAV,
    *,
    session_id: str = "sess-voice",
    media_type: str = "audio/wav",
    name: str = "turn.wav",
) -> VoiceTurnRequest:
    """Return a spoken-turn request."""
    return VoiceTurnRequest(
        session_id=session_id,
        turn_id=turn_id,
        media_type=media_type,
        display_name=name,
        data=data,
    )


def turn(
    voice: VoiceAssistant, turn_id: str, data: bytes = TONE_WAV, **options: Any
) -> VoiceTurnRecord:
    """Run one uploaded turn as automated_test evidence."""
    session_id = options.pop("session_id", "sess-voice")
    evidence = options.pop("evidence_class", TEST)
    item = request(turn_id, data, session_id=session_id, **options)
    return asyncio.run(voice.run_turn(item, evidence_class=evidence))


def fixture_turn(
    voice: VoiceAssistant, turn_id: str, fixture_id: str, session_id: str = "sess-voice"
) -> VoiceTurnRecord:
    """Run one committed fixture turn as automated_test evidence."""
    return asyncio.run(voice.run_fixture_turn(session_id, turn_id, fixture_id, evidence_class=TEST))


class ScriptedSpeechToText:
    """Speech-to-text test double that 'hears' the next scripted transcript on every call."""

    def __init__(self, transcripts: list[str]) -> None:
        self.transcripts = list(transcripts)
        self.calls = 0

    @property
    def descriptor(self) -> ProviderDescriptor:
        return STT_DOUBLE

    async def transcribe(self, request: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
        self.calls += 1
        text = self.transcripts.pop(0)
        end = request.audio.duration_ms or 1
        yield TranscriptSegment(
            provider=STT_DOUBLE, text=text, is_final=True, start_ms=0, end_ms=end
        )


def heard(*transcripts: str, **service_options: Any) -> tuple[SpeechService, ScriptedSpeechToText]:
    """Return a speech service whose STT double hears the transcripts in order."""
    double = ScriptedSpeechToText(list(transcripts))
    service = SpeechService(
        CATALOG,
        speech_to_text=SpeechToTextBinding(lambda _: double, DOUBLE),
        **service_options,
    )
    return service, double


def talking(
    *transcripts: str,
    text_to_speech: TextToSpeechBinding | None = None,
    session_config: SessionConfig | None = None,
    **options: Any,
) -> tuple[VoiceAssistant, SessionConfig]:
    """Return a started assistant whose STT double hears the transcripts in order."""
    extra = {"text_to_speech": text_to_speech} if text_to_speech is not None else {}
    service, _ = heard(*transcripts, **extra)
    return started(session_config, speech=service, **options)


class ScriptedTextToSpeech:
    """Text-to-speech test double whose behavior is supplied per test."""

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


def tts_binding(
    behavior: Callable[[SessionContentStore, SpeechSynthesisRequest], Any],
) -> TextToSpeechBinding:
    """Return a text-to-speech binding over a scripted double."""

    def factory(store: SessionContentStore, _: AudioLimits) -> ScriptedTextToSpeech:
        return ScriptedTextToSpeech(store, behavior)

    return TextToSpeechBinding(factory, DOUBLE)


def stored_audio(
    data: bytes, *, duration_ms: int, media_type: str = "audio/wav"
) -> Callable[[SessionContentStore, SpeechSynthesisRequest], Any]:
    """Return a TTS behavior that stores fixed bytes and reports them as generated audio."""

    async def behavior(store: SessionContentStore, request: SpeechSynthesisRequest) -> Any:
        ref = store.put(request.session_id, "generated", data)
        return SynthesizedAudio(
            provider=TTS_DOUBLE, audio_ref=ref, media_type=media_type, duration_ms=duration_ms
        )

    return behavior


class ScriptedReasoner:
    """Reasoning-port test double that streams a fixed script or misbehaves on purpose."""

    def __init__(
        self,
        script: Callable[[ReasoningRequest], AsyncIterator[Any]],
        descriptor: ProviderDescriptor = REASONER_DOUBLE,
    ) -> None:
        self.script = script
        self._descriptor = descriptor
        self.requests: list[ReasoningRequest] = []

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def stream_reason(self, request: ReasoningRequest) -> AsyncIterator[Any]:
        self.requests.append(request)
        return self.script(request)


def reasoning_double(
    script: Callable[[ReasoningRequest], AsyncIterator[Any]],
    descriptor: ProviderDescriptor = REASONER_DOUBLE,
) -> tuple[ReasoningBinding, ScriptedReasoner]:
    """Return a reasoning binding over a scripted double, and the double."""
    double = ScriptedReasoner(script, descriptor)
    binding = ReasoningBinding(
        factory=lambda: double, processing=ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
    )
    return binding, double


def streams(document: str, *, final: bool = True) -> Callable[..., AsyncIterator[Any]]:
    """Return a reasoning script that streams one document as a single chunk."""

    async def script(_: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        yield ReasoningChunk(provider=REASONER_DOUBLE, text=document, is_final=final)

    return script


def small_limits(**overrides: Any) -> VoiceLimits:
    """Return tight voice limits for bound tests."""
    values: dict[str, Any] = {"max_retained_turns": 2, "max_context_turns": 2}
    values.update(overrides)
    return VoiceLimits(**values)
