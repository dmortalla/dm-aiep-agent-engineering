"""Bounds for real-time streaming (Story 9.7, ADR-009-008). From application configuration only."""

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.contracts.conversation import MAX_REPLY_ACTS
from multimodal_voice_platform.contracts.streaming import MAX_CLIENT_MESSAGE_BYTES

MAX_STREAM_AUDIO_BYTES: Final = 2 * 1024 * 1024
"""Hard ceiling on decoded audio in one streamed turn."""
MAX_EVENTS_PER_TURN: Final = 256
MAX_PROTOCOL_ERRORS: Final = 16
MAX_SEND_TIMEOUT_S: Final = 30.0
MAX_IDLE_TIMEOUT_S: Final = 900.0
MAX_TURN_TIMEOUT_S: Final = 120.0
MAX_CONNECTIONS: Final = 256
ENVELOPE_BYTES: Final = 4 * 1024
"""Room in one client message for everything except the encoded audio."""


class StreamingLimits(BaseModel):
    """Bounds on connections, client messages, streamed turns, and sends. Each has a ceiling.

    Every bound exists so a slow, silent, or hostile client cannot make the server hold unbounded
    memory, tasks, or provider work.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_inbound_message_bytes: int = Field(
        default=512 * 1024, ge=ENVELOPE_BYTES, le=MAX_CLIENT_MESSAGE_BYTES
    )
    max_audio_bytes: int = Field(default=256 * 1024, gt=0, le=MAX_STREAM_AUDIO_BYTES)
    max_reply_fragments: int = Field(default=MAX_REPLY_ACTS, ge=1, le=MAX_REPLY_ACTS)
    max_events_per_turn: int = Field(default=64, ge=4, le=MAX_EVENTS_PER_TURN)
    max_protocol_errors: int = Field(default=3, ge=1, le=MAX_PROTOCOL_ERRORS)
    send_timeout_s: float = Field(default=5.0, gt=0, le=MAX_SEND_TIMEOUT_S)
    idle_timeout_s: float = Field(default=120.0, gt=0, le=MAX_IDLE_TIMEOUT_S)
    turn_timeout_s: float = Field(default=60.0, gt=0, le=MAX_TURN_TIMEOUT_S)
    max_connections: int = Field(default=16, ge=1, le=MAX_CONNECTIONS)

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """Require the largest allowed audio to fit in one client message.

        Returns:
            The validated limits.

        Raises:
            ValueError: If base64-encoded audio of ``max_audio_bytes`` cannot fit in a message.
        """
        encoded = 4 * ((self.max_audio_bytes + 2) // 3)
        if encoded + ENVELOPE_BYTES > self.max_inbound_message_bytes:
            raise ValueError("max_audio_bytes, base64-encoded, must fit in one client message")
        return self
