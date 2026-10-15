"""Builders for Story 9.4 test audio. Every input is generated in-process; nothing is downloaded.

Well-formed WAV files are written with the standard-library ``wave`` writer. Malformed and
unusual containers are assembled chunk by chunk so their structure is fully known.
"""

import io
import math
import struct
import wave

PCM_GUID_TAIL = b"\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"


def encode_sample(value: int, width: int) -> bytes:
    """Encode one signed sample as little-endian PCM (8-bit is unsigned with a 128 offset)."""
    if width == 1:
        return bytes([value + 128])
    return value.to_bytes(width, "little", signed=True)


def full_scale(width: int) -> int:
    """Return the positive full-scale magnitude for a sample width."""
    return 1 << (8 * width - 1)


def sine_frames(
    frequency: float,
    duration_ms: int,
    *,
    rate: int = 16_000,
    width: int = 2,
    channels: int = 1,
    amplitude: float = 0.5,
) -> bytes:
    """Return interleaved PCM frames of a sine tone, identical on every channel."""
    frames = rate * duration_ms // 1000
    peak = amplitude * (full_scale(width) - 1)
    out = bytearray()
    for n in range(frames):
        sample = encode_sample(round(peak * math.sin(2 * math.pi * frequency * n / rate)), width)
        out += sample * channels
    return bytes(out)


def pcm_wav(frames: bytes, *, rate: int = 16_000, width: int = 2, channels: int = 1) -> bytes:
    """Write PCM frames as a WAV file with the standard-library writer."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(rate)
        writer.writeframes(frames)
    return buffer.getvalue()


def sine_wav(frequency: float = 440.0, duration_ms: int = 250, **options: int | float) -> bytes:
    """Return a WAV file containing a sine tone."""
    rate = int(options.get("rate", 16_000))
    width = int(options.get("width", 2))
    channels = int(options.get("channels", 1))
    amplitude = float(options.get("amplitude", 0.5))
    frames = sine_frames(
        frequency, duration_ms, rate=rate, width=width, channels=channels, amplitude=amplitude
    )
    return pcm_wav(frames, rate=rate, width=width, channels=channels)


def chunk(kind: bytes, body: bytes) -> bytes:
    """Return one RIFF chunk, padded to an even length."""
    return kind + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) % 2 else b"")


def fmt_body(
    *,
    tag: int = 1,
    channels: int = 1,
    rate: int = 16_000,
    bits: int = 16,
    block_align: int | None = None,
    byte_rate: int | None = None,
    subformat: bytes | None = None,
    valid_bits: int | None = None,
) -> bytes:
    """Return a WAV ``fmt`` chunk body; extensible when ``subformat`` is given."""
    align = channels * bits // 8 if block_align is None else block_align
    rate_bytes = rate * align if byte_rate is None else byte_rate
    body = struct.pack("<HHIIHH", tag, channels, rate, rate_bytes, align, bits)
    if subformat is not None:
        body += struct.pack("<HHI", 22, bits if valid_bits is None else valid_bits, 0) + subformat
    return body


def riff(chunks: list[bytes], *, riff_size: int | None = None) -> bytes:
    """Assemble a RIFF/WAVE container from prepared chunks."""
    body = b"WAVE" + b"".join(chunks)
    size = len(body) if riff_size is None else riff_size
    return b"RIFF" + struct.pack("<I", size) + body


def extensible_wav(frames: bytes, *, subformat_code: int = 1, bits: int = 16) -> bytes:
    """Return a WAVE_FORMAT_EXTENSIBLE container around the given frames."""
    subformat = struct.pack("<I", subformat_code) + PCM_GUID_TAIL
    fmt = fmt_body(tag=0xFFFE, bits=bits, subformat=subformat)
    return riff([chunk(b"fmt ", fmt), chunk(b"data", frames)])
