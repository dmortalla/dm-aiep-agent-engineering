"""Optional SDK adapters: text data only, no SDK retry or model-owned authority.

Imports/construction never request inference. Offline factories accept exact SDK
HTTP MockTransports and fixed dummy configuration. Live clients are constructed
only at invocation after trusted runtime opt-in, an allowlisted provider/model,
a current human live-execution authorization, and an application-resolved
trusted credential; credentials alone do nothing and SDK environment, profile,
or federation credential discovery is never used on the live path.
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
from harness_engineering.live_authorization import require_live_execution_authorization
from harness_engineering.live_credentials import (
    CREDENTIAL_SOURCE_TYPES,
    CredentialUnavailableError,
    LiveCredential,
)
from harness_engineering.providers import (
    ModelRequest,
    ProviderCallContext,
    ProviderExecutionError,
    ProviderOutputRejected,
    ProviderTimeoutError,
    RejectionPoint,
    _units,
)
from harness_engineering.usage import UsageFacts, UsageState

# Response bounds. Answer text is limited separately (UTF-8 bytes, per call).
STRING_MAX_BYTES = 16_384
# Known opaque non-answer fields (encrypted reasoning) get an explicit, separate cap.
OPAQUE_FIELD_MAX_BYTES = 32_768
PAYLOAD_MAX_BYTES = 65_536
MAX_UNMODELED_FIELDS = 16
MAX_OUTPUT_ITEMS = 5
MAX_REASONING_PARTS = 8
_FIELD_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")
_ITEM_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")

# Usage keys the application recognizes per provider; every other usage key is
# unknown metadata governed by the same policy as unknown top-level fields.
_KNOWN_USAGE_KEYS = {
    "openai": frozenset({
        "input_tokens", "output_tokens", "total_tokens",
        "input_tokens_details", "output_tokens_details",
    }),
    "anthropic": frozenset({
        "input_tokens", "output_tokens", "cache_creation", "cache_creation_input_tokens",
        "cache_read_input_tokens", "inference_geo", "output_tokens_details",
        "server_tool_use", "service_tier",
    }),
}


def _unknown_names_acceptable(names: set[Any]) -> bool:
    """Apply the single unknown-metadata name policy to a set of unknown field names.

    Unknown provider fields are untrusted informational metadata that is ignored
    and discarded. At most ``MAX_UNMODELED_FIELDS`` may appear and each name must be
    a short ASCII identifier (``[A-Za-z0-9_]{1,64}``); names never become authority,
    model, tool, or capability identifiers. Values are bounded separately by the
    payload walk.

    Args:
        names: Field names present in a provider object but not recognized.

    Returns:
        True only when the count and every name satisfy the policy.
    """
    return len(names) <= MAX_UNMODELED_FIELDS and all(
        type(name) is str and _FIELD_NAME.fullmatch(name) is not None for name in names
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
) -> HarnessConfig | None:
    """Return the revalidated live configuration, or None for offline transports.

    Raises:
        ContractValidationError: For an unsupported adapter type.
        AuthorityViolationError: Without explicit opt-in, matching finite
            budget, live policy, and an allowlisted provider/model pair.
    """
    if type(provider) not in (OpenAIProvider, AnthropicProvider):
        raise ContractValidationError("Bind the deterministic fake or an approved vendor adapter.")
    if provider._transport is not None:
        return None  # Exact MockTransport established at bootstrap; no socket path.
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
    if value.live is None:
        raise AuthorityViolationError("Live provider disabled; no live provider policy is bound.")
    if not value.live.permits(provider._sdk, provider._model):
        raise AuthorityViolationError("Provider/model is outside the application allowlist.")
    return value


def _resolve_credential(source: object, vendor: str) -> LiveCredential:
    """Resolve one call-local credential, exposing only a fixed category."""
    credential: LiveCredential | None = None
    if type(source) in CREDENTIAL_SOURCE_TYPES:
        try:
            credential = source.resolve(vendor)  # type: ignore[union-attr]
        except CredentialUnavailableError:
            credential = None
    if type(credential) is not LiveCredential:
        # Raised outside any except scope: no lookup diagnostic is chained.
        raise ProviderConfigurationError("Trusted live credential is unavailable.")
    return credential


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
        credential: LiveCredential | None = None
        if self._transport is None:
            if not context._live_allowed:
                raise AuthorityViolationError(
                    "Live provider invocation is not application-authorized."
                )
            # Final pre-dispatch gates: explicit current human authorization for
            # this exact provider/model, then an application-resolved credential.
            require_live_execution_authorization(
                context._authorization, provider=self._sdk, model=self._model
            )
            credential = _resolve_credential(context._credentials, self._sdk)
            context.checkpoint()
        sdk, http = _load(self._sdk), _load(self._http)
        configuration_error = sdk.OpenAIError if self._sdk == "openai" else sdk.AnthropicError
        raw: object = None
        failure: tuple[type[HarnessError], str, RejectionPoint | None] | None = None
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
                # An explicit key disables SDK environment/profile credential discovery.
                options["api_key"] = (
                    "module-06-5-offline-dummy" if credential is None
                    else credential.reveal_for_sdk()
                )
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
                    context.checkpoint()
                    context._dispatched.set()
                    raw = self._call(client, value, context)
        except sdk.APITimeoutError:
            failure = (ProviderTimeoutError, "SDK timeout; discard provider result.", None)
        except sdk.APIResponseValidationError:
            failure = (
                ProviderOutputRejected,
                "SDK response violates the supported profile.",
                RejectionPoint.SDK_VALIDATION,
            )
        except json.JSONDecodeError:
            failure = (
                ProviderOutputRejected,
                "SDK response contains malformed JSON.",
                RejectionPoint.MALFORMED_JSON,
            )
        except sdk.APIConnectionError:
            failure = (
                ProviderUnavailableError, "SDK transport unavailable; attempt consumed.", None,
            )
        except sdk.APIStatusError as exc:
            failure = (
                (ProviderUnavailableError, "Provider service unavailable; attempt consumed.", None)
                if exc.status_code in (408, 409, 429) or exc.status_code >= 500
                else (
                    ProviderRequestError,
                    "Provider rejected request; check application configuration.",
                    None,
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
                None,
            )
        if failure is not None:
            # Raise outside the SDK except scope: no secret-bearing exception context survives.
            kind, message, point = failure
            error = kind(message)
            if isinstance(error, ProviderOutputRejected):
                error.point = point
            raise error from _SanitizedCause(kind.__name__)
        response_type = sdk.types.responses.Response if self._sdk == "openai" else sdk.types.Message
        if type(raw) is not response_type:
            _reject(RejectionPoint.RESPONSE_TYPE)
        try:
            data = _payload(
                raw, opaque=_OPAQUE_FIELDS if self._sdk == "openai" else frozenset()
            )
        except ProviderOutputRejected:
            context._usage.report(UsageFacts(state=UsageState.MALFORMED))
            raise
        _usage(data.get("usage"), context, total=self._sdk == "openai")
        context.checkpoint()
        text = self._text(data, context)
        # Local text ceiling in UTF-8 bytes; provider tokens are bounded separately
        # by the SDK request cap and by the reported-usage check above.
        if not text or _units(text) > context.max_output_bytes:
            raise ProviderOutputRejected(
                "Provider text is empty or exceeds the application bound.",
                RejectionPoint.TEXT_BYTES,
            )
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
            _reject(RejectionPoint.OUTPUT_PROFILE)
        output = data.get("output")
        if (
            type(output) is not list
            or not 1 <= len(output) <= MAX_OUTPUT_ITEMS
            or any(type(item) is not dict for item in output)
        ):
            _reject(RejectionPoint.OUTPUT_ITEMS)
        # Exactly one final assistant message, last; anything before it must be a
        # validated reasoning item, which is discarded here and never read again.
        *leading, message = output
        for item in leading:
            _validate_reasoning_item(item)
        if (
            set(message) - {"id", "type", "status", "role", "content", "phase"}
            or message.get("type") != "message"
            or message.get("role") != "assistant"
            or message.get("status") != "completed"
            or message.get("phase") not in (None, "final_answer")
        ):
            _reject(RejectionPoint.OUTPUT_ITEMS)
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
            _reject(RejectionPoint.OUTPUT_PROFILE)
        return _blocks(data.get("content"), "text", {"citations"})


def _reject(point: RejectionPoint) -> None:
    """Refuse a provider result with a fixed message and a content-free point."""
    raise ProviderOutputRejected("Vendor response violates the supported text-only profile.", point)


# Known opaque non-answer fields given the explicit separate cap, by field name.
_OPAQUE_FIELDS = frozenset({"encrypted_content"})


def _payload(raw: Any, *, opaque: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Bound a genuine SDK response and return only its SDK-modeled top-level fields.

    Fields the installed SDK does not model are untrusted informational metadata:
    they must satisfy every generic bound (names, count, depth, collection, string,
    and total size limits), are never interpreted, and are discarded here.

    Args:
        raw: Exact SDK response model.
        opaque: Field names whose string values are opaque provider data (for
            example encrypted reasoning) allowed the explicit separate byte cap.

    Returns:
        A dict of the SDK-modeled top-level fields only.

    Raises:
        ProviderOutputRejected: For any shape or size violation.
    """
    if not hasattr(raw, "model_dump") or not hasattr(type(raw), "model_fields"):
        _reject(RejectionPoint.PAYLOAD_SHAPE)
    data = raw.model_dump(mode="python", warnings=False)
    if type(data) is not dict:
        _reject(RejectionPoint.PAYLOAD_SHAPE)
    known = set(type(raw).model_fields)
    if not _unknown_names_acceptable(set(data) - known):
        _reject(RejectionPoint.PAYLOAD_SHAPE)
    remaining = 4096

    def check(value: object, depth: int = 0, key: str | None = None) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 12:
            _reject(RejectionPoint.PAYLOAD_LIMITS)
        if type(value) is dict:
            if len(value) > 256 or any(type(k) is not str for k in value):
                _reject(RejectionPoint.PAYLOAD_LIMITS)
            for name, item in value.items():
                check(name, depth + 1)
                check(item, depth + 1, name)
        elif type(value) is list:
            if len(value) > 256:
                _reject(RejectionPoint.PAYLOAD_LIMITS)
            for item in value:
                check(item, depth + 1, key)
        elif type(value) is str:
            if _units(value) > (OPAQUE_FIELD_MAX_BYTES if key in opaque else STRING_MAX_BYTES):
                _reject(RejectionPoint.PAYLOAD_LIMITS)
        elif (value is not None and type(value) not in (int, float, bool)) or (
            type(value) is float and not isfinite(value)
        ):
            _reject(RejectionPoint.PAYLOAD_SHAPE)

    check(data)
    if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > PAYLOAD_MAX_BYTES:
        _reject(RejectionPoint.PAYLOAD_LIMITS)
    return {name: value for name, value in data.items() if name in known}


def _validate_reasoning_item(item: dict[str, Any]) -> None:
    """Validate and discard one known non-answer reasoning output item.

    Only the documented reasoning structure is recognized. Its summary, content
    and encrypted payload are bounded, never returned, never persisted as model
    text, and never interpreted; any other item type fails closed.
    """
    parts = (("summary", "summary_text"), ("content", "reasoning_text"))
    identifier = item.get("id")
    if (
        set(item) - {"id", "type", "status", "summary", "content", "encrypted_content"}
        or item.get("type") != "reasoning"
        or item.get("status") not in (None, "completed")
        or type(identifier) is not str
        or _ITEM_ID.fullmatch(identifier) is None
    ):
        _reject(RejectionPoint.OUTPUT_ITEMS)
    encrypted = item.get("encrypted_content")
    if encrypted is not None and (
        type(encrypted) is not str or _units(encrypted) > OPAQUE_FIELD_MAX_BYTES
    ):
        _reject(RejectionPoint.OUTPUT_ITEMS)
    for field, kind in parts:
        value = item.get(field)
        if value is None:
            continue
        if type(value) is not list or len(value) > MAX_REASONING_PARTS:
            _reject(RejectionPoint.OUTPUT_ITEMS)
        for part in value:
            if (
                type(part) is not dict
                or set(part) - {"type", "text"}
                or part.get("type") != kind
                or type(part.get("text")) is not str
            ):
                _reject(RejectionPoint.OUTPUT_ITEMS)


def _blocks(value: object, kind: str, empty_fields: set[str]) -> str:
    if type(value) is not list or not 1 <= len(value) <= 8:
        _reject(RejectionPoint.TEXT_BLOCKS)
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
            _reject(RejectionPoint.TEXT_BLOCKS)
        pieces.append(block["text"])
    return "".join(pieces)


def describe_usage_shape(value: object) -> dict[str, str]:
    """Return a content-free structural description of a provider usage object.

    For live-evidence sanitizers and offline diagnostics: each field name (bounded
    identifiers only) maps to a type classification, and only the two accounting
    counts additionally expose their integer value. No string or nested content,
    and no credentials, can appear in the result.

    Args:
        value: Provider usage as a plain dict (for example from ``model_dump``).

    Returns:
        Mapping of field name to ``"int"``, ``"int=<n>"`` (accounting counts only),
        ``"str"``, ``"bool"``, ``"float"``, ``"null"``, ``"dict"``, ``"list"`` or
        ``"other"``; ``{}`` when ``value`` is not a dict.
    """
    if type(value) is not dict:
        return {}
    names = {int: "int", str: "str", bool: "bool", float: "float", dict: "dict", list: "list"}
    shape: dict[str, str] = {}
    for name, item in list(value.items())[:64]:
        label = name if type(name) is str and _FIELD_NAME.fullmatch(name) else "<invalid-name>"
        kind = "null" if item is None else names.get(type(item), "other")
        if kind == "int" and label in ("input_tokens", "output_tokens", "total_tokens"):
            kind = f"int={item}"
        shape[label] = kind
    return shape


def _usage(value: object, context: ProviderCallContext, *, total: bool) -> None:
    """Normalize provider usage to the two bounded accounting counts.

    Only exact integer ``input_tokens``/``output_tokens`` (and, for OpenAI, a
    consistent ``total_tokens``) are trusted accounting facts. Any other usage
    key is untrusted informational metadata under the same policy as unknown
    top-level fields (at most 16, ASCII identifier names, values already bounded
    by the generic payload walk); it is ignored here and never affects
    accounting, pricing, budget, retry, or authority. Known keys do not count
    toward the unknown limit. Anthropic cache token counts must be absent or
    zero because this adapter never requests caching, so they cannot hide spend.
    Missing or malformed usage records MISSING/MALFORMED, never an invented zero.
    """
    point: RejectionPoint | None = RejectionPoint.USAGE_SHAPE
    facts: UsageFacts | None = None
    known = _KNOWN_USAGE_KEYS["openai" if total else "anthropic"]
    if type(value) is dict and _unknown_names_acceptable(set(value) - known):
        counted, produced = value.get("input_tokens"), value.get("output_tokens")
        if (
            type(counted) is int and type(produced) is int and counted >= 0 and produced >= 0
        ):
            if (
                counted > context._max_context_tokens
                or produced > context.max_output_tokens
                or counted > 12_000
                or produced > 2_000
            ):
                point = RejectionPoint.USAGE_BOUNDS
            elif (
                total
                and (
                    type(value.get("total_tokens")) is not int
                    or value["total_tokens"] != counted + produced
                )
            ) or (
                not total
                and any(
                    (cached := value.get(name)) is not None
                    and (type(cached) is not int or cached != 0)
                    for name in ("cache_creation_input_tokens", "cache_read_input_tokens")
                )
            ):
                point = RejectionPoint.USAGE_SHAPE
            else:
                facts = UsageFacts(
                    state=UsageState.REPORTED, input_tokens=counted, output_tokens=produced,
                )
    if facts is None:
        context._usage.report(UsageFacts(
            state=UsageState.MISSING if value is None else UsageState.MALFORMED,
        ))
        raise ProviderOutputRejected(
            "Vendor response violates the supported text-only profile.", point
        )
    context._usage.report(facts)
