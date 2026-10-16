"""Intentional failures of the streaming coordinator (Story 9.7).

Turn failures reuse the Story 9.4 to 9.6 error vocabulary, so a streamed turn and a synchronous
turn report the same codes for the same failure.
"""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class StreamingConfigurationError(Module9Error):
    """Raised when application code wires streaming in a way it cannot honestly record.

    This signals a defect in application code, not untrusted input, so it is raised rather than
    recorded.
    """


class StreamingInputError(Module9Error):
    """Raised when a streamed turn names something the server does not offer, such as a fixture."""

    code = ErrorCode.INPUT_REJECTED
