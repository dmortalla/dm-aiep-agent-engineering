"""Normalized, validated multimodal input contracts (ADR-009-006, ADR-009-007)."""

from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Annotated, Final, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from multimodal_voice_platform.contracts.limits import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_DURATION_MS,
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_PAGES,
    MAX_IMAGE_BYTES,
    MAX_TEXT_CHARS,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
"""Opaque lowercase identifier. Never a filesystem path or URL."""

_FORBIDDEN_NAME_CHARS: Final = frozenset('/\\:*?"<>|')


class Modality(StrEnum):
    """Supported input modalities."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"


class TrustLevel(StrEnum):
    """Trust classification. Only application code and configuration are trusted."""

    UNTRUSTED_EXTERNAL = "untrusted_external"
    UNTRUSTED_MODEL_OUTPUT = "untrusted_model_output"
    APPLICATION = "application"


UNTRUSTED_LEVELS: Final = frozenset(
    {TrustLevel.UNTRUSTED_EXTERNAL, TrustLevel.UNTRUSTED_MODEL_OUTPUT}
)


class InputSource(StrEnum):
    """Where an input came from."""

    USER_UPLOAD = "user_upload"
    USER_MICROPHONE = "user_microphone"
    USER_TEXT = "user_text"
    DETERMINISTIC_FIXTURE = "deterministic_fixture"


MEDIA_TYPES: Final = MappingProxyType(
    {
        Modality.TEXT: MappingProxyType({"text/plain": frozenset({".txt"})}),
        Modality.IMAGE: MappingProxyType(
            {
                "image/png": frozenset({".png"}),
                "image/jpeg": frozenset({".jpg", ".jpeg"}),
                "image/webp": frozenset({".webp"}),
            }
        ),
        Modality.AUDIO: MappingProxyType(
            {
                "audio/wav": frozenset({".wav"}),
                "audio/mpeg": frozenset({".mp3"}),
                "audio/webm": frozenset({".webm"}),
            }
        ),
        Modality.DOCUMENT: MappingProxyType(
            {
                "application/pdf": frozenset({".pdf"}),
                "text/markdown": frozenset({".md"}),
                "text/plain": frozenset({".txt"}),
            }
        ),
    }
)
"""Allowlist of media types per modality, each with its permitted file extensions."""

MAX_INPUT_BYTES: Final = MappingProxyType(
    {
        Modality.TEXT: MAX_TEXT_CHARS * 4,
        Modality.IMAGE: MAX_IMAGE_BYTES,
        Modality.AUDIO: MAX_AUDIO_BYTES,
        Modality.DOCUMENT: MAX_DOCUMENT_BYTES,
    }
)
"""Hard byte ceiling per modality. Configurable budgets must stay at or below these."""


class ModalityInput(BaseModel):
    """A validated, normalized input. Always untrusted, whatever it contains.

    Text is carried inline. Binary content (image, audio, document) is carried by an opaque
    ``content_ref`` issued by the application, never by a caller-supplied path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_id: Identifier
    session_id: Identifier
    modality: Modality
    media_type: str
    source: InputSource
    trust: TrustLevel = TrustLevel.UNTRUSTED_EXTERNAL
    size_bytes: int = Field(gt=0)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    content_ref: Identifier | None = None
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT_CHARS)
    duration_ms: int | None = Field(default=None, gt=0)
    page_count: int | None = Field(default=None, gt=0)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        """Reject filenames that could act as paths or carry control characters.

        Args:
            value: Display name supplied with the input.

        Returns:
            The unchanged display name.

        Raises:
            ValueError: If the name contains path separators, traversal, reserved characters,
                control characters, or starts with a dot.
        """
        if value is None:
            return value
        if any(char in _FORBIDDEN_NAME_CHARS for char in value):
            raise ValueError("display_name must not contain path separators or reserved characters")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("display_name must not contain control characters")
        if value.startswith(".") or ".." in value:
            raise ValueError("display_name must not start with a dot or contain '..'")
        return value

    @model_validator(mode="after")
    def validate_input(self) -> Self:
        """Enforce trust, media type, extension, content, and size invariants.

        Returns:
            The validated input.

        Raises:
            ValueError: If any invariant fails. Validation fails closed and never guesses.
        """
        if self.trust is not TrustLevel.UNTRUSTED_EXTERNAL:
            raise ValueError("external input must be classified untrusted_external")
        allowed = MEDIA_TYPES[self.modality]
        if self.media_type not in allowed:
            raise ValueError(f"media type {self.media_type!r} is not allowed for {self.modality}")
        if self.display_name is not None:
            suffix = PurePosixPath(self.display_name).suffix.lower()
            if suffix not in allowed[self.media_type]:
                raise ValueError("display_name extension does not match media type")
        if self.size_bytes > MAX_INPUT_BYTES[self.modality]:
            raise ValueError(f"{self.modality} input exceeds the hard size ceiling")
        self._validate_content()
        self._validate_modality_metadata()
        return self

    def _validate_content(self) -> None:
        if self.modality is Modality.TEXT:
            if self.text is None or self.content_ref is not None:
                raise ValueError("text input requires inline text and no content_ref")
            if self.size_bytes != len(self.text.encode("utf-8")):
                raise ValueError("size_bytes must equal the UTF-8 length of text")
        elif self.content_ref is None or self.text is not None:
            raise ValueError(f"{self.modality} input requires content_ref and no inline text")

    def _validate_modality_metadata(self) -> None:
        if self.modality is Modality.AUDIO:
            if self.duration_ms is None:
                raise ValueError("audio input requires duration_ms")
            if self.duration_ms > MAX_AUDIO_DURATION_MS:
                raise ValueError("audio input exceeds the hard duration ceiling")
        elif self.duration_ms is not None:
            raise ValueError("duration_ms applies only to audio input")
        if self.modality is Modality.DOCUMENT:
            if self.page_count is not None and self.page_count > MAX_DOCUMENT_PAGES:
                raise ValueError("document input exceeds the hard page ceiling")
        elif self.page_count is not None:
            raise ValueError("page_count applies only to document input")
