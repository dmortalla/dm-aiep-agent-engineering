"""Story 7 Helicone settings: explicit, secret-safe and inactive by default.

The accepted ``RuntimeSettings`` schema is unchanged. Gateway evidence requires
live runtime mode, explicit runtime live enablement, this module's own flag and
explicit budget configuration. Ambient ``HELICONE_*``/``HELC_*`` variables are
never read here; their presence refuses the live branch.

Three distinct typed URL concepts are validated here and are never runtime
substitutable with one another:
1. ``gateway_base_url`` — the Helicone gateway proxy origin;
2. ``evidence_api_base_url`` — the Helicone evidence/query API origin;
3. ``provider_target_url`` — the application-owned provider target used only
   to compose ``Helicone-Target-URL``.

The provider target is https-only, validated syntactically, and is never
resolved through DNS and never contacted by the adapter: DNS qualification
(the accepted Story 6 precedent) is reserved for the endpoints the adapter
actually transmits to, while the provider target stays inert routing metadata
so the adapter can never become a fetch/proxy primitive.
"""

import os
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .config import RuntimeSettings
from .domain import ExecutionMode
from .errors import ConfigurationError
from .langsmith_config import _is_loopback, _is_prohibited_hostname_syntax

_AMBIENT_PREFIXES = ("HELICONE_", "HELC_")
# The accepted Story 6 reserved non-routable test origin, reused verbatim.
_RESERVED_TEST_ORIGIN_HOST = "198.51.100.1"


def ambient_helicone_variables() -> frozenset[str]:
    """Return ambient ``HELICONE_*``/``HELC_*`` variable names present now.

    Returns:
        The matching environment variable names; never values.
    """
    return frozenset(
        name
        for name in os.environ
        if name.upper().startswith(_AMBIENT_PREFIXES)
    )


def _validate_base_url(value: str) -> str:
    """Validate a gateway/evidence base URL: HTTPS, loopback HTTP or the seam origin.

    Args:
        value: Candidate URL.

    Returns:
        The URL without a trailing slash.

    Raises:
        ValueError: With a fixed message that never echoes the URL.
    """
    message = (
        "base URLs must be https (http only for loopback) without credentials, "
        "query, fragment, whitespace or control characters"
    )
    if not value.strip() or any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise ValueError(message)
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        _ = parts.port  # Raises ValueError for a malformed port.
    except ValueError:
        raise ValueError(message) from None
    reserved = hostname is not None and hostname == _RESERVED_TEST_ORIGIN_HOST
    secure = parts.scheme == "https" or (
        parts.scheme == "http"
        and hostname is not None
        and (_is_loopback(hostname) or reserved)
    )
    if (
        not secure
        or not hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
    ):
        raise ValueError(message)
    return value.rstrip("/")


def _validate_provider_target_url(value: str) -> str:
    """Validate the application-owned provider target URL syntactically.

    Args:
        value: Candidate URL; composed only as ``Helicone-Target-URL``.

    Returns:
        The URL without a trailing slash.

    Raises:
        ValueError: With a fixed message that never echoes the URL.
    """
    message = (
        "provider_target_url must be a canonical https URL without credentials, "
        "query, fragment, whitespace or control characters"
    )
    if not value.strip() or any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise ValueError(message)
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        raise ValueError(message) from None
    if (
        parts.scheme != "https"
        or not hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
        or _is_prohibited_hostname_syntax(hostname)
    ):
        raise ValueError(message)
    return value.rstrip("/")


class HeliconeSettings(BaseSettings):
    """Validated immutable Helicone gateway-evidence settings.

    Attributes:
        enabled: Explicit Helicone enablement; credentials alone never enable it.
        api_key: Externally supplied Helicone API key.
        gateway_base_url: Explicit gateway proxy base URL.
        evidence_api_base_url: Explicit evidence/query API base URL.
        provider_target_url: Explicit application-owned provider target URL for
            ``Helicone-Target-URL`` composition only.
        cost_tolerance_usd: Finite nonnegative absolute cost tolerance for the
            ``match`` classification.
        max_http_requests: Finite request-count budget, at most 1024.
        reservation_per_request_usd: Nonnegative never-refunded per-request
            reservation; unset means live execution is refused.
        run_cost_limit_usd: Explicit positive run cost limit.
        request_timeout_seconds: Per-HTTP-request timeout.
        lifecycle_timeout_seconds: Application wait bound for close and other
            blocking lifecycle operations.
        readback_attempts: Finite live-verification readback attempts.
        readback_interval_seconds: Wait between live-verification readbacks.
        live_deadline_seconds: Whole live-run deadline, at most 600.
    """

    model_config = SettingsConfigDict(
        env_prefix="MODULE7_HELICONE_",
        env_file=None,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    enabled: bool = False
    api_key: SecretStr | None = Field(default=None, repr=False)
    gateway_base_url: str | None = Field(default=None, repr=False, max_length=2048)
    evidence_api_base_url: str | None = Field(default=None, repr=False, max_length=2048)
    provider_target_url: str | None = Field(
        default=None, repr=False, max_length=2048
    )
    cost_tolerance_usd: float = Field(default=0.01, ge=0.0, allow_inf_nan=False)
    max_http_requests: int = Field(default=64, ge=1, le=1024)
    reservation_per_request_usd: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False
    )
    run_cost_limit_usd: float | None = Field(
        default=None, gt=0.0, allow_inf_nan=False
    )
    request_timeout_seconds: int = Field(default=10, ge=1, le=30)
    lifecycle_timeout_seconds: float = Field(
        default=10.0, ge=0, le=60, allow_inf_nan=False
    )
    readback_attempts: int = Field(default=3, ge=1, le=10)
    readback_interval_seconds: float = Field(
        default=5.0, ge=0, le=30, allow_inf_nan=False
    )
    live_deadline_seconds: float = Field(default=120.0, gt=0, le=600, allow_inf_nan=False)

    def __init__(self, **values: object) -> None:
        """Validate settings without exposing raw configuration input.

        Args:
            **values: Explicit values; missing values may come from
                ``MODULE7_HELICONE_*`` environment variables.

        Raises:
            ConfigurationError: If Helicone configuration is invalid.
        """
        error_message: str | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            safe_errors = exc.errors(
                include_input=False, include_context=False, include_url=False,
            )
            messages = "; ".join(str(error["msg"]) for error in safe_errors)
            error_message = f"Invalid Module 7 Helicone configuration: {messages}"
        if error_message is not None:
            raise ConfigurationError(error_message)

    @field_validator("gateway_base_url", "evidence_api_base_url")
    @classmethod
    def validate_base_urls(cls, value: str | None) -> str | None:
        """Accept only explicitly validated gateway/evidence base URLs.

        Args:
            value: Candidate base URL.

        Returns:
            The validated URL without a trailing slash.

        Raises:
            ValueError: With a fixed message that never echoes the URL.
        """
        if value is None:
            return None
        return _validate_base_url(value)

    @field_validator("provider_target_url")
    @classmethod
    def validate_provider_target(cls, value: str | None) -> str | None:
        """Accept only a canonical https provider target URL.

        Args:
            value: Candidate provider target URL.

        Returns:
            The validated URL without a trailing slash.

        Raises:
            ValueError: With a fixed message that never echoes the URL.
        """
        if value is None:
            return None
        return _validate_provider_target_url(value)

    @model_validator(mode="after")
    def validate_enabled_configuration(self) -> Self:
        """Require complete, budgeted configuration when Helicone is enabled.

        Returns:
            The validated settings.

        Raises:
            ValueError: Naming missing fields, never their values.
        """
        if not self.enabled:
            return self
        missing: list[str] = []
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            missing.append("api_key")
        if self.gateway_base_url is None:
            missing.append("gateway_base_url")
        if self.evidence_api_base_url is None:
            missing.append("evidence_api_base_url")
        if self.provider_target_url is None:
            missing.append("provider_target_url")
        if self.reservation_per_request_usd is None:
            missing.append("reservation_per_request_usd")
        if self.run_cost_limit_usd is None:
            missing.append("run_cost_limit_usd")
        if missing:
            raise ValueError(
                "Enabled Helicone gateway evidence requires externally supplied "
                "non-blank " + ", ".join(missing)
            )
        if (
            self.run_cost_limit_usd is not None
            and self.reservation_per_request_usd is not None
            and self.reservation_per_request_usd > self.run_cost_limit_usd
        ):
            raise ValueError(
                "Enabled Helicone gateway evidence requires a reservation within "
                "the run cost limit."
            )
        return self

    def is_remote_https_endpoint(self) -> bool:
        """Return whether the gateway URL is HTTPS and syntactically non-local.

        This syntactic check never advances the live branch by itself; the
        stronger bounded qualification (including fail-closed resolution) runs
        before anything is constructed.
        """
        if self.gateway_base_url is None:
            return False
        parts = urlsplit(self.gateway_base_url)
        return (
            parts.scheme == "https"
            and parts.hostname is not None
            and not _is_prohibited_hostname_syntax(parts.hostname)
        )

    def is_remote_evidence_https_endpoint(self) -> bool:
        """Return whether the evidence URL is HTTPS and syntactically non-local."""
        if self.evidence_api_base_url is None:
            return False
        parts = urlsplit(self.evidence_api_base_url)
        return (
            parts.scheme == "https"
            and parts.hostname is not None
            and not _is_prohibited_hostname_syntax(parts.hostname)
        )


def require_live_helicone(
    runtime: RuntimeSettings,
    settings: HeliconeSettings,
) -> bool:
    """Decide whether real gateway evidence may be constructed.

    All activation gates are enforced here: explicit runtime live mode with
    live integration enablement, an enabled complete settings object, and no
    ambient ``HELICONE_*``/``HELC_*`` variables. Explicit live-call opt-in is
    enforced separately by the transport contract and the owned live
    verification wrapper, which also require the explicit opt-in variable.

    Args:
        runtime: Accepted Story 1 runtime settings.
        settings: Validated Helicone settings.

    Returns:
        False when Helicone is disabled; True only for a fully activated,
        live, complete and budgeted configuration.

    Raises:
        ConfigurationError: If Helicone is enabled outside an explicitly
            activated live configuration or ambient vendor variables exist.
    """
    if not settings.enabled:
        return False
    missing: list[str] = []
    if runtime.mode is not ExecutionMode.LIVE or not runtime.live_integrations_enabled:
        raise ConfigurationError(
            "Helicone gateway evidence requires live mode with explicit live "
            "integration enablement."
        )
    ambient = ambient_helicone_variables()
    if ambient:
        raise ConfigurationError(
            "Live Helicone gateway evidence refuses to run while ambient "
            "HELICONE_*/HELC_* variables are present."
        )
    if (
        settings.reservation_per_request_usd is None
        or settings.run_cost_limit_usd is None
    ):
        missing.append("reservation_per_request_usd, run_cost_limit_usd")
    if missing:
        raise ConfigurationError(
            "Live Helicone gateway evidence requires explicit "
            + ", ".join(missing) + "."
        )
    return True


__all__ = [
    "HeliconeSettings",
    "ambient_helicone_variables",
    "require_live_helicone",
]
