"""Safe structured errors for the Module 9 application and streaming boundaries."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

SafeMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class ErrorCode(StrEnum):
    """Stable error codes that may cross the application boundary."""

    INPUT_REJECTED = "input_rejected"
    UNSUPPORTED_MODALITY = "unsupported_modality"
    LIMIT_EXCEEDED = "limit_exceeded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    LIVE_MODE_NOT_AUTHORIZED = "live_mode_not_authorized"
    PROTOCOL_ERROR = "protocol_error"
    INTERNAL_ERROR = "internal_error"


class SafeError(BaseModel):
    """Error payload safe to show users: no stack traces, secrets, or raw provider output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: SafeMessage
    retryable: bool = False


class Module9Error(Exception):
    """Base class for intentional Module 9 failures.

    Attributes:
        code: Stable error code for the failure.
        safe_message: Message that is safe to show outside the application.
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, safe_message: str) -> None:
        """Create the error.

        Args:
            safe_message: Message that is safe to show outside the application.
        """
        super().__init__(safe_message)
        self.safe_message = safe_message

    def to_safe_error(self, *, retryable: bool = False) -> SafeError:
        """Convert the error into a boundary-safe payload.

        Args:
            retryable: Whether the client may retry the operation.

        Returns:
            The safe error payload.
        """
        return SafeError(code=self.code, message=self.safe_message, retryable=retryable)


class StreamProtocolError(Module9Error):
    """Raised when a streaming message violates the typed protocol."""

    code = ErrorCode.PROTOCOL_ERROR
