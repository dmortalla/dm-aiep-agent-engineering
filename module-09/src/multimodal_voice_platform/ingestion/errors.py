"""Intentional failures raised while validating and staging untrusted uploads (Story 9.3)."""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class IngestionError(Module9Error):
    """Raised when an upload is rejected before any processing runs."""

    code = ErrorCode.INPUT_REJECTED


class UnsupportedMediaError(IngestionError):
    """Raised when a modality or media type is not supported by the ingestion path."""

    code = ErrorCode.UNSUPPORTED_MODALITY


class MediaMismatchError(IngestionError):
    """Raised when content bytes do not match the declared media type."""


class InputLimitError(IngestionError):
    """Raised when an upload exceeds the session resource budget."""

    code = ErrorCode.LIMIT_EXCEEDED
