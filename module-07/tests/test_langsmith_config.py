"""Story 6 LangSmith settings tests: explicit gating and secret safety."""

import pytest
from pydantic import SecretStr

from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import ExecutionMode
from reliability_safety_observability.errors import ConfigurationError
from reliability_safety_observability.langsmith_config import (
    LangSmithSettings,
    ambient_langsmith_variables,
    qualify_https_endpoint,
    require_live_langsmith,
)


def runtime(mode: ExecutionMode = ExecutionMode.LIVE):
    """Build one runtime settings object consistent with the mode."""
    live = mode is ExecutionMode.LIVE
    return RuntimeSettings(
        mode=mode,
        live_integrations_enabled=live,
        provider_api_key=SecretStr("provider-key"),
    )


def enabled_settings(**override):
    """Build one enabled settings object with explicit budgets."""
    base = {
        "enabled": True,
        "api_key": SecretStr("langsmith-key"),
        "api_url": "https://api.smith.langchain.com",
        "reservation_per_request_usd": 0.001,
        "run_cost_limit_usd": 1.0,
    }
    base.update(override)
    return LangSmithSettings(**base)


def enabled_settings_values(**override):
    """Build one enabled settings values mapping with explicit budgets."""
    values = {
        "enabled": True,
        "api_key": SecretStr("langsmith-key"),
        "api_url": "https://api.smith.langchain.com",
        "reservation_per_request_usd": 0.001,
        "run_cost_limit_usd": 1.0,
    }
    values.update(override)
    return values


def test_default_settings_are_not_enabled() -> None:
    """Settings construct disabled without ambient configuration."""
    settings = LangSmithSettings()
    assert settings.enabled is False
    assert settings.api_key is None
    assert settings.max_exported_scenarios == 12
    assert settings.is_remote_https_endpoint() is False


def test_credential_presence_alone_does_not_enable(monkeypatch) -> None:
    """Credential presence alone never enables live configuration."""
    monkeypatch.setenv("MODULE7_LANGSMITH_API_KEY", "ambient-key")
    settings = LangSmithSettings()
    assert settings.enabled is False
    assert settings.api_key.get_secret_value() == "ambient-key"


def test_enabled_configuration_requires_complete_budgets() -> None:
    """Enablement without complete, budgeted configuration fails closed."""
    with pytest.raises(ConfigurationError):
        LangSmithSettings(enabled=True)
    with pytest.raises(ConfigurationError):
        LangSmithSettings(
            enabled=True,
            api_key=SecretStr("k"),
            api_url="https://api.smith.langchain.com",
        )
    with pytest.raises(ConfigurationError):
        LangSmithSettings(
            enabled=True,
            api_key=SecretStr("k"),
            api_url="https://api.smith.langchain.com",
            run_cost_limit_usd=1.0,
        )


def test_enabled_settings_accept_complete_budgeted_configuration() -> None:
    """Complete, budgeted settings validate and stay remote for HTTPS."""
    settings = enabled_settings()
    assert settings.is_remote_https_endpoint() is True
    assert settings.api_key.get_secret_value() == "langsmith-key"


def test_enabled_settings_refuse_zero_or_oversize_reservation() -> None:
    """An oversize reservation is refused; an explicit zero one is permitted."""
    enabled_zero = enabled_settings(reservation_per_request_usd=0.0)
    assert enabled_zero.reservation_per_request_usd == 0.0
    with pytest.raises(ConfigurationError):
        enabled_settings(reservation_per_request_usd=2.0, run_cost_limit_usd=1.0)
    # A missing reservation is never silently treated as zero.
    values = enabled_settings_values()
    values["reservation_per_request_usd"] = None
    with pytest.raises(ConfigurationError):
        LangSmithSettings(**values)


def test_api_url_rejects_http_non_loopback_and_credentials() -> None:
    """Non-loopback HTTP, credentials, queries and fragments are refused."""
    for bad_url in (
        "http://api.smith.langchain.com",
        "https://user:pass@api.smith.langchain.com",
        "https://api.smith.langchain.com/path?query=1",
        "https://api.smith.langchain.com#fragment",
        "https://[invalid",
    ):
        with pytest.raises(ConfigurationError):
            LangSmithSettings(api_url=bad_url)


def test_api_url_allows_loopback_http() -> None:
    """Loopback HTTP is configurable but never a remote HTTPS endpoint."""
    settings = LangSmithSettings(api_url="http://127.0.0.1:19876")
    assert settings.is_remote_https_endpoint() is False


def test_ambient_langsmith_variables_reports_names(monkeypatch) -> None:
    """Ambient detection reports only variable names, never values."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "ambient-secret")
    ambient = ambient_langsmith_variables()
    assert "ambient-secret" not in str(ambient)
    assert "LANGCHAIN_API_KEY" in ambient
    assert "LANGSMITH_TRACING" in ambient


def test_langsmith_enabled_outside_live_setup_raises() -> None:
    """Enabled settings against a deterministic runtime are refused."""
    with pytest.raises(ConfigurationError):
        require_live_langsmith(
            runtime(ExecutionMode.DETERMINISTIC), enabled_settings()
        )


def test_disabled_settings_never_activate() -> None:
    """Disabled settings return False without any ambient interrogation."""
    assert not require_live_langsmith(runtime(), LangSmithSettings())


def test_ambient_vendor_variables_block_live_activation(monkeypatch) -> None:
    """Ambient LANGSMITH_*/LANGCHAIN_* presence refuses the live branch."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(ConfigurationError):
        require_live_langsmith(runtime(), enabled_settings(), opt_in=True)


def test_require_live_langsmith_requires_explicit_opt_in() -> None:
    """Omitting the explicit live-call opt-in is a fixed refusal."""
    with pytest.raises(ConfigurationError):
        require_live_langsmith(runtime(), enabled_settings(), opt_in=False)
    assert require_live_langsmith(runtime(), enabled_settings(), opt_in=True)


def test_settings_repr_hides_secrets() -> None:
    """Settings repr exposes no secret material."""
    settings = enabled_settings(workspace_id="5e9b1a11-1111-5111-8111-111111111111")
    rendered = repr(settings)
    assert "langsmith-key" not in rendered
    assert "provider-key" not in rendered


def test_each_activation_gate_is_individually_refused(monkeypatch) -> None:
    """Every missing gate produces its own specific refusal and builds nothing.

    Contract Test 17: mode, live flag, LangSmith flag, key, endpoint,
    reservation, opt-in, ambient-variable guard and budget plan are each
    enforced; failing any one refuses in isolation.
    """
    # Non-live runtime mode (mode + live integration flag gates).
    with pytest.raises(
        ConfigurationError, match="live integration enablement"
    ):
        require_live_langsmith(
            runtime(mode=ExecutionMode.DETERMINISTIC),
            enabled_settings(),
            opt_in=True,
        )
    # A missing credential is refused while LangSmith is enabled.
    with pytest.raises(ConfigurationError, match="api_key"):
        enabled_settings(api_key=None)
    # A missing endpoint is refused while LangSmith is enabled.
    with pytest.raises(ConfigurationError, match="api_url"):
        enabled_settings(api_url=None)
    # A missing reservation is refused; zero is only ever explicit.
    values = enabled_settings_values()
    del values["reservation_per_request_usd"]
    with pytest.raises(ConfigurationError, match="reservation_per_request_usd"):
        LangSmithSettings(**values)
    # Ambient LANGSMITH_*/LANGCHAIN_* variables refuse the live branch.
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    with pytest.raises(ConfigurationError, match="ambient"):
        require_live_langsmith(runtime(), enabled_settings(), opt_in=True)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    # The disabled flag refuses without any live complaint.
    assert require_live_langsmith(runtime(), LangSmithSettings(enabled=False), opt_in=True) is False


def test_endpoint_qualification_refuses_every_prohibited_form() -> None:
    """Loopback, link-local, unspecified, mapped and local aliases are refused.

    Contract Test 21(b): a loopback HTTPS endpoint never reaches vendor
    construction; every noncanonical local spelling is refused because the
    qualification happens before any client construction or credential use.
    """
    prohibited = (
        "https://127.0.0.1",
        "https://127.1",
        "https://127.000.000.001",
        "https://127.111.222.333",  # A noncanonical dotted quad.
        "https://0.0.0.0",
        "https://0",
        "https://2130706433",
        "https://0x7f000001",
        "http://127.0.0.1.localdomain",
        "https://localhost.localdomain",
        "https://api.local",
        "https://api.internal",
        "https://sub.localhost",
        "https://169.254.1.1",
        "https://[::]",
        "https://[::1]",
        "https://[::ffff:127.0.0.1]",
        "https://[fe80::1]",
        "ftp://api.smith.langchain.com",
        "https:///no-host",
        "https://user:pass@api.smith.langchain.com",
        "https://api.example.com/?x=1",
        "https://api.example.com/#frag",
    )
    for candidate in prohibited:
        with pytest.raises(ConfigurationError) as exc_info:
            qualify_https_endpoint(candidate)
        message = str(exc_info.value)
        assert "qualifica" in message
        assert candidate not in message  # Never echoes the refused URL.


def test_endpoint_qualification_resolves_fail_closed(monkeypatch) -> None:
    """Unresolvable, local-resolving and slow hostnames are all refused.

    A hostname resolving to any prohibited address, zero addresses, or taking
    longer than the bounded wait fails closed (prohibited).
    """
    fake = _MinimalResolver()
    fake.rules = {
        "api.example.private": [_addr_entry("127.0.0.1")],
        "bogus.demo.invalid": [],
        "resolved.demo.invalid": [_addr_entry("169.254.41.2")],
    }
    monkeypatch.setattr(
        "reliability_safety_observability.langsmith_config.socket.getaddrinfo",
        fake.resolve,
    )
    for name in ("api.example.private", "bogus.demo.invalid", "resolved.demo.invalid"):
        with pytest.raises(ConfigurationError):
            qualify_https_endpoint(f"https://{name}")
    fake.rules = {"api.example.public": [_addr_entry("8.8.8.8")]}
    assert qualify_https_endpoint("https://api.example.public") is True


class _MinimalResolver:
    """Minimal getaddrinfo double for bounded-resolution testing."""

    def __init__(self) -> None:
        self.rules: dict[str, list[tuple]] = {}

    def resolve(self, hostname, *args, **kwargs):
        if hostname not in self.rules:
            raise OSError("no resolution configured")
        return self.rules[hostname]


def _addr_entry(address: str):
    """Return one getaddrinfo-shaped entry for an address string."""
    return ("AF_INET", 1, 6, "", (address, 443))


def test_endpoint_qualification_is_bounded_not_hanging(monkeypatch) -> None:
    """A never-returning resolver is refused, not awaited indefinitely."""
    import threading
    import time

    from reliability_safety_observability import langsmith_config

    release = threading.Event()

    def never_resolving(hostname, *args, **kwargs):
        release.wait(30)
        return []

    monkeypatch.setattr(
        langsmith_config.socket, "getaddrinfo", never_resolving
    )
    started = time.monotonic()
    with pytest.raises(ConfigurationError):
        qualify_https_endpoint("https://slow-forever.example.com")
    elapsed = time.monotonic() - started
    release.set()
    assert elapsed < 20.0 and langsmith_config._ENDPOINT_RESOLUTION_TIMEOUT_SECONDS == 3.0


def test_settings_still_accept_only_canonical_loopback_http_urls() -> None:
    """The settings URL validator keeps rejecting noncanonical HTTP loopback."""
    for bad in (
        "http://127.1",
        "http://localhost.localdomain",
        "http://127.000.000.001",
    ):
        with pytest.raises(ConfigurationError):
            LangSmithSettings(api_url=bad)
