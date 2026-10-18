"""OpenAI reasoning adapters behind the reasoning ports, with genuine provider streaming (9.8).

Both adapters call the Responses API with ``stream=True`` and strict structured output, and
translate the provider's server-sent events inside the adapter: only output-text deltas, the
completion, and failures matter; no raw provider event leaves this module.

- ``OpenAICrossModalReasoner`` (``ReasoningPort``) streams the ``ReasonerOutput`` document for the
  Story 9.5 cross-modal workflow. Deltas are coalesced into bounded chunks; the workflow validates
  every citation against the observations it supplied.
- ``OpenAIConversationReasoner`` (``ReasoningPort`` and ``IncrementalReplyPort``) answers voice
  turns. ``stream_reply`` releases each reply fragment as soon as the provider has streamed its
  closing brace, while the provider is still generating the rest, so the Story 9.7 coordinator can
  validate it and send ``response_delta`` before the response completes. Fragments are whole reply
  acts assembled from provider token deltas, not individual tokens.

Each operation is bounded by the provider-call budget, the configured output-token ceiling, and an
operation deadline that counts only time spent waiting on the provider.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, aclosing
from typing import Any, Final

from pydantic import ValidationError

from multimodal_voice_platform.adapters.openai.client import (
    OpenAIAdapter,
    safe_request_id,
    usage_from,
)
from multimodal_voice_platform.contracts.conversation import (
    MAX_REPLY_ACTS,
    AssistantReply,
    ReplyAct,
    ReplyFragment,
)
from multimodal_voice_platform.contracts.limits import MAX_DELTA_CHARS
from multimodal_voice_platform.contracts.live import LiveCapability
from multimodal_voice_platform.contracts.providers import (
    ProviderPort,
    ReasoningChunk,
    ReasoningRequest,
)
from multimodal_voice_platform.live.errors import (
    LiveProviderError,
    ProviderOutputError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from multimodal_voice_platform.live.json_stream import ArrayElementScanner, StreamedJsonError
from multimodal_voice_platform.live.prompts import (
    CONVERSATION_INSTRUCTIONS,
    CROSS_MODAL_INSTRUCTIONS,
    CROSS_MODAL_SCHEMA,
    REPLY_FRAGMENTS_SCHEMA,
    data_block,
    json_schema_format,
)

COALESCE_CHARS: Final = 1_000
"""Delta text gathered into one chunk for document-shaped (non-incremental) consumers."""
_ACT_FIELDS: Final = (
    "kind",
    "statement_id",
    "quote",
    "slot",
    "value",
    "history_index",
    "history_quote",
)


class _ResponsesStreamer(OpenAIAdapter):
    """Runs one streamed Responses API call and yields its output-text deltas."""

    capability = LiveCapability.REASONING
    port = ProviderPort.REASONING
    instructions: str = ""
    schema_name: str = ""
    schema: dict[str, Any] = {}  # noqa: RUF012 - overridden as class constants

    _rejection: LiveProviderError | None = None

    async def _deltas(self, request: ReasoningRequest) -> AsyncIterator[str]:
        self._check_budget()
        self._rejection = None
        model = self._config.reasoning_model
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._config.max_operation_s
        started = time.perf_counter()
        first: float | None = None
        events = 0
        request_id: str | None = None
        usage = None
        finished = False
        try:
            async with AsyncExitStack() as stack:
                async with asyncio.timeout_at(deadline):
                    client = await stack.enter_async_context(self._client())
                    stream = await client.responses.create(
                        model=model,
                        instructions=self.instructions,
                        input=data_block(request),
                        text={"format": json_schema_format(self.schema_name, self.schema)},
                        max_output_tokens=min(
                            request.max_output_tokens, self._config.max_output_tokens
                        ),
                        reasoning={"effort": self._config.reasoning_effort},
                        store=False,
                        stream=True,
                    )
                await stack.enter_async_context(stream)
                events_iter = stream.__aiter__()
                while True:
                    try:
                        async with asyncio.timeout_at(deadline):
                            event = await anext(events_iter)
                    except StopAsyncIteration:
                        break
                    events += 1
                    kind = getattr(event, "type", None)
                    if kind == "response.created":
                        request_id = getattr(getattr(event, "response", None), "id", None)
                    elif kind == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if isinstance(delta, str) and delta:
                            first = first if first is not None else time.perf_counter()
                            yield delta
                    elif kind == "response.refusal.delta":
                        raise ProviderRefusalError("the live provider refused to answer")
                    elif kind == "response.completed":
                        usage = usage_from(getattr(getattr(event, "response", None), "usage", None))
                        finished = True
                    elif kind == "response.incomplete":
                        raise ProviderOutputError("the live provider stopped before completing")
                    elif kind in {"response.failed", "error"}:
                        raise ProviderUnavailableError("the live provider failed the response")
            if not finished:
                raise ProviderOutputError("the live provider stream ended without completing")
        except TimeoutError:
            self._fail(model, started, ProviderTimeoutError("the live provider stream timed out"))
        except Exception as exc:  # Translated and recorded; never re-raised raw.
            self._fail(model, started, exc)
        except BaseException:
            # Cancelled or closed early by the consumer: the call was made, record it.
            rejection = self._rejection
            self._record(
                model,
                started,
                error=rejection,
                request_id=safe_request_id(request_id),
                streamed=True,
                first_output=first,
                events=events,
                cancelled=rejection is None,
            )
            raise
        self._record(
            model,
            started,
            request_id=safe_request_id(request_id),
            usage=usage,
            streamed=True,
            first_output=first,
            events=events,
        )

    def _reject(self, error: LiveProviderError) -> LiveProviderError:
        """Remember why the consumer rejected the provider's output, then return the error."""
        self._rejection = error
        return error


class OpenAICrossModalReasoner(_ResponsesStreamer):
    """Model-backed cross-modal reasoning streaming a ``ReasonerOutput`` document."""

    instructions = CROSS_MODAL_INSTRUCTIONS
    schema_name = "cross_modal_findings"
    schema = CROSS_MODAL_SCHEMA

    async def stream_reason(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Stream the structured findings document as provider output arrives.

        Args:
            request: The bounded cross-modal reasoning request.

        Yields:
            Bounded chunks of the JSON document, ending with exactly one final chunk.

        Raises:
            LiveProviderError: A sanitized provider, budget, refusal, or output failure.
        """
        pending = ""
        async with aclosing(self._deltas(request)) as deltas:
            async for delta in deltas:
                pending += delta
                while len(pending) >= COALESCE_CHARS:
                    piece, pending = pending[:COALESCE_CHARS], pending[COALESCE_CHARS:]
                    yield ReasoningChunk(provider=self.descriptor, text=piece, is_final=False)
        yield ReasoningChunk(provider=self.descriptor, text=pending, is_final=True)


def _split(text: str) -> list[str]:
    return [text[i : i + MAX_DELTA_CHARS] for i in range(0, len(text), MAX_DELTA_CHARS)]


class OpenAIConversationReasoner(_ResponsesStreamer):
    """Model-backed voice-turn reasoning with incremental reply fragments."""

    instructions = CONVERSATION_INSTRUCTIONS
    schema_name = "reply_fragments"
    schema = REPLY_FRAGMENTS_SCHEMA

    async def stream_reply(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Stream one reply fragment per act, each as soon as the provider has finished it.

        Args:
            request: The bounded voice-turn reasoning request.

        Yields:
            One chunk per ``ReplyFragment``, then one final chunk with empty text.

        Raises:
            LiveProviderError: A sanitized provider, budget, refusal, or output failure.
        """
        scanner = ArrayElementScanner()
        index = 0
        async with aclosing(self._deltas(request)) as deltas:
            async for delta in deltas:
                try:
                    elements = scanner.feed(delta)
                except StreamedJsonError as exc:
                    raise self._reject(ProviderOutputError("malformed streamed reply")) from exc
                for element in elements:
                    if index >= MAX_REPLY_ACTS:
                        raise self._reject(ProviderOutputError("too many reply fragments"))
                    fragment = self._fragment(element, index)
                    index += 1
                    yield ReasoningChunk(
                        provider=self.descriptor, text=fragment.model_dump_json(), is_final=False
                    )
        try:
            scanner.close()
        except StreamedJsonError as exc:
            error = ProviderOutputError("the streamed reply was incomplete")
            raise self._amend_failure(error) from exc
        yield ReasoningChunk(provider=self.descriptor, text="", is_final=True)

    async def stream_reason(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Answer a synchronous voice turn: collect the fragments, then stream the reply document.

        Args:
            request: The bounded voice-turn reasoning request.

        Yields:
            Chunks of one ``AssistantReply`` document, ending with exactly one final chunk.

        Raises:
            LiveProviderError: A sanitized provider, budget, refusal, or output failure.
        """
        async with aclosing(self.stream_reply(request)) as chunks:
            fragments = [
                ReplyFragment.model_validate_json(chunk.text)
                async for chunk in chunks
                if not chunk.is_final
            ]
        if not fragments:
            raise self._amend_failure(ProviderOutputError("the live provider returned no reply"))
        try:
            document = AssistantReply(
                schema_version=1,
                reply=" ".join(fragment.sentence for fragment in fragments),
                acts=tuple(fragment.act for fragment in fragments),
            ).model_dump_json()
        except ValidationError as exc:
            error = ProviderOutputError("the live reply does not form a valid reply")
            raise self._amend_failure(error) from exc
        pieces = _split(document)
        for position, piece in enumerate(pieces):
            yield ReasoningChunk(
                provider=self.descriptor, text=piece, is_final=position == len(pieces) - 1
            )

    def _fragment(self, element: str, index: int) -> ReplyFragment:
        try:
            raw = json.loads(element)
            act = ReplyAct(**{name: raw.get(name) for name in _ACT_FIELDS})
            return ReplyFragment(
                schema_version=1, index=index, act=act, sentence=str(raw["sentence"]).strip()
            )
        except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
            raise self._reject(ProviderOutputError("malformed reply fragment")) from exc
