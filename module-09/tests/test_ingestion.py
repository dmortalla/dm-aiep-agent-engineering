"""Story 9.3 ingestion tests: content sniffing, budgets, safe names, and staging behavior."""

import pytest
from media_builders import build_pdf, encode, quadrant_image

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import InputSource, Modality, TrustLevel
from multimodal_voice_platform.ingestion import (
    IngestionError,
    InputLimitError,
    MediaMismatchError,
    UnsupportedMediaError,
    decode_text_content,
    sniff_binary_media_type,
    stage_content,
    verify_media_content,
)

PNG = encode(quadrant_image(), "PNG")
JPEG = encode(quadrant_image(), "JPEG", quality=95)
WEBP = encode(quadrant_image(), "WEBP", lossless=True)
PDF = build_pdf([["Hello"]])
MARKDOWN = b"# Title\n\nBody text.\n"


def _stage(store: SessionContentStore, **overrides: object):
    fields: dict[str, object] = {
        "session_id": "sess-ingest",
        "budget": ResourceBudget(),
        "modality": Modality.IMAGE,
        "media_type": "image/png",
        "display_name": "pattern.png",
        "data": PNG,
    }
    fields.update(overrides)
    return stage_content(store, **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (WEBP, "image/webp"),
        (PDF, "application/pdf"),
        (MARKDOWN, None),
        (b"RIFF\x00\x00\x00\x00WAVE", None),
        (b"", None),
    ],
)
def test_sniffing_identifies_allowlisted_binary_signatures(
    data: bytes, expected: str | None
) -> None:
    assert sniff_binary_media_type(data) == expected


@pytest.mark.parametrize(
    ("modality", "media_type", "data"),
    [
        (Modality.IMAGE, "image/png", PNG),
        (Modality.IMAGE, "image/jpeg", JPEG),
        (Modality.IMAGE, "image/webp", WEBP),
        (Modality.DOCUMENT, "application/pdf", PDF),
        (Modality.DOCUMENT, "text/markdown", MARKDOWN),
        (Modality.DOCUMENT, "text/plain", b"plain words\n"),
    ],
)
def test_matching_content_is_accepted(modality: Modality, media_type: str, data: bytes) -> None:
    verify_media_content(modality, media_type, data)


@pytest.mark.parametrize(
    ("modality", "media_type", "data"),
    [
        (Modality.IMAGE, "image/jpeg", PNG),
        (Modality.IMAGE, "image/png", JPEG),
        (Modality.IMAGE, "image/webp", PDF),
        (Modality.DOCUMENT, "application/pdf", MARKDOWN),
        (Modality.DOCUMENT, "text/markdown", PDF),
        (Modality.DOCUMENT, "text/plain", PNG),
        (Modality.DOCUMENT, "text/plain", b"text with a NUL\x00 byte"),
        (Modality.DOCUMENT, "text/plain", b"\xff\xfe not utf-8"),
    ],
)
def test_content_that_contradicts_its_media_type_is_rejected(
    modality: Modality, media_type: str, data: bytes
) -> None:
    with pytest.raises(MediaMismatchError) as caught:
        verify_media_content(modality, media_type, data)
    assert caught.value.code is ErrorCode.INPUT_REJECTED


@pytest.mark.parametrize(
    ("modality", "media_type"),
    [
        (Modality.IMAGE, "image/gif"),
        (Modality.IMAGE, "image/svg+xml"),
        (Modality.DOCUMENT, "text/html"),
    ],
)
def test_unlisted_media_types_are_unsupported(modality: Modality, media_type: str) -> None:
    with pytest.raises(UnsupportedMediaError) as caught:
        verify_media_content(modality, media_type, PNG)
    assert caught.value.code is ErrorCode.UNSUPPORTED_MODALITY


def test_text_decoding_strips_bom_and_keeps_whitespace_controls() -> None:
    assert decode_text_content(b"\xef\xbb\xbfa\tb\r\nc\f") == "a\tb\r\nc\f"
    assert decode_text_content("Résumé — naïve ✓".encode()) == "Résumé — naïve ✓"


def test_staging_produces_an_untrusted_input_held_by_opaque_reference() -> None:
    store = SessionContentStore()
    item = _stage(store)
    assert item.trust is TrustLevel.UNTRUSTED_EXTERNAL
    assert item.source is InputSource.USER_UPLOAD
    assert item.size_bytes == len(PNG)
    assert item.content_ref is not None and item.content_ref.startswith("ref-")
    assert item.text is None
    assert store.read("sess-ingest", item.content_ref) == PNG
    assert _stage(store).input_id == item.input_id


@pytest.mark.parametrize(
    "display_name",
    [
        "../pattern.png",
        "dir/pattern.png",
        "dir\\pattern.png",
        "C:pattern.png",
        ".hidden.png",
        "a\x00.png",
    ],
)
def test_unsafe_display_names_are_rejected_and_nothing_is_stored(display_name: str) -> None:
    store = SessionContentStore()
    with pytest.raises(IngestionError, match="input validation"):
        _stage(store, display_name=display_name)
    assert store.reference_count("sess-ingest") == 0


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"display_name": "pattern.jpg"}, IngestionError),
        ({"data": b""}, IngestionError),
        ({"media_type": "image/jpeg", "display_name": "pattern.jpg"}, MediaMismatchError),
        ({"modality": Modality.AUDIO, "media_type": "audio/wav"}, UnsupportedMediaError),
        ({"modality": Modality.TEXT, "media_type": "text/plain"}, UnsupportedMediaError),
        ({"budget": ResourceBudget(max_image_bytes=len(PNG) - 1)}, InputLimitError),
    ],
)
def test_invalid_uploads_are_rejected_before_storage(
    overrides: dict[str, object], error: type[Exception]
) -> None:
    store = SessionContentStore()
    with pytest.raises(error):
        _stage(store, **overrides)
    assert store.reference_count("sess-ingest") == 0


def test_document_budget_applies_to_documents() -> None:
    store = SessionContentStore()
    with pytest.raises(InputLimitError) as caught:
        _stage(
            store,
            modality=Modality.DOCUMENT,
            media_type="application/pdf",
            display_name="report.pdf",
            data=PDF,
            budget=ResourceBudget(max_document_bytes=len(PDF) - 1),
        )
    assert caught.value.code is ErrorCode.LIMIT_EXCEEDED
