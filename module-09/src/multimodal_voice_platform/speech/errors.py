"""Intentional failures at the speech pipeline's provider and configuration boundaries."""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class SpeechConfigurationError(Module9Error):
    """Raised when application code wires the pipeline in a way it cannot honestly record.

    This signals a defect in application code, not untrusted input, so it is raised rather than
    recorded.
    """


class LiveSpeechUnavailableError(Module9Error):
    """Raised when a live session requests speech processing. Live adapters are Story 9.8."""

    code = ErrorCode.LIVE_MODE_NOT_AUTHORIZED


class SpeechProviderUnavailableError(Module9Error):
    """Raised by a speech adapter whose provider cannot serve the request. Retryable.

    Adapters translate their own provider failures into this error so that no raw provider
    exception or message crosses the pipeline boundary.
    """

    code = ErrorCode.PROVIDER_UNAVAILABLE


class SpeechProviderTimeoutError(Module9Error):
    """Raised when a speech provider call exceeds the request timeout. Retryable."""

    code = ErrorCode.PROVIDER_TIMEOUT


class SpeechProviderOutputError(Module9Error):
    """Raised when a speech provider returns output that violates the port contract."""

    code = ErrorCode.PROVIDER_UNAVAILABLE
