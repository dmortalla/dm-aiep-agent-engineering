"""Story 9.4 audio processing tests: sniffing, strict WAV parsing, staging, and measurement."""

import struct

import pytest
from audio_builders import (
    chunk,
    encode_sample,
    extensible_wav,
    fmt_body,
    pcm_wav,
    riff,
    sine_frames,
    sine_wav,
)

from multimodal_voice_platform.adapters.deterministic import FixtureCatalog, SessionContentStore
from multimodal_voice_platform.audio import (
    AudioLimits,
    MalformedAudioError,
    PcmEncoding,
    SignalContent,
    UnsupportedAudioError,
    WavFormatTag,
    analyze_wav,
    parse_wav,
    sniff_audio_media_type,
    stage_audio_content,
    verify_audio_content,
)
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import InputSource, Modality, TrustLevel
from multimodal_voice_platform.ingestion import (
    IngestionError,
    InputLimitError,
    MediaMismatchError,
    UnsupportedMediaError,
)

LIMITS = AudioLimits.from_budget(ResourceBudget())
TONE = sine_wav(440.0, 250)
PCM_FMT = chunk(b"fmt ", fmt_body())
FOUR_FRAMES = chunk(b"data", b"\x00\x00" * 4)


def _analyze(data: bytes, limits: AudioLimits = LIMITS):
    return analyze_wav(data, "audio/wav", limits)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (TONE, "audio/wav"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00", "audio/mpeg"),
        (b"\xff\xfb\x90\x64\x00", "audio/mpeg"),
        (b"\x1a\x45\xdf\xa3\x01\x00", "audio/webm"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", None),
        (b"\x89PNG\r\n\x1a\n", None),
        (b"\xff\xd8\xff\xe0", None),
        (b"plain text", None),
        (b"", None),
    ],
)
def test_audio_sniffing_identifies_allowlisted_signatures(
    data: bytes, expected: str | None
) -> None:
    assert sniff_audio_media_type(data) == expected


@pytest.mark.parametrize(
    ("media_type", "data", "error"),
    [
        ("audio/mpeg", b"ID3\x04\x00\x00\x00\x00\x00\x00", UnsupportedMediaError),
        ("audio/webm", b"\x1a\x45\xdf\xa3\x01\x00", UnsupportedMediaError),
        ("audio/wav", b"ID3\x04\x00\x00\x00\x00\x00\x00", MediaMismatchError),
        ("audio/mpeg", TONE, MediaMismatchError),
        ("audio/ogg", TONE, UnsupportedMediaError),
        ("image/png", TONE, UnsupportedMediaError),
    ],
)
def test_audio_content_must_match_a_decodable_declared_type(
    media_type: str, data: bytes, error: type[Exception]
) -> None:
    with pytest.raises(error):
        verify_audio_content(media_type, data)


def test_real_pcm_properties_are_decoded_from_the_bytes() -> None:
    analysis = _analyze(TONE)
    assert analysis.format_tag is WavFormatTag.PCM
    assert analysis.encoding is PcmEncoding.PCM_S16LE
    assert (analysis.sample_rate_hz, analysis.channels, analysis.bits_per_sample) == (16000, 1, 16)
    assert analysis.frame_count == 4000
    assert analysis.data_bytes == 8000
    assert analysis.duration_ms == 250.0
    assert analysis.peak_level == pytest.approx(0.5, abs=0.001)
    assert analysis.peak_dbfs == pytest.approx(-6.02, abs=0.02)
    assert analysis.rms_level == pytest.approx(0.5 / 2**0.5, abs=0.001)
    assert analysis.zero_crossing_rate_per_s == pytest.approx(880, rel=0.01)
    assert analysis.dc_offset == pytest.approx(0, abs=0.001)
    assert analysis.clipped_sample_share == 0
    assert analysis.silent_window_share == 0
    assert analysis.content is SignalContent.SIGNAL


@pytest.mark.parametrize(
    ("width", "encoding"),
    [
        (1, PcmEncoding.PCM_U8),
        (2, PcmEncoding.PCM_S16LE),
        (3, PcmEncoding.PCM_S24LE),
        (4, PcmEncoding.PCM_S32LE),
    ],
)
def test_every_supported_sample_width_decodes_to_the_same_levels(
    width: int, encoding: PcmEncoding
) -> None:
    analysis = _analyze(sine_wav(250.0, 200, width=width, rate=8000, amplitude=0.25))
    assert analysis.encoding is encoding
    assert analysis.bits_per_sample == width * 8
    assert analysis.peak_level == pytest.approx(0.25, abs=0.01)
    assert analysis.zero_crossing_rate_per_s == pytest.approx(500, rel=0.02)
    assert analysis.dc_offset == pytest.approx(0, abs=0.01)


def test_channels_are_measured_separately() -> None:
    frames = bytearray()
    loud, quiet = sine_frames(300, 100, amplitude=0.8), sine_frames(300, 100, amplitude=0.1)
    for index in range(0, len(loud), 2):
        frames += loud[index : index + 2] + quiet[index : index + 2]
    analysis = _analyze(pcm_wav(bytes(frames), channels=2))
    assert analysis.channels == 2
    left, right = analysis.channel_levels
    assert left.peak_level == pytest.approx(0.8, abs=0.01)
    assert right.peak_level == pytest.approx(0.1, abs=0.01)


def test_silence_clipping_and_dc_offset_are_measured() -> None:
    silent = _analyze(pcm_wav(b"\x00\x00" * 1600))
    assert silent.content is SignalContent.SILENT
    assert silent.silent_window_share == 1
    assert silent.peak_dbfs is None and silent.rms_dbfs is None
    clipped = _analyze(pcm_wav(encode_sample(32767, 2) * 800 + encode_sample(-32768, 2) * 800))
    assert clipped.clipped_sample_share == 1
    assert clipped.peak_level == 1
    offset = _analyze(pcm_wav(encode_sample(8192, 2) * 1600))
    assert offset.dc_offset == pytest.approx(0.25)
    assert offset.zero_crossing_rate_per_s == 0
    half_silent = _analyze(pcm_wav(sine_frames(440, 100) + b"\x00\x00" * 1600))
    assert half_silent.silent_window_share == pytest.approx(0.5)


def test_committed_fixture_is_genuinely_decoded() -> None:
    analysis = _analyze(FixtureCatalog.load_default().content("audio-tone"))
    assert analysis.encoding is PcmEncoding.PCM_U8
    assert (analysis.sample_rate_hz, analysis.frame_count, analysis.duration_ms) == (
        8000,
        4000,
        500,
    )
    assert analysis.peak_level == pytest.approx(50 / 128)
    assert analysis.zero_crossing_rate_per_s == pytest.approx(798)


def test_extensible_pcm_and_extra_chunks_are_supported() -> None:
    frames = sine_frames(440, 50)
    extensible = parse_wav(extensible_wav(frames))
    assert extensible.format_tag is WavFormatTag.EXTENSIBLE_PCM
    with_list = riff(
        [chunk(b"LIST", b"INFOISFT\x05\x00\x00\x00evil\x00"), PCM_FMT, chunk(b"data", frames)]
    )
    layout = parse_wav(with_list)
    assert layout.skipped_chunk_count == 1
    assert layout.frame_count == len(frames) // 2


def test_analysis_output_is_reproducible() -> None:
    assert _analyze(TONE) == _analyze(TONE)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"RIFF\x04\x00\x00\x00WAVE"[:10], "not a RIFF/WAVE"),
        (riff([PCM_FMT, FOUR_FRAMES], riff_size=10_000), "truncated"),
        (riff([PCM_FMT, FOUR_FRAMES]) + b"\x00\x00\x00", "beyond its declared size"),
        (riff([PCM_FMT, b"data" + struct.pack("<I", 1_000_000) + b"\x00" * 8]), "extends beyond"),
        (riff([PCM_FMT, FOUR_FRAMES + b"da"]), "chunk header is truncated"),
        (riff([FOUR_FRAMES, PCM_FMT]), "precedes the fmt"),
        (riff([PCM_FMT, PCM_FMT, FOUR_FRAMES]), "duplicated"),
        (riff([PCM_FMT, FOUR_FRAMES, FOUR_FRAMES]), "duplicated"),
        (riff([PCM_FMT]), "requires fmt and data"),
        (riff([PCM_FMT, chunk(b"data", b"")]), "no samples"),
        (riff([PCM_FMT, chunk(b"data", b"\x00\x00\x00")]), "incomplete frame"),
        (riff([chunk(b"fmt ", fmt_body()[:12]), FOUR_FRAMES]), "too short"),
        (riff([chunk(b"fmt ", fmt_body(block_align=3)), FOUR_FRAMES]), "block alignment"),
        (riff([chunk(b"fmt ", fmt_body(byte_rate=1)), FOUR_FRAMES]), "byte rate"),
        (riff([chunk(b"junk", b"") for _ in range(70)] + [PCM_FMT, FOUR_FRAMES]), "too many"),
    ],
)
def test_malformed_and_pathological_containers_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(MalformedAudioError, match=message) as caught:
        parse_wav(data)
    assert caught.value.code is ErrorCode.INPUT_REJECTED


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            riff([chunk(b"fmt ", fmt_body(tag=3, bits=32)), chunk(b"data", bytes(16))]),
            "floating-point",
        ),
        (riff([chunk(b"fmt ", fmt_body(tag=2)), FOUR_FRAMES]), "encoding is not supported"),
        (extensible_wav(b"\x00" * 16, subformat_code=3, bits=32), "floating-point"),
        (extensible_wav(b"\x00" * 16, subformat_code=2), "not integer PCM"),
        (
            riff([chunk(b"fmt ", fmt_body(bits=12, block_align=2, byte_rate=32000)), FOUR_FRAMES]),
            "8, 16, 24, or 32",
        ),
        (
            riff([chunk(b"fmt ", fmt_body(channels=9)), chunk(b"data", b"\x00" * 18)]),
            "channel count",
        ),
        (riff([chunk(b"fmt ", fmt_body(rate=4000)), FOUR_FRAMES]), "sample rate"),
        (riff([chunk(b"fmt ", fmt_body(rate=400_000)), FOUR_FRAMES]), "sample rate"),
    ],
)
def test_unsupported_encodings_and_parameters_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(UnsupportedAudioError, match=message):
        parse_wav(data)


def test_padded_extensible_samples_are_rejected() -> None:
    subformat = struct.pack("<I", 1) + b"\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    fmt = fmt_body(tag=0xFFFE, bits=32, subformat=subformat, valid_bits=24)
    with pytest.raises(UnsupportedAudioError, match="padded"):
        parse_wav(riff([chunk(b"fmt ", fmt), chunk(b"data", b"\x00" * 8)]))


def _stage(store: SessionContentStore, **overrides: object):
    fields: dict[str, object] = {
        "session_id": "sess-audio",
        "limits": LIMITS,
        "media_type": "audio/wav",
        "display_name": "tone.wav",
        "data": TONE,
    }
    fields.update(overrides)
    return stage_audio_content(store, **fields)  # type: ignore[arg-type]


def test_staging_produces_a_validated_untrusted_audio_input() -> None:
    store = SessionContentStore()
    item = _stage(store)
    assert item.modality is Modality.AUDIO
    assert item.trust is TrustLevel.UNTRUSTED_EXTERNAL
    assert item.source is InputSource.USER_UPLOAD
    assert item.duration_ms == 250
    assert item.size_bytes == len(TONE)
    assert item.content_ref is not None and item.content_ref.startswith("ref-")
    assert store.read("sess-audio", item.content_ref) == TONE


@pytest.mark.parametrize(
    ("overrides", "error", "code"),
    [
        ({"data": b""}, IngestionError, ErrorCode.INPUT_REJECTED),
        ({"display_name": "tone.mp3"}, IngestionError, ErrorCode.INPUT_REJECTED),
        ({"display_name": "../tone.wav"}, IngestionError, ErrorCode.INPUT_REJECTED),
        ({"display_name": "C:\\tone.wav"}, IngestionError, ErrorCode.INPUT_REJECTED),
        ({"display_name": ".tone.wav"}, IngestionError, ErrorCode.INPUT_REJECTED),
        (
            {"media_type": "audio/mpeg", "display_name": "a.mp3"},
            MediaMismatchError,
            ErrorCode.INPUT_REJECTED,
        ),
        (
            {
                "data": b"ID3\x04" + b"\x00" * 64,
                "media_type": "audio/mpeg",
                "display_name": "a.mp3",
            },
            UnsupportedMediaError,
            ErrorCode.UNSUPPORTED_MODALITY,
        ),
        ({"data": TONE[:-100]}, MalformedAudioError, ErrorCode.INPUT_REJECTED),
        (
            {
                "limits": AudioLimits(
                    max_audio_bytes=len(TONE) - 1, max_audio_duration_ms=60_000, timeout_s=5
                )
            },
            InputLimitError,
            ErrorCode.LIMIT_EXCEEDED,
        ),
        (
            {
                "limits": AudioLimits(
                    max_audio_bytes=10_000_000, max_audio_duration_ms=249, timeout_s=5
                )
            },
            InputLimitError,
            ErrorCode.LIMIT_EXCEEDED,
        ),
    ],
)
def test_invalid_audio_is_rejected_before_storage(
    overrides: dict[str, object], error: type[Exception], code: ErrorCode
) -> None:
    store = SessionContentStore()
    with pytest.raises(error) as caught:
        _stage(store, **overrides)
    assert caught.value.code is code  # type: ignore[attr-defined]
    assert store.reference_count("sess-audio") == 0


def test_declared_frame_count_cannot_inflate_duration_past_the_bytes() -> None:
    huge = riff([PCM_FMT, b"data" + struct.pack("<I", 0x7FFFFFF0) + b"\x00" * 16])
    with pytest.raises(MalformedAudioError):
        _stage(SessionContentStore(), data=huge)


def test_analysis_reverifies_bytes_and_budgets() -> None:
    with pytest.raises(MediaMismatchError):
        analyze_wav(b"ID3" + b"\x00" * 32, "audio/wav", LIMITS)
    short = AudioLimits(max_audio_bytes=10_000_000, max_audio_duration_ms=100, timeout_s=5)
    with pytest.raises(InputLimitError, match="duration"):
        analyze_wav(TONE, "audio/wav", short)
