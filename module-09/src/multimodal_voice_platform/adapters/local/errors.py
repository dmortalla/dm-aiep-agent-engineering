"""Intentional failures raised by the local image and document processing adapters (Story 9.3)."""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class LocalProcessingError(Module9Error):
    """Raised when local processing rejects or cannot process an input."""

    code = ErrorCode.INPUT_REJECTED


class MalformedContentError(LocalProcessingError):
    """Raised when content cannot be decoded or parsed as its declared format."""


class UnsupportedContentError(LocalProcessingError):
    """Raised for well-formed content that uses an unsupported feature, such as encryption."""


class EmptyDocumentError(LocalProcessingError):
    """Raised when a document yields no extractable text."""


class ProcessingLimitError(LocalProcessingError):
    """Raised when content exceeds a processing limit such as pixels or pages."""

    code = ErrorCode.LIMIT_EXCEEDED


class ProcessingTimeoutError(LocalProcessingError):
    """Raised when local processing does not finish within the request timeout."""

    code = ErrorCode.PROVIDER_TIMEOUT
