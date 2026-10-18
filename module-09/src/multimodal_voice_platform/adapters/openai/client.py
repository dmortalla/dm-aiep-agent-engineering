"""OpenAI client construction, failure translation, and call evidence (Story 9.8).

Everything OpenAI-specific about talking to the provider lives in ``adapters/openai``. Clients are
created per provider call, inside ``async with``, with:

- the key passed explicitly from the live session (never read from the environment here);
- the fixed official endpoint (no configurable or user-supplied base URL, so no SSRF surface);
- ``max_retries=0``: the application never retries a paid call automatically;
- the configured request timeout.

A test may inject an ``httpx2`` transport. That transport is trusted, internal wiring: an adapter
built with one reports ``real_endpoint = False``, so its runs can only ever be ``automated_test``
evidence.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final, NoReturn

import httpx2
import openai
from pydantic import SecretStr, ValidationError

from multimodal_voice_platform.contracts.errors import Module9Error
from multimodal_voice_platform.contracts.live import LiveCall, LiveCapability, ProviderUsage
from multimodal_voice_platform.contracts.providers import ProviderDescriptor, ProviderPort
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.live.config import LiveProviderConfig
from multimodal_voice_platform.live.errors import (
    LiveBudgetError,
    LiveProviderError,
    ProviderAuthenticationError,
    ProviderOutputError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderRequestRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

OPENAI_API_BASE: Final = "https://api.openai.com/v1"
"""The only endpoint the adapters use. Not configurable."""
PROVIDER_FAMILY: Final = "openai"
_REQUEST_ID_CHARS: Final = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def safe_request_id(value: object) -> str | None:
    """Keep a provider request identifier only if it is a short plain token.

    Args:
        value: Candidate identifier from a response header or body.

    Returns:
        The identifier, or ``None`` if it is absent or not a plain token.
    """
    if isinstance(value, str) and 0 < len(value) <= 128 and set(value) <= _REQUEST_ID_CHARS:
        return value
    return None


def translate(exc: BaseException) -> LiveProviderError:
    """Translate a provider or transport exception into a sanitized application error.

    Args:
        exc: The exception raised by the SDK or its transport.

    Returns:
        A ``LiveProviderError`` with a fixed message and non-secret diagnostics only.
    """
    status = getattr(exc, "status_code", None)
    status = status if isinstance(status, int) else None
    request_id = safe_request_id(getattr(exc, "request_id", None))
    details = {"status_code": status, "request_id": request_id}
    if isinstance(exc, openai.AuthenticationError):
        return ProviderAuthenticationError("the live provider rejected the API key", **details)
    if isinstance(exc, openai.PermissionDeniedError | openai.NotFoundError):
        return ProviderPermissionError(
            "the API key cannot use the configured model or operation", **details
        )
    if isinstance(exc, openai.RateLimitError):
        return ProviderRateLimitError(
            "the live provider rate-limited the request or the account has no quota", **details
        )
    if isinstance(exc, openai.APITimeoutError | TimeoutError):
        return ProviderTimeoutError("the live provider did not respond in time", **details)
    if isinstance(exc, openai.APIConnectionError | httpx2.TransportError):
        return ProviderUnavailableError("the live provider could not be reached", **details)
    if isinstance(exc, openai.BadRequestError | openai.UnprocessableEntityError):
        return ProviderRequestRejectedError(
            "the live provider rejected the request as invalid", **details
        )
    if isinstance(exc, openai.APIResponseValidationError | ValidationError | ValueError):
        return ProviderOutputError("the live provider returned a malformed response", **details)
    if isinstance(exc, openai.APIStatusError):
        return ProviderUnavailableError(
            "the live provider failed to complete the request", **details
        )
    return ProviderUnavailableError("the live provider call failed", **details)


def usage_from(usage: object) -> ProviderUsage | None:
    """Map provider usage onto bounded, provider-neutral quantities.

    Args:
        usage: The SDK usage object, or ``None``.

    Returns:
        Provider-neutral usage, or ``None`` when nothing usable was reported.
    """
    if usage is None:
        return None

    def number(owner: object, name: str) -> int | None:
        value = getattr(owner, name, None)
        return value if isinstance(value, int) and value >= 0 else None

    details = getattr(usage, "output_tokens_details", None)
    seconds = getattr(usage, "seconds", None)
    try:
        return ProviderUsage(
            input_tokens=number(usage, "input_tokens"),
            output_tokens=number(usage, "output_tokens"),
            reasoning_tokens=number(details, "reasoning_tokens") if details is not None else None,
            total_tokens=number(usage, "total_tokens"),
            audio_seconds=float(seconds) if isinstance(seconds, int | float) else None,
        )
    except ValidationError:
        return None


class OpenAIAdapter:
    """Shared machinery of every OpenAI adapter: client, call budget, and call evidence."""

    capability: LiveCapability
    port: ProviderPort

    def __init__(
        self,
        credential: SecretStr,
        config: LiveProviderConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the adapter for one live operation.

        Args:
            credential: The live session's key. Held only by this adapter instance.
            config: Application-owned live configuration.
            transport: Trusted test transport. When given, the adapter is a contract test double
                and ``real_endpoint`` is ``False``.
        """
        if not isinstance(credential, SecretStr):
            raise TypeError("live adapters take the key as a SecretStr")
        self._credential = credential
        self._config = config
        self._transport = transport
        self._calls: list[LiveCall] = []
        self._descriptor = ProviderDescriptor(
            provider_id=f"{PROVIDER_FAMILY}-{self.capability.value.replace('_', '-')}",
            port=self.port,
            mode=ExecutionMode.LIVE,
        )

    def __repr__(self) -> str:
        """Describe the adapter without its credential."""
        return f"{type(self).__name__}(real_endpoint={self.real_endpoint})"

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter: its ID, port, and live execution."""
        return self._descriptor

    @property
    def real_endpoint(self) -> bool:
        """Whether this adapter talks to the real provider endpoint."""
        return self._transport is None

    @property
    def live_calls(self) -> tuple[LiveCall, ...]:
        """The provider calls this adapter instance made."""
        return tuple(self._calls)

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[openai.AsyncOpenAI]:
        """Create a provider client for one call and close it afterwards."""
        http_client = (
            httpx2.AsyncClient(transport=self._transport) if self._transport is not None else None
        )
        client = openai.AsyncOpenAI(
            api_key=self._credential.get_secret_value(),
            base_url=OPENAI_API_BASE,
            timeout=self._config.request_timeout_s,
            max_retries=0,
            http_client=http_client,
        )
        try:
            yield client
        finally:
            await client.close()

    def _check_budget(self) -> None:
        """Refuse a call beyond the operation's provider-call budget, before any request."""
        if len(self._calls) >= self._config.max_calls_per_adapter:
            raise LiveBudgetError("the live operation reached its provider-call budget")

    def _record(
        self,
        model: str,
        started: float,
        *,
        error: Module9Error | None = None,
        request_id: str | None = None,
        usage: ProviderUsage | None = None,
        streamed: bool = False,
        first_output: float | None = None,
        events: int = 0,
        cancelled: bool = False,
    ) -> None:
        now = time.perf_counter()
        self._calls.append(
            LiveCall(
                provider_family=PROVIDER_FAMILY,
                capability=self.capability,
                model=model,
                real_endpoint=self.real_endpoint,
                streamed=streamed,
                outcome=(
                    "cancelled" if cancelled else "failed" if error is not None else "succeeded"
                ),
                failure=error.code if error is not None else None,
                request_id=safe_request_id(request_id),
                usage=usage,
                latency_ms=round(max(0.0, (now - started) * 1000), 3),
                first_output_ms=(
                    round(max(0.0, (first_output - started) * 1000), 3)
                    if first_output is not None
                    else None
                ),
                output_events=min(events, 100_000),
            )
        )

    def _amend_failure(self, error: LiveProviderError) -> LiveProviderError:
        """Mark the last completed call failed when its output is rejected after it finished."""
        if self._calls and self._calls[-1].outcome == "succeeded":
            self._calls[-1] = self._calls[-1].model_copy(
                update={"outcome": "failed", "failure": error.code}
            )
        return error

    def _fail(self, model: str, started: float, exc: BaseException) -> NoReturn:
        """Record a failed call and raise its sanitized translation."""
        error = exc if isinstance(exc, LiveProviderError) else translate(exc)
        self._record(model, started, error=error, request_id=error.request_id)
        raise error from None


def output_refused(response: Any) -> bool:
    """Whether a Responses API result contains a refusal instead of output text.

    Args:
        response: The SDK response object.

    Returns:
        ``True`` if any output content part is a refusal.
    """
    for item in getattr(response, "output", None) or ():
        for part in getattr(item, "content", None) or ():
            if getattr(part, "type", None) == "refusal":
                return True
    return False
