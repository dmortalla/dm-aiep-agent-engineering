"""Validate untrusted image and document bytes and stage them as ``ModalityInput`` (ADR-009-006).

Staging is the ingestion boundary for Story 9.3. It checks modality, media type, content
signature, and session byte budget, then validates the normalized input contract, and only then
places the bytes in the session-scoped content store. Rejected content is never stored.
"""

import hashlib
from typing import Final

from pydantic import ValidationError

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import InputSource, Modality, ModalityInput
from multimodal_voice_platform.ingestion.errors import (
    IngestionError,
    InputLimitError,
    UnsupportedMediaError,
)
from multimodal_voice_platform.ingestion.media import verify_media_content

STAGEABLE_MODALITIES: Final = frozenset({Modality.IMAGE, Modality.DOCUMENT})
"""Modalities this ingestion path accepts. Audio ingestion belongs to Story 9.4."""

_PENDING_REF: Final = "ref-pending"


def _byte_budget(modality: Modality, budget: ResourceBudget) -> int:
    return budget.max_image_bytes if modality is Modality.IMAGE else budget.max_document_bytes


def stage_content(
    store: SessionContentStore,
    *,
    session_id: str,
    budget: ResourceBudget,
    modality: Modality,
    media_type: str,
    display_name: str,
    data: bytes,
    source: InputSource = InputSource.USER_UPLOAD,
) -> ModalityInput:
    """Validate untrusted bytes and stage them for one session.

    Args:
        store: Session-scoped content store that will hold accepted bytes.
        session_id: Session that owns the content.
        budget: Application-owned session budget.
        modality: Modality the content is submitted as (image or document).
        media_type: Declared media type. Verified against the content, never trusted alone.
        display_name: Untrusted display name. Must be a safe file name whose extension matches.
        data: Untrusted content bytes.
        source: Where the content came from.

    Returns:
        The validated, untrusted input, carrying an opaque content reference.

    Raises:
        UnsupportedMediaError: If the modality or media type is not supported.
        InputLimitError: If the content exceeds the session byte budget.
        MediaMismatchError: If the bytes do not match the declared media type.
        IngestionError: If the content is empty or fails input contract validation.
    """
    if modality not in STAGEABLE_MODALITIES:
        raise UnsupportedMediaError(f"{modality} input is not supported by this ingestion path")
    if not data:
        raise IngestionError("uploaded content is empty")
    if len(data) > _byte_budget(modality, budget):
        raise InputLimitError(f"{modality} content exceeds the session byte budget")
    verify_media_content(modality, media_type, data)
    input_id = f"input-{hashlib.sha256(data).hexdigest()[:16]}"
    try:
        candidate = ModalityInput(
            input_id=input_id,
            session_id=session_id,
            modality=modality,
            media_type=media_type,
            source=source,
            size_bytes=len(data),
            display_name=display_name,
            content_ref=_PENDING_REF,
        )
    except ValidationError as exc:
        raise IngestionError("upload failed input validation") from exc
    content_ref = store.put(session_id, input_id, data)
    return candidate.model_copy(update={"content_ref": content_ref})
