"""Story 9.7 socket-level acceptance: Uvicorn and a ``websockets`` client over 127.0.0.1.

These tests start the real gateway in a real Uvicorn server on an ephemeral loopback port and talk
to it with an independent RFC 6455 client over an OS TCP socket. That is genuine local WebSocket
integration evidence (handshake, framing, close codes, and timing over a socket), classified as
``automated_test`` under the module's evidence policy. It is not external or live-provider
evidence: every connection is to 127.0.0.1, which a socket guard enforces.
"""

import asyncio
import base64
import json
import math
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from stream_builders import app, coordinator, fixture_turn
from voice_builders import TONE_WAV
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from multimodal_voice_platform.contracts.streaming import parse_stream_event
from multimodal_voice_platform.interface import bound_port, build_server
from multimodal_voice_platform.interface.server import NonLoopbackHostError
from multimodal_voice_platform.streaming import StreamingLimits, StreamingVoiceCoordinator

LOOPBACK = {"127.0.0.1", "::1"}


@pytest.fixture
def loopback_only(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail any socket connection that is not to a loopback address; record the ones made."""
    connected: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guard(address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        assert host in LOOPBACK, f"non-loopback connection attempted: {host}"
        connected.append(host)

    def checked_connect(self: socket.socket, address: Any) -> None:
        guard(address)
        return real_connect(self, address)

    def checked_connect_ex(self: socket.socket, address: Any) -> int:
        guard(address)
        return real_connect_ex(self, address)

    def checked_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        assert host in LOOPBACK | {None, "localhost"}, f"non-loopback lookup: {host}"
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", checked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", checked_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", checked_getaddrinfo)
    return connected


@asynccontextmanager
async def serving(application: Any) -> AsyncIterator[str]:
    """Run the application in Uvicorn on an ephemeral loopback port; yield its WebSocket URL."""
    server = build_server(application, host="127.0.0.1", port=0)
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            assert not task.done(), "the server failed to start"
            await asyncio.sleep(0.01)
        yield f"ws://127.0.0.1:{bound_port(server)}/ws/voice"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


async def _event(ws: ClientConnection) -> dict[str, Any]:
    raw = await asyncio.wait_for(ws.recv(), 5)
    assert isinstance(raw, str)
    parse_stream_event(raw)
    return json.loads(raw)


async def _until(ws: ClientConnection, event_type: str) -> list[dict[str, Any]]:
    seen = []
    while True:
        event = await _event(ws)
        seen.append(event)
        if event["type"] == event_type:
            return seen


def test_real_socket_conversation_streams_and_measures_latency(loopback_only: list[str]) -> None:
    streaming = coordinator()
    application = app(streaming)

    async def body() -> None:
        async with serving(application) as url:
            connect_started = time.perf_counter()
            async with connect(url, max_size=2**20) as ws:
                started = await _event(ws)
                assert started["type"] == "session_started"
                setup = await _event(ws)
                assert setup["stage"] == "session_setup"
                session = started["session_id"]
                timeline: list[tuple[str, float]] = []
                sent = time.perf_counter()
                await ws.send(fixture_turn("turn-1", "voice-remember"))
                for event in await _until(ws, "turn_complete"):
                    timeline.append((event["type"], (time.perf_counter() - sent) * 1000))
                await _event(ws)
                await ws.send(fixture_turn("turn-2", "voice-recall"))
                second = await _until(ws, "turn_complete")
                done = second[-1]
                assert done["committed"] and done["conversation_sequence"] == 2
                delta = next(e for e in second if e["type"] == "response_delta")
                assert "falcon" in delta["text"]
                kinds = [kind for kind, _ in timeline]
                first_delta = kinds.index("response_delta")
                assert first_delta < kinds.index("response_complete") < kinds.index("turn_complete")
                client_ms = [ms for _, ms in timeline]
                assert all(math.isfinite(ms) and ms >= 0 for ms in client_ms)
                assert client_ms == sorted(client_ms)
                assert (time.perf_counter() - connect_started) < 30
                await ws.send(json.dumps({"type": "end_session"}))
                tail = await _until(ws, "session_complete")
                assert tail[-1]["reason"] == "completed"
                with pytest.raises(ConnectionClosed) as closed:
                    await asyncio.wait_for(ws.recv(), 5)
                assert closed.value.rcvd is not None and closed.value.rcvd.code == 1000
                assert all(e["session_id"] == session for e in second)
        assert streaming.voice.store.active_sessions == 0

    asyncio.run(body())
    assert loopback_only and set(loopback_only) <= LOOPBACK


def test_real_socket_uploaded_audio_and_disconnect_mid_turn(loopback_only: list[str]) -> None:
    from stream_builders import gated

    binding, double = gated(gates=1)
    transcript = (
        "Please remember that the project code word is falcon. Remember that the room is blue."
    )
    streaming = coordinator(reply=binding, transcripts=[transcript])
    application = app(streaming)
    message = json.dumps(
        {
            "type": "voice_turn",
            "turn_id": "turn-1",
            "media_type": "audio/wav",
            "display_name": "turn.wav",
            "audio_base64": base64.b64encode(TONE_WAV).decode("ascii"),
        }
    )

    async def body() -> None:
        async with serving(application) as url:
            async with connect(url) as ws:
                await _event(ws)
                await _event(ws)
                await ws.send(message)
                events = await _until(ws, "response_delta")
                assert [e["type"] for e in events if e["type"] != "metric"] == [
                    "turn_accepted",
                    "transcript_final",
                    "response_delta",
                ]
                assert len(double.produced) == 1
            for _ in range(200):
                if streaming.voice.store.active_sessions == 0 and streaming.active_turns == 0:
                    break
                await asyncio.sleep(0.01)
            assert double.cancelled and double.closed
            assert streaming.active_turns == 0
            assert streaming.voice.store.active_sessions == 0
            assert application.state.gateway.active_connections == 0

    asyncio.run(body())


def test_real_socket_refuses_foreign_origin_and_oversized_frames(
    loopback_only: list[str],
) -> None:
    limits = StreamingLimits(max_inbound_message_bytes=64 * 1024, max_audio_bytes=16 * 1024)
    streaming = coordinator(limits=limits)
    application = app(streaming)

    async def body() -> None:
        async with serving(application) as url:
            with pytest.raises(InvalidStatus) as refused:
                async with connect(url, origin="https://evil.example"):
                    pass
            assert refused.value.response.status_code == 403
            async with connect(url) as ws:
                await _event(ws)
                await _event(ws)
                await ws.send("x" * (64 * 1024 + 1))
                error = await _event(ws)
                assert error["error"]["code"] == "protocol_error"
                tail = await _until(ws, "session_complete")
                assert tail[-1]["reason"] == "error"
            async with connect(url) as ws:
                await _event(ws)
                await _event(ws)
                await ws.send("y" * (256 * 1024))
                with pytest.raises(ConnectionClosed) as closed:
                    while True:
                        await asyncio.wait_for(ws.recv(), 5)
                assert closed.value.rcvd is not None and closed.value.rcvd.code == 1009

    asyncio.run(body())


def test_server_binds_loopback_only() -> None:
    application = app(StreamingVoiceCoordinator())
    for host in ("0.0.0.0", "::", "192.168.1.10", "example.com"):
        with pytest.raises(NonLoopbackHostError):
            build_server(application, host=host)
    server = build_server(application)
    assert server.config.host == "127.0.0.1"
    assert server.config.ws_per_message_deflate is False
    limits = application.state.gateway.limits
    assert server.config.ws_max_size == limits.max_inbound_message_bytes + 4096
