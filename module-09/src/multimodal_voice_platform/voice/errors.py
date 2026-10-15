"""Intentional failures at the voice assistant's session, turn, and state boundaries (Story 9.6).

Reasoning-provider failures reuse the Story 9.5 errors (``crossmodal.errors``) and speech failures
are reported inside the embedded Story 9.4 records, so a voice turn names one error vocabulary.
"""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class VoiceConfigurationError(Module9Error):
    """Raised when application code wires the assistant in a way it cannot honestly record.

    This signals a defect in application code, not untrusted input, so it is raised rather than
    recorded.
    """


class LiveVoiceUnavailableError(Module9Error):
    """Raised when a live session is started or used. Live voice providers are Story 9.8."""

    code = ErrorCode.LIVE_MODE_NOT_AUTHORIZED


class VoiceSessionError(Module9Error):
    """Base class for rejected session operations. The session ID is correlation, not identity."""

    code = ErrorCode.INPUT_REJECTED


class UnknownSessionError(VoiceSessionError):
    """Raised when a session ID does not name an active conversation in this assistant."""


class DuplicateSessionError(VoiceSessionError):
    """Raised when a conversation with the same session ID is already active."""


class SessionBusyError(VoiceSessionError):
    """Raised when a turn arrives while another turn of the same session is still running."""


class SessionExpiredError(VoiceSessionError):
    """Raised when a session has outlived its application-configured session timeout."""

    code = ErrorCode.LIMIT_EXCEEDED


class DuplicateTurnError(VoiceSessionError):
    """Raised when a turn ID was already committed in the session (replay protection)."""


class ConversationLimitError(VoiceSessionError):
    """Raised when a session or the assistant has reached a conversation bound."""

    code = ErrorCode.LIMIT_EXCEEDED


class TurnBudgetExhaustedError(VoiceSessionError):
    """Raised when a turn would exceed the session's provider-call budget."""

    code = ErrorCode.BUDGET_EXHAUSTED


class TranscriptRejectedError(Module9Error):
    """Raised when a transcript is empty, oversized, or not safe to carry into conversation."""

    code = ErrorCode.INPUT_REJECTED


class ReplyRejectedError(Module9Error):
    """Raised when a reasoning reply is valid output but exceeds the assistant's reply bounds."""

    code = ErrorCode.LIMIT_EXCEEDED


class StateCommitError(Module9Error):
    """Raised when a completed turn cannot be committed because the session changed under it."""

    code = ErrorCode.INTERNAL_ERROR
