"""Story 6 LangSmith settings: explicit, secret-safe and inactive by default.

The accepted ``RuntimeSettings`` schema is unchanged. LangSmith export requires
live runtime mode, explicit runtime live enablement, this module's own flag and
explicit budget configuration. Ambient ``LANGSMITH_*`` and ``LANGCHAIN_*``
variables are never read here; their presence refuses the live branch.
"""

import ipaddress
import os
import re
import socket
import threading
import uuid as uuid_module
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .config import RuntimeSettings
from .domain import ExecutionMode
from .errors import ConfigurationError

_LOOPBACK_NAMES = frozenset({"localhost"})
_LOCALHOST_SUFFIXES = frozenset({".localhost", ".localdomain", ".local", ".internal"})
_AMBIENT_PREFIXES = ("LANGSMITH_", "LANGCHAIN_")
_EXPORT_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

_QUALIFICATION_MESSAGE = (
    "LangSmith endpoint failed qualification and was refused."
)
_ENDPOINT_RESOLUTION_TIMEOUT_SECONDS: float = 3.0


def _is_loopback(hostname: str) -> bool:
    """Return whether a URL hostname is a loopback name or address."""
    if hostname.casefold() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_prohibited_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is ever a permitted LangSmith target.

    Loopback, link-local, unspecified, IPv4-mapped IPv6 and every private or
    reserved address family are prohibited; only globally routable public
    addresses qualify for the live branch (the reserved non-routable test
    origin is a separate documented seam, checked elsewhere).
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return not address.is_global or address.is_multicast


def _is_numerical_hostname(hostname: str) -> bool:
    """Return whether a hostname tries to smuggle a noncanonical IPv4 form.

    Canonical-only policy: recognized noncanonical numeric spellings (pure
    decimal integers, compressed or zero-padded octets) are refused regardless
    of which address they would resolve to.
    """
    if hostname and hostname.isascii() and all(ch.isdigit() for ch in hostname):
        return True  # A pure decimal integer, e.g. 2130706433.
    if "." not in hostname:
        return False
    parts = hostname.split(".")
    return all(
        bool(part) and part.isascii() and part.isdigit() for part in parts
    )


def _is_prohibited_hostname_syntax(hostname: str) -> bool:
    """Return whether a hostname is locally prohibited without any lookup.

    Canonical IP literals are judged by their address family rules only;
    anything that fails canonical parsing but looks numeric (pure decimal
    integers, compressed or zero-padded octets) is refused outright, so
    noncanonical numeric spellings never reach DNS.
    """
    name = hostname.casefold().rstrip(".")
    if name in _LOOPBACK_NAMES or name.startswith("localhost."):
        return True
    if any(name.endswith(suffix) for suffix in _LOCALHOST_SUFFIXES):
        return True
    try:
        # A canonical IP literal: either its family is prohibited or it is
        # eligible to resolve further (never re-parsed leniency-wise).
        return _is_prohibited_address(ipaddress.ip_address(hostname))
    except ValueError:
        return _is_numerical_hostname(hostname)


def _resolve_prohibited(hostname: str) -> bool:
    """Boundedly resolve a hostname and refuse anything not globally routable.

    Resolution runs one bounded worker; any timeout, resolution failure or
    prohibited address fails closed (prohibited). IP literals never resolve
    through DNS here.
    """
    outcome: dict[str, list[str] | None] = {"addresses": None}
    guard = threading.Thread(
        target=_resolve_worker,
        args=(hostname, outcome),
        name="module7-endpoint-qualification",
        daemon=True,
    )
    guard.start()
    guard.join(_ENDPOINT_RESOLUTION_TIMEOUT_SECONDS)
    addresses = outcome["addresses"]
    if addresses is None:
        return True  # Unresolved or timed out: fail closed.
    if not addresses:
        return True  # Resolution never produced an address: fail closed.
    try:
        parsed = [ipaddress.ip_address(item) for item in addresses]
    except ValueError:
        return True
    return any(_is_prohibited_address(address) for address in parsed)


def _resolve_worker(hostname: str, outcome: dict[str, list[str] | None]) -> None:
    """Worker body: collect every resolved address, never raising."""
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        outcome["addresses"] = [str(info[4][0]) for info in infos]
    except Exception:
        outcome["addresses"] = []
    finally:
        socket.setdefaulttimeout(None)


def qualify_https_endpoint(api_url: str | None) -> bool:
    """Qualify an HTTPS endpoint for the live branch before anything is built.

    Enforced before any client construction or credential use: HTTPS only, no
    prohibited local/mapped/numeric forms, no local hostname aliases, and
    fail-closed bounded resolution for ordinary hostnames.

    Args:
        api_url: The configured base URL.

    Returns:
        True when the endpoint qualifies; a reserved seam origin is never
        qualified by the live branch and is checked separately.

    Raises:
        ConfigurationError: With a fixed message that never echoes the URL.
    """
    if api_url is None:
        raise ConfigurationError(_QUALIFICATION_MESSAGE)
    parts = urlsplit(api_url)
    hostname = parts.hostname
    if (
        parts.scheme != "https"
        or not hostname
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
    ):
        raise ConfigurationError(_QUALIFICATION_MESSAGE)
    if _is_prohibited_hostname_syntax(hostname):
        raise ConfigurationError(_QUALIFICATION_MESSAGE)
    if _resolve_prohibited(hostname):
        raise ConfigurationError(_QUALIFICATION_MESSAGE)
    return True


def ambient_langsmith_variables() -> frozenset[str]:
    """Return ambient ``LANGSMITH_``/``LANGCHAIN_`` variable names present now.

    Returns:
        The matching environment variable names; never values.
    """
    return frozenset(
        name for name in os.environ if name.upper().startswith(_AMBIENT_PREFIXES)
    )


class LangSmithSettings(BaseSettings):
    """Validated immutable LangSmith export settings.

    Attributes:
        enabled: Explicit LangSmith enablement; credentials alone never enable it.
        api_key: Externally supplied LangSmith API key.
        api_url: Explicit LangSmith base URL; HTTPS, or HTTP for loopback only.
        workspace_id: Optional non-secret workspace UUID.
        export_name_prefix: Application-owned export name prefix.
        max_exported_scenarios: Explicit exported-scenario limit, at most 64.
        max_http_requests: Finite request-count budget, at most 1024.
        reservation_per_request_usd: Nonnegative never-refunded per-request
            reservation; unset means live execution is refused.
        run_cost_limit_usd: Explicit positive run cost limit.
        request_timeout_seconds: Per-SDK-call HTTP timeout.
        lifecycle_timeout_seconds: Application wait bound for close and other
            blocking lifecycle operations.
        readback_attempts: Finite live-verification readback attempts.
        readback_interval_seconds: Wait between live-verification readbacks.
        live_deadline_seconds: Whole live-run deadline, at most 600.
    """

    model_config = SettingsConfigDict(
        env_prefix="MODULE7_LANGSMITH_",
        env_file=None,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    enabled: bool = False
    api_key: SecretStr | None = Field(default=None, repr=False)
    api_url: str | None = Field(default=None, repr=False, max_length=2048)
    workspace_id: uuid_module.UUID | None = None
    export_name_prefix: str = "module7"
    max_exported_scenarios: int = Field(default=12, ge=1, le=64)
    max_http_requests: int = Field(default=256, ge=1, le=1024)
    reservation_per_request_usd: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False,
    )
    run_cost_limit_usd: float | None = Field(
        default=None, gt=0.0, allow_inf_nan=False,
    )
    request_timeout_seconds: int = Field(default=10, ge=1, le=30)
    lifecycle_timeout_seconds: float = Field(default=10.0, ge=0, le=60, allow_inf_nan=False)
    readback_attempts: int = Field(default=6, ge=1, le=10)
    readback_interval_seconds: float = Field(default=5.0, ge=0, le=30, allow_inf_nan=False)
    live_deadline_seconds: float = Field(default=120.0, gt=0, le=600, allow_inf_nan=False)

    def __init__(self, **values: object) -> None:
        """Validate settings without exposing raw configuration input.

        Args:
            **values: Explicit values; missing values may come from
                ``MODULE7_LANGSMITH_*`` environment variables.

        Raises:
            ConfigurationError: If LangSmith configuration is invalid.
        """
        error_message: str | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            safe_errors = exc.errors(
                include_input=False, include_context=False, include_url=False,
            )
            messages = "; ".join(str(error["msg"]) for error in safe_errors)
            error_message = f"Invalid Module 7 LangSmith configuration: {messages}"
        if error_message is not None:
            raise ConfigurationError(error_message)

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str | None) -> str | None:
        """Accept only an explicit credential-free HTTPS or loopback HTTP URL.

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
            "api_url must be an https URL (http only for loopback) without "
            "credentials, query, fragment, whitespace or control characters"
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

    @field_validator("export_name_prefix")
    @classmethod
    def validate_export_name_prefix(cls, value: str) -> str:
        """Refuse export name prefixes outside the safe bounded pattern.

        Args:
            value: Candidate prefix; the fixed committed default is safe.

        Returns:
            The validated prefix.

        Raises:
            ValueError: With a fixed message.
        """
        if _EXPORT_PREFIX_PATTERN.match(value):
            return value
        raise ValueError("export_name_prefix uses an unsupported name pattern.")

    @model_validator(mode="after")
    def validate_enabled_configuration(self) -> Self:
        """Require complete, budgeted configuration when LangSmith is enabled.

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
        if self.api_url is None:
            missing.append("api_url")
        if self.reservation_per_request_usd is None:
            missing.append("reservation_per_request_usd")
        if self.run_cost_limit_usd is None:
            missing.append("run_cost_limit_usd")
        if missing:
            raise ValueError(
                "Enabled LangSmith export requires externally supplied non-blank "
                + ", ".join(missing)
            )
        if (
            self.run_cost_limit_usd is not None
            and self.reservation_per_request_usd is not None
            and self.reservation_per_request_usd > self.run_cost_limit_usd
        ):
            # An explicit zero reservation is permitted; any other explicit
            # reservation must fit within the run cost limit.
            raise ValueError(
                "Enabled LangSmith export requires a reservation within "
                "the run cost limit."
            )
        return self

    def is_remote_https_endpoint(self) -> bool:
        """Return whether the endpoint is HTTPS and syntactically non-local.

        This syntactic check never advances the live branch by itself; the
        stronger bounded qualification (including fail-closed resolution) runs
        before anything is constructed.
        """
        if self.api_url is None:
            return False
        parts = urlsplit(self.api_url)
        return (
            parts.scheme == "https"
            and parts.hostname is not None
            and not _is_prohibited_hostname_syntax(parts.hostname)
        )


def require_live_langsmith(
    runtime: RuntimeSettings,
    settings: LangSmithSettings,
    *,
    opt_in: bool = False,
) -> bool:
    """Decide whether real LangSmith export may be constructed.

    All activation gates are enforced here: explicit runtime live mode with live
    integration enablement, an enabled complete settings object, no ambient
    ``LANGSMITH_``/``LANGCHAIN_`` variables, and a separate explicit opt-in.

    Args:
        runtime: Accepted Story 1 runtime settings.
        settings: Validated LangSmith settings.
        opt_in: Explicit live-call opt-in, separate from configuration.

    Returns:
        False when LangSmith is disabled; True only for a fully activated,
        live, complete, budgeted and opted-in configuration.

    Raises:
        ConfigurationError: If LangSmith is enabled outside an explicitly
            activated live configuration or ambient vendor variables exist.
    """
    if not settings.enabled:
        return False
    missing: list[str] = []
    if runtime.mode is not ExecutionMode.LIVE or not runtime.live_integrations_enabled:
        raise ConfigurationError(
            "LangSmith export requires live mode with explicit live integration enablement."
        )
    if not opt_in:
        missing.append("opt_in")
    ambient = ambient_langsmith_variables()
    if ambient:
        raise ConfigurationError(
            "Live LangSmith export refuses to run while ambient "
            "LANGSMITH_*/LANGCHAIN_* variables are present."
        )
    if (
        settings.reservation_per_request_usd is None
        or settings.run_cost_limit_usd is None
    ):
        missing.append("reservation_per_request_usd, run_cost_limit_usd")
    if missing:
        raise ConfigurationError(
            "Live LangSmith export requires explicit " + ", ".join(missing) + "."
        )
    return True


__all__ = [
    "LangSmithSettings",
    "ambient_langsmith_variables",
    "qualify_https_endpoint",
    "require_live_langsmith",
]
