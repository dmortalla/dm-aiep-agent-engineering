"""Validated configuration and bounded-execution policy."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mcp_enterprise_integration.errors import ConfigurationError


class ExecutionBounds(BaseModel):
    """Define finite execution limits for later integration boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_tool_calls: int = Field(default=8, ge=1, le=50)
    max_workflow_steps: int = Field(default=12, ge=1, le=100)
    max_result_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)


class ProviderPolicy(BaseModel):
    """Control whether non-deterministic or paid provider execution is allowed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_live_provider_calls: bool = False
    allow_paid_provider_calls: bool = False


class ApplicationSettings(BaseModel):
    """Validated application settings for deterministic Module 8 execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution: ExecutionBounds = Field(default_factory=ExecutionBounds)
    providers: ProviderPolicy = Field(default_factory=ProviderPolicy)


def load_settings(data: dict[str, object] | None = None) -> ApplicationSettings:
    """Validate application settings at the configuration boundary.

    Args:
        data: Optional untrusted configuration mapping. Defaults to safe settings.

    Returns:
        A validated immutable application-settings object.

    Raises:
        ConfigurationError: If supplied configuration violates the contract.
    """
    try:
        return ApplicationSettings.model_validate(data or {})
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid Module 8 configuration: {exc}") from exc
