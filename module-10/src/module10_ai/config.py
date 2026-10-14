"""Explicit no-key configuration; environment credentials are never consulted."""

from dataclasses import dataclass

from module10_ai.contracts import MAX_TEXT_CHARACTERS
from module10_ai.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Validated deterministic runtime configuration.

    Args:
        mode: Only deterministic execution is implemented in Story 10.2.
        max_text_characters: Application input ceiling within the domain hard limit.

    Raises:
        ConfigurationError: Mode or resource bound is invalid.
    """

    mode: str = "deterministic"
    max_text_characters: int = MAX_TEXT_CHARACTERS

    def __post_init__(self) -> None:
        """Fail closed on unsupported modes and invalid resource limits."""
        if type(self.mode) is not str or self.mode != "deterministic":
            raise ConfigurationError("Only deterministic mode is available in Story 10.2.")
        if (type(self.max_text_characters) is not int
                or not 1 <= self.max_text_characters <= MAX_TEXT_CHARACTERS):
            raise ConfigurationError("Text ceiling must be an integer from 1 through 4096.")
