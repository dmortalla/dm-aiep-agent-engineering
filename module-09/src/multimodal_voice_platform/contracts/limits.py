"""Hard resource ceilings, configurable budgets, and latency stages (ADR-009-008)."""

from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TEXT_CHARS: Final = 20_000
MAX_TRANSCRIPT_CHARS: Final = 20_000
MAX_DELTA_CHARS: Final = 4_000
MAX_IMAGE_BYTES: Final = 10 * 1024 * 1024
MAX_AUDIO_BYTES: Final = 25 * 1024 * 1024
MAX_DOCUMENT_BYTES: Final = 20 * 1024 * 1024
MAX_AUDIO_DURATION_MS: Final = 5 * 60 * 1000
MAX_DOCUMENT_PAGES: Final = 50
MAX_OUTPUT_TOKENS: Final = 4_096
MAX_REQUEST_TIMEOUT_S: Final = 60.0
MAX_SESSION_TIMEOUT_S: Final = 30 * 60.0
MAX_RETRIES: Final = 3
MAX_HISTORY_TURNS: Final = 50
MAX_PROVIDER_CALLS_PER_SESSION: Final = 200
MAX_REASONING_PARTS: Final = 16


class LatencyStage(StrEnum):
    """Pipeline stages whose latency is measured and reported to reviewers."""

    INGESTION = "ingestion"
    SPEECH_TO_TEXT = "speech_to_text"
    VISION = "vision"
    DOCUMENT_UNDERSTANDING = "document_understanding"
    REASONING = "reasoning"
    FIRST_RESPONSE = "first_response"
    TEXT_TO_SPEECH = "text_to_speech"
    END_TO_END = "end_to_end"
    SESSION_SETUP = "session_setup"
    """Story 9.7: from WebSocket connection to ``session_started``."""
    TURN_ACCEPTANCE = "turn_acceptance"
    """Story 9.7: from turn receipt to admission."""
    TRANSCRIPT_READY = "transcript_ready"
    """Story 9.7: from turn receipt to ``transcript_final``."""
    RESPONSE_COMPLETION = "response_completion"
    """Story 9.7: from turn receipt to ``response_complete``."""
    AUDIO_READY = "audio_ready"
    """Story 9.7: from turn receipt to ``audio_ready``."""


class ResourceBudget(BaseModel):
    """Configurable per-session budget that can never exceed the hard ceilings.

    Budgets come only from application configuration, never from content or model output.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_image_bytes: int = Field(default=5 * 1024 * 1024, gt=0, le=MAX_IMAGE_BYTES)
    max_audio_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=MAX_AUDIO_BYTES)
    max_document_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=MAX_DOCUMENT_BYTES)
    max_audio_duration_ms: int = Field(default=2 * 60 * 1000, gt=0, le=MAX_AUDIO_DURATION_MS)
    max_document_pages: int = Field(default=20, gt=0, le=MAX_DOCUMENT_PAGES)
    max_output_tokens: int = Field(default=1_024, gt=0, le=MAX_OUTPUT_TOKENS)
    request_timeout_s: float = Field(default=30.0, gt=0, le=MAX_REQUEST_TIMEOUT_S)
    session_timeout_s: float = Field(default=15 * 60.0, gt=0, le=MAX_SESSION_TIMEOUT_S)
    max_retries: int = Field(default=2, ge=0, le=MAX_RETRIES)
    max_history_turns: int = Field(default=20, gt=0, le=MAX_HISTORY_TURNS)
    max_provider_calls_per_session: int = Field(
        default=60, gt=0, le=MAX_PROVIDER_CALLS_PER_SESSION
    )

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """Reject budgets whose parts contradict each other.

        Returns:
            The validated budget.

        Raises:
            ValueError: If a single request could exhaust the session budget through retries, or
                the request timeout exceeds the session timeout.
        """
        if self.max_retries >= self.max_provider_calls_per_session:
            raise ValueError("max_retries must be below max_provider_calls_per_session")
        if self.request_timeout_s > self.session_timeout_s:
            raise ValueError("request_timeout_s must not exceed session_timeout_s")
        return self
