"""Deterministic speech adapters (Story 9.4).

``ToneSequenceSynthesizer`` implements ``TextToSpeechPort`` with reproducible procedural tone
generation. It is not speech synthesis. Speech-to-text in deterministic mode remains the Story 9.2
fixture-playback adapter (``adapters.deterministic``), which is not speech recognition.
"""

from multimodal_voice_platform.adapters.speech.errors import (
    SynthesisInputError,
    SynthesisLimitError,
)
from multimodal_voice_platform.adapters.speech.tone_synthesis import (
    DEFAULT_VOICE,
    SAMPLE_RATE_HZ,
    SUPPORTED_VOICES,
    TONE_TTS_ID,
    ToneSequenceSynthesizer,
    plan_segments,
    planned_duration_ms,
    render_wav,
)

__all__ = [
    "DEFAULT_VOICE",
    "SAMPLE_RATE_HZ",
    "SUPPORTED_VOICES",
    "TONE_TTS_ID",
    "SynthesisInputError",
    "SynthesisLimitError",
    "ToneSequenceSynthesizer",
    "plan_segments",
    "planned_duration_ms",
    "render_wav",
]
