"""Optional SDK adapters: text data only, no SDK retry or model-owned authority.

Imports/construction never request inference. Offline factories accept exact SDK
HTTP MockTransports and fixed dummy configuration. Live clients are constructed
only at invocation after trusted runtime opt-in; credentials alone do nothing.
"""

import importlib
import json
import re
from math import isfinite
from typing import Any

from pydantic import ValidationError

from harness_engineering.config import HarnessConfig
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    ContractValidationError,
    HarnessError,
)
from harness_engineering.providers import (
    ModelRequest,
    ProviderCallContext,
    ProviderExecutionError,
    ProviderOutputRejected,
    ProviderTimeoutError,
    _units,
)


class ProviderConfigurationError(ContractValidationError):
    """Missing optional dependency, invalid binding or missing SDK configuration."""


class ProviderRequestError(ProviderExecutionError):
    """Provider rejected a request; no automatic retry or raw SDK diagnostics."""


class ProviderUnavailableError(ProviderExecutionError):
    """Provider transport/service unavailable; consumed attempts remain consumed."""


class _SanitizedCause(Exception):
    """Fixed local category only; never retains the SDK error/request/response."""


def _load(name: str) -> Any:
    failure = False
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise  # A broken dependency/programming import is not optional absence.
        failure = True
    if failure:
        raise ProviderConfigurationError("Install the Module 6.5 providers extra.")
    return module


def _validate_binding(
    provider: object, config: HarnessConfig | None, budget: RuntimeBudget
) -> bool:
    if type(provider) not in (OpenAIProvider, AnthropicProvider):
        raise ContractValidationError("Bind the deterministic fake or an approved vendor adapter.")
    if provider._transport is not None:
        return False  # Exact MockTransport established at bootstrap; no socket path.
    try:
        value = HarnessConfig.model_validate(config.model_dump(), strict=True) if config else None
    except (ValidationError, AttributeError):
        value = None
    if (
        value is None
        or value.deterministic_mode
        or not value.allow_live_providers
        or value.budget != budget
        or budget.max_cost_usd is None
        or not isfinite(budget.max_cost_usd)
    ):
        raise AuthorityViolationError(
            "Live provider disabled; explicit application opt-in and monetary budget required."
        )
    return True


class _Vendor:
    """Trusted implementation shared by the two exact supported adapters."""

    _sdk: str
    _http: str
    _base_url: str

    def __init__(self, model: str, *, mock_transport: object | None = None) -> None:
        if (
            type(model) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model) is None
        ):
            raise ProviderConfigurationError("Bind a bounded application-owned model identifier.")
        self._model = model
        self._transport = mock_transport
        if mock_transport is not None:
            http = _load(self._http)
            if type(mock_transport) is not http.MockTransport:
                raise ProviderConfigurationError(
                    "Offline SDK testing requires an exact MockTransport."
                )

    def generate(self, request: ModelRequest, context: ProviderCallContext) -> object:
        """Invoke one SDK request after application checks and normalize text only.

        Expected SDK failures expose only fixed local categories. Unexpected
        programming defects propagate. SDK clients are call-local and closed;
        neither clients nor raw responses enter application result/state.
        """
        try:
            value = ModelRequest.model_validate(request)
        except ValidationError:
            raise ContractValidationError("Provider input violates ModelRequest.") from None
        context.checkpoint()
        if _units(value.prompt) > context._max_context_tokens:
            raise ContractValidationError("Provider input exceeds application context bound.")
        if self._transport is None and not context._live_allowed:
            raise AuthorityViolationError("Live provider invocation is not application-authorized.")
        sdk, http = _load(self._sdk), _load(self._http)
        configuration_error = sdk.OpenAIError if self._sdk == "openai" else sdk.AnthropicError
        raw: object = None
        failure: tuple[type[HarnessError], str] | None = None
        try:
            timeout = context.remaining_seconds
            with http.Client(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=timeout,
            ) as transport:
                options: dict[str, object] = {
                    "http_client": transport,
                    "base_url": self._base_url,
                    "max_retries": 0,
                    "timeout": timeout,
                }
                if self._transport is not None:
                    options["api_key"] = "module-06-5-offline-dummy"
                # Explicit ancillary settings avoid environment-derived alternate auth.
                if self._sdk == "openai":
                    options.update(admin_api_key="", organization="", project="", webhook_secret="")
                    client_type = sdk.OpenAI
                else:
                    options["webhook_key"] = ""
                    client_type = sdk.Anthropic
                with client_type(**options) as client:
                    context.checkpoint()
                    if self._sdk == "openai" and not client.api_key:
                        raise ProviderConfigurationError("OpenAI API-key configuration is absent.")
                    if (
                        self._sdk == "anthropic"
                        and client.api_key is None
                        and client.auth_token is None
                        and client.credentials is None
                    ):
                        # The SDK otherwise raises a generic TypeError at header construction.
                        # Check only absent configuration, not credential content or validity.
                        raise ProviderConfigurationError(
                            "Anthropic authentication is not configured."
                        )
                    raw = self._call(client, value, context)
        except sdk.APITimeoutError:
            failure = (ProviderTimeoutError, "SDK timeout; discard provider result.")
        except sdk.APIResponseValidationError:
            failure = (ProviderOutputRejected, "SDK response violates the supported profile.")
        except json.JSONDecodeError:
            failure = (ProviderOutputRejected, "SDK response contains malformed JSON.")
        except sdk.APIConnectionError:
            failure = (ProviderUnavailableError, "SDK transport unavailable; attempt consumed.")
        except sdk.APIStatusError as exc:
            failure = (
                (ProviderUnavailableError, "Provider service unavailable; attempt consumed.")
                if exc.status_code in (408, 409, 429) or exc.status_code >= 500
                else (
                    ProviderRequestError,
                    "Provider rejected request; check application configuration.",
                )
            )
        except configuration_error as exc:
            # Only the SDK's exact base configuration error is known here.
            if type(exc) is not configuration_error and not (
                self._sdk == "anthropic" and isinstance(exc, sdk.CredentialsError)
            ):
                raise
            failure = (
                ProviderConfigurationError,
                "SDK configuration unavailable; check provider setup.",
            )
        if failure is not None:
            # Raise outside the SDK except scope: no secret-bearing exception context survives.
            kind, message = failure
            raise kind(message) from _SanitizedCause(kind.__name__)
        context.checkpoint()
        response_type = sdk.types.responses.Response if self._sdk == "openai" else sdk.types.Message
        if type(raw) is not response_type:
            _reject()
        data = _payload(raw)
        text = self._text(data, context)
        if not text or _units(text) > context.max_output_tokens:
            raise ProviderOutputRejected("Provider text is empty or exceeds the application bound.")
        return {"text": text}

    def _call(self, client: Any, request: ModelRequest, context: ProviderCallContext) -> object:
        raise NotImplementedError

    def _text(self, data: dict[str, Any], context: ProviderCallContext) -> str:
        raise NotImplementedError


class OpenAIProvider(_Vendor):
    """Optional OpenAI Responses SDK adapter, constructed without inference.

    Args:
        model: Trusted model identifier; no automatic model selection.
        mock_transport: Optional exact httpx.MockTransport for offline SDK evidence.
    """

    _sdk, _http, _base_url = "openai", "httpx", "https://api.openai.com/v1"

    def _call(self, client: Any, request: ModelRequest, context: ProviderCallContext) -> object:
        return client.responses.create(
            model=self._model,
            input=[{"role": "user", "content": request.prompt}],
            max_output_tokens=context.max_output_tokens,
            store=False,
            stream=False,
            tools=[],
            tool_choice="none",
            timeout=context.remaining_seconds,
        )

    def _text(self, data: dict[str, Any], context: ProviderCallContext) -> str:
        if (
            data.get("object") != "response"
            or data.get("status") != "completed"
            or data.get("error") is not None
            or data.get("incomplete_details") is not None
            or data.get("metadata") not in (None, {})
        ):
            _reject()
        output = data.get("output")
        if type(output) is not list or len(output) != 1 or type(output[0]) is not dict:
            _reject()
        message = output[0]
        if (
            set(message) - {"id", "type", "status", "role", "content", "phase"}
            or message.get("type") != "message"
            or message.get("role") != "assistant"
            or message.get("status") != "completed"
            or message.get("phase") not in (None, "final_answer")
        ):
            _reject()
        _usage(data.get("usage"), context, total=True)
        return _blocks(message.get("content"), "output_text", {"annotations", "logprobs"})


class AnthropicProvider(_Vendor):
    """Optional Anthropic Messages SDK adapter with the same text-only semantics.

    Args:
        model: Trusted model identifier; no automatic model selection.
        mock_transport: Optional exact httpx2.MockTransport for offline SDK evidence.
    """

    _sdk, _http, _base_url = "anthropic", "httpx2", "https://api.anthropic.com"

    def _call(self, client: Any, request: ModelRequest, context: ProviderCallContext) -> object:
        return client.messages.create(
            model=self._model,
            messages=[{"role": "user", "content": request.prompt}],
            max_tokens=context.max_output_tokens,
            stream=False,
            timeout=context.remaining_seconds,
        )

    def _text(self, data: dict[str, Any], context: ProviderCallContext) -> str:
        if (
            data.get("type") != "message"
            or data.get("role") != "assistant"
            or data.get("stop_reason") != "end_turn"
            or data.get("stop_sequence") is not None
            or any(
                data.get(key) is not None for key in ("container", "diagnostics", "stop_details")
            )
        ):
            _reject()
        _usage(data.get("usage"), context, total=False)
        return _blocks(data.get("content"), "text", {"citations"})


def _reject() -> None:
    raise ProviderOutputRejected("Vendor response violates the supported text-only profile.")


def _payload(raw: Any) -> dict[str, Any]:
    # Genuine SDK models are loose; application acceptance independently validates.
    if not hasattr(raw, "model_dump") or not hasattr(type(raw), "model_fields"):
        _reject()
    data = raw.model_dump(mode="python", warnings=False)
    if type(data) is not dict or set(data) - set(type(raw).model_fields):
        _reject()
    remaining = 4096

    def check(value: object, depth: int = 0) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 12:
            _reject()
        if type(value) is dict:
            if len(value) > 256 or any(type(k) is not str for k in value):
                _reject()
            for key, item in value.items():
                check(key, depth + 1)
                check(item, depth + 1)
        elif type(value) is list:
            if len(value) > 256:
                _reject()
            for item in value:
                check(item, depth + 1)
        elif type(value) is str:
            if _units(value) > 16_384:
                _reject()
        elif (value is not None and type(value) not in (int, float, bool)) or (
            type(value) is float and not isfinite(value)
        ):
            _reject()

    check(data)
    if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > 65_536:
        _reject()
    return data


def _blocks(value: object, kind: str, empty_fields: set[str]) -> str:
    if type(value) is not list or not 1 <= len(value) <= 8:
        _reject()
    pieces = []
    for block in value:
        if (
            type(block) is not dict
            or set(block) - {"type", "text"} - empty_fields
            or block.get("type") != kind
            or type(block.get("text")) is not str
            or not block["text"]
            or any(block.get(k) not in (None, []) for k in empty_fields)
        ):
            _reject()
        pieces.append(block["text"])
    return "".join(pieces)


def _usage(value: object, context: ProviderCallContext, *, total: bool) -> None:
    if type(value) is not dict:
        _reject()
    for key, limit in (
        ("input_tokens", context._max_context_tokens),
        ("output_tokens", context.max_output_tokens),
    ):
        count = value.get(key)
        if type(count) is not int or not 0 <= count <= limit:
            _reject()
    if total and (
        type(value.get("total_tokens")) is not int
        or value["total_tokens"] != (value["input_tokens"] + value["output_tokens"])
    ):
        _reject()
