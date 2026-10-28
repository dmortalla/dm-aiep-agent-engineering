"""Deterministic application configuration for the governed agent harness."""

from math import isfinite
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.domain import RuntimeBudget

LiveProvider = Literal["openai", "anthropic"]
CredentialSourceKind = Literal["environment", "secret_store", "byok"]

# Application-owned catalog (ENG-008). Deployment policy may only narrow it.
# Identifiers are fixed, current low-exposure models chosen for a bounded live
# validation; adding a model is a reviewed code change, never runtime input.
# Deprecated or shut-down models (gpt-4.1-mini, gpt-4.1-nano, gpt-5-mini,
# gpt-5-nano) are deliberately excluded so no new live exercise can target them.
SUPPORTED_LIVE_MODELS: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-6-luna",),
    "anthropic": ("claude-haiku-5-5",),
}

# Published standard USD tariffs per million tokens, by prompt-size tier:
# (max_prompt_tokens or None for unbounded, input, output). Operator-supplied
# official-source observation, 2026-10-25. These are price floors: a human
# live authorization may approve higher upper bounds, never lower ones.
PUBLISHED_LIVE_TARIFFS: dict[str, tuple[tuple[int | None, float, float], ...]] = {
    "gpt-6-luna": ((None, 0.10, 0.50),),
    "claude-haiku-5-5": ((100_000, 0.10, 0.50), (None, 0.50, 2.50)),
}

# Live-path ceilings, stricter than the frozen deterministic workflow caps.
LIVE_MAX_COST_USD = 1.0
LIVE_MAX_PROVIDER_ATTEMPTS = 4
LIVE_MAX_RETRIES_PER_ACTION = 1
# Local returned-text ceiling in UTF-8 bytes, distinct from provider tokens.
LIVE_MAX_OUTPUT_BYTES = 8_192
LIVE_MAX_OUTPUT_TOKENS = 1_024
LIVE_MAX_CONTEXT_TOKENS = 8_000
LIVE_MAX_ACTION_TIMEOUT_SECONDS = 30.0
LIVE_MAX_WORKFLOW_DEADLINE_SECONDS = 120.0


class LiveProviderPolicy(BaseModel):
    """Application-owned opt-in live-provider allowlists and credential-source policy.

    This is the application-owned configuration contract behind ``ENG-008``.
    It names the providers and models the application may ever invoke and the
    approved credential-delivery path: trusted server-side configuration
    (``environment`` or ``secret_store``) or a transient user-supplied key
    (``byok``). Both paths are first-class and neither replaces the other. The
    policy carries no credential values and grants no authority: credentials
    resolve only at invocation through the bound credential source and grant
    connectivity only.

    Attributes:
        allowed_providers: Unique providers from the application catalog.
        allowed_models: Per-provider model allowlist, each a subset of
            ``SUPPORTED_LIVE_MODELS``; every allowed provider needs one.
        credential_source: Approved credential-delivery path for this policy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    allowed_providers: tuple[LiveProvider, ...] = Field(min_length=1, max_length=2)
    allowed_models: dict[LiveProvider, tuple[str, ...]]
    credential_source: CredentialSourceKind

    @model_validator(mode="after")
    def validate_allowlists(self) -> Self:
        """Fail closed on duplicate, uncovered, or uncatalogued allowlist entries.

        Returns:
            The validated immutable policy.

        Raises:
            ValueError: If providers repeat, a provider lacks a model allowlist,
                a model allowlist names a non-allowed provider, or a model is
                outside the application catalog.
        """
        if len(set(self.allowed_providers)) != len(self.allowed_providers):
            raise ValueError("provider allowlist entries must be unique")
        if set(self.allowed_models) != set(self.allowed_providers):
            raise ValueError("each allowlisted provider requires exactly one model allowlist")
        for provider, models in self.allowed_models.items():
            if not models or len(set(models)) != len(models):
                raise ValueError("model allowlists must be non-empty and unique")
            if any(model not in SUPPORTED_LIVE_MODELS[provider] for model in models):
                raise ValueError("model is outside the application model catalog")
        return self

    def permits(self, provider: str, model: str) -> bool:
        """Return whether this policy allowlists the exact provider/model pair.

        Args:
            provider: Adapter vendor name.
            model: Adapter-bound model identifier.

        Returns:
            True only for an exact allowlisted pair; never grants authority.
        """
        models = dict(self.allowed_models)
        return provider in self.allowed_providers and model in models.get(provider, ())


class HarnessConfig(BaseModel):
    """Configure deterministic harness behavior without granting authority.

    Configuration is explicit, validated, and fail-closed. Credentials and
    provider-specific secrets are intentionally outside this domain contract.

    Attributes:
        environment: Logical execution environment label.
        deterministic_mode: Whether deterministic local behavior is required.
        allow_live_providers: Whether live model-provider adapters may run.
        allow_external_tools: Whether external tool execution may run.
        allow_mcp: Whether MCP capability invocation may run.
        require_human_approval: Whether configured approval gates are enforced.
        budget: Immutable workflow resource limits.
        live: Optional opt-in live-provider policy. Live runtime binding
            requires it; its absence keeps every vendor adapter unbindable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: str = Field(default="local", min_length=1, max_length=64)
    deterministic_mode: bool = True
    allow_live_providers: bool = False
    allow_external_tools: bool = False
    allow_mcp: bool = False
    require_human_approval: bool = True
    budget: RuntimeBudget = Field(default_factory=RuntimeBudget)
    live: LiveProviderPolicy | None = None

    @model_validator(mode="after")
    def validate_deterministic_mode(self) -> Self:
        """Prevent deterministic mode from enabling live external execution.

        Returns:
            The validated immutable configuration.

        Raises:
            ValueError: If deterministic mode enables a live external path, or
                a live policy is present without explicit live enablement,
                human approval, a finite positive cost budget, and limits
                inside the live-path ceilings.
        """
        if self.deterministic_mode and self.allow_live_providers:
            raise ValueError("deterministic mode cannot allow live providers")
        if self.deterministic_mode and self.allow_external_tools:
            raise ValueError("deterministic mode cannot allow external tools")
        if self.deterministic_mode and self.allow_mcp:
            raise ValueError("deterministic mode cannot allow MCP invocation")
        if self.live is None:
            return self
        b = self.budget
        if self.deterministic_mode or not self.allow_live_providers:
            raise ValueError("live provider policy requires explicit live enablement")
        if not self.require_human_approval:
            raise ValueError("live provider policy cannot disable human approval")
        if b.max_cost_usd is None or not isfinite(b.max_cost_usd):
            raise ValueError("live provider policy requires a finite cost budget")
        if b.max_output_bytes is None:
            raise ValueError("live provider policy requires an explicit output byte ceiling")
        if (
            b.max_output_bytes > LIVE_MAX_OUTPUT_BYTES
            or b.max_cost_usd > LIVE_MAX_COST_USD
            or b.max_provider_attempts > LIVE_MAX_PROVIDER_ATTEMPTS
            or b.max_retries_per_action > LIVE_MAX_RETRIES_PER_ACTION
            or b.max_output_tokens > LIVE_MAX_OUTPUT_TOKENS
            or b.max_context_tokens > LIVE_MAX_CONTEXT_TOKENS
            or b.action_timeout_seconds > LIVE_MAX_ACTION_TIMEOUT_SECONDS
            or b.workflow_deadline_seconds > LIVE_MAX_WORKFLOW_DEADLINE_SECONDS
        ):
            raise ValueError("live provider budget exceeds the live-path ceilings")
        return self


def default_config() -> HarnessConfig:
    """Return the credential-free deterministic reviewer configuration.

    Returns:
        A validated configuration with all live external paths disabled.
    """
    return HarnessConfig()
