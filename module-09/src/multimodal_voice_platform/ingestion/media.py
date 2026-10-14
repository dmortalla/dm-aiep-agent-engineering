"""Content sniffing: verify that untrusted bytes really are the declared media type (SEC-003).

Binary formats are identified by their magic bytes. Text formats have no signature, so they must
decode as UTF-8 text without NUL or other non-text control characters and must not carry a known
binary signature. The declared media type is never trusted on its own.
"""

from typing import Final

from multimodal_voice_platform.contracts.modality import MEDIA_TYPES, Modality
from multimodal_voice_platform.ingestion.errors import MediaMismatchError, UnsupportedMediaError

TEXT_MEDIA_TYPES: Final = frozenset({"text/markdown", "text/plain"})
"""Document media types that are UTF-8 text rather than a binary container."""

_UTF8_BOM: Final = b"\xef\xbb\xbf"
_ALLOWED_TEXT_CONTROLS: Final = frozenset("\t\n\r\f")
_BINARY_SIGNATURES: Final = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"%PDF-",
    b"PK\x03\x04",
    b"\x7fELF",
)
"""Signatures that disqualify content declared as text (others fail the control-character check)."""


def sniff_binary_media_type(data: bytes) -> str | None:
    """Identify an allowlisted binary media type from its magic bytes.

    Args:
        data: Untrusted content bytes.

    Returns:
        ``image/png``, ``image/jpeg``, ``image/webp``, or ``application/pdf`` when the signature
        matches, otherwise ``None``.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def decode_text_content(data: bytes) -> str:
    """Decode untrusted text content strictly.

    A leading UTF-8 byte order mark is removed. Everything else must be valid UTF-8 with no NUL or
    other control characters apart from tab, newline, carriage return, and form feed.

    Args:
        data: Untrusted content bytes.

    Returns:
        The decoded text.

    Raises:
        MediaMismatchError: If the content carries a binary signature, is not valid UTF-8, or
            contains forbidden control characters.
    """
    if data.startswith(_BINARY_SIGNATURES):
        raise MediaMismatchError("text content carries a binary file signature")
    try:
        text = data.removeprefix(_UTF8_BOM).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MediaMismatchError("text content is not valid UTF-8") from exc
    for char in text:
        code = ord(char)
        if (code < 32 or code == 127) and char not in _ALLOWED_TEXT_CONTROLS:
            raise MediaMismatchError("text content contains binary control characters")
    return text


def verify_media_content(modality: Modality, media_type: str, data: bytes) -> None:
    """Confirm that content matches its declared, allowlisted media type.

    Args:
        modality: Modality the content was submitted as.
        media_type: Declared media type.
        data: Untrusted content bytes.

    Raises:
        UnsupportedMediaError: If the media type is not allowlisted for the modality.
        MediaMismatchError: If the bytes do not match the declared media type.
    """
    if media_type not in MEDIA_TYPES[modality]:
        raise UnsupportedMediaError(f"media type is not supported for {modality} input")
    if media_type in TEXT_MEDIA_TYPES:
        decode_text_content(data)
        return
    sniffed = sniff_binary_media_type(data)
    if sniffed != media_type:
        raise MediaMismatchError("content does not match the declared media type")
