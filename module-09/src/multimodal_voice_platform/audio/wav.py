"""Audio content sniffing and strict, bounded parsing of PCM WAV containers (Story 9.4).

Only integer PCM WAV is decoded. MP3 and WebM are allowlisted by the input contract and recognized
by their signatures, but decoding them needs a codec library that this story does not add, so they
are rejected as unsupported rather than guessed at.

The RIFF structure is walked with ``struct`` so that every declared size is checked against the
real byte length: truncated chunks, chunks that overrun the container, trailing bytes, duplicate or
misordered ``fmt``/``data`` chunks, inconsistent block alignment or byte rate, and out-of-range
channel counts or sample rates are all rejected before any sample is decoded. The standard-library
``wave`` reader then parses the same in-memory bytes, and both readers must agree.
"""

import io
import math
import struct
import wave
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.audio.errors import MalformedAudioError, UnsupportedAudioError
from multimodal_voice_platform.audio.limits import (
    MAX_CHANNELS,
    MAX_SAMPLE_RATE_HZ,
    MAX_WAV_CHUNKS,
    MIN_SAMPLE_RATE_HZ,
)
from multimodal_voice_platform.contracts.modality import MEDIA_TYPES, Modality
from multimodal_voice_platform.ingestion.errors import MediaMismatchError, UnsupportedMediaError

WAV_MEDIA_TYPE: Final = "audio/wav"
DECODABLE_AUDIO_MEDIA_TYPES: Final = frozenset({WAV_MEDIA_TYPE})
"""Audio media types this story can decode. The rest of the audio allowlist is rejected."""

_FORMAT_PCM: Final = 0x0001
_FORMAT_FLOAT: Final = 0x0003
_FORMAT_EXTENSIBLE: Final = 0xFFFE
_GUID_TAIL: Final = b"\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
_PCM_SUBFORMAT: Final = b"\x01\x00\x00\x00" + _GUID_TAIL
_FLOAT_SUBFORMAT: Final = b"\x03\x00\x00\x00" + _GUID_TAIL
_EBML_MAGIC: Final = b"\x1a\x45\xdf\xa3"


class PcmEncoding(StrEnum):
    """Supported integer PCM sample encodings (little-endian, as stored in WAV)."""

    PCM_U8 = "pcm_u8"
    PCM_S16LE = "pcm_s16le"
    PCM_S24LE = "pcm_s24le"
    PCM_S32LE = "pcm_s32le"


ENCODING_FOR_BITS: Final = {
    8: PcmEncoding.PCM_U8,
    16: PcmEncoding.PCM_S16LE,
    24: PcmEncoding.PCM_S24LE,
    32: PcmEncoding.PCM_S32LE,
}


class WavFormatTag(StrEnum):
    """Which WAV format header declared the PCM data."""

    PCM = "pcm"
    EXTENSIBLE_PCM = "extensible_pcm"


class WavLayout(BaseModel):
    """Validated structure of a PCM WAV container. Describes the bytes; holds none of them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_tag: WavFormatTag
    encoding: PcmEncoding
    channels: int = Field(ge=1, le=MAX_CHANNELS)
    sample_rate_hz: int = Field(ge=MIN_SAMPLE_RATE_HZ, le=MAX_SAMPLE_RATE_HZ)
    bits_per_sample: int
    block_align: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    data_offset: int = Field(ge=12)
    data_bytes: int = Field(gt=0)
    skipped_chunk_count: int = Field(ge=0, le=MAX_WAV_CHUNKS)

    @property
    def exact_duration_ms(self) -> float:
        """Return the exact duration in milliseconds."""
        return self.frame_count * 1000 / self.sample_rate_hz

    @property
    def duration_ms(self) -> int:
        """Return the duration rounded up to whole milliseconds (at least 1)."""
        return max(1, math.ceil(self.exact_duration_ms))


def sniff_audio_media_type(data: bytes) -> str | None:
    """Identify an allowlisted audio media type from its signature.

    Args:
        data: Untrusted content bytes.

    Returns:
        ``audio/wav`` for RIFF/WAVE, ``audio/webm`` for an EBML header, ``audio/mpeg`` for an ID3
        tag or an MPEG audio frame sync, otherwise ``None``.
    """
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return WAV_MEDIA_TYPE
    if data.startswith(_EBML_MAGIC):
        return "audio/webm"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return None


def verify_audio_content(media_type: str, data: bytes) -> None:
    """Confirm audio bytes match their declared, allowlisted, decodable media type (SEC-003).

    Args:
        media_type: Declared media type.
        data: Untrusted content bytes.

    Raises:
        UnsupportedMediaError: If the media type is not an allowlisted audio type, or is
            allowlisted but not decodable by this story (MP3, WebM).
        MediaMismatchError: If the bytes do not match the declared media type.
    """
    if media_type not in MEDIA_TYPES[Modality.AUDIO]:
        raise UnsupportedMediaError("media type is not supported for audio input")
    if sniff_audio_media_type(data) != media_type:
        raise MediaMismatchError("content does not match the declared media type")
    if media_type not in DECODABLE_AUDIO_MEDIA_TYPES:
        raise UnsupportedMediaError(
            f"{media_type} decoding is not supported; submit integer PCM WAV audio"
        )


def parse_wav(data: bytes) -> WavLayout:
    """Parse and validate the structure of an in-memory PCM WAV container.

    Args:
        data: Untrusted WAV bytes.

    Returns:
        The validated layout.

    Raises:
        MalformedAudioError: If the container is truncated, inconsistent, or structurally invalid,
            or the standard-library reader disagrees with the structural parse.
        UnsupportedAudioError: If the audio is well formed but uses an unsupported encoding,
            sample width, channel count, or sample rate.
    """
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise MalformedAudioError("content is not a RIFF/WAVE container")
    (riff_size,) = struct.unpack_from("<I", data, 4)
    riff_end = 8 + riff_size
    if riff_end > len(data):
        raise MalformedAudioError("WAV container is truncated")
    if len(data) - riff_end > 1:
        raise MalformedAudioError("WAV container has bytes beyond its declared size")
    fmt: bytes | None = None
    data_chunk: tuple[int, int] | None = None
    skipped = 0
    offset = 12
    for _ in range(MAX_WAV_CHUNKS):
        if offset >= riff_end:
            break
        if riff_end - offset < 8:
            raise MalformedAudioError("WAV chunk header is truncated")
        chunk_id = data[offset : offset + 4]
        (size,) = struct.unpack_from("<I", data, offset + 4)
        start = offset + 8
        if start + size > riff_end:
            raise MalformedAudioError("WAV chunk extends beyond the container")
        if chunk_id == b"fmt ":
            if fmt is not None or data_chunk is not None:
                raise MalformedAudioError("WAV fmt chunk is duplicated or follows the data chunk")
            fmt = data[start : start + size]
        elif chunk_id == b"data":
            if data_chunk is not None or fmt is None:
                raise MalformedAudioError("WAV data chunk is duplicated or precedes the fmt chunk")
            data_chunk = (start, size)
        else:
            skipped += 1
        offset = start + size + (size & 1)
    else:
        if offset < riff_end:
            raise MalformedAudioError("WAV container has too many chunks")
    if fmt is None or data_chunk is None:
        raise MalformedAudioError("WAV container requires fmt and data chunks")
    layout = _layout(fmt, data_chunk, skipped)
    _cross_check(data, layout)
    return layout


def _layout(fmt: bytes, data_chunk: tuple[int, int], skipped: int) -> WavLayout:
    if len(fmt) < 16:
        raise MalformedAudioError("WAV fmt chunk is too short")
    tag, channels, rate, byte_rate, block_align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if tag == _FORMAT_EXTENSIBLE:
        if len(fmt) < 40:
            raise MalformedAudioError("WAV extensible fmt chunk is too short")
        (valid_bits,) = struct.unpack_from("<H", fmt, 18)
        subformat = fmt[24:40]
        if subformat == _FLOAT_SUBFORMAT:
            raise UnsupportedAudioError("floating-point WAV is not supported; use integer PCM")
        if subformat != _PCM_SUBFORMAT:
            raise UnsupportedAudioError("WAV extensible subformat is not integer PCM")
        if valid_bits != bits:
            raise UnsupportedAudioError("WAV samples with padded bits are not supported")
        format_tag = WavFormatTag.EXTENSIBLE_PCM
    elif tag == _FORMAT_PCM:
        format_tag = WavFormatTag.PCM
    elif tag == _FORMAT_FLOAT:
        raise UnsupportedAudioError("floating-point WAV is not supported; use integer PCM")
    else:
        raise UnsupportedAudioError("WAV encoding is not supported; use integer PCM")
    encoding = ENCODING_FOR_BITS.get(bits)
    if encoding is None:
        raise UnsupportedAudioError("WAV sample width must be 8, 16, 24, or 32 bits")
    if not 1 <= channels <= MAX_CHANNELS:
        raise UnsupportedAudioError(f"WAV channel count must be between 1 and {MAX_CHANNELS}")
    if not MIN_SAMPLE_RATE_HZ <= rate <= MAX_SAMPLE_RATE_HZ:
        raise UnsupportedAudioError(
            f"WAV sample rate must be between {MIN_SAMPLE_RATE_HZ} and {MAX_SAMPLE_RATE_HZ} Hz"
        )
    if block_align != channels * bits // 8:
        raise MalformedAudioError("WAV block alignment is inconsistent with its format")
    if byte_rate != rate * block_align:
        raise MalformedAudioError("WAV byte rate is inconsistent with its format")
    start, size = data_chunk
    if size == 0:
        raise MalformedAudioError("WAV audio contains no samples")
    if size % block_align:
        raise MalformedAudioError("WAV data ends with an incomplete frame")
    return WavLayout(
        format_tag=format_tag,
        encoding=encoding,
        channels=channels,
        sample_rate_hz=rate,
        bits_per_sample=bits,
        block_align=block_align,
        frame_count=size // block_align,
        data_offset=start,
        data_bytes=size,
        skipped_chunk_count=skipped,
    )


def _cross_check(data: bytes, layout: WavLayout) -> None:
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            params = (
                reader.getnchannels(),
                reader.getsampwidth(),
                reader.getframerate(),
                reader.getnframes(),
            )
    except (wave.Error, EOFError, struct.error) as exc:
        raise MalformedAudioError("the standard-library WAV reader rejected the audio") from exc
    expected = (
        layout.channels,
        layout.bits_per_sample // 8,
        layout.sample_rate_hz,
        layout.frame_count,
    )
    if params != expected:
        raise MalformedAudioError("WAV header readers disagree about the audio format")
