"""Audio processing limits, derived from the session ``ResourceBudget`` (SEC-005, SEC-006)."""

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.contracts.limits import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_DURATION_MS,
    MAX_REQUEST_TIMEOUT_S,
    ResourceBudget,
)

MIN_SAMPLE_RATE_HZ: Final = 8_000
MAX_SAMPLE_RATE_HZ: Final = 192_000
MAX_CHANNELS: Final = 8
MAX_WAV_CHUNKS: Final = 64
"""Hard ceilings on WAV parameters and structure, checked from the header before decoding."""


class AudioLimits(BaseModel):
    """Bounds applied to audio input and generated audio. From application configuration only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_audio_bytes: int = Field(gt=0, le=MAX_AUDIO_BYTES)
    max_audio_duration_ms: int = Field(gt=0, le=MAX_AUDIO_DURATION_MS)
    timeout_s: float = Field(gt=0, le=MAX_REQUEST_TIMEOUT_S)

    @classmethod
    def from_budget(cls, budget: ResourceBudget) -> Self:
        """Derive audio limits from a session budget.

        Args:
            budget: Application-owned session budget.

        Returns:
            Limits that never exceed the budget or the hard ceilings.
        """
        return cls(
            max_audio_bytes=budget.max_audio_bytes,
            max_audio_duration_ms=budget.max_audio_duration_ms,
            timeout_s=budget.request_timeout_s,
        )
