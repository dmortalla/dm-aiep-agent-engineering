"""Session, conversation, and execution-mode contracts (ADR-009-004)."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from multimodal_voice_platform.contracts.limits import MAX_TEXT_CHARS, ResourceBudget
from multimodal_voice_platform.contracts.modality import Identifier, TrustLevel


class ExecutionMode(StrEnum):
    """First-class execution modes. Deterministic is the default."""

    DETERMINISTIC = "deterministic"
    LIVE = "live"


class ConversationRole(StrEnum):
    """Speaker of a conversation turn."""

    USER = "user"
    ASSISTANT = "assistant"


class ConversationTurn(BaseModel):
    """One turn of conversation history. Both roles carry untrusted content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ConversationRole
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    trust: TrustLevel

    @model_validator(mode="after")
    def validate_trust(self) -> Self:
        """Bind each role to its untrusted classification.

        Returns:
            The validated turn.

        Raises:
            ValueError: If the trust level does not match the role.
        """
        expected = (
            TrustLevel.UNTRUSTED_EXTERNAL
            if self.role is ConversationRole.USER
            else TrustLevel.UNTRUSTED_MODEL_OUTPUT
        )
        if self.trust is not expected:
            raise ValueError(f"{self.role} turns must be classified {expected}")
        return self


class LiveCredential(BaseModel):
    """User-supplied provider credential. Ephemeral: held in session memory only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: Identifier
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        """Bound the credential length without revealing its value.

        Args:
            value: The secret credential.

        Returns:
            The unchanged secret.

        Raises:
            ValueError: If the credential is implausibly short or long.
        """
        if not 8 <= len(value.get_secret_value()) <= 512:
            raise ValueError("api_key length is outside the accepted range")
        return value


class SessionConfig(BaseModel):
    """Application-owned session configuration. The only source of mode and budget authority.

    Live mode requires explicit opt-in, a credential, and a provider on the application
    allowlist. Credential presence alone never selects live mode.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: Identifier
    mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    live_opt_in: bool = False
    credential: LiveCredential | None = Field(default=None, exclude=True, repr=False)
    allowed_live_providers: frozenset[Identifier] = frozenset()
    budget: ResourceBudget = Field(default_factory=ResourceBudget)

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        """Fail closed on any ambiguous mode or credential combination.

        Returns:
            The validated configuration.

        Raises:
            ValueError: If live mode lacks opt-in, a credential, or an allowlisted provider, or if
                deterministic mode carries live settings.
        """
        if self.mode is ExecutionMode.LIVE:
            if not self.live_opt_in:
                raise ValueError("live mode requires explicit live_opt_in")
            if self.credential is None:
                raise ValueError("live mode requires a user-supplied credential")
            if self.credential.provider_id not in self.allowed_live_providers:
                raise ValueError("credential provider is not on the live provider allowlist")
        elif self.live_opt_in or self.credential is not None:
            raise ValueError("deterministic mode must not carry live opt-in or credentials")
        return self
