"""Validate untrusted text submitted for speech synthesis as a text ``ModalityInput``."""

import hashlib
from typing import Final

from pydantic import ValidationError

from multimodal_voice_platform.contracts.limits import MAX_TEXT_CHARS
from multimodal_voice_platform.contracts.modality import InputSource, Modality, ModalityInput
from multimodal_voice_platform.ingestion.errors import IngestionError, InputLimitError

_ALLOWED_CONTROLS: Final = frozenset("\t\n\r")


def stage_text_input(
    session_id: str, text: str, *, source: InputSource = InputSource.USER_TEXT
) -> ModalityInput:
    """Validate untrusted text and normalize it into an inline text input.

    Args:
        session_id: Session that owns the input.
        text: Untrusted text.
        source: Where the text came from.

    Returns:
        The validated, untrusted text input.

    Raises:
        InputLimitError: If the text exceeds the hard text ceiling.
        IngestionError: If the text is blank, contains control characters or unencodable
            characters, or fails input contract validation.
    """
    if len(text) > MAX_TEXT_CHARS:
        raise InputLimitError(f"text exceeds the {MAX_TEXT_CHARS}-character limit")
    if not text.strip():
        raise IngestionError("text for synthesis is empty")
    for char in text:
        code = ord(char)
        if (code < 32 or 127 <= code < 160) and char not in _ALLOWED_CONTROLS:
            raise IngestionError("text contains control characters")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise IngestionError("text contains characters that cannot be encoded as UTF-8") from exc
    try:
        return ModalityInput(
            input_id=f"input-{hashlib.sha256(encoded).hexdigest()[:16]}",
            session_id=session_id,
            modality=Modality.TEXT,
            media_type="text/plain",
            source=source,
            size_bytes=len(encoded),
            text=text,
        )
    except ValidationError as exc:
        raise IngestionError("text failed input validation") from exc
