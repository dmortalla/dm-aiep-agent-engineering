"""Typed runtime configuration with explicit live-mode activation."""

from typing import Self

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .domain import ExecutionMode
from .errors import ConfigurationError


class RuntimeSettings(BaseSettings):
    """Validated immutable Module 7 runtime settings.

    Live behavior requires both live mode and explicit integration enablement.
    Credential presence alone never activates a live integration.
    """

    model_config = SettingsConfigDict(
        env_prefix="MODULE7_",
        env_file=None,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    live_integrations_enabled: bool = False
    provider_api_key: SecretStr | None = Field(default=None, repr=False)

    def __init__(self, **values: object) -> None:
        """Validate settings without exposing raw configuration input.

        Args:
            **values: Explicit settings values. Missing values may be loaded from
                the configured Module 7 environment variables.

        Raises:
            ConfigurationError: If security-critical configuration is invalid.
        """
        error_message: str | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            safe_errors = exc.errors(
                include_input=False,
                include_context=False,
                include_url=False,
            )
            messages = "; ".join(str(error["msg"]) for error in safe_errors)
            error_message = f"Invalid Module 7 runtime configuration: {messages}"

        if error_message is not None:
            raise ConfigurationError(error_message)


    @model_validator(mode="after")
    def validate_live_configuration(self) -> Self:
        """Validate security-critical live-mode invariants.

        Returns:
            The validated immutable settings instance.

        Raises:
            ValueError: If live execution is not explicitly and safely configured.
        """
        if self.mode is ExecutionMode.LIVE:
            if not self.live_integrations_enabled:
                raise ValueError(
                    "Live mode requires explicit live integration enablement."
                )
            if self.provider_api_key is None:
                raise ValueError(
                    "Live mode requires externally supplied provider credentials."
                )
            if not self.provider_api_key.get_secret_value().strip():
                raise ValueError(
                    "Live mode requires non-blank externally supplied provider credentials."
                )

        if self.mode is ExecutionMode.DETERMINISTIC and self.live_integrations_enabled:
            raise ValueError(
                "Live integrations cannot be enabled while deterministic mode is active."
            )

        return self

    def validated_update(self, **changes: object) -> Self:
        """Return a new settings object after complete validation.

        Args:
            **changes: Settings fields to replace atomically.

        Returns:
            A newly validated immutable settings instance.

        Raises:
            ConfigurationError: If the resulting configuration is invalid.
        """
        values = {name: getattr(self, name) for name in type(self).model_fields}
        values.update(changes)
        return type(self)(**values, _env_file=None)
