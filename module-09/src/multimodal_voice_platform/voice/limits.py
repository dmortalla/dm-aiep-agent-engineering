"""Bounds for the voice assistant (ADR-009-008). From application configuration only."""

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.contracts.conversation import MAX_REPLY_CHARS
from multimodal_voice_platform.contracts.limits import MAX_HISTORY_TURNS

MAX_RETAINED_TURNS: Final = MAX_HISTORY_TURNS // 2
"""Hard ceiling on retained exchanges. Each exchange is two history entries (user, assistant)."""
MAX_HISTORY_CHARS: Final = 64_000
MAX_TURNS_PER_SESSION: Final = 200
MAX_ACTIVE_SESSIONS: Final = 256
MAX_TURN_TRANSCRIPT_CHARS: Final = 4_000
MAX_OUTPUT_CHUNKS: Final = 16
MAX_OUTPUT_CHARS: Final = 32_000
PROVIDER_CALLS_PER_TURN: Final = 3
"""Speech-to-text, reasoning, and text-to-speech. Each turn reserves this many calls up front."""


class VoiceLimits(BaseModel):
    """Bounds on conversations and turns. Every field has a hard ceiling.

    Retention bounds what the application keeps; context bounds what one reasoning call sees. Both
    are counted in exchanges (one user turn plus its assistant reply) and characters.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_retained_turns: int = Field(default=6, ge=1, le=MAX_RETAINED_TURNS)
    max_history_chars: int = Field(default=12_000, gt=0, le=MAX_HISTORY_CHARS)
    max_context_turns: int = Field(default=4, ge=1, le=MAX_RETAINED_TURNS)
    max_context_chars: int = Field(default=6_000, gt=0, le=MAX_HISTORY_CHARS)
    max_turns_per_session: int = Field(default=50, ge=1, le=MAX_TURNS_PER_SESSION)
    max_active_sessions: int = Field(default=16, ge=1, le=MAX_ACTIVE_SESSIONS)
    max_transcript_chars: int = Field(default=2_000, gt=0, le=MAX_TURN_TRANSCRIPT_CHARS)
    max_reply_chars: int = Field(default=600, gt=0, le=MAX_REPLY_CHARS)
    max_output_chunks: int = Field(default=8, gt=0, le=MAX_OUTPUT_CHUNKS)
    max_output_chars: int = Field(default=16_000, gt=0, le=MAX_OUTPUT_CHARS)

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """Reject bounds whose parts contradict each other.

        Returns:
            The validated limits.

        Raises:
            ValueError: If the context could exceed retention, or one exchange could not fit in
                retained history.
        """
        if self.max_context_turns > self.max_retained_turns:
            raise ValueError("max_context_turns must not exceed max_retained_turns")
        if self.max_context_chars > self.max_history_chars:
            raise ValueError("max_context_chars must not exceed max_history_chars")
        if self.max_transcript_chars + self.max_reply_chars > self.max_history_chars:
            raise ValueError("one exchange must fit within max_history_chars")
        return self
