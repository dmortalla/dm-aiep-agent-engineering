"""Audio and speech pipeline service and records (Story 9.4).

Validated audio is decoded and measured locally; transcription and synthesis run through the
accepted ``SpeechToTextPort`` and ``TextToSpeechPort``. In deterministic mode the transcript is
fixture playback and the generated audio is a tone sequence: neither is speech recognition or
speech synthesis, and every record says so.
"""

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
    SpeechOperation,
    SpeechProcessingKind,
    SpeechRecord,
    SpeechStage,
    SpeechStatus,
    SpeechTiming,
    SynthesisResult,
    TranscriptResult,
)
from multimodal_voice_platform.speech.service import (
    SpeechService,
    SpeechToTextBinding,
    TextToSpeechBinding,
)
from multimodal_voice_platform.speech.text_input import stage_text_input

__all__ = [
    "LOCAL_AUDIO_PROCESSING",
    "MAX_TRANSCRIPT_SEGMENTS",
    "LiveSpeechUnavailableError",
    "SpeechConfigurationError",
    "SpeechOperation",
    "SpeechProcessingKind",
    "SpeechProviderOutputError",
    "SpeechProviderTimeoutError",
    "SpeechProviderUnavailableError",
    "SpeechRecord",
    "SpeechService",
    "SpeechStage",
    "SpeechStatus",
    "SpeechTiming",
    "SpeechToTextBinding",
    "SynthesisResult",
    "TextToSpeechBinding",
    "TranscriptResult",
    "stage_text_input",
]
