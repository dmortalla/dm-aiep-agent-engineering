"""Ephemeral bring-your-own-key handling for explicit live sessions (Story 9.8).

The backend receives the caller's API key at the trusted application boundary (the Story 9.9 UI
will collect it in a password field) and builds a live ``SessionConfig`` with it. The key lives only
in that session object, as a ``SecretStr`` excluded from serialization and ``repr``; it is never
written to disk, logs, records, events, or errors. Live adapters read it only while they build the
provider client for one call.

Live mode is never implied: an environment variable is read only when application code calls
``credential_from_environment`` explicitly, and even then the caller must still build a live
session explicitly.
"""

import os
from typing import Final

from pydantic import SecretStr, ValidationError

from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.session import (
    ExecutionMode,
    LiveCredential,
    SessionConfig,
)
from multimodal_voice_platform.live.errors import LiveCredentialError

LIVE_PROVIDER_ID: Final = "openai"
MIN_KEY_CHARS: Final = 20
MAX_KEY_CHARS: Final = 512


def _checked_key(api_key: str | SecretStr) -> SecretStr:
    value = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
    if not isinstance(value, str) or not value:
        raise LiveCredentialError("live mode requires an API key; none was supplied")
    if not MIN_KEY_CHARS <= len(value) <= MAX_KEY_CHARS:
        raise LiveCredentialError("the supplied API key has an implausible length")
    if not value.isascii() or not value.isprintable() or any(c.isspace() for c in value):
        raise LiveCredentialError("the supplied API key contains characters a key cannot have")
    return SecretStr(value)


def live_session(
    session_id: str,
    api_key: str | SecretStr,
    *,
    budget: ResourceBudget | None = None,
) -> SessionConfig:
    """Build an explicit, opted-in live session that holds the caller's key ephemerally.

    Args:
        session_id: Application-generated session ID.
        api_key: The caller's provider API key, received at the trusted backend boundary.
        budget: Resource budget; defaults to ``ResourceBudget()``.

    Returns:
        A live ``SessionConfig`` allowlisting only the live provider family.

    Raises:
        LiveCredentialError: If the key is missing or cannot be a key. The key is never echoed.
    """
    key = _checked_key(api_key)
    try:
        return SessionConfig(
            session_id=session_id,
            mode=ExecutionMode.LIVE,
            live_opt_in=True,
            credential=LiveCredential(provider_id=LIVE_PROVIDER_ID, api_key=key),
            allowed_live_providers=frozenset({LIVE_PROVIDER_ID}),
            budget=budget if budget is not None else ResourceBudget(),
        )
    except ValidationError:
        # Validation output can echo inputs; report a fixed message instead.
        raise LiveCredentialError("the live session configuration is invalid") from None


def credential_from_environment(variable: str = "OPENAI_API_KEY") -> SecretStr:
    """Read a key from one named environment variable, for explicit developer execution only.

    Args:
        variable: The variable name. Its value is never printed.

    Returns:
        The key as a ``SecretStr``.

    Raises:
        LiveCredentialError: If the variable is unset or not a plausible key.
    """
    value = os.environ.get(variable)
    if not value:
        raise LiveCredentialError(f"{variable} is not set; live mode needs an explicit API key")
    return _checked_key(value)


def session_credential(session: SessionConfig, provider_id: str = LIVE_PROVIDER_ID) -> SecretStr:
    """Return the key of an explicit live session for one provider family, or fail closed.

    Args:
        session: Application-owned session configuration.
        provider_id: The provider family the adapter belongs to.

    Returns:
        The session's key.

    Raises:
        LiveCredentialError: If the session is not an opted-in live session with a credential for
            this provider on its allowlist.
    """
    credential = session.credential
    if (
        session.mode is not ExecutionMode.LIVE
        or not session.live_opt_in
        or credential is None
        or credential.provider_id != provider_id
        or provider_id not in session.allowed_live_providers
    ):
        raise LiveCredentialError(
            "live providers need an opted-in live session with an allowlisted credential"
        )
    return credential.api_key
