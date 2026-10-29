"""Explicit opt-in live-provider check for the reviewer session (BYOK or server credentials).

The deterministic reviewer path needs no key and is untouched by this module.
A live call happens only when a person explicitly opts in for the session,
acknowledges that the call may incur provider charges, selects a provider and
model from the application-owned allowlist, and supplies an approved credential:
a temporary bring-your-own key typed for this session, or trusted server-side
configuration when the operator has enabled that path. The credential grants
connectivity only. Every bound (context, output tokens and bytes, cost, attempts,
retries, time) is application-owned and cannot be influenced by the credential,
the browser, or the model. The call goes through the same governed
``ProviderRuntime`` as the accepted live exercise, so it reports at most
``adapter`` evidence: a session call is never accepted ``live_provider`` evidence,
which exists only as an independently reviewed repository record.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from harness_engineering.config import SUPPORTED_LIVE_MODELS, HarnessConfig, LiveProviderPolicy
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    HarnessError,
)
from harness_engineering.live_authorization import LiveExecutionAuthorization, published_tariff
from harness_engineering.live_credentials import (
    ENVIRONMENT_VARIABLES,
    CredentialSource,
    EnvironmentCredentialSource,
    TransientCredentialSource,
)
from harness_engineering.providers import (
    ProviderOutputRejected,
    ProviderRuntime,
    ProviderTimeoutError,
)
from harness_engineering.vendor_providers import (
    AnthropicProvider,
    OpenAIProvider,
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderUnavailableError,
)

CredentialPath = Literal["byok", "server"]

# Operator opt-in for the server-credential path. Do NOT enable it on a public
# deployment unless a separate operator-spend control or global quota exists; the planned
# public deployment allows BYOK live mode only and leaves this path disabled (the default).
SERVER_PATH_ENABLE_VARIABLE = "MODULE_6_5_ENABLE_SERVER_CREDENTIAL_PATH"
MAX_LIVE_CALLS_PER_SESSION = 5
SESSION_AUTHORIZATION_SECONDS = 900

# Fixed, application-owned prompts: the browser selects an identifier, never free text.
LIVE_PROMPTS: dict[str, str] = {
    "budgets": "In one short sentence, say why an AI agent harness needs bounded budgets.",
    "authority": "In one short sentence, say why a credential must not grant authority.",
    "untrusted": "In one short sentence, say why model output must be treated as untrusted.",
}

_FAILURE_CATEGORIES: tuple[tuple[type[Exception], str], ...] = (
    (ProviderOutputRejected, "output_rejected"),
    (ProviderTimeoutError, "timeout"),
    (ProviderUnavailableError, "provider_unavailable"),
    (ProviderRequestError, "request_rejected"),
    (ProviderConfigurationError, "configuration"),
    (BudgetExceededError, "budget"),
    (AuthorityViolationError, "not_authorized"),
)


def live_session_budget() -> RuntimeBudget:
    """Return the fixed application-owned bounds for one session live call.

    Matches the bounds of the independently reviewed live exercise. Nothing from
    the browser or the credential can change them.

    Returns:
        A budget inside every live-path ceiling.
    """
    return RuntimeBudget(
        max_context_tokens=512, max_output_tokens=256, max_output_bytes=4096,
        max_cost_usd=0.001, max_provider_attempts=1, max_retries_per_action=0,
        action_timeout_seconds=20.0, workflow_deadline_seconds=60.0,
    )


def server_credential_path_enabled() -> bool:
    """Return operator path enablement from the exact flag, without reading credentials."""
    return os.environ.get(SERVER_PATH_ENABLE_VARIABLE) == "1"


def server_credentials_available(provider: str) -> bool:
    """Report whether the operator enabled the server-credential path for a provider.

    Only presence is checked; no value is read into application state.

    Args:
        provider: Catalogued provider name.

    Returns:
        True only if the operator opt-in flag is ``1`` and the provider's trusted
        server-side variable is set.
    """
    name = ENVIRONMENT_VARIABLES.get(provider)
    return (
        name is not None
        and server_credential_path_enabled()
        and bool(os.environ.get(name))
    )


@dataclass
class LiveSession:
    """Per-session count of live calls; display-side state, never authority."""

    calls: int = 0


class LiveCheckView(BaseModel):
    """Inert, bounded result of one session live call; holds no credential."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: Literal["openai", "anthropic"]
    model: Annotated[str, Field(max_length=128)]
    path: CredentialPath
    status: Literal["succeeded", "failed"]
    text: Annotated[str, Field(max_length=4096)] | None = None
    failure_category: str | None = None
    rejection_point: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    exposure_usd: str
    evidence_class: Literal["adapter"] = "adapter"


def _adapter(provider: str, model: str) -> OpenAIProvider | AnthropicProvider:
    return OpenAIProvider(model) if provider == "openai" else AnthropicProvider(model)


def run_live_check(
    *,
    live_mode: bool,
    acknowledged_charges: bool,
    provider: str,
    model: str,
    prompt_id: str,
    path: str,
    byok_key: str | None,
    session: LiveSession,
) -> LiveCheckView:
    """Run exactly one bounded live call after explicit opt-in, then drop the key.

    Args:
        live_mode: True only when the person explicitly selected live mode.
        acknowledged_charges: True only when the person acknowledged possible charges.
        provider: Provider from the application-owned catalog.
        model: Model from that provider's application-owned allowlist.
        prompt_id: Identifier of a fixed application-owned prompt.
        path: ``"byok"`` (temporary key typed for this session) or ``"server"``.
        byok_key: The typed key for ``byok``; not persisted, logged or echoed by this code.
        session: Per-session call counter.

    Returns:
        A bounded view; failures carry only a fixed category and rejection point.

    Raises:
        AuthorityViolationError: Without explicit opt-in or acknowledgement, if the
            session cap is reached, or if the server path is not operator-enabled.
        ContractValidationError: For a provider, model, prompt or path outside the
            application-owned allowlists, or a malformed key (value never echoed).
    """
    if live_mode is not True:
        raise AuthorityViolationError("Live mode requires explicit opt-in.")
    if acknowledged_charges is not True:
        raise AuthorityViolationError("Acknowledge possible provider charges first.")
    if provider not in SUPPORTED_LIVE_MODELS or model not in SUPPORTED_LIVE_MODELS[provider]:
        raise ContractValidationError("Choose a provider and model from the allowlist.")
    if prompt_id not in LIVE_PROMPTS or path not in ("byok", "server"):
        raise ContractValidationError("Choose an available prompt and credential path.")
    if session.calls >= MAX_LIVE_CALLS_PER_SESSION:
        raise AuthorityViolationError("The live-call limit for this session was reached.")

    source: CredentialSource
    if path == "byok":
        source = TransientCredentialSource(provider, byok_key or "")
    elif server_credentials_available(provider):
        source = EnvironmentCredentialSource()
    else:
        raise AuthorityViolationError("The server credential path is not enabled.")

    budget = live_session_budget()
    prompt_bound = budget.max_context_tokens + 256
    floor_in, floor_out = published_tariff(model, prompt_bound)
    config = HarnessConfig(
        environment="live", deterministic_mode=False, allow_live_providers=True, budget=budget,
        live=LiveProviderPolicy(
            allowed_providers=(provider,), allowed_models={provider: (model,)},  # type: ignore[dict-item]
            credential_source=source.kind,
        ),
    )
    # Session opt-in authorization: minted only here, from the explicit opt-in and
    # acknowledgement above (never from the credential), short-lived, priced at the
    # published floor, and re-checked by the runtime immediately before dispatch.
    authorization = LiveExecutionAuthorization(
        provider=provider, model=model,  # type: ignore[arg-type]
        usd_per_million_input_tokens=float(floor_in),
        usd_per_million_output_tokens=float(floor_out),
        authorized_by="reviewer-session",
        authorization_reference=f"session-opt-in-{uuid4().hex[:12]}",
        expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_AUTHORIZATION_SECONDS),
    )
    runtime = ProviderRuntime(
        provider=_adapter(provider, model), budget=budget, live_config=config,
        live_authorization=authorization, credentials=source,
    )
    session.calls += 1
    text: str | None = None
    category: str | None = None
    point: str | None = None
    try:
        text = runtime.generate({"prompt": LIVE_PROMPTS[prompt_id]}).text
    except HarnessError as error:
        category = next((name for kind, name in _FAILURE_CATEGORIES if isinstance(error, kind)),
                        "failed")
        rejection = getattr(error, "point", None)
        point = None if rejection is None else str(rejection.value)
    finally:
        if isinstance(source, TransientCredentialSource):
            source.discard()
    receipts = runtime.usage_receipts
    usage = receipts[0].usage if receipts else None
    return LiveCheckView(
        provider=provider, model=model, path=path,  # type: ignore[arg-type]
        status="succeeded" if category is None else "failed",
        text=text, failure_category=category, rejection_point=point,
        input_tokens=None if usage is None else usage.input_tokens,
        output_tokens=None if usage is None else usage.output_tokens,
        exposure_usd=f"{runtime.live_exposure_usd:f}",
        evidence_class=runtime.evidence_class.value,  # type: ignore[arg-type]
    )
