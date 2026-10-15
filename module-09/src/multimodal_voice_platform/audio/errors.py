"""Intentional failures raised while validating and processing untrusted audio (Story 9.4)."""

from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.ingestion.errors import IngestionError


class MalformedAudioError(IngestionError):
    """Raised when audio bytes are not a well-formed container of their declared type."""


class UnsupportedAudioError(IngestionError):
    """Raised for well-formed audio that uses an unsupported encoding or parameter."""


class AudioProcessingTimeoutError(IngestionError):
    """Raised when local audio decoding and measurement exceed the request timeout."""

    code = ErrorCode.PROVIDER_TIMEOUT
