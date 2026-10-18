"""Typed WebSocket streaming protocol (ADR-009-005).

Story 9.1 defined the server event vocabulary and a strict parser. Story 9.7 extends it, within
protocol version 1, with the events and fields the WebSocket gateway needs to stream a voice turn
truthfully, and with the typed client messages the gateway accepts:

- every event may carry ``turn_id``; the Story 9.7 server sets it on every turn-scoped event;
- ``turn_accepted`` reports that a turn passed admission;
- ``turn_complete`` reports a turn's final outcome and whether it committed to session state;
- ``metric`` states whether it measures one stage or the time elapsed since a reference point.

Client messages carry no session ID, mode, budget, provider, trust, or evidence field: the session
is bound to the connection by the server, and everything else is application configuration. A
message with any field outside its model is rejected.
"""

import base64
import binascii
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from multimodal_voice_platform.contracts.errors import SafeError, StreamProtocolError
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_DURATION_MS,
    MAX_DELTA_CHARS,
    MAX_TRANSCRIPT_CHARS,
    LatencyStage,
)
from multimodal_voice_platform.contracts.modality import MEDIA_TYPES, Identifier, Modality
from multimodal_voice_platform.contracts.session import ExecutionMode

PROTOCOL_VERSION: Final = 1
MAX_EVENT_BYTES: Final = 64 * 1024
MAX_CLIENT_MESSAGE_BYTES: Final = 4 * 1024 * 1024
"""Hard ceiling on one client message. Deployments configure a lower bound."""
MAX_ENCODED_AUDIO_CHARS: Final = 4 * ((MAX_AUDIO_BYTES + 2) // 3)
"""Base64 length of the largest audio any session budget allows."""

StageName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,39}$")]
"""A server-side pipeline stage name, such as ``audio_validation``."""


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
    TURN_ACCEPTED = "turn_accepted"
    TURN_COMPLETE = "turn_complete"


class _StreamEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal[1] = PROTOCOL_VERSION
    session_id: Identifier
    sequence: int = Field(ge=0)
    turn_id: Identifier | None = None


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
    """Generated audio is available by reference.

    ``audio_sha256`` and ``size_bytes`` (Story 9.7) identify the validated audio the server holds.
    """

    type: Literal["audio_ready"] = "audio_ready"
    audio_ref: Identifier
    media_type: str
    duration_ms: int = Field(gt=0, le=MAX_AUDIO_DURATION_MS)
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, gt=0, le=MAX_AUDIO_BYTES)

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
    """Measured latency for one pipeline stage or milestone.

    ``measure`` (Story 9.7) says what ``duration_ms`` is: the duration of one ``stage``, the time
    since the server received the turn request, or the time since the connection was received.
    Every value is a local wall-clock measurement, not a service-level objective.
    """

    type: Literal["metric"] = "metric"
    stage: LatencyStage
    duration_ms: float = Field(ge=0, le=3_600_000, allow_inf_nan=False)
    measure: Literal["stage", "since_turn_received", "since_connect"] = "stage"


class StreamError(_StreamEventBase):
    """A safe, structured error."""

    type: Literal["error"] = "error"
    error: SafeError


class SessionComplete(_StreamEventBase):
    """The streaming session ended."""

    type: Literal["session_complete"] = "session_complete"
    reason: Literal["completed", "client_closed", "error", "timeout", "budget_exhausted"]


class TurnAccepted(_StreamEventBase):
    """A turn passed admission: the session was idle and the turn ID was not a replay."""

    type: Literal["turn_accepted"] = "turn_accepted"


class TurnComplete(_StreamEventBase):
    """A turn's final outcome, and whether it committed to conversation state.

    ``delta_count`` is the number of ``response_delta`` events the server sent for the turn, so
    partial output streamed before a later failure is never hidden. ``committed`` is true only
    when every required stage succeeded and the exchange was appended to session state.
    """

    type: Literal["turn_complete"] = "turn_complete"
    status: Literal["committed", "rejected", "failed", "cancelled"]
    committed: bool
    conversation_sequence: int | None = Field(default=None, ge=1)
    failed_stage: StageName | None = None
    delta_count: int = Field(ge=0)
    evidence_class: EvidenceClass | None = None
    execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    stt_processing: Identifier | None = None
    reasoning_processing: Identifier | None = None
    tts_processing: Identifier | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Keep the outcome, commit flag, and failed stage consistent.

        Returns:
            The validated event.

        Raises:
            ValueError: If the commit flag, sequence, or failed stage contradicts the status.
        """
        if self.committed != (self.status == "committed"):
            raise ValueError("a turn is committed exactly when its status is committed")
        if self.committed and (self.conversation_sequence is None or self.failed_stage):
            raise ValueError("a committed turn has a conversation sequence and no failed stage")
        if not self.committed and self.conversation_sequence is not None:
            raise ValueError("an uncommitted turn has no conversation sequence")
        if self.status in {"rejected", "failed"} and self.failed_stage is None:
            raise ValueError("a rejected or failed turn names its failed stage")
        if self.evidence_class in {
            EvidenceClass.DESIGN_DOCUMENTATION,
            EvidenceClass.DEPLOYMENT_RELEASE,
        }:
            raise ValueError("streamed turns carry runtime evidence only")
        live_class = self.evidence_class is EvidenceClass.LIVE_INTEGRATION
        if live_class and self.execution_mode is not ExecutionMode.LIVE:
            raise ValueError("live_integration turns ran in live execution mode")
        return self


StreamEvent = Annotated[
    SessionStarted
    | TranscriptPartial
    | TranscriptFinal
    | ResponseDelta
    | ResponseComplete
    | AudioReady
    | Metric
    | StreamError
    | SessionComplete
    | TurnAccepted
    | TurnComplete,
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

    Raises:
        StreamProtocolError: If the serialized event exceeds the event size bound.
    """
    text = _STREAM_EVENT_ADAPTER.dump_json(event).decode("utf-8")
    if len(text.encode("utf-8")) > MAX_EVENT_BYTES:
        raise StreamProtocolError("stream event exceeds the maximum size")
    return text


# --- Client messages (Story 9.7) -----------------------------------------------------------------


class ClientMessageType(StrEnum):
    """Message types a client may send over the streaming boundary."""

    VOICE_TURN = "voice_turn"
    FIXTURE_TURN = "fixture_turn"
    END_SESSION = "end_session"


class _ClientMessageBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal[1] = PROTOCOL_VERSION


class VoiceTurnMessage(_ClientMessageBase):
    """One spoken turn: base64-encoded audio and the client-chosen turn ID.

    The audio is untrusted. It is decoded here and then validated, decoded, and measured by the
    Story 9.4 audio path like any upload.
    """

    type: Literal["voice_turn"] = "voice_turn"
    turn_id: Identifier
    media_type: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=128)
    audio_base64: str = Field(min_length=4, max_length=MAX_ENCODED_AUDIO_CHARS, repr=False)
    language: str | None = Field(default=None, min_length=2, max_length=16)

    def audio_bytes(self, max_bytes: int) -> bytes:
        """Strictly decode the audio payload within a byte bound.

        Args:
            max_bytes: Largest decoded audio the server accepts, from application limits.

        Returns:
            The decoded audio bytes.

        Raises:
            StreamProtocolError: If the payload is not canonical base64 or decodes to more than
                ``max_bytes``.
        """
        if (len(self.audio_base64) // 4) * 3 - 2 > max_bytes:
            raise StreamProtocolError("voice_turn audio exceeds the maximum size")
        try:
            data = base64.b64decode(self.audio_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise StreamProtocolError("voice_turn audio is not valid base64") from exc
        if not data or len(data) > max_bytes:
            raise StreamProtocolError("voice_turn audio is empty or exceeds the maximum size")
        return data


class FixtureTurnMessage(_ClientMessageBase):
    """One turn that replays a committed audio fixture the server already holds."""

    type: Literal["fixture_turn"] = "fixture_turn"
    turn_id: Identifier
    fixture_id: Identifier
    language: str | None = Field(default=None, min_length=2, max_length=16)


class EndSession(_ClientMessageBase):
    """The client is finished; the server ends the session and closes the connection."""

    type: Literal["end_session"] = "end_session"


ClientMessage = Annotated[
    VoiceTurnMessage | FixtureTurnMessage | EndSession,
    Field(discriminator="type"),
]

_CLIENT_MESSAGE_ADAPTER: Final[TypeAdapter[ClientMessage]] = TypeAdapter(ClientMessage)


class ClientMessageTooLargeError(StreamProtocolError):
    """Raised when a client message exceeds the server's message size bound."""


def parse_client_message(
    raw: str | bytes, *, max_bytes: int = MAX_CLIENT_MESSAGE_BYTES
) -> ClientMessage:
    """Parse one JSON client message, rejecting anything outside the protocol.

    Args:
        raw: The text message received over the streaming boundary.
        max_bytes: Largest message accepted, from application limits.

    Returns:
        The typed client message.

    Raises:
        ClientMessageTooLargeError: If the message exceeds ``max_bytes``. Checked before parsing.
        StreamProtocolError: If the message is malformed, of unknown type, carries any field
            outside its model, or violates a message invariant.
    """
    size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if size > min(max_bytes, MAX_CLIENT_MESSAGE_BYTES):
        raise ClientMessageTooLargeError("client message exceeds the maximum size")
    try:
        return _CLIENT_MESSAGE_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        raise StreamProtocolError("client message violates the streaming protocol") from exc
