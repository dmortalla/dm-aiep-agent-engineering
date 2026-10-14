"""Tests for Story 1 runtime configuration boundaries."""

import pytest
from pydantic import SecretStr

from reliability_safety_observability import ConfigurationError, ExecutionMode, RuntimeSettings


def test_deterministic_mode_is_default_without_credentials(monkeypatch) -> None:
    """Start safely without requiring vendor credentials."""
    monkeypatch.delenv("MODULE7_MODE", raising=False)
    monkeypatch.delenv("MODULE7_LIVE_INTEGRATIONS_ENABLED", raising=False)
    monkeypatch.delenv("MODULE7_PROVIDER_API_KEY", raising=False)
    settings = RuntimeSettings(_env_file=None)

    assert settings.mode is ExecutionMode.DETERMINISTIC
    assert settings.live_integrations_enabled is False
    assert settings.provider_api_key is None


def test_credential_presence_does_not_enable_live_mode() -> None:
    """Prevent credentials alone from activating billable behavior."""
    settings = RuntimeSettings(
        provider_api_key=SecretStr('fixture-secret'),
        _env_file=None,
    )

    assert settings.mode is ExecutionMode.DETERMINISTIC
    assert settings.live_integrations_enabled is False


def test_live_mode_requires_explicit_enablement() -> None:
    """Fail closed when live mode lacks explicit integration enablement."""
    with pytest.raises(ConfigurationError, match='explicit live integration enablement'):
        RuntimeSettings(
            mode=ExecutionMode.LIVE,
            provider_api_key=SecretStr('fixture-secret'),
            _env_file=None,
        )


def test_live_mode_requires_external_credentials() -> None:
    """Fail closed when explicitly enabled live mode lacks credentials."""
    with pytest.raises(ConfigurationError, match='externally supplied provider credentials'):
        RuntimeSettings(
            mode=ExecutionMode.LIVE,
            live_integrations_enabled=True,
            _env_file=None,
        )


def test_live_enablement_is_invalid_in_deterministic_mode() -> None:
    """Reject contradictory execution and integration modes."""
    with pytest.raises(ConfigurationError, match='cannot be enabled'):
        RuntimeSettings(
            mode=ExecutionMode.DETERMINISTIC,
            live_integrations_enabled=True,
            provider_api_key=SecretStr('fixture-secret'),
            _env_file=None,
        )


def test_explicit_live_configuration_is_accepted() -> None:
    """Accept live mode only when all required controls are explicit."""
    settings = RuntimeSettings(
        mode=ExecutionMode.LIVE,
        live_integrations_enabled=True,
        provider_api_key=SecretStr('fixture-secret'),
        _env_file=None,
    )

    assert settings.mode is ExecutionMode.LIVE
    assert settings.live_integrations_enabled is True


def test_secret_is_not_exposed_in_settings_repr() -> None:
    """Keep credentials out of normal settings representation."""
    secret = 'super-secret-fixture-value'
    settings = RuntimeSettings(
        provider_api_key=SecretStr(secret),
        _env_file=None,
    )

    assert secret not in repr(settings)
    assert secret not in str(settings)
