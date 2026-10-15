"""Decode PCM WAV samples and measure bounded signal properties (Story 9.4, SRC-003).

This is genuine local audio processing: the samples are decoded from the actual bytes and measured.
It is not speech recognition. Nothing here detects, classifies, or transcribes speech; the
measurements are signal levels, clipping, silence, and zero crossings.

Sample conversion uses ``array`` and byte slicing so that per-sample work stays in C, apart from
the zero-crossing count. Byte, duration, channel, and sample-rate ceilings (checked from the header
before decoding) bound the total work.
"""

import math
import operator
import sys
from array import array
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.audio.limits import MAX_CHANNELS, AudioLimits
from multimodal_voice_platform.audio.wav import (
    PcmEncoding,
    WavFormatTag,
    WavLayout,
    parse_wav,
    verify_audio_content,
)
from multimodal_voice_platform.ingestion.errors import InputLimitError

ANALYSIS_WINDOW_MS: Final = 20
SILENCE_LEVEL: Final = 0.001
"""Linear RMS level (-60 dBFS) below which a window, or a whole signal's peak, counts as silent."""

_U8_TO_S8: Final = bytes((value - 128) & 0xFF for value in range(256))


class SignalContent(StrEnum):
    """Coarse signal classification from levels alone. Says nothing about speech."""

    SILENT = "silent"
    SIGNAL = "signal"


class ChannelLevel(BaseModel):
    """Measured levels for one channel, normalized to full scale."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: int = Field(ge=0, lt=MAX_CHANNELS)
    peak_level: float = Field(ge=0, le=1)
    rms_level: float = Field(ge=0, le=1)


class AudioAnalysis(BaseModel):
    """Decoded properties and signal measurements of one PCM WAV input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    container: Literal["wav"] = "wav"
    format_tag: WavFormatTag
    encoding: PcmEncoding
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(ge=1, le=MAX_CHANNELS)
    bits_per_sample: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    data_bytes: int = Field(gt=0)
    duration_ms: float = Field(gt=0)
    skipped_chunk_count: int = Field(ge=0)
    peak_level: float = Field(ge=0, le=1)
    peak_dbfs: float | None
    rms_level: float = Field(ge=0, le=1)
    rms_dbfs: float | None
    dc_offset: float = Field(ge=-1, le=1)
    clipped_sample_share: float = Field(ge=0, le=1)
    silent_window_share: float = Field(ge=0, le=1)
    analysis_window_ms: int = ANALYSIS_WINDOW_MS
    zero_crossing_rate_per_s: float = Field(ge=0)
    content: SignalContent
    channel_levels: tuple[ChannelLevel, ...] = Field(min_length=1, max_length=MAX_CHANNELS)


def enforce_audio_limits(layout: WavLayout, size_bytes: int, limits: AudioLimits) -> None:
    """Check byte and duration budgets from the header, before any sample is decoded.

    Args:
        layout: Validated WAV layout.
        size_bytes: Total content size.
        limits: Application-owned audio limits.

    Raises:
        InputLimitError: If the content exceeds the byte or duration budget.
    """
    if size_bytes > limits.max_audio_bytes:
        raise InputLimitError("audio content exceeds the session byte budget")
    if layout.exact_duration_ms > limits.max_audio_duration_ms:
        raise InputLimitError("audio duration exceeds the session duration budget")


def analyze_wav(data: bytes, media_type: str, limits: AudioLimits) -> AudioAnalysis:
    """Validate, decode, and measure in-memory PCM WAV audio.

    Args:
        data: Untrusted audio bytes.
        media_type: Declared media type. Re-verified against the bytes.
        limits: Application-owned audio limits.

    Returns:
        The decoded properties and signal measurements.

    Raises:
        UnsupportedMediaError: If the media type is not decodable audio.
        MediaMismatchError: If the bytes do not match the declared media type.
        MalformedAudioError: If the WAV container is malformed or truncated.
        UnsupportedAudioError: If the WAV encoding or parameters are unsupported.
        InputLimitError: If the audio exceeds the byte or duration budget.
    """
    verify_audio_content(media_type, data)
    layout = parse_wav(data)
    enforce_audio_limits(layout, len(data), limits)
    samples, full_scale = _decode(
        data[layout.data_offset : layout.data_offset + layout.data_bytes], layout.encoding
    )
    return _measure(layout, samples, full_scale)


def _decode(raw: bytes, encoding: PcmEncoding) -> tuple[array, int]:
    if encoding is PcmEncoding.PCM_U8:
        return array("b", raw.translate(_U8_TO_S8)), 128
    if encoding is PcmEncoding.PCM_S16LE:
        samples = array("h", raw)
        full_scale = 1 << 15
    else:
        if encoding is PcmEncoding.PCM_S24LE:
            widened = bytearray(len(raw) // 3 * 4)
            widened[1::4], widened[2::4], widened[3::4] = raw[0::3], raw[1::3], raw[2::3]
            raw = bytes(widened)
        samples = array("i", raw)
        full_scale = 1 << 31
    if sys.byteorder == "big":
        samples.byteswap()
    return samples, full_scale


def _level(value: float) -> float:
    return round(min(1.0, value), 6)


def _dbfs(level: float) -> float | None:
    return round(20 * math.log10(level), 2) if level > 0 else None


def _rms(samples: array, full_scale: int) -> float:
    return math.sqrt(math.sumprod(samples, samples) / len(samples)) / full_scale


def _peak(samples: array, full_scale: int) -> float:
    return max(max(samples), -min(samples)) / full_scale


def _measure(layout: WavLayout, samples: array, full_scale: int) -> AudioAnalysis:
    channels = layout.channels
    total = len(samples)
    top = full_scale - (256 if layout.encoding is PcmEncoding.PCM_S24LE else 1)
    clipped = samples.count(top) + samples.count(-full_scale)
    levels = []
    crossings = 0
    for index in range(channels):
        channel = samples[index::channels]
        levels.append(
            ChannelLevel(
                channel=index,
                peak_level=_level(_peak(channel, full_scale)),
                rms_level=_level(_rms(channel, full_scale)),
            )
        )
        negative = list(map((0).__gt__, channel))
        crossings += sum(map(operator.ne, negative, negative[1:]))
    window = max(1, layout.sample_rate_hz * ANALYSIS_WINDOW_MS // 1000) * channels
    windows = range(0, total, window)
    silent = sum(
        1 for start in windows if _rms(samples[start : start + window], full_scale) < SILENCE_LEVEL
    )
    peak = _level(_peak(samples, full_scale))
    rms = _level(_rms(samples, full_scale))
    duration_s = layout.frame_count / layout.sample_rate_hz
    return AudioAnalysis(
        format_tag=layout.format_tag,
        encoding=layout.encoding,
        sample_rate_hz=layout.sample_rate_hz,
        channels=channels,
        bits_per_sample=layout.bits_per_sample,
        frame_count=layout.frame_count,
        data_bytes=layout.data_bytes,
        duration_ms=round(layout.exact_duration_ms, 3),
        skipped_chunk_count=layout.skipped_chunk_count,
        peak_level=peak,
        peak_dbfs=_dbfs(peak),
        rms_level=rms,
        rms_dbfs=_dbfs(rms),
        dc_offset=round(max(-1.0, min(1.0, sum(samples) / total / full_scale)), 6),
        clipped_sample_share=round(clipped / total, 6),
        silent_window_share=round(silent / len(windows), 6),
        zero_crossing_rate_per_s=round(crossings / channels / duration_s, 3),
        content=SignalContent.SILENT if peak < SILENCE_LEVEL else SignalContent.SIGNAL,
        channel_levels=tuple(levels),
    )
