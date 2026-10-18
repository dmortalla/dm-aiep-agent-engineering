"""Bounded loopback WebSocket client using the accepted gateway and typed wire contracts."""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from websockets.asyncio.client import connect

from multimodal_voice_platform.contracts.streaming import parse_stream_event
from multimodal_voice_platform.interface import bound_port, build_server, create_app
from multimodal_voice_platform.streaming import StreamingVoiceCoordinator


@dataclass(frozen=True)
class ReceivedEvent:
    """One validated wire message with client-measured elapsed time.

    Attributes:
        event: Typed-event JSON, parsed before it is shown.
        elapsed_ms: Local client measurement since connection attempt, not a production SLO.
    """

    event: dict[str, object]
    elapsed_ms: float


async def stream_demo(
    receive: Callable[[ReceivedEvent], None],
    *,
    cancel_after_first: bool = False,
) -> list[ReceivedEvent]:
    """Present events as received from a real short-lived loopback gateway.

    Args:
        receive: Renderer invoked immediately for each validated message, before the next receive.
        cancel_after_first: Disconnect after the first fragment to demonstrate cancellation.

    Returns:
        Bounded event history for later inspection. No complete response is precomputed.

    Raises:
        TimeoutError: If local hosting, the conversation, or shutdown exceeds its bound.
        OSError: If local sockets cannot be opened.
    """
    coordinator = StreamingVoiceCoordinator()
    server = build_server(create_app(coordinator), port=0)
    # Uvicorn otherwise installs process signal handlers; this app runs in a Streamlit thread.
    server_task = asyncio.create_task(server.serve())
    events: list[ReceivedEvent] = []
    started = time.perf_counter()
    try:
        async with asyncio.timeout(30):
            while not server.started:
                if server_task.done():
                    await server_task
                    raise OSError("Local WebSocket server could not start.")
                await asyncio.sleep(0.01)
            async with connect(
                f"ws://127.0.0.1:{bound_port(server)}/ws/voice",
                proxy=None,
                max_size=65536,
                open_timeout=5,
                close_timeout=2,
            ) as ws:

                async def until(kind: str) -> bool:
                    while len(events) < 256:
                        raw = await asyncio.wait_for(ws.recv(), 10)
                        typed = parse_stream_event(raw)
                        event = ReceivedEvent(
                            json.loads(typed.model_dump_json()),
                            (time.perf_counter() - started) * 1000,
                        )
                        events.append(event)
                        receive(event)
                        if cancel_after_first and event.event["type"] == "response_delta":
                            # Actual transport disconnect, not a forged completion event.
                            await ws.close()
                            return False
                        if event.event["type"] in {"error", "session_complete"}:
                            return False
                        if event.event["type"] == kind:
                            return True
                    raise TimeoutError("WebSocket event bound reached.")

                if not await until("session_started"):
                    return events
                for index, fixture in enumerate(("voice-remember", "voice-recall"), start=1):
                    await ws.send(
                        json.dumps(
                            {
                                "type": "fixture_turn",
                                "turn_id": f"turn-{index}",
                                "fixture_id": fixture,
                            }
                        )
                    )
                    if not await until("turn_complete"):
                        return events
                await ws.send(json.dumps({"type": "end_session"}))
                await until("session_complete")
        return events
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, 5)
        finally:
            if not server_task.done():
                server_task.cancel()
                await asyncio.gather(server_task, return_exceptions=True)
