"""Validated HTTP-only settings, independent of the inference core."""

from dataclasses import dataclass
from math import isfinite

from module10_ai.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class HttpConfig:
    """Bound HTTP resource use with explicit trusted construction.

    Args:
        inference_timeout_seconds: Cooperative inference deadline, 0.01 to 30 seconds.
        body_timeout_seconds: Total body-read deadline, 0.01 to 30 seconds.
        max_body_bytes: Raw body ceiling, 128 to 65536 bytes.
        max_text_characters: HTTP text ceiling, 1 to the domain ceiling of 4096.
        max_request_id_characters: Identifier ceiling, 32 to 128 ASCII characters.
        docs_enabled: Explicit opt-in for interactive documentation.

    Raises:
        ConfigurationError: A supplied setting is invalid.
    """

    inference_timeout_seconds: float = 5.0
    body_timeout_seconds: float = 5.0
    max_body_bytes: int = 32768
    max_text_characters: int = 4096
    max_request_id_characters: int = 64
    docs_enabled: bool = False

    def __post_init__(self) -> None:
        """Reject coercion, nonfinite deadlines, and unsafe resource bounds."""
        for value in (self.inference_timeout_seconds, self.body_timeout_seconds):
            if type(value) not in (int, float) or not isfinite(value) or not 0.01 <= value <= 30:
                raise ConfigurationError("HTTP deadlines must be finite numbers from 0.01 to 30.")
        for value, lower, upper in (
            (self.max_body_bytes, 128, 65536),
            (self.max_text_characters, 1, 4096),
            (self.max_request_id_characters, 32, 128),
        ):
            if type(value) is not int or not lower <= value <= upper:
                raise ConfigurationError("HTTP resource setting is outside its integer bounds.")
        if type(self.docs_enabled) is not bool:
            raise ConfigurationError("Documentation setting must be a boolean.")
