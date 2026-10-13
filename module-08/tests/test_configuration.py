"""Tests for safe configuration and bounded execution."""

import pytest

from mcp_enterprise_integration.config import (
    ApplicationSettings,
    ExecutionBounds,
    ProviderPolicy,
    load_settings,
)
from mcp_enterprise_integration.errors import ConfigurationError


def test_default_settings_are_zero_paid_and_bounded() -> None:
    """Keep normal deterministic execution safe and finite by default."""
    settings = load_settings()

    assert settings.providers.allow_live_provider_calls is False
    assert settings.providers.allow_paid_provider_calls is False
    assert settings.execution.timeout_seconds == 10.0
    assert settings.execution.max_retries == 2
    assert settings.execution.max_tool_calls == 8
    assert settings.execution.max_workflow_steps == 12
    assert settings.execution.max_result_bytes == 1_000_000


def test_execution_bounds_accept_valid_overrides() -> None:
    """Allow bounded overrides without removing finite limits."""
    bounds = ExecutionBounds(
        timeout_seconds=30.0,
        max_retries=3,
        max_tool_calls=10,
        max_workflow_steps=20,
        max_result_bytes=2_000_000,
    )

    assert bounds.timeout_seconds == 30.0
    assert bounds.max_retries == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeout_seconds", 0),
        ("timeout_seconds", 121),
        ("max_retries", -1),
        ("max_retries", 6),
        ("max_tool_calls", 0),
        ("max_tool_calls", 51),
        ("max_workflow_steps", 0),
        ("max_workflow_steps", 101),
        ("max_result_bytes", 100),
        ("max_result_bytes", 10_000_001),
    ],
)
def test_execution_bounds_reject_unbounded_values(field: str, value: object) -> None:
    """Reject values outside the approved finite execution envelope."""
    with pytest.raises(ValueError):
        ExecutionBounds.model_validate({field: value})


def test_configuration_rejects_unknown_fields() -> None:
    """Reject configuration that attempts to introduce undeclared controls."""
    with pytest.raises(ConfigurationError, match="Invalid Module 8 configuration"):
        load_settings({"self_authorize": True})


def test_configuration_error_preserves_validation_cause() -> None:
    """Preserve causal diagnostics at the configuration boundary."""
    with pytest.raises(ConfigurationError) as captured:
        load_settings({"execution": {"max_retries": 999}})

    assert captured.value.__cause__ is not None


def test_provider_policy_defaults_do_not_treat_credentials_as_authority() -> None:
    """Require explicit policy rather than credential presence for live execution."""
    policy = ProviderPolicy()

    assert policy.allow_live_provider_calls is False
    assert policy.allow_paid_provider_calls is False


def test_settings_are_immutable() -> None:
    """Prevent runtime mutation of accepted execution policy."""
    settings = ApplicationSettings()

    with pytest.raises(ValueError):
        settings.providers = ProviderPolicy(allow_live_provider_calls=True)
