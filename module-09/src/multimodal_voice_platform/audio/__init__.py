"""Validated, bounded local audio processing (Story 9.4, SRC-003).

Audio ingestion, strict PCM WAV parsing, and signal measurement, all in-process with the Python
standard library. This is audio processing, not speech recognition.
"""

from multimodal_voice_platform.audio.analysis import (
    ANALYSIS_WINDOW_MS,
    AudioAnalysis,
    ChannelLevel,
    SignalContent,
    analyze_wav,
    enforce_audio_limits,
)
from multimodal_voice_platform.audio.errors import (
    AudioProcessingTimeoutError,
    MalformedAudioError,
    UnsupportedAudioError,
)
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.audio.staging import stage_audio_content
from multimodal_voice_platform.audio.wav import (
    DECODABLE_AUDIO_MEDIA_TYPES,
    WAV_MEDIA_TYPE,
    PcmEncoding,
    WavFormatTag,
    WavLayout,
    parse_wav,
    sniff_audio_media_type,
    verify_audio_content,
)

__all__ = [
    "ANALYSIS_WINDOW_MS",
    "DECODABLE_AUDIO_MEDIA_TYPES",
    "WAV_MEDIA_TYPE",
    "AudioAnalysis",
    "AudioLimits",
    "AudioProcessingTimeoutError",
    "ChannelLevel",
    "MalformedAudioError",
    "PcmEncoding",
    "SignalContent",
    "UnsupportedAudioError",
    "WavFormatTag",
    "WavLayout",
    "analyze_wav",
    "enforce_audio_limits",
    "parse_wav",
    "sniff_audio_media_type",
    "stage_audio_content",
    "verify_audio_content",
]
