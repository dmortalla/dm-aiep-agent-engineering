"""WebSocket streaming gateway: the application interface for real-time voice turns (Story 9.7).

A Starlette ASGI application with one WebSocket route. Each connection is one conversation:

1. The handshake is refused (close 1008) when a browser ``Origin`` is not on the configured
   allowlist, and (close 1013) when the connection or session bound is reached.
2. The server opens a session with a server-generated ID and application-owned configuration,
   accepts the connection, and sends ``session_started`` and a ``session_setup`` metric.
3. Client messages are bounded, strictly typed JSON text (``voice_turn``, ``fixture_turn``,
   ``end_session``). A malformed, unknown, or forged message gets a safe ``error`` event; an
   oversized message, or too many protocol errors, ends the session.
4. One turn runs at a time, as one bounded task beside the receive task. Its coordinator updates
   are sent as typed events as they happen (``turn_accepted``, ``metric``, ``transcript_final``,
   ``response_delta`` ..., ``response_complete``, ``audio_ready``, ``turn_complete``). Every send
   is awaited with a timeout, so a client that cannot keep up stalls only its own turn, and is then
   disconnected; nothing is queued without bound.
5. ``end_session``, a client disconnect, an idle timeout, or a fatal error ends the session: the
   running turn is cancelled (closing the reasoning stream and releasing the busy mark, with no
   commit), the conversation is closed, and, if the client is still there, ``session_complete`` is
   sent and the connection closed.

Business logic stays in ``StreamingVoiceCoordinator``. This module only translates between the
wire protocol and the coordinator, measures transport-level latency, and enforces transport bounds.
There is no authentication: a session ID is correlation, not identity, and deployment (Story 9.10)
must add authentication and TLS in front of this application.
"""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from enum import Enum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from multimodal_voice_platform.contracts.errors import (
    ErrorCode,
    Module9Error,
    SafeError,
    StreamProtocolError,
)
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import LatencyStage
from multimodal_voice_platform.contracts.streaming import (
    AudioReady,
    ClientMessageTooLargeError,
    EndSession,
    FixtureTurnMessage,
    Metric,
    ResponseComplete,
    ResponseDelta,
    SessionComplete,
    SessionStarted,
    StreamError,
    TranscriptFinal,
    TurnAccepted,
    TurnComplete,
    VoiceTurnMessage,
    parse_client_message,
    serialize_stream_event,
)
from multimodal_voice_platform.streaming.coordinator import StreamingVoiceCoordinator
from multimodal_voice_platform.streaming.records import (
    AudioReadyUpdate,
    ResponseCompletedUpdate,
    ResponseFragmentUpdate,
    StageTimedUpdate,
    StreamedTurnRecord,
    TranscriptReadyUpdate,
    TurnAcceptedUpdate,
    TurnFinished,
    TurnUpdate,
)
from multimodal_voice_platform.voice.orchestrator import VoiceTurnRequest
from multimodal_voice_platform.voice.records import (
    LATENCY_STAGES,
    VOICE_EVIDENCE_CLASSES,
    VoiceStage,
)

WEBSOCKET_PATH: Final = "/ws/voice"
CLOSE_NORMAL: Final = 1000
CLOSE_POLICY_VIOLATION: Final = 1008
CLOSE_MESSAGE_TOO_BIG: Final = 1009
CLOSE_INTERNAL_ERROR: Final = 1011
CLOSE_TRY_AGAIN_LATER: Final = 1013
_ORIGIN: Final = re.compile(r"^https?://[a-z0-9.-]{1,253}(:[0-9]{1,5})?$")
_CLOSE_TIMEOUT_S: Final = 1.0
_LOG: Final = logging.getLogger(__name__)

SessionEndReason = Literal["completed", "client_closed", "error", "timeout", "budget_exhausted"]


class GatewaySettings(BaseModel):
    """Deployment-facing gateway settings. From application configuration only.

    ``allowed_origins`` is empty by default, so every browser origin is refused until a deployment
    names its own. Clients that send no ``Origin`` header (non-browser clients) are allowed unless
    ``allow_missing_origin`` is false. Neither is authentication.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_origins: frozenset[str] = frozenset()
    allow_missing_origin: bool = True
    evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO
    path: str = Field(default=WEBSOCKET_PATH, pattern=r"^/[a-z0-9/_-]{1,64}$")

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: frozenset[str]) -> frozenset[str]:
        """Require exact ``scheme://host[:port]`` origins with no wildcard.

        Args:
            value: Configured origins.

        Returns:
            The unchanged origins.

        Raises:
            ValueError: If an origin is not an exact lowercase http(s) origin.
        """
        for origin in value:
            if not _ORIGIN.fullmatch(origin):
                raise ValueError("allowed origins are exact lowercase http(s) origins")
        return value

    @field_validator("evidence_class")
    @classmethod
    def validate_evidence(cls, value: EvidenceClass) -> EvidenceClass:
        """Allow runtime evidence classes supported by streamed voice turns.

        Live evidence is permitted at this interface boundary because the streaming
        coordinator independently requires an explicitly live session and validates
        the requested evidence class against its live provider binding.

        Args:
            value: Configured evidence class.

        Returns:
            The unchanged runtime evidence class.

        Raises:
            ValueError: If the class is not valid runtime evidence.
        """
        if value not in {
            *VOICE_EVIDENCE_CLASSES,
            EvidenceClass.LIVE_INTEGRATION,
        }:
            raise ValueError("streamed turns require runtime evidence")
        return value


class _ClientGone(Exception):
    """The client disconnected; nothing more can be sent."""


class _ClientTooSlow(Exception):
    """A send did not complete within the send timeout."""


class _TurnEventLimit(Exception):
    """A turn tried to send more events than the per-turn bound."""


class _TurnOutcome(Enum):
    CONTINUE = "continue"
    CLOSE = "close"


class WebSocketGateway:
    """The WebSocket endpoint. Counts connections and runs one ``_Connection`` per client."""

    def __init__(
        self,
        coordinator: StreamingVoiceCoordinator,
        settings: GatewaySettings,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        """Create the gateway.

        Args:
            coordinator: Application service that runs streamed turns.
            settings: Gateway settings.
            clock: Monotonic clock in seconds for latency measurements.
        """
        self.coordinator = coordinator
        self.settings = settings
        self.limits = coordinator.limits
        self._clock = clock
        self.active_connections = 0

    def origin_allowed(self, origin: str | None) -> bool:
        """Apply the origin policy to a handshake's ``Origin`` header.

        Args:
            origin: The header value, or ``None`` when absent.

        Returns:
            Whether the handshake may proceed.
        """
        if origin is None:
            return self.settings.allow_missing_origin
        return origin.lower() in self.settings.allowed_origins

    async def handle(self, websocket: WebSocket) -> None:
        """Serve one WebSocket connection.

        Args:
            websocket: The connection, before the handshake is accepted.
        """
        connected = self._clock()
        if not self.origin_allowed(websocket.headers.get("origin")):
            await websocket.close(code=CLOSE_POLICY_VIOLATION)
            return
        if self.active_connections >= self.limits.max_connections:
            await websocket.close(code=CLOSE_TRY_AGAIN_LATER)
            return
        self.active_connections += 1
        try:
            connection = _Connection(self, websocket, connected)
            await connection.run()
        finally:
            self.active_connections -= 1


class _Connection:
    """One client connection: one session, at most one running turn."""

    def __init__(self, gateway: WebSocketGateway, websocket: WebSocket, connected: float) -> None:
        self.gateway = gateway
        self.coordinator = gateway.coordinator
        self.limits = gateway.limits
        self.websocket = websocket
        self.connected = connected
        self.session_id = ""
        self._clock = gateway._clock
        self._sequence = 0
        self._send_lock = asyncio.Lock()
        self._protocol_errors = 0
        self._turn_id: str | None = None
        self._turn_events = 0
        self._turn_deltas = 0
        self._turn_received = 0.0
        self._turn_reported = False
        self._close_code = CLOSE_POLICY_VIOLATION

    async def run(self) -> None:
        try:
            snapshot = self.coordinator.open_session()
        except Module9Error:
            await self.websocket.close(code=CLOSE_TRY_AGAIN_LATER)
            return
        self.session_id = snapshot.session_id
        reason: SessionEndReason = "client_closed"
        code: int | None = None
        receive: asyncio.Task[Any] | None = None
        turn: asyncio.Task[_TurnOutcome] | None = None
        try:
            await self.websocket.accept()
            await self._send(SessionStarted, mode=snapshot.mode)
            await self._send(
                Metric,
                stage=LatencyStage.SESSION_SETUP,
                duration_ms=self._since(self.connected),
                measure="since_connect",
            )
            while True:
                if receive is None:
                    receive = asyncio.create_task(self.websocket.receive())
                waiting: set[asyncio.Task[Any]] = {receive} if turn is None else {receive, turn}
                done, _ = await asyncio.wait(
                    waiting,
                    timeout=None if turn is not None else self.limits.idle_timeout_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    reason, code = "timeout", CLOSE_NORMAL
                    break
                if turn is not None and turn in done:
                    finished, turn = turn, None
                    if await self._turn_ended(finished) is _TurnOutcome.CLOSE:
                        reason, code = "error", self._close_code
                        break
                if receive in done:
                    message, receive = receive.result(), None
                    if message["type"] == "websocket.disconnect":
                        break
                    outcome = await self._dispatch(message, busy=turn is not None)
                    if isinstance(outcome, VoiceTurnMessage | FixtureTurnMessage):
                        turn = asyncio.create_task(self._run_turn(outcome))
                    elif outcome is not None:
                        reason, code = outcome
                        break
        except _ClientGone:
            code = None
        except _ClientTooSlow:
            reason, code = "error", CLOSE_POLICY_VIOLATION
        finally:
            await _stop(turn)
            await _stop(receive)
            self.coordinator.close_session(self.session_id)
        if code is not None:
            await self._finish(reason, code)

    async def _dispatch(
        self, message: dict[str, Any], *, busy: bool
    ) -> VoiceTurnMessage | FixtureTurnMessage | tuple[SessionEndReason, int] | None:
        """Parse one client message and decide what it starts or ends."""
        raw = message.get("text")
        if raw is None:
            return await self._protocol_error(
                StreamProtocolError("binary messages are not part of the protocol")
            )
        try:
            parsed = parse_client_message(raw, max_bytes=self.limits.max_inbound_message_bytes)
        except ClientMessageTooLargeError as exc:
            await self._send_error(exc.to_safe_error(), None)
            return "error", CLOSE_MESSAGE_TOO_BIG
        except StreamProtocolError as exc:
            return await self._protocol_error(exc)
        if isinstance(parsed, EndSession):
            return "completed", CLOSE_NORMAL
        if busy:
            await self._send_error(
                SafeError(
                    code=ErrorCode.INPUT_REJECTED,
                    message="another turn of this session is still running",
                    retryable=True,
                ),
                parsed.turn_id,
            )
            return None
        return parsed

    async def _protocol_error(
        self, exc: StreamProtocolError
    ) -> tuple[SessionEndReason, int] | None:
        self._protocol_errors += 1
        await self._send_error(exc.to_safe_error(), None)
        if self._protocol_errors >= self.limits.max_protocol_errors:
            return "error", CLOSE_POLICY_VIOLATION
        return None

    async def _run_turn(self, message: VoiceTurnMessage | FixtureTurnMessage) -> _TurnOutcome:
        """Run one turn and send its events. Returns whether the connection must close."""
        self._turn_received = self._clock()
        self._turn_id, self._turn_events, self._turn_deltas = message.turn_id, 0, 0
        self._turn_reported = False
        finished: StreamedTurnRecord | None = None
        try:
            updates = self._updates(message)
        except StreamProtocolError as exc:
            await self._reject_payload(message.turn_id, exc.to_safe_error())
            return _TurnOutcome.CONTINUE
        try:
            async with asyncio.timeout(self.limits.turn_timeout_s), aclosing(updates) as stream:
                async for update in stream:
                    if isinstance(update, TurnFinished):
                        finished = update.record
                    await self._publish(update)
        except TimeoutError:
            if finished is not None and not self._turn_reported:
                await self._finish_turn(finished)
            elif finished is None:
                await self._abandon(
                    SafeError(
                        code=ErrorCode.LIMIT_EXCEEDED,
                        message="the turn exceeded its time limit and was cancelled",
                        retryable=True,
                    )
                )
        except _TurnEventLimit:
            await self._abandon(
                SafeError(
                    code=ErrorCode.LIMIT_EXCEEDED,
                    message="the turn exceeded its event limit and was cancelled",
                )
            )
        except (_ClientGone, _ClientTooSlow):
            return _TurnOutcome.CLOSE
        finally:
            self._turn_id = None
        return _TurnOutcome.CONTINUE

    def _updates(self, message: VoiceTurnMessage | FixtureTurnMessage) -> AsyncIterator[TurnUpdate]:
        evidence = self.gateway.settings.evidence_class
        if isinstance(message, FixtureTurnMessage):
            return self.coordinator.stream_fixture_turn(
                self.session_id,
                message.turn_id,
                message.fixture_id,
                language=message.language,
                evidence_class=evidence,
            )
        data = message.audio_bytes(self.limits.max_audio_bytes)
        try:
            request = VoiceTurnRequest(
                session_id=self.session_id,
                turn_id=message.turn_id,
                media_type=message.media_type,
                display_name=message.display_name,
                data=data,
                language=message.language,
            )
        except ValidationError as exc:
            raise StreamProtocolError("voice_turn violates the streaming protocol") from exc
        return self.coordinator.stream_turn(request, evidence_class=evidence)

    async def _publish(self, update: TurnUpdate) -> None:
        """Send the protocol events for one coordinator update."""
        turn_id = update.turn_id
        match update:
            case TurnAcceptedUpdate():
                await self._turn_event(TurnAccepted, turn_id=turn_id)
                await self._milestone(LatencyStage.TURN_ACCEPTANCE)
            case StageTimedUpdate(stage=stage, duration_ms=duration):
                latency = LATENCY_STAGES.get(stage)
                if latency is not None and stage is not VoiceStage.END_TO_END:
                    await self._turn_event(
                        Metric, turn_id=turn_id, stage=latency, duration_ms=duration
                    )
            case TranscriptReadyUpdate(text=text):
                await self._turn_event(TranscriptFinal, turn_id=turn_id, text=text)
                await self._milestone(LatencyStage.TRANSCRIPT_READY)
            case ResponseFragmentUpdate(index=index, text=text):
                await self._turn_event(ResponseDelta, turn_id=turn_id, index=index, text=text)
                self._turn_deltas += 1
                if self._turn_deltas == 1:
                    await self._milestone(LatencyStage.FIRST_RESPONSE)
            case ResponseCompletedUpdate(fragment_count=count):
                await self._turn_event(
                    ResponseComplete, turn_id=turn_id, finish_reason="completed", delta_count=count
                )
                await self._milestone(LatencyStage.RESPONSE_COMPLETION)
            case AudioReadyUpdate():
                await self._turn_event(
                    AudioReady,
                    turn_id=turn_id,
                    audio_ref=update.audio_ref,
                    media_type=update.media_type,
                    duration_ms=update.duration_ms,
                    audio_sha256=update.audio_sha256,
                    size_bytes=update.size_bytes,
                )
                await self._milestone(LatencyStage.AUDIO_READY)
            case TurnFinished(record=record):
                await self._finish_turn(record)

    async def _finish_turn(self, record: StreamedTurnRecord) -> None:
        turn = record.turn
        if turn.error is not None:
            await self._send(StreamError, turn_id=turn.turn_id, error=turn.error)
        transcription, synthesis = turn.transcription, turn.synthesis
        await self._send(
            TurnComplete,
            turn_id=turn.turn_id,
            status=str(turn.status),
            committed=turn.committed,
            conversation_sequence=turn.sequence,
            failed_stage=str(turn.failed_stage) if turn.failed_stage is not None else None,
            delta_count=self._turn_deltas,
            evidence_class=turn.evidence.evidence_class,
            execution_mode=turn.evidence.execution_mode,
            stt_processing=_kind(transcription.provider_processing if transcription else None),
            reasoning_processing=_kind(turn.reasoning_kind),
            tts_processing=_kind(synthesis.provider_processing if synthesis else None),
        )
        await self._send(
            Metric,
            turn_id=turn.turn_id,
            stage=LatencyStage.END_TO_END,
            duration_ms=self._since(self._turn_received),
            measure="since_turn_received",
        )
        self._turn_reported = True

    async def _reject_payload(self, turn_id: str, error: SafeError) -> None:
        await self._send(StreamError, turn_id=turn_id, error=error)
        await self._send(
            TurnComplete,
            turn_id=turn_id,
            status="rejected",
            committed=False,
            failed_stage=VoiceStage.AUDIO_VALIDATION.value,
            delta_count=0,
        )

    async def _abandon(self, error: SafeError) -> None:
        """Report a turn the gateway cancelled. The coordinator released it without a commit."""
        turn_id = self._turn_id
        await self._send(StreamError, turn_id=turn_id, error=error)
        await self._send(
            TurnComplete,
            turn_id=turn_id,
            status="cancelled",
            committed=False,
            delta_count=self._turn_deltas,
        )

    async def _turn_ended(self, task: asyncio.Task[_TurnOutcome]) -> _TurnOutcome:
        """Inspect a finished turn task. Unexpected failures end the session with a safe error."""
        try:
            return task.result()
        except Exception:  # Log only a fixed event; unexpected exceptions may contain secrets.
            _LOG.error("streamed voice turn failed unexpectedly")
            await self._send_error(
                SafeError(
                    code=ErrorCode.INTERNAL_ERROR,
                    message="the server could not complete the turn",
                ),
                None,
            )
            self._close_code = CLOSE_INTERNAL_ERROR
            return _TurnOutcome.CLOSE

    async def _turn_event(self, event: Callable[..., Any], **fields: Any) -> None:
        if self._turn_events >= self.limits.max_events_per_turn:
            raise _TurnEventLimit
        self._turn_events += 1
        await self._send(event, **fields)

    async def _milestone(self, stage: LatencyStage) -> None:
        await self._turn_event(
            Metric,
            turn_id=self._turn_id,
            stage=stage,
            duration_ms=self._since(self._turn_received),
            measure="since_turn_received",
        )

    async def _send_error(self, error: SafeError, turn_id: str | None) -> None:
        await self._send(StreamError, turn_id=turn_id, error=error)

    async def _send(self, event: Callable[..., Any], **fields: Any) -> None:
        """Build, serialize, and send one event, in sequence order, within the send timeout."""
        async with self._send_lock:
            text = serialize_stream_event(
                event(session_id=self.session_id, sequence=self._sequence, **fields)
            )
            try:
                async with asyncio.timeout(self.limits.send_timeout_s):
                    await self.websocket.send_text(text)
            except TimeoutError as exc:
                raise _ClientTooSlow from exc
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                raise _ClientGone from exc
            self._sequence += 1

    async def _finish(self, reason: SessionEndReason, code: int) -> None:
        """Send ``session_complete`` and close, if the client is still listening."""
        try:
            async with asyncio.timeout(_CLOSE_TIMEOUT_S):
                await self._send(SessionComplete, reason=reason)
                await self.websocket.close(code=code)
        except (_ClientGone, _ClientTooSlow, TimeoutError, RuntimeError, OSError):
            return

    def _since(self, started: float) -> float:
        return round(max(0.0, (self._clock() - started) * 1000), 3)


async def _stop(task: asyncio.Task[Any] | None) -> None:
    """Cancel a task and wait until it has finished, so no work outlives its connection.

    The task's own failure, if any, is retrieved and logged rather than lost.
    """
    if task is None:
        return
    task.cancel()
    await asyncio.wait({task})
    exc = None if task.cancelled() else task.exception()
    if exc is not None and not isinstance(
        exc, _ClientGone | _ClientTooSlow | WebSocketDisconnect | OSError
    ):
        _LOG.error("connection task failed while stopping")


def _kind(kind: Enum | None) -> str | None:
    return None if kind is None else str(kind.value)


def create_app(
    coordinator: StreamingVoiceCoordinator | None = None,
    *,
    settings: GatewaySettings | None = None,
) -> Starlette:
    """Build the ASGI application that serves the WebSocket streaming endpoint.

    Args:
        coordinator: Streaming coordinator. Defaults to the deterministic coordinator.
        settings: Gateway settings. Defaults to ``GatewaySettings()`` (no browser origins).

    Returns:
        The Starlette application. ``app.state.gateway`` is the ``WebSocketGateway``.
    """
    gateway = WebSocketGateway(
        coordinator if coordinator is not None else StreamingVoiceCoordinator(),
        settings if settings is not None else GatewaySettings(),
    )
    app = Starlette(routes=[WebSocketRoute(gateway.settings.path, gateway.handle)])
    app.state.gateway = gateway
    return app
