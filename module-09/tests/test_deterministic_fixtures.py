"""Tests for the committed deterministic fixtures, their provenance, and the fixture catalog.

The image and audio builders below are the documented generators for the committed binary
fixtures. They use only the standard library, so the fixtures are project-owned and reproducible.
"""

import hashlib
import io
import json
import struct
import wave
import zlib
from importlib import resources
from typing import Any

import pytest
from pydantic import ValidationError

from multimodal_voice_platform.adapters.deterministic.errors import (
    DeterministicInputError,
    FixtureIntegrityError,
    UnknownFixtureError,
)
from multimodal_voice_platform.adapters.deterministic.fixtures import (
    FIXTURE_PACKAGE,
    MANIFEST_NAME,
    MAX_FIXTURE_BYTES,
    FixtureCatalog,
    FixtureManifest,
    FixtureSpec,
)
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.modality import Modality

IMAGE_SIZE = 8
QUADRANT_COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
AUDIO_RATE_HZ = 8_000
AUDIO_FRAMES = 4_000
SQUARE_HALF_PERIOD = 10
SQUARE_LEVELS = (178, 78)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def expected_pixels() -> list[list[tuple[int, int, int]]]:
    """Return the 8x8 four-quadrant test pattern: red, green / blue, white."""
    half = IMAGE_SIZE // 2
    return [
        [QUADRANT_COLORS[(y >= half) * 2 + (x >= half)] for x in range(IMAGE_SIZE)]
        for y in range(IMAGE_SIZE)
    ]


def build_png() -> bytes:
    """Build the committed image fixture: an 8-bit RGB PNG of the quadrant pattern."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in expected_pixels())
    header = struct.pack(">IIBBBBB", IMAGE_SIZE, IMAGE_SIZE, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def expected_samples() -> bytes:
    """Return the 400 Hz square wave as unsigned 8-bit PCM samples."""
    return bytes(SQUARE_LEVELS[(n // SQUARE_HALF_PERIOD) % 2] for n in range(AUDIO_FRAMES))


def build_wav() -> bytes:
    """Build the committed audio fixture: 500 ms of a 400 Hz square tone, mono, 8 kHz."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(1)
        writer.setframerate(AUDIO_RATE_HZ)
        writer.writeframes(expected_samples())
    return buffer.getvalue()


def decode_png_pixels(data: bytes) -> list[list[tuple[int, int, int]]]:
    """Decode an unfiltered 8-bit RGB PNG, verifying every chunk CRC."""
    assert data.startswith(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    chunks: dict[bytes, bytes] = {}
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, kind
        chunks[kind] = chunks.get(kind, b"") + body
        offset += 12 + length
    width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (width, height, depth, color, interlace) == (IMAGE_SIZE, IMAGE_SIZE, 8, 2, 0)
    assert b"IEND" in chunks
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = 1 + width * 3
    rows = []
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        assert row[0] == 0
        rows.append([tuple(row[1 + x * 3 : 4 + x * 3]) for x in range(width)])
    return rows


@pytest.fixture(scope="module")
def catalog() -> FixtureCatalog:
    return FixtureCatalog.load_default()


def _manifest_json() -> dict[str, Any]:
    return json.loads(resources.files(FIXTURE_PACKAGE).joinpath(MANIFEST_NAME).read_text("utf-8"))


def _fixture_bytes(catalog: FixtureCatalog) -> dict[str, bytes]:
    return {catalog.get(fid).file_name: catalog.content(fid) for fid in catalog.fixture_ids}


def test_catalog_has_one_valid_fixture_per_modality(catalog: FixtureCatalog) -> None:
    specs = [catalog.get(fid) for fid in catalog.fixture_ids]
    assert sorted(spec.modality for spec in specs) == sorted(Modality)
    for spec in specs:
        content = catalog.content(spec.fixture_id)
        assert len(content) == spec.size_bytes <= MAX_FIXTURE_BYTES
        assert hashlib.sha256(content).hexdigest() == spec.sha256


def test_image_fixture_is_the_generated_quadrant_png(catalog: FixtureCatalog) -> None:
    content = catalog.content("image-quadrants")
    assert decode_png_pixels(content) == expected_pixels()
    assert decode_png_pixels(build_png()) == expected_pixels()


def test_audio_fixture_is_the_generated_square_tone(catalog: FixtureCatalog) -> None:
    content = catalog.content("audio-tone")
    assert content == build_wav()
    with wave.open(io.BytesIO(content), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 1
        assert reader.getframerate() == AUDIO_RATE_HZ
        frames = reader.getnframes()
        assert reader.readframes(frames) == expected_samples()
    assert catalog.get("audio-tone").duration_ms == frames * 1000 // AUDIO_RATE_HZ == 500


def test_text_and_document_fixtures_are_lf_utf8(catalog: FixtureCatalog) -> None:
    for fixture_id in ("text-brief", "document-brief"):
        content = catalog.content(fixture_id)
        assert not content.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in content
        content.decode("utf-8")


def test_document_script_sections_come_from_the_document(catalog: FixtureCatalog) -> None:
    spec = catalog.get("document-brief")
    text = catalog.content("document-brief").decode("utf-8")
    assert spec.document is not None
    assert spec.document.title is not None
    assert f"# {spec.document.title}\n" in text
    for section in spec.document.sections:
        assert f"## {section.heading}\n" in text
        assert " ".join(section.text.split()) in " ".join(text.split())


def test_catalog_loading_is_reproducible(catalog: FixtureCatalog) -> None:
    again = FixtureCatalog.load_default()
    assert again.fixture_ids == catalog.fixture_ids
    for fid in catalog.fixture_ids:
        assert again.get(fid) == catalog.get(fid)
        assert again.content(fid) == catalog.content(fid)


def test_tampered_fixture_bytes_fail_integrity(catalog: FixtureCatalog) -> None:
    manifest = FixtureManifest.model_validate(_manifest_json())
    contents = _fixture_bytes(catalog)
    contents["image-quadrants.png"] = contents["image-quadrants.png"][:-1] + b"\x00"
    with pytest.raises(FixtureIntegrityError, match="integrity") as excinfo:
        FixtureCatalog(manifest, contents)
    assert excinfo.value.code is ErrorCode.INTERNAL_ERROR


def test_missing_or_extra_fixture_files_fail_integrity(catalog: FixtureCatalog) -> None:
    manifest = FixtureManifest.model_validate(_manifest_json())
    contents = _fixture_bytes(catalog)
    with pytest.raises(FixtureIntegrityError, match="manifest"):
        FixtureCatalog(manifest, {**contents, "extra.txt": b"x"})
    contents.pop("audio-tone.wav")
    with pytest.raises(FixtureIntegrityError, match="manifest"):
        FixtureCatalog(manifest, contents)


def test_unknown_fixture_ids_are_rejected_without_path_use(catalog: FixtureCatalog) -> None:
    for fixture_id in ("missing", "../manifest.json", "/etc/passwd", "manifest", ""):
        with pytest.raises(UnknownFixtureError) as excinfo:
            catalog.get(fixture_id)
        assert excinfo.value.code is ErrorCode.INPUT_REJECTED
        with pytest.raises(UnknownFixtureError):
            catalog.content(fixture_id)


def test_match_requires_exact_committed_content(catalog: FixtureCatalog) -> None:
    assert catalog.match(Modality.IMAGE, build_png()).fixture_id == "image-quadrants"
    with pytest.raises(DeterministicInputError, match="does not match"):
        catalog.match(Modality.IMAGE, b"not a fixture")
    with pytest.raises(DeterministicInputError, match="does not match"):
        catalog.match(Modality.DOCUMENT, catalog.content("image-quadrants"))


def _spec(**overrides: Any) -> dict[str, Any]:
    spec = next(s for s in _manifest_json()["fixtures"] if s["fixture_id"] == "audio-tone")
    spec.update(overrides)
    return spec


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"media_type": "video/mp4"}, "not allowed"),
        ({"file_name": "audio-tone.mp3"}, "extension"),
        ({"file_name": "../audio-tone.wav"}, "file_name"),
        ({"display_name": "tone.png"}, "extension"),
        ({"duration_ms": None}, "duration_ms"),
        ({"page_count": 1}, "page_count"),
        ({"size_bytes": MAX_FIXTURE_BYTES + 1}, "size_bytes"),
        ({"sha256": "abc"}, "sha256"),
        ({"transcript": None}, "scripted output"),
        ({"vision": {"description": "x"}}, "scripted output"),
        ({"duration_ms": 100}, "beyond the audio duration"),
        ({"unexpected": True}, "unexpected"),
    ],
)
def test_malformed_fixture_specs_are_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        FixtureSpec.model_validate(_spec(**overrides))


def test_transcript_scripts_must_end_with_one_final_segment() -> None:
    segments = _spec()["transcript"]["segments"]
    with pytest.raises(ValidationError, match="final"):
        FixtureSpec.model_validate(
            _spec(transcript={"segments": [{**seg, "is_final": False} for seg in segments]})
        )
    with pytest.raises(ValidationError, match="final"):
        FixtureSpec.model_validate(_spec(transcript={"segments": list(reversed(segments))}))


def test_manifest_requires_unique_ids_and_every_modality() -> None:
    data = _manifest_json()
    duplicated = {**data, "fixtures": [*data["fixtures"], data["fixtures"][0]]}
    with pytest.raises(ValidationError, match="unique"):
        FixtureManifest.model_validate(duplicated)
    no_audio = {**data, "fixtures": [f for f in data["fixtures"] if f["modality"] != "audio"]}
    with pytest.raises(ValidationError, match="every modality"):
        FixtureManifest.model_validate(no_audio)
    with pytest.raises(ValidationError):
        FixtureManifest.model_validate({**data, "schema_version": 2})
