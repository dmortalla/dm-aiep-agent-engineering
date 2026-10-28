"""Story 13: credential seam for the explicit opt-in live provider path.

Two approved credential-delivery paths exist and neither replaces the other:
trusted server-side sources (environment or secret store bound at bootstrap)
and a transient bring-your-own-key (BYOK) source holding a key the user typed
for the current session. Credentials are never workflow, model, MCP, or memory
input, are not persisted in application-owned or durable state (a UI framework may
hold widget state in memory temporarily), and grant connectivity
only, never authority. A credential is opaque: it cannot be printed, compared,
pickled, copied, or serialized, and lookup failures surface only fixed text.
"""

import os
import re
from collections.abc import Callable
from typing import ClassVar, NoReturn

from harness_engineering.config import CredentialSourceKind, LiveProvider
from harness_engineering.errors import ContractValidationError

# Application-owned names; callers cannot redirect lookup to arbitrary secrets.
ENVIRONMENT_VARIABLES: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
SECRET_STORE_NAMES: dict[str, str] = {
    "openai": "module-06-5-openai-api-key",
    "anthropic": "module-06-5-anthropic-api-key",
}
_CREDENTIAL_PROFILE = re.compile(r"[\x21-\x7e]{8,512}")


class CredentialUnavailableError(ContractValidationError):
    """A trusted credential is absent, malformed, or its lookup failed."""


class LiveCredential:
    """Opaque connectivity secret; never authority, evidence, or display data."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        """Wrap one bounded printable credential.

        Args:
            value: Credential resolved from a trusted source.

        Raises:
            CredentialUnavailableError: If the value violates the profile; the
                value itself is never included in the error.
        """
        if type(value) is not str or _CREDENTIAL_PROFILE.fullmatch(value) is None:
            raise CredentialUnavailableError("Trusted live credential is malformed.")
        self.__value = value

    def reveal_for_sdk(self) -> str:
        """Return the secret for exactly one SDK client construction.

        Returns:
            The raw credential, for the vendor adapter's call-local client only.
        """
        return self.__value

    def __repr__(self) -> str:
        """Return a redacted representation."""
        return "LiveCredential(<redacted>)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        """Compare by identity only so credential content cannot be probed."""
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __reduce__(self) -> NoReturn:
        """Refuse pickling/copying into durable or transferable state."""
        raise TypeError("Live credentials cannot be serialized.")


def _checked(provider: str) -> LiveProvider:
    if provider not in ENVIRONMENT_VARIABLES:
        raise CredentialUnavailableError("Credentials exist only for catalogued providers.")
    return provider  # type: ignore[return-value]


class EnvironmentCredentialSource:
    """Resolve credentials from fixed server-side environment variables at call time."""

    kind: ClassVar[CredentialSourceKind] = "environment"

    def resolve(self, provider: str) -> LiveCredential:
        """Resolve the provider credential from the process environment.

        Args:
            provider: Allowlisted adapter vendor name.

        Returns:
            An opaque credential.

        Raises:
            CredentialUnavailableError: If the variable is absent or malformed.
        """
        value = os.environ.get(ENVIRONMENT_VARIABLES[_checked(provider)])
        if not value:
            raise CredentialUnavailableError("Trusted live credential is not configured.")
        return LiveCredential(value)

    def __repr__(self) -> str:
        """Name the mechanism only."""
        return "EnvironmentCredentialSource()"


class SecretStoreCredentialSource:
    """Resolve credentials through a trusted secret-store lookup bound at bootstrap.

    The lookup is trusted application code (for example a Key Vault or
    platform-secrets client). It receives only fixed application secret names.
    """

    kind: ClassVar[CredentialSourceKind] = "secret_store"

    def __init__(self, lookup: Callable[[str], str | None]) -> None:
        """Bind the trusted lookup callable.

        Args:
            lookup: Returns the secret for an application secret name or None.

        Raises:
            ContractValidationError: If the lookup is not callable.
        """
        if not callable(lookup):
            raise ContractValidationError("Bind a trusted secret-store lookup.")
        self._lookup = lookup

    def resolve(self, provider: str) -> LiveCredential:
        """Resolve the provider credential from the secret store.

        Args:
            provider: Allowlisted adapter vendor name.

        Returns:
            An opaque credential.

        Raises:
            CredentialUnavailableError: If the secret is absent, malformed, or
                the store fails; store diagnostics are never chained.
        """
        name = SECRET_STORE_NAMES[_checked(provider)]
        failed = False
        value: object = None
        try:
            value = self._lookup(name)
        except Exception:
            failed = True
        if failed:
            # Raised outside the except scope so no store diagnostic is chained.
            raise CredentialUnavailableError("Trusted secret store lookup failed.")
        if not value:
            raise CredentialUnavailableError("Trusted live credential is not configured.")
        return LiveCredential(value)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        """Name the mechanism only, never the bound lookup."""
        return "SecretStoreCredentialSource()"


class TransientCredentialSource:
    """Hold one user-supplied (BYOK) credential for a single provider, in memory only.

    The key exists only for the interactive session or request that supplied it.
    It is never written to disk, logged, serialized, copied, compared, placed in a
    URL, prompt, evidence, or error, and is never durable application state. It
    is bound to one provider, handed out only to the provider invocation
    boundary, and dropped by ``discard``. Holding a valid key confers
    connectivity only: it does not enable live mode, pass an allowlist, grant an
    authorization, or alter any bound. (Python cannot scrub memory; dropping the
    reference is the strongest guarantee, so no custom encryption or storage is
    attempted.)
    """

    kind: ClassVar[CredentialSourceKind] = "byok"
    __slots__ = ("_credential", "_provider")

    def __init__(self, provider: str, value: str) -> None:
        """Bind a provider and wrap the typed key.

        Args:
            provider: Catalogued provider the key is for.
            value: The user-supplied key; validated against the credential profile.

        Raises:
            CredentialUnavailableError: For an uncatalogued provider or a key that
                violates the profile; the value is never included in the error.
        """
        self._provider = _checked(provider)
        self._credential: LiveCredential | None = LiveCredential(value)

    def resolve(self, provider: str) -> LiveCredential:
        """Return the key for the bound provider at the invocation boundary only.

        Args:
            provider: Adapter vendor about to be invoked.

        Returns:
            The opaque credential.

        Raises:
            CredentialUnavailableError: If discarded or requested for another provider.
        """
        if self._credential is None or provider != self._provider:
            raise CredentialUnavailableError("Trusted live credential is not available.")
        return self._credential

    def discard(self) -> None:
        """Drop the only reference this source holds to the key."""
        self._credential = None

    def __repr__(self) -> str:
        """Name the mechanism only."""
        return "TransientCredentialSource(<redacted>)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        """Compare by identity only."""
        return self is other

    __hash__ = None  # type: ignore[assignment]

    def __reduce__(self) -> NoReturn:
        """Refuse pickling/copying into durable or transferable state."""
        raise TypeError("Live credentials cannot be serialized.")


CredentialSource = (
    EnvironmentCredentialSource | SecretStoreCredentialSource | TransientCredentialSource
)
CREDENTIAL_SOURCE_TYPES = (
    EnvironmentCredentialSource, SecretStoreCredentialSource, TransientCredentialSource,
)
