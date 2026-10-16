"""Builders for Story 9.7 streaming tests.

``AsgiWebSocket`` drives the real Starlette application through the ASGI WebSocket interface in
process (no socket): it is the same interface Uvicorn uses, so these tests exercise the gateway's
real handshake, receive, send, and close paths, but not RFC 6455 framing. Socket-level framing is
covered by the loopback tests, which run Uvicorn and a ``websockets`` client over 127.0.0.1.

``GatedReasoner`` is an incremental-reply test double that yields fragments one at a time and then
waits on a gate the test controls, so tests can observe events while reasoning is provably still
running.
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from voice_builders import CATALOG, REASONER_DOUBLE, TEST, heard

from multimodal_voice_platform.adapters.reasoning.conversation import (
    DeterministicConversationReasoner,
)
from multimodal_voice_platform.contracts.conversation import ReplyAct, ReplyActKind, ReplyFragment
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ReasoningChunk,
    ReasoningRequest,
)
from multimodal_voice_platform.contracts.reasoning import ObservationView
from multimodal_voice_platform.crossmodal import ReasoningKind
from multimodal_voice_platform.interface import GatewaySettings, create_app
from multimodal_voice_platform.streaming import (
    IncrementalReplyBinding,
    StreamingLimits,
    StreamingVoiceCoordinator,
)
from multimodal_voice_platform.voice import VoiceAssistant, VoiceLimits

PATH = "/ws/voice"
STEP_S = 5.0
"""Generous per-step timeout; tests never wait this long unless something is broken."""


def session_ids(prefix: str = "ws-test") -> Callable[[], str]:
    """Return a deterministic session ID generator."""
    counter = iter(range(1, 1_000_000))
    return lambda: f"{prefix}-{next(counter)}"


def coordinator(
    *,
    voice: VoiceAssistant | None = None,
    reply: IncrementalReplyBinding | None = None,
    limits: StreamingLimits | None = None,
    voice_limits: VoiceLimits | None = None,
    transcripts: Iterable[str] | None = None,
) -> StreamingVoiceCoordinator:
    """Return a coordinator over the committed catalog, or over scripted transcripts."""
    if voice is None:
        options: dict[str, Any] = {"catalog": CATALOG}
        if voice_limits is not None:
            options["limits"] = voice_limits
        if transcripts is not None:
            service, _ = heard(*transcripts)
            options["speech"] = service
        voice = VoiceAssistant(**options)
    return StreamingVoiceCoordinator(voice, reply=reply, limits=limits, session_ids=session_ids())


def app(streaming: StreamingVoiceCoordinator | None = None, **settings: Any) -> Any:
    """Return the gateway application recording automated_test evidence."""
    settings.setdefault("evidence_class", TEST)
    return create_app(streaming or coordinator(), settings=GatewaySettings(**settings))


def voice_turn(turn_id: str, data: bytes, **extra: Any) -> str:
    """Return a ``voice_turn`` client message."""
    message = {
        "type": "voice_turn",
        "turn_id": turn_id,
        "media_type": "audio/wav",
        "display_name": "turn.wav",
        "audio_base64": base64.b64encode(data).decode("ascii"),
    }
    message.update(extra)
    return json.dumps(message)


def fixture_turn(turn_id: str, fixture_id: str, **extra: Any) -> str:
    """Return a ``fixture_turn`` client message."""
    message = {"type": "fixture_turn", "turn_id": turn_id, "fixture_id": fixture_id}
    return json.dumps({**message, **extra})


END = json.dumps({"type": "end_session"})


class AsgiWebSocket:
    """In-process ASGI WebSocket client for the gateway application."""

    def __init__(
        self,
        application: Any,
        *,
        origin: str | None = None,
        path: str = PATH,
        send_gate: asyncio.Event | None = None,
    ) -> None:
        self.application = application
        headers = [(b"host", b"testserver")]
        if origin is not None:
            headers.append((b"origin", origin.encode("ascii")))
        self.scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "scheme": "ws",
            "http_version": "1.1",
            "path": path,
            "raw_path": path.encode("ascii"),
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        self.to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.send_gate = send_gate
        self.disconnected = False
        self.task: asyncio.Task[None] | None = None
        self.accepted = False
        self.close_code: int | None = None
        self.events: list[dict[str, Any]] = []

    async def _receive(self) -> dict[str, Any]:
        return await self.to_app.get()

    async def _send(self, message: dict[str, Any]) -> None:
        if self.disconnected:
            raise OSError("client disconnected")
        if self.send_gate is not None and message["type"] == "websocket.send":
            await self.send_gate.wait()
        await self.from_app.put(message)

    async def connect(self) -> "AsgiWebSocket":
        """Start the application and complete (or fail) the handshake."""
        self.task = asyncio.create_task(self.application(self.scope, self._receive, self._send))
        await self.to_app.put({"type": "websocket.connect"})
        first = await asyncio.wait_for(self.from_app.get(), STEP_S)
        if first["type"] == "websocket.accept":
            self.accepted = True
        else:
            self.close_code = first.get("code")
        return self

    async def send(self, text: str) -> None:
        """Send one text message to the server."""
        await self.to_app.put({"type": "websocket.receive", "text": text})

    async def send_bytes(self, data: bytes) -> None:
        """Send one binary message to the server."""
        await self.to_app.put({"type": "websocket.receive", "bytes": data})

    async def event(self, timeout: float = STEP_S) -> dict[str, Any]:
        """Return the next event, failing if the server closed instead."""
        message = await asyncio.wait_for(self.from_app.get(), timeout)
        if message["type"] == "websocket.close":
            self.close_code = message.get("code")
            raise ConnectionError(f"server closed the connection with {self.close_code}")
        event = json.loads(message["text"])
        self.events.append(event)
        return event

    async def until(self, event_type: str, timeout: float = STEP_S) -> list[dict[str, Any]]:
        """Collect events up to and including the first of ``event_type``."""
        seen = []
        while True:
            event = await self.event(timeout)
            seen.append(event)
            if event["type"] == event_type:
                return seen

    async def closed(self, timeout: float = STEP_S) -> list[dict[str, Any]]:
        """Collect events until the server closes the connection; return them."""
        seen = []
        while True:
            message = await asyncio.wait_for(self.from_app.get(), timeout)
            if message["type"] == "websocket.close":
                self.close_code = message.get("code")
                await self.finished()
                return seen
            event = json.loads(message["text"])
            self.events.append(event)
            seen.append(event)

    async def disconnect(self, code: int = 1001) -> None:
        """Disconnect abruptly, as a client that goes away would."""
        self.disconnected = True
        await self.to_app.put({"type": "websocket.disconnect", "code": code})
        await self.finished()

    async def finished(self) -> None:
        """Wait for the application to return."""
        assert self.task is not None
        await asyncio.wait_for(self.task, STEP_S)


def run(coro: Any) -> Any:
    """Run one async test body."""
    return asyncio.run(coro)


class GatedReasoner:
    """Incremental reply double: real rule-based fragments, released one gate at a time.

    After yielding fragment ``i`` it waits on ``gates[i]``. ``produced`` records each fragment at
    the moment it is generated, and ``closed`` records that its stream was closed or cancelled.
    """

    def __init__(self, gates: int = 1, descriptor: ProviderDescriptor = REASONER_DOUBLE) -> None:
        self.gates = [asyncio.Event() for _ in range(gates)]
        self.produced: list[str] = []
        self.closed = False
        self.cancelled = False
        self._descriptor = descriptor
        self._inner = DeterministicConversationReasoner()

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def stream_reply(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        try:
            index = 0
            async for chunk in self._inner.stream_reply(request):
                if chunk.is_final:
                    yield ReasoningChunk(provider=self._descriptor, text="", is_final=True)
                    return
                self.produced.append(chunk.text)
                yield ReasoningChunk(provider=self._descriptor, text=chunk.text, is_final=False)
                if index < len(self.gates):
                    await self.gates[index].wait()
                index += 1
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.closed = True


def gated(gates: int = 1) -> tuple[IncrementalReplyBinding, GatedReasoner]:
    """Return a binding over a gated incremental reasoner, and the reasoner."""
    double = GatedReasoner(gates)
    return (
        IncrementalReplyBinding(
            factory=lambda: double, processing=ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
        ),
        double,
    )


class ScriptedReply:
    """Incremental reply double that streams a fixed chunk script."""

    def __init__(self, script: Callable[[ReasoningRequest], AsyncIterator[Any]]) -> None:
        self.script = script

    @property
    def descriptor(self) -> ProviderDescriptor:
        return REASONER_DOUBLE

    def stream_reply(self, request: ReasoningRequest) -> AsyncIterator[Any]:
        return self.script(request)


def scripted(script: Callable[[ReasoningRequest], AsyncIterator[Any]]) -> IncrementalReplyBinding:
    """Return a binding over a scripted incremental reply double."""
    double = ScriptedReply(script)
    return IncrementalReplyBinding(
        factory=lambda: double, processing=ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
    )


def heard_fragment(view: ObservationView, index: int = 0, sentence: str | None = None) -> str:
    """Return a valid ``heard`` fragment document citing the first statement."""
    first = view.statements[0]
    act = ReplyAct(kind=ReplyActKind.HEARD, statement_id=first.statement_id, quote=first.text[:40])
    return ReplyFragment(
        schema_version=1, index=index, act=act, sentence=sentence or f"I heard you ({index})."
    ).model_dump_json()


def current_view(request: ReasoningRequest) -> ObservationView:
    """Return the observation a voice-turn reasoning request carries."""
    return ObservationView.model_validate_json(request.parts[0].content)
