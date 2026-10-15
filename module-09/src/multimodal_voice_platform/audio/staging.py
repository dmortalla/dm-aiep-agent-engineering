"""Validate untrusted audio bytes and stage them as an audio ``ModalityInput`` (ADR-009-006).

The audio counterpart of the Story 9.3 image and document ingestion boundary. It checks the media
type, content signature, WAV structure, byte budget, and duration budget, and validates the
normalized input contract (including the safe display name) before the bytes are stored. The
duration comes from the parsed header, never from the caller. Rejected content is never stored.
"""

import hashlib
from typing import Final

from pydantic import ValidationError

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.audio.analysis import enforce_audio_limits
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.audio.wav import parse_wav, verify_audio_content
from multimodal_voice_platform.contracts.modality import InputSource, Modality, ModalityInput
from multimodal_voice_platform.ingestion.errors import IngestionError, InputLimitError

_PENDING_REF: Final = "ref-pending"


def stage_audio_content(
    store: SessionContentStore,
    *,
    session_id: str,
    limits: AudioLimits,
    media_type: str,
    display_name: str,
    data: bytes,
    source: InputSource = InputSource.USER_UPLOAD,
) -> ModalityInput:
    """Validate untrusted audio bytes and stage them for one session.

    Args:
        store: Session-scoped content store that will hold accepted bytes.
        session_id: Session that owns the content.
        limits: Application-owned audio limits.
        media_type: Declared media type. Verified against the content, never trusted alone.
        display_name: Untrusted display name. Must be a safe file name whose extension matches.
        data: Untrusted audio bytes.
        source: Where the content came from.

    Returns:
        The validated, untrusted audio input, carrying an opaque content reference and the
        duration measured from the WAV header.

    Raises:
        UnsupportedMediaError: If the media type is not decodable audio.
        MediaMismatchError: If the bytes do not match the declared media type.
        MalformedAudioError: If the WAV container is malformed or truncated.
        UnsupportedAudioError: If the WAV encoding or parameters are unsupported.
        InputLimitError: If the audio exceeds the byte or duration budget.
        IngestionError: If the content is empty or fails input contract validation.
    """
    if not data:
        raise IngestionError("uploaded audio is empty")
    if len(data) > limits.max_audio_bytes:
        raise InputLimitError("audio content exceeds the session byte budget")
    verify_audio_content(media_type, data)
    layout = parse_wav(data)
    enforce_audio_limits(layout, len(data), limits)
    input_id = f"input-{hashlib.sha256(data).hexdigest()[:16]}"
    try:
        candidate = ModalityInput(
            input_id=input_id,
            session_id=session_id,
            modality=Modality.AUDIO,
            media_type=media_type,
            source=source,
            size_bytes=len(data),
            display_name=display_name,
            content_ref=_PENDING_REF,
            duration_ms=layout.duration_ms,
        )
    except ValidationError as exc:
        raise IngestionError("audio upload failed input validation") from exc
    content_ref = store.put(session_id, input_id, data)
    return candidate.model_copy(update={"content_ref": content_ref})
