"""Builders for Story 9.8 live-provider tests. No test here reaches a real provider.

``FakeOpenAI`` is an in-process ``httpx2.MockTransport`` handler that speaks the OpenAI HTTP API
shapes the adapters use (Responses JSON and server-sent events, audio transcriptions, audio
speech). The real OpenAI SDK and the real adapters run against it, so request construction,
response parsing, streaming translation, and error translation are exercised end to end, while
the adapters report ``real_endpoint = False`` and every run is ``automated_test`` evidence.
"""

import asyncio
import json
import math
from collections.abc import Callable, Iterable
from typing import Any

import httpx2
from pydantic import SecretStr

from multimodal_voice_platform.adapters.openai import openai_bindings
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.live.config import LiveProviderConfig
from multimodal_voice_platform.live.credentials import live_session

FAKE_KEY = "sk-test-FAKE-DO-NOT-LEAK-0123456789abcdef"
"""A recognizable fake credential. Tests assert it never leaves the adapter."""
SECRET_IN_ERROR = "sk-proj-LEAKED-IN-PROVIDER-BODY-9876543210"


def pcm_tone(ms: int = 300, hz: float = 440.0, rate: int = 24_000) -> bytes:
    """Return 16-bit mono little-endian PCM samples of a sine tone."""
    frames = rate * ms // 1000
    return b"".join(
        int(8000 * math.sin(2 * math.pi * hz * i / rate)).to_bytes(2, "little", signed=True)
        for i in range(frames)
    )


def response_json(text: str, *, status: str = "completed", refusal: bool = False) -> dict[str, Any]:
    """Return a minimal Responses API result whose output text is ``text``."""
    part = (
        {"type": "refusal", "refusal": "I can't help with that."}
        if refusal
        else {"type": "output_text", "text": text, "annotations": []}
    )
    return {
        "id": "resp_test123",
        "object": "response",
        "created_at": 1,
        "model": "gpt-test",
        "status": status,
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [part],
            }
        ],
        "usage": {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens": 30,
            "output_tokens_details": {"reasoning_tokens": 10},
            "total_tokens": 150,
        },
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }


def sse(events: Iterable[dict[str, Any]]) -> bytes:
    """Encode events as a server-sent event stream."""
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    return body.encode("utf-8")


def text_stream(deltas: Iterable[str], *, finish: str = "completed") -> list[dict[str, Any]]:
    """Return the Responses streaming events for a sequence of output-text deltas."""
    events: list[dict[str, Any]] = [
        {"type": "response.created", "sequence_number": 0, "response": response_json("")}
    ]
    for number, delta in enumerate(deltas, start=1):
        events.append(
            {
                "type": "response.output_text.delta",
                "sequence_number": number,
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": delta,
                "logprobs": [],
            }
        )
    if finish == "completed":
        events.append(
            {"type": "response.completed", "sequence_number": 99, "response": response_json("")}
        )
    elif finish == "incomplete":
        events.append(
            {
                "type": "response.incomplete",
                "sequence_number": 99,
                "response": response_json("", status="incomplete"),
            }
        )
    elif finish == "refusal":
        events.append(
            {
                "type": "response.refusal.delta",
                "sequence_number": 99,
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": "no",
            }
        )
    return events


class FakeOpenAI:
    """Scripted stand-in for the OpenAI HTTP API. Records every request it receives."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.bodies: list[Any] = []
        self.vision_text = json.dumps(
            {
                "description": "A square split into four colored quadrants.",
                "observations": ["The top-left quadrant is red.", "The bottom-right is blue."],
            }
        )
        self.transcript = "Please remember that the project code word is falcon."
        self.speech_pcm = pcm_tone()
        self.reasoning_deltas: list[str] = []
        self.reasoning_finish = "completed"
        self.failure: tuple[int, dict[str, Any]] | None = None
        self.raise_transport: Exception | None = None
        self.gate: asyncio.Event | None = None

    def transport(self) -> httpx2.MockTransport:
        """Return the mock transport serving this fake."""
        return httpx2.MockTransport(self._handle)

    def bindings(self, config: LiveProviderConfig | None = None) -> Any:
        """Return OpenAI bindings over this fake (contract test doubles)."""
        return openai_bindings(config, transport=self.transport())

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        content = await request.aread()
        try:
            self.bodies.append(json.loads(content))
        except (ValueError, UnicodeDecodeError):
            self.bodies.append(content)
        if self.raise_transport is not None:
            raise self.raise_transport
        if self.failure is not None:
            status, body = self.failure
            return httpx2.Response(status, json=body, headers={"x-request-id": "req_fail123"})
        path = request.url.path
        headers = {"x-request-id": "req_test123"}
        if path.endswith("/audio/transcriptions"):
            return httpx2.Response(200, json={"text": self.transcript}, headers=headers)
        if path.endswith("/audio/speech"):
            return httpx2.Response(200, content=self.speech_pcm, headers=headers)
        if path.endswith("/responses"):
            body = self.bodies[-1]
            if isinstance(body, dict) and body.get("stream"):
                stream = self._stream(
                    text_stream(self.reasoning_deltas, finish=self.reasoning_finish)
                )
                return httpx2.Response(
                    200,
                    stream=stream,
                    headers={**headers, "content-type": "text/event-stream"},
                )
            return httpx2.Response(200, json=response_json(self.vision_text), headers=headers)
        return httpx2.Response(404, json={"error": {"message": "unknown path"}})

    def _stream(self, events: list[dict[str, Any]]) -> "_GatedStream":
        return _GatedStream(events, self.gate)


class _GatedStream(httpx2.AsyncByteStream):
    """Streams SSE events one at a time; can pause after the first delta until a gate opens."""

    def __init__(self, events: list[dict[str, Any]], gate: asyncio.Event | None) -> None:
        self.events = events
        self.gate = gate
        self.closed = False

    async def __aiter__(self) -> Any:
        deltas = 0
        for event in self.events:
            yield sse([event])
            if event["type"] == "response.output_text.delta":
                deltas += 1
                if deltas == 1 and self.gate is not None:
                    await self.gate.wait()
            await asyncio.sleep(0)

    async def aclose(self) -> None:
        self.closed = True


def session(session_id: str = "sess-live", **budget: Any) -> Any:
    """Return an explicit live session holding the fake key."""
    return live_session(
        session_id, SecretStr(FAKE_KEY), budget=ResourceBudget(**budget) if budget else None
    )


def fragments(*items: dict[str, Any]) -> list[str]:
    """Split a reply-fragments document into small deltas, as a provider would stream it."""
    document = json.dumps({"fragments": list(items)})
    return [document[i : i + 7] for i in range(0, len(document), 7)]


def split_after_first(first: dict[str, Any], *rest: dict[str, Any]) -> list[str]:
    """Stream a reply document so the first delta completes exactly the first fragment.

    With ``FakeOpenAI.gate`` set, the fake pauses after that first delta, so a test can observe the
    first fragment while the provider has not streamed the rest of its response.
    """
    tail = "".join(f",{json.dumps(item)}" for item in rest)
    return ['{"fragments":[' + json.dumps(first), tail + "]}"]


def act(
    kind: str,
    statement_id: str,
    quote: str,
    sentence: str,
    *,
    slot: str | None = None,
    value: str | None = None,
    history_index: int | None = None,
    history_quote: str | None = None,
) -> dict[str, Any]:
    """Return one reply-fragment item as the model would emit it."""
    return {
        "kind": kind,
        "statement_id": statement_id,
        "quote": quote,
        "slot": slot,
        "value": value,
        "history_index": history_index,
        "history_quote": history_quote,
        "sentence": sentence,
    }


def run(coro: Any) -> Any:
    """Run one async test body."""
    return asyncio.run(coro)


def secrets_absent(*texts: str) -> bool:
    """Whether no known secret value appears in any of the texts."""
    return not any(
        secret in text for text in texts for secret in (FAKE_KEY, SECRET_IN_ERROR, "LEAKED")
    )


Handler = Callable[[httpx2.Request], httpx2.Response]
