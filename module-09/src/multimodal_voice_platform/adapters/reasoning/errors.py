"""Intentional failures raised by the deterministic reasoning adapter (Story 9.5)."""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class ReasoningInputError(Module9Error):
    """Raised when a reasoning request's parts are not observation documents the rules can read."""

    code = ErrorCode.INPUT_REJECTED
