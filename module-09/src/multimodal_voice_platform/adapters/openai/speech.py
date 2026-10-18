"""OpenAI speech adapters behind the speech-to-text and text-to-speech ports (Story 9.8).

Speech-to-text: the audio has already passed Module 9 ingestion and local PCM decoding and
measurement. The adapter sends the validated bytes to the audio transcriptions API and returns one
final ``TranscriptSegment``. The transcript is untrusted output. No partial transcript is produced.

Text-to-speech: the bounded reply text is sent to the audio speech API with ``pcm`` output, which
the provider documents as 24 kHz, 16-bit, mono, little-endian samples with no header. The adapter
wraps the samples in a WAV header it writes itself and stores them; the Story 9.4 output-audio
validation then decodes and measures that WAV locally before anything is accepted. Provider media
metadata is never trusted on its own.
"""

import asyncio
import math
import struct
import time
from collections.abc import AsyncIterator
from typing import Final

import httpx2
from pydantic import SecretStr, ValidationError

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.deterministic.errors import ContentNotFoundError
from multimodal_voice_platform.adapters.openai.client import (
    OpenAIAdapter,
    usage_from,
)
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.contracts.limits import MAX_TRANSCRIPT_CHARS
from multimodal_voice_platform.contracts.live import LiveCapability
from multimodal_voice_platform.contracts.providers import (
    ProviderPort,
    SpeechSynthesisRequest,
    SynthesizedAudio,
    TranscriptionRequest,
    TranscriptSegment,
)
from multimodal_voice_platform.live.config import LiveProviderConfig
from multimodal_voice_platform.live.errors import LiveBudgetError, ProviderOutputError

PCM_SAMPLE_RATE_HZ: Final = 24_000
PCM_SAMPLE_BYTES: Final = 2
PCM_CHANNELS: Final = 1
WAV_MEDIA_TYPE: Final = "audio/wav"


def pcm16_wav(samples: bytes, sample_rate_hz: int = PCM_SAMPLE_RATE_HZ) -> bytes:
    """Wrap 16-bit mono little-endian PCM samples in a canonical WAV header.

    Args:
        samples: Raw PCM sample bytes.
        sample_rate_hz: Sample rate.

    Returns:
        A complete RIFF/WAVE file.
    """
    block = PCM_CHANNELS * PCM_SAMPLE_BYTES
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(samples),
        b"WAVE",
        b"fmt ",
        16,
        1,
        PCM_CHANNELS,
        sample_rate_hz,
        sample_rate_hz * block,
        block,
        PCM_SAMPLE_BYTES * 8,
        b"data",
        len(samples),
    )
    return header + samples


class OpenAISpeechToText(OpenAIAdapter):
    """Model-backed speech recognition through the audio transcriptions API."""

    capability = LiveCapability.SPEECH_TO_TEXT
    port = ProviderPort.SPEECH_TO_TEXT

    def __init__(
        self,
        credential: SecretStr,
        store: SessionContentStore,
        config: LiveProviderConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the adapter for one operation.

        Args:
            credential: The live session's key.
            store: The run's content store holding the validated audio.
            config: Live configuration.
            transport: Trusted test transport; makes the adapter a contract test double.
        """
        super().__init__(credential, config, transport=transport)
        self._store = store

    async def transcribe(self, request: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
        """Transcribe one validated audio input.

        Args:
            request: Transcription request for a validated audio input.

        Yields:
            Exactly one final segment spanning the audio.

        Raises:
            LiveProviderError: A sanitized provider, budget, or output failure.
        """
        audio = request.audio
        if audio.content_ref is None:
            raise ProviderOutputError("the audio has no stored content to send")
        try:
            data = self._store.read(audio.session_id, audio.content_ref)
        except ContentNotFoundError as exc:
            raise ProviderOutputError("the audio content is no longer available") from exc
        self._check_budget()
        model = self._config.transcription_model
        language = request.language.split("-")[0] if request.language else None
        options = {"language": language} if language else {}
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._config.max_operation_s), self._client() as client:
                raw = await client.audio.transcriptions.with_raw_response.create(
                    model=model,
                    file=(audio.display_name or "audio.wav", data, audio.media_type),
                    response_format="json",
                    **options,
                )
                transcription = raw.parse()
            text = getattr(transcription, "text", None)
            if not isinstance(text, str) or len(text) > MAX_TRANSCRIPT_CHARS:
                raise ProviderOutputError("the live provider returned a malformed transcript")
            segment = TranscriptSegment(
                provider=self.descriptor,
                text=text.strip(),
                is_final=True,
                start_ms=0,
                end_ms=audio.duration_ms or 0,
            )
        except Exception as exc:  # Translated and recorded; never re-raised raw.
            self._fail(model, started, exc)
        self._record(
            model,
            started,
            request_id=raw.request_id,
            usage=usage_from(getattr(transcription, "usage", None)),
        )
        yield segment


class OpenAITextToSpeech(OpenAIAdapter):
    """Model-backed speech synthesis through the audio speech API."""

    capability = LiveCapability.TEXT_TO_SPEECH
    port = ProviderPort.TEXT_TO_SPEECH

    def __init__(
        self,
        credential: SecretStr,
        store: SessionContentStore,
        limits: AudioLimits,
        config: LiveProviderConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the adapter for one operation.

        Args:
            credential: The live session's key.
            store: The run's content store that receives the generated audio.
            limits: Audio bounds derived from the session budget.
            config: Live configuration.
            transport: Trusted test transport; makes the adapter a contract test double.
        """
        super().__init__(credential, config, transport=transport)
        self._store = store
        self._limits = limits

    async def synthesize(self, request: SpeechSynthesisRequest) -> SynthesizedAudio:
        """Render bounded text as speech audio.

        Args:
            request: Synthesis request with validated text.

        Returns:
            The generated audio, stored by reference; validated by the caller before use.

        Raises:
            LiveProviderError: A sanitized provider, budget, or output failure.
        """
        if len(request.text) > self._config.max_speech_chars:
            raise LiveBudgetError("the text exceeds the live text-to-speech character budget")
        self._check_budget()
        model = self._config.speech_model
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._config.max_operation_s), self._client() as client:
                raw = await client.audio.speech.with_raw_response.create(
                    model=model,
                    voice=self._config.voice,
                    input=request.text,
                    response_format="pcm",
                )
                samples = raw.parse().content
            audio = self._stored(request, samples)
        except Exception as exc:  # Translated and recorded; never re-raised raw.
            self._fail(model, started, exc)
        self._record(model, started, request_id=raw.request_id)
        return audio

    def _stored(self, request: SpeechSynthesisRequest, samples: bytes) -> SynthesizedAudio:
        if not isinstance(samples, bytes) or not samples or len(samples) % PCM_SAMPLE_BYTES:
            raise ProviderOutputError("the live provider returned audio that is not 16-bit PCM")
        wav = pcm16_wav(samples)
        if len(wav) > self._limits.max_audio_bytes:
            raise LiveBudgetError("the generated audio exceeds the session byte budget")
        frames = len(samples) // (PCM_SAMPLE_BYTES * PCM_CHANNELS)
        duration_ms = max(1, math.ceil(frames * 1000 / PCM_SAMPLE_RATE_HZ))
        ref = self._store.put(request.session_id, f"live-tts-{len(self.live_calls) + 1}", wav)
        try:
            return SynthesizedAudio(
                provider=self.descriptor,
                audio_ref=ref,
                media_type=WAV_MEDIA_TYPE,
                duration_ms=duration_ms,
            )
        except ValidationError as exc:
            raise ProviderOutputError("the generated audio is outside the duration bound") from exc
