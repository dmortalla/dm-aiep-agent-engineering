"""Shared credential-free builders for the Story 13 live-provider seam.

Nothing here reads a real credential or opens a network connection. Dummy
credentials are fixed literals; authorizations are deterministic fixtures for
verifying gates, never a human live-execution decision.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from harness_engineering.config import HarnessConfig, LiveProviderPolicy
from harness_engineering.domain import RuntimeBudget
from harness_engineering.live_authorization import LiveExecutionAuthorization
from harness_engineering.live_credentials import EnvironmentCredentialSource
from harness_engineering.providers import ProviderRuntime
from harness_engineering.vendor_providers import AnthropicProvider, OpenAIProvider

LIVE_MODEL = {"openai": "gpt-6-luna", "anthropic": "claude-haiku-5-5"}
ADAPTER = {"openai": OpenAIProvider, "anthropic": AnthropicProvider}
ENV_NAME = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
DUMMY_KEY = "controlled-dummy-not-a-real-key"
_DEFAULT: Any = object()


def live_budget(**overrides: Any) -> RuntimeBudget:
    """Return a budget inside every live-path ceiling."""
    values: dict[str, Any] = {
        "max_cost_usd": 0.01, "max_provider_attempts": 4, "max_retries_per_action": 1,
        "max_output_tokens": 256, "max_context_tokens": 2_000,
        "action_timeout_seconds": 10.0, "workflow_deadline_seconds": 60.0,
    }
    values.update(overrides)
    return RuntimeBudget(**values)


def live_config(
    provider: str, *, budget: RuntimeBudget | None = None, credential_source: str = "environment",
) -> HarnessConfig:
    """Return an explicit, allowlisted live opt-in for one provider."""
    return HarnessConfig(
        environment="live", deterministic_mode=False, allow_live_providers=True,
        budget=live_budget() if budget is None else budget,
        live=LiveProviderPolicy(
            allowed_providers=(provider,),
            allowed_models={provider: (LIVE_MODEL[provider],)},
            credential_source=credential_source,
        ),
    )


def authorization(
    provider: str,
    model: str | None = None,
    *,
    expires_in: timedelta = timedelta(hours=1),
    input_price: float = 0.4,
    output_price: float = 1.6,
) -> LiveExecutionAuthorization:
    """Return a deterministic authorization fixture for gate verification."""
    return LiveExecutionAuthorization(
        provider=provider, model=LIVE_MODEL[provider] if model is None else model,
        usd_per_million_input_tokens=input_price, usd_per_million_output_tokens=output_price,
        authorized_by="fixture-approver",
        authorization_reference="fixture-gate-verification-only",
        expires_at=datetime.now(UTC) + expires_in,
    )


def live_runtime(
    provider: str,
    *,
    budget: RuntimeBudget | None = None,
    credentials: Any = _DEFAULT,
    live_authorization: Any = _DEFAULT,
    **kwargs: Any,
) -> ProviderRuntime:
    """Bind a live-configured runtime; dispatch is exercised only with patched SDKs."""
    chosen = live_budget() if budget is None else budget
    return ProviderRuntime(
        provider=ADAPTER[provider](LIVE_MODEL[provider]),
        budget=chosen,
        live_config=live_config(provider, budget=chosen),
        credentials=EnvironmentCredentialSource() if credentials is _DEFAULT else credentials,
        live_authorization=(
            authorization(provider) if live_authorization is _DEFAULT else live_authorization
        ),
        **kwargs,
    )
