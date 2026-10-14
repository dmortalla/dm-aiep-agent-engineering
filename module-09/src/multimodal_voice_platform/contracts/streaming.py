"""Typed WebSocket streaming protocol (ADR-009-005).

Defines the event vocabulary and a strict parser only. The WebSocket server is Story 9.7.
"""

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from multimodal_voice_platform.contracts.errors import SafeError, StreamProtocolError
from multimodal_voice_platform.contracts.limits import (
    MAX_AUDIO_DURATION_MS,
    MAX_DELTA_CHARS,
    MAX_TRANSCRIPT_CHARS,
    LatencyStage,
)
from multimodal_voice_platform.contracts.modality import MEDIA_TYPES, Identifier, Modality
from multimodal_voice_platform.contracts.session import ExecutionMode

PROTOCOL_VERSION: Final = 1
MAX_EVENT_BYTES: Final = 64 * 1024


class StreamEventType(StrEnum):
    """Event types carried over the streaming boundary."""

    SESSION_STARTED = "session_started"
    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_FINAL = "transcript_final"
    RESPONSE_DELTA = "response_delta"
    RESPONSE_COMPLETE = "response_complete"
    AUDIO_READY = "audio_ready"
    METRIC = "metric"
    ERROR = "error"
    SESSION_COMPLETE = "session_complete"


class _StreamEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal[1] = PROTOCOL_VERSION
    session_id: Identifier
    sequence: int = Field(ge=0)


class SessionStarted(_StreamEventBase):
    """A streaming session began in the given execution mode."""

    type: Literal["session_started"] = "session_started"
    mode: ExecutionMode


class TranscriptPartial(_StreamEventBase):
    """Interim speech-to-text output."""

    type: Literal["transcript_partial"] = "transcript_partial"
    text: str = Field(max_length=MAX_TRANSCRIPT_CHARS)


class TranscriptFinal(_StreamEventBase):
    """Final speech-to-text output for the utterance."""

    type: Literal["transcript_final"] = "transcript_final"
    text: str = Field(max_length=MAX_TRANSCRIPT_CHARS)


class ResponseDelta(_StreamEventBase):
    """Incremental assistant response text."""

    type: Literal["response_delta"] = "response_delta"
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=MAX_DELTA_CHARS)


class ResponseComplete(_StreamEventBase):
    """The assistant response finished."""

    type: Literal["response_complete"] = "response_complete"
    finish_reason: Literal["completed", "budget_exhausted", "cancelled"]
    delta_count: int = Field(ge=0)


class AudioReady(_StreamEventBase):
    """Synthesized audio is available by reference."""

    type: Literal["audio_ready"] = "audio_ready"
    audio_ref: Identifier
    media_type: str
    duration_ms: int = Field(gt=0, le=MAX_AUDIO_DURATION_MS)

    @model_validator(mode="after")
    def validate_media_type(self) -> Self:
        """Require an allowlisted audio media type.

        Returns:
            The validated event.

        Raises:
            ValueError: If the media type is not an allowed audio type.
        """
        if self.media_type not in MEDIA_TYPES[Modality.AUDIO]:
            raise ValueError("audio_ready media type is not allowed")
        return self


class Metric(_StreamEventBase):
    """Measured latency for one pipeline stage."""

    type: Literal["metric"] = "metric"
    stage: LatencyStage
    duration_ms: float = Field(ge=0, le=3_600_000)


class StreamError(_StreamEventBase):
    """A safe, structured error."""

    type: Literal["error"] = "error"
    error: SafeError


class SessionComplete(_StreamEventBase):
    """The streaming session ended."""

    type: Literal["session_complete"] = "session_complete"
    reason: Literal["completed", "client_closed", "error", "timeout", "budget_exhausted"]


StreamEvent = Annotated[
    SessionStarted
    | TranscriptPartial
    | TranscriptFinal
    | ResponseDelta
    | ResponseComplete
    | AudioReady
    | Metric
    | StreamError
    | SessionComplete,
    Field(discriminator="type"),
]

_STREAM_EVENT_ADAPTER: Final[TypeAdapter[StreamEvent]] = TypeAdapter(StreamEvent)


def parse_stream_event(raw: str | bytes) -> StreamEvent:
    """Parse one JSON stream message, rejecting anything outside the protocol.

    Args:
        raw: The JSON message received over the streaming boundary.

    Returns:
        The typed stream event.

    Raises:
        StreamProtocolError: If the message is too large, malformed, of unknown type, or violates
            an event invariant.
    """
    size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if size > MAX_EVENT_BYTES:
        raise StreamProtocolError("stream message exceeds the maximum size")
    try:
        return _STREAM_EVENT_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        raise StreamProtocolError("stream message violates the streaming protocol") from exc


def serialize_stream_event(event: StreamEvent) -> str:
    """Serialize a typed stream event to JSON.

    Args:
        event: The event to serialize.

    Returns:
        The JSON message.
    """
    return _STREAM_EVENT_ADAPTER.dump_json(event).decode("utf-8")
