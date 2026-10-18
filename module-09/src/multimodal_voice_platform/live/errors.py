"""Stable, sanitized live-provider failures (Story 9.8).

Adapters translate every provider exception into one of these before it crosses the adapter
boundary. Messages are fixed application text: they never include provider messages, HTTP bodies,
request payloads, or credentials, and the provider exception is not chained (SDK messages can
echo parts of a credential or a request body). Non-secret diagnostics travel as attributes.
"""

from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error


class LiveConfigurationError(Module9Error):
    """Raised when application code wires live providers in a way it cannot honestly record.

    This signals a defect in application code, not untrusted input, so it is raised rather than
    recorded. Examples: a binding that claims real-provider evidence over a test transport.
    """


class LiveCredentialError(Module9Error):
    """Raised when live mode is selected without a usable credential. Fails closed."""

    code = ErrorCode.LIVE_MODE_NOT_AUTHORIZED


class LiveProviderError(Module9Error):
    """Base class for translated provider failures.

    Attributes:
        status_code: The provider's HTTP status, when there was one.
        request_id: The provider's request identifier, when one was returned.
    """

    code = ErrorCode.PROVIDER_UNAVAILABLE

    def __init__(
        self, safe_message: str, *, status_code: int | None = None, request_id: str | None = None
    ) -> None:
        """Create the error.

        Args:
            safe_message: Fixed application message, safe to show.
            status_code: Provider HTTP status, if any.
            request_id: Provider request identifier, if any.
        """
        super().__init__(safe_message)
        self.status_code = status_code
        self.request_id = request_id


class ProviderAuthenticationError(LiveProviderError):
    """The provider rejected the credential."""

    code = ErrorCode.PROVIDER_AUTHENTICATION_FAILED


class ProviderPermissionError(LiveProviderError):
    """The credential cannot use the configured model or operation."""

    code = ErrorCode.PROVIDER_PERMISSION_DENIED


class ProviderRateLimitError(LiveProviderError):
    """The provider throttled the request or the account has no remaining quota."""

    code = ErrorCode.PROVIDER_RATE_LIMITED


class ProviderTimeoutError(LiveProviderError):
    """The provider did not respond within the configured timeout."""

    code = ErrorCode.PROVIDER_TIMEOUT


class ProviderUnavailableError(LiveProviderError):
    """The provider or the network path to it is unavailable."""

    code = ErrorCode.PROVIDER_UNAVAILABLE


class ProviderRequestRejectedError(LiveProviderError):
    """The provider rejected the request as invalid (for example unsupported media)."""

    code = ErrorCode.INPUT_REJECTED


class ProviderOutputError(LiveProviderError):
    """The provider's response was malformed, incomplete, or failed local validation."""

    code = ErrorCode.PROVIDER_UNAVAILABLE


class ProviderRefusalError(LiveProviderError):
    """The provider refused to produce the requested content."""

    code = ErrorCode.PROVIDER_REFUSED


class LiveBudgetError(LiveProviderError):
    """A live operation would exceed its application-owned call, size, or time budget."""

    code = ErrorCode.BUDGET_EXHAUSTED
