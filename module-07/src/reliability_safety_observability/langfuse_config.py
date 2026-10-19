"""Story 5 Langfuse settings: explicit, secret-safe and inactive by default.

The accepted ``RuntimeSettings`` schema is unchanged. Langfuse export also needs
live runtime mode, explicit runtime live enablement and this module's own flag.
Ambient ``LANGFUSE_*`` variables are never read here.
"""

import ipaddress
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .config import RuntimeSettings
from .domain import ExecutionMode
from .errors import ConfigurationError

_LOOPBACK_NAMES = frozenset({"localhost"})


def _is_loopback(hostname: str) -> bool:
    """Return whether a URL hostname is a loopback name or address."""
    if hostname in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class LangfuseSettings(BaseSettings):
    """Validated immutable Langfuse export settings.

    Attributes:
        enabled: Explicit Langfuse enablement; credentials alone never enable it.
        public_key: Externally supplied Langfuse public key.
        secret_key: Externally supplied Langfuse secret key.
        host: Explicit Langfuse base URL; HTTPS, or HTTP for loopback only.
        request_timeout_seconds: Per-request SDK/exporter timeout.
        lifecycle_timeout_seconds: Application wait bound for flush/close/readback.
        max_record_bytes: Largest neutral record the adapter admits.
        max_observations: Finite observations accepted per adapter instance.
        flush_at: SDK export batch size.
        flush_interval_seconds: SDK scheduled export delay.
        readback_attempts: Finite live-verification readback attempts.
        readback_interval_seconds: Wait between live-verification readbacks.
    """

    model_config = SettingsConfigDict(
        env_prefix="MODULE7_LANGFUSE_",
        env_file=None,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    enabled: bool = False
    public_key: SecretStr | None = Field(default=None, repr=False)
    secret_key: SecretStr | None = Field(default=None, repr=False)
    host: str | None = Field(default=None, repr=False, max_length=2048)
    request_timeout_seconds: int = Field(default=5, ge=1, le=30)
    lifecycle_timeout_seconds: float = Field(default=10.0, gt=0, le=60, allow_inf_nan=False)
    max_record_bytes: int = Field(default=16_384, ge=512, le=65_536)
    max_observations: int = Field(default=256, ge=1, le=4096)
    flush_at: int = Field(default=64, ge=1, le=512)
    flush_interval_seconds: float = Field(default=1.0, ge=0.1, le=60, allow_inf_nan=False)
    readback_attempts: int = Field(default=6, ge=1, le=10)
    readback_interval_seconds: float = Field(default=5.0, ge=0, le=30, allow_inf_nan=False)

    def __init__(self, **values: object) -> None:
        """Validate settings without exposing raw configuration input.

        Args:
            **values: Explicit values; missing values may come from
                ``MODULE7_LANGFUSE_*`` environment variables.

        Raises:
            ConfigurationError: If Langfuse configuration is invalid.
        """
        error_message: str | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            safe_errors = exc.errors(include_input=False, include_context=False, include_url=False)
            messages = "; ".join(str(error["msg"]) for error in safe_errors)
            error_message = f"Invalid Module 7 Langfuse configuration: {messages}"

        if error_message is not None:
            raise ConfigurationError(error_message)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str | None) -> str | None:
        """Accept only an explicit credential-free HTTPS or loopback HTTP base URL.

        Args:
            value: Candidate base URL.

        Returns:
            The URL without a trailing slash.

        Raises:
            ValueError: With a fixed message that never echoes the URL.
        """
        if value is None:
            return None
        message = (
            "host must be an https URL (http only for loopback) without credentials, "
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
        secure = parts.scheme == "https" or (
            parts.scheme == "http" and hostname is not None and _is_loopback(hostname)
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

    @model_validator(mode="after")
    def validate_enabled_configuration(self) -> Self:
        """Require complete credentials and host only when Langfuse is enabled.

        Returns:
            The validated settings.

        Raises:
            ValueError: Naming missing fields, never their values.
        """
        if not self.enabled:
            return self
        missing = [
            name
            for name, secret in (("public_key", self.public_key), ("secret_key", self.secret_key))
            if secret is None or not secret.get_secret_value().strip()
        ]
        if self.host is None:
            missing.append("host")
        if missing:
            raise ValueError(
                "Enabled Langfuse export requires externally supplied non-blank "
                + ", ".join(missing)
            )
        return self


def require_live_langfuse(runtime: RuntimeSettings, settings: LangfuseSettings) -> bool:
    """Decide whether real Langfuse export may be constructed.

    Args:
        runtime: Accepted Story 1 runtime settings (live mode keeps requiring
            ``provider_api_key``).
        settings: Validated Langfuse settings.

    Returns:
        False when Langfuse is disabled; True only for an explicitly enabled,
        live, complete configuration.

    Raises:
        ConfigurationError: If Langfuse is enabled outside explicit live mode.
    """
    if not settings.enabled:
        return False
    if runtime.mode is not ExecutionMode.LIVE or not runtime.live_integrations_enabled:
        raise ConfigurationError(
            "Langfuse export requires live mode with explicit live integration enablement."
        )
    return True
