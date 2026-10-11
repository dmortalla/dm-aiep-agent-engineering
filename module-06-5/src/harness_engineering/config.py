"""Deterministic application configuration for the governed agent harness."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.domain import RuntimeBudget


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
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: str = Field(default="local", min_length=1, max_length=64)
    deterministic_mode: bool = True
    allow_live_providers: bool = False
    allow_external_tools: bool = False
    allow_mcp: bool = False
    require_human_approval: bool = True
    budget: RuntimeBudget = Field(default_factory=RuntimeBudget)

    @model_validator(mode="after")
    def validate_deterministic_mode(self) -> Self:
        """Prevent deterministic mode from enabling live external execution.

        Returns:
            The validated immutable configuration.

        Raises:
            ValueError: If deterministic mode enables a live external path.
        """
        if self.deterministic_mode and self.allow_live_providers:
            raise ValueError("deterministic mode cannot allow live providers")
        if self.deterministic_mode and self.allow_external_tools:
            raise ValueError("deterministic mode cannot allow external tools")
        if self.deterministic_mode and self.allow_mcp:
            raise ValueError("deterministic mode cannot allow MCP invocation")
        return self


def default_config() -> HarnessConfig:
    """Return the credential-free deterministic reviewer configuration.

    Returns:
        A validated configuration with all live external paths disabled.
    """
    return HarnessConfig()
