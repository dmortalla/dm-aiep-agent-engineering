"""Intentional failures raised by the deterministic speech adapters (Story 9.4)."""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class SynthesisInputError(Module9Error):
    """Raised when a synthesis request cannot be rendered, such as an unsupported voice."""

    code = ErrorCode.INPUT_REJECTED


class SynthesisLimitError(SynthesisInputError):
    """Raised when generated audio would exceed the session duration or byte budget."""

    code = ErrorCode.LIMIT_EXCEEDED
