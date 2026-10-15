"""Intentional failures at the cross-modal workflow's request, context, and provider boundaries."""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class CrossModalConfigurationError(Module9Error):
    """Raised when application code wires the workflow in a way it cannot honestly record.

    This signals a defect in application code, not untrusted input, so it is raised rather than
    recorded.
    """


class CrossModalInputError(Module9Error):
    """Raised when a cross-modal request is malformed."""

    code = ErrorCode.INPUT_REJECTED


class CrossModalLimitError(CrossModalInputError):
    """Raised when a request or its reasoning context exceeds a workflow bound."""

    code = ErrorCode.LIMIT_EXCEEDED


class InsufficientModalitiesError(CrossModalInputError):
    """Raised when fewer than two distinct modalities are supplied or survive processing."""

    code = ErrorCode.UNSUPPORTED_MODALITY


class LiveReasoningUnavailableError(Module9Error):
    """Raised when a live session requests the workflow. Live adapters are Story 9.8."""

    code = ErrorCode.LIVE_MODE_NOT_AUTHORIZED


class ReasoningProviderUnavailableError(Module9Error):
    """Raised by a reasoning adapter whose provider cannot serve the request. Retryable.

    Adapters translate their own provider failures into this error so that no raw provider
    exception or message crosses the workflow boundary.
    """

    code = ErrorCode.PROVIDER_UNAVAILABLE


class ReasoningProviderTimeoutError(Module9Error):
    """Raised when the reasoning provider exceeds the request timeout. Retryable."""

    code = ErrorCode.PROVIDER_TIMEOUT


class ReasoningOutputError(Module9Error):
    """Raised when reasoning output violates the port contract or cites what does not exist."""

    code = ErrorCode.PROVIDER_UNAVAILABLE
