"""Ingestion boundary for untrusted image and document uploads (Story 9.3, ADR-009-006).

Validates modality, media type, content signature, size budget, and display name before any
content is stored or processed.
"""

from multimodal_voice_platform.ingestion.errors import (
    IngestionError,
    InputLimitError,
    MediaMismatchError,
    UnsupportedMediaError,
)
from multimodal_voice_platform.ingestion.media import (
    decode_text_content,
    sniff_binary_media_type,
    verify_media_content,
)
from multimodal_voice_platform.ingestion.staging import STAGEABLE_MODALITIES, stage_content

__all__ = [
    "STAGEABLE_MODALITIES",
    "IngestionError",
    "InputLimitError",
    "MediaMismatchError",
    "UnsupportedMediaError",
    "decode_text_content",
    "sniff_binary_media_type",
    "stage_content",
    "verify_media_content",
]
