"""Tests for deterministic harness configuration."""

import pytest
from pydantic import ValidationError

from harness_engineering.config import HarnessConfig, default_config


def test_default_config_is_credential_free_and_deterministic() -> None:
    """Keep the normal reviewer path local and deterministic by default."""
    config = default_config()

    assert config.environment == "local"
    assert config.deterministic_mode is True
    assert config.allow_live_providers is False
    assert config.allow_external_tools is False
    assert config.allow_mcp is False
    assert config.require_human_approval is True


@pytest.mark.parametrize(
    "field_name, expected_message",
    [
        ("allow_live_providers", "deterministic mode cannot allow live providers"),
        ("allow_external_tools", "deterministic mode cannot allow external tools"),
        ("allow_mcp", "deterministic mode cannot allow MCP invocation"),
    ],
)
def test_deterministic_mode_rejects_live_paths(
    field_name: str,
    expected_message: str,
) -> None:
    """Fail closed when deterministic mode is combined with a live path."""
    with pytest.raises(ValidationError, match=expected_message):
        HarnessConfig(**{field_name: True})


def test_non_deterministic_mode_requires_explicit_opt_in() -> None:
    """Permit a live path only after deterministic mode is explicitly disabled."""
    config = HarnessConfig(
        deterministic_mode=False,
        allow_live_providers=True,
    )

    assert config.deterministic_mode is False
    assert config.allow_live_providers is True


def test_config_forbids_unknown_fields() -> None:
    """Reject undeclared configuration rather than silently accepting it."""
    with pytest.raises(ValidationError):
        HarnessConfig(unknown_setting=True)


def test_config_is_immutable() -> None:
    """Prevent runtime mutation of validated configuration."""
    config = HarnessConfig()

    with pytest.raises(ValidationError):
        config.allow_mcp = True
