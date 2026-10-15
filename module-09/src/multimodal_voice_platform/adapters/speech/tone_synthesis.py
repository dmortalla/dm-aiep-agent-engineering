"""Deterministic tone-sequence synthesizer for the text-to-speech port (Story 9.4).

``ToneSequenceSynthesizer`` implements ``TextToSpeechPort`` by rendering text into a reproducible
sequence of sine-tone bursts and pauses, encoded as genuine 16 kHz mono 16-bit PCM WAV with the
standard-library ``wave`` writer. It is procedural signal generation, not speech synthesis: the
output is not intelligible speech, no voice model or neural network runs, and no network or key is
used. It exists so that the text-to-speech boundary, generated-audio validation, and later voice
orchestration can be exercised deterministically with real, valid, text-dependent audio.

Rendering, per character of the text:

- letters and digits: a 60 ms sine burst (5 ms fades) at ``220 + (code point mod 48) * 20`` Hz;
- whitespace: 40 ms of silence;
- anything else (punctuation, symbols): 90 ms of silence;

with 50 ms of silence at each end. Identical text and voice always produce identical bytes.
"""

import asyncio
import hashlib
import io
import math
import sys
import wave
from array import array
from typing import Final

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.speech.errors import (
    SynthesisInputError,
    SynthesisLimitError,
)
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.audio.wav import WAV_MEDIA_TYPE
from multimodal_voice_platform.contracts.limits import MAX_AUDIO_DURATION_MS
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    SpeechSynthesisRequest,
    SynthesizedAudio,
)
from multimodal_voice_platform.contracts.session import ExecutionMode

TONE_TTS_ID: Final = "local-tone-sequence-tts"
DEFAULT_VOICE: Final = "tone-default"
SUPPORTED_VOICES: Final = frozenset({DEFAULT_VOICE})
SAMPLE_RATE_HZ: Final = 16_000
TONE_MS: Final = 60
SPACE_MS: Final = 40
PAUSE_MS: Final = 90
EDGE_MS: Final = 50
FADE_MS: Final = 5
AMPLITUDE: Final = 0.25
BASE_HZ: Final = 220
STEP_HZ: Final = 20
STEPS: Final = 48

_FRAMES_PER_MS: Final = SAMPLE_RATE_HZ // 1000

Segment = tuple[int | None, int]
"""One rendered segment: tone frequency in Hz (``None`` for silence) and duration in ms."""


def plan_segments(text: str) -> tuple[Segment, ...]:
    """Map text to the tone and pause segments that render it.

    Args:
        text: Text to render.

    Returns:
        Segments in order, including the leading and trailing silence.
    """
    segments: list[Segment] = [(None, EDGE_MS)]
    for char in text:
        if char.isalnum():
            segments.append((BASE_HZ + (ord(char) % STEPS) * STEP_HZ, TONE_MS))
        elif char.isspace():
            segments.append((None, SPACE_MS))
        else:
            segments.append((None, PAUSE_MS))
    segments.append((None, EDGE_MS))
    return tuple(segments)


def planned_duration_ms(segments: tuple[Segment, ...]) -> int:
    """Return the total duration of planned segments in milliseconds.

    Args:
        segments: Planned segments.

    Returns:
        The summed duration.
    """
    return sum(duration for _, duration in segments)


def render_wav(segments: tuple[Segment, ...]) -> bytes:
    """Render planned segments as 16 kHz mono 16-bit PCM WAV bytes.

    Args:
        segments: Planned segments.

    Returns:
        The WAV bytes.
    """
    bursts: dict[int, array] = {}
    samples = array("h")
    for frequency, duration in segments:
        frames = duration * _FRAMES_PER_MS
        if frequency is None:
            samples.extend(array("h", bytes(frames * 2)))
            continue
        if frequency not in bursts:
            bursts[frequency] = _burst(frequency, frames)
        samples.extend(bursts[frequency])
    if sys.byteorder == "big":
        samples.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE_HZ)
        writer.writeframes(samples.tobytes())
    return buffer.getvalue()


def _burst(frequency: int, frames: int) -> array:
    fade = FADE_MS * _FRAMES_PER_MS
    peak = AMPLITUDE * 32767
    burst = array("h")
    for n in range(frames):
        envelope = min(1.0, n / fade, (frames - 1 - n) / fade)
        phase = 2 * math.pi * frequency * n / SAMPLE_RATE_HZ
        burst.append(round(peak * envelope * math.sin(phase)))
    return burst


class ToneSequenceSynthesizer:
    """``TextToSpeechPort`` adapter that renders text as a deterministic tone sequence.

    Not speech synthesis: see the module docstring.
    """

    def __init__(self, store: SessionContentStore, limits: AudioLimits) -> None:
        """Create the adapter.

        Args:
            store: Session content store that will hold generated audio by opaque reference.
            limits: Application-owned audio limits applied to generated audio.
        """
        self._store = store
        self._limits = limits
        self._descriptor = ProviderDescriptor(
            provider_id=TONE_TTS_ID,
            port=ProviderPort.TEXT_TO_SPEECH,
            mode=ExecutionMode.DETERMINISTIC,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter: its ID, port, and in-process deterministic execution mode."""
        return self._descriptor

    async def synthesize(self, request: SpeechSynthesisRequest) -> SynthesizedAudio:
        """Render text as a deterministic tone sequence held by opaque reference.

        Args:
            request: Validated synthesis request.

        Returns:
            The generated audio's reference, media type, and duration.

        Raises:
            SynthesisInputError: If the voice is not supported.
            SynthesisLimitError: If the rendered audio would exceed the duration or byte budget.
        """
        voice = request.voice or DEFAULT_VOICE
        if voice not in SUPPORTED_VOICES:
            raise SynthesisInputError("voice is not supported by the tone-sequence synthesizer")
        segments = plan_segments(request.text)
        duration_ms = planned_duration_ms(segments)
        if duration_ms > min(self._limits.max_audio_duration_ms, MAX_AUDIO_DURATION_MS):
            raise SynthesisLimitError("text is too long for the session audio duration budget")
        data = await asyncio.to_thread(render_wav, segments)
        if len(data) > self._limits.max_audio_bytes:
            raise SynthesisLimitError("generated audio exceeds the session byte budget")
        digest = hashlib.sha256(data).hexdigest()
        audio_ref = self._store.put(request.session_id, f"tts-{digest[:16]}", data)
        return SynthesizedAudio(
            provider=self.descriptor,
            audio_ref=audio_ref,
            media_type=WAV_MEDIA_TYPE,
            duration_ms=duration_ms,
        )
