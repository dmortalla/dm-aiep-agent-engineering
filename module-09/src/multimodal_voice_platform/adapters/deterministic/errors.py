"""Intentional failures raised by the deterministic foundation."""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class DeterministicInputError(Module9Error):
    """Raised when a deterministic request or fixture is invalid or not recognized."""

    code = ErrorCode.INPUT_REJECTED


class UnknownFixtureError(DeterministicInputError):
    """Raised when a fixture ID is not in the committed fixture catalog."""


class FixtureIntegrityError(DeterministicInputError):
    """Raised when committed fixture data does not match its manifest."""

    code = ErrorCode.INTERNAL_ERROR


class FixtureBudgetError(DeterministicInputError):
    """Raised when a fixture exceeds the session resource budget."""

    code = ErrorCode.LIMIT_EXCEEDED


class ContentNotFoundError(DeterministicInputError):
    """Raised when a content reference is unknown or was released with its session."""
