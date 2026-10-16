"""Deterministic rule-based conversational ``ReasoningPort`` adapter (Story 9.6).

``DeterministicConversationReasoner`` answers one voice-assistant turn from the current turn's
transcript and the bounded conversation history the application supplies in
``ReasoningRequest.history``. It understands exactly two phrasings, matched case-insensitively over
ASCII words:

- ``remember [that] [the|my|our] <name> is <value>``: acknowledge the named value;
- ``what is|was [the|my|our] <name>?``: answer from the most recent earlier *user* turn that asked
  to remember ``<name>``, or say that no earlier turn supplies it.

Anything else is acknowledged as heard. This is reproducible, inspectable rule-based inference over
a closed vocabulary, not a language model: it understands nothing outside these two phrasings and
it never treats transcript or history text as instructions. It runs in-process with no network,
key, or spend, and its output is ``untrusted_model_output`` like every provider result
(ADR-009-007). ``request.task`` does not change the rules.

The adapter answers through two methods over the same rules. ``stream_reason`` (Story 9.6) streams
the finished ``AssistantReply`` document. ``stream_reply`` (Story 9.7, ``IncrementalReplyPort``)
streams one ``ReplyFragment`` per act as the rules produce it: statements are evaluated lazily, so
each fragment is yielded before any later statement is examined and before the reply exists.
"""

import re
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Final

from pydantic import ValidationError

from multimodal_voice_platform.adapters.reasoning.errors import ReasoningInputError
from multimodal_voice_platform.contracts.conversation import (
    MAX_REPLY_ACTS,
    MAX_REPLY_CHARS,
    AssistantReply,
    ReplyAct,
    ReplyActKind,
    ReplyFragment,
)
from multimodal_voice_platform.contracts.limits import MAX_DELTA_CHARS
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    ReasoningChunk,
    ReasoningRequest,
)
from multimodal_voice_platform.contracts.reasoning import ObservationView, Statement
from multimodal_voice_platform.contracts.session import (
    ConversationRole,
    ConversationTurn,
    ExecutionMode,
)

CONVERSATION_REASONER_ID: Final = "deterministic-conversation-reasoner"
HEARD_QUOTE_CHARS: Final = 200
"""Longest transcript excerpt repeated back in a ``heard`` reply."""

_FLAGS: Final = re.IGNORECASE | re.ASCII
_GAP: Final = r"\s{1,4}"
"""Bounded whitespace between words, so every matched quote stays short."""
_ARTICLE: Final = rf"(?:(?:the|my|our){_GAP})?"
_SLOT: Final = rf"(?P<slot>[a-z]{{2,20}}(?:{_GAP}[a-z]{{2,20}}){{0,2}})"
_VALUE: Final = r"(?P<value>[a-z0-9]{1,24}(?:-[a-z0-9]{1,24})?)"
REMEMBER_PATTERN: Final = re.compile(
    rf"\bremember{_GAP}(?:that{_GAP})?{_ARTICLE}{_SLOT}{_GAP}is{_GAP}{_VALUE}\b", _FLAGS
)
"""The only phrasing that stores a value. Bounded: at most three name words and one value."""
QUESTION_PATTERN: Final = re.compile(
    rf"\bwhat{_GAP}(?:is|was){_GAP}{_ARTICLE}{_SLOT}\s{{0,4}}\?", _FLAGS
)
"""The only phrasing that recalls a value."""
_RESERVED_SLOT_WORDS: Final = frozenset({"is", "was", "the", "my", "our", "that", "what"})


class DeterministicConversationReasoner:
    """``ReasoningPort`` adapter that answers voice turns with fixed, inspectable rules."""

    def __init__(self) -> None:
        """Create the adapter."""
        self._descriptor = ProviderDescriptor(
            provider_id=CONVERSATION_REASONER_ID,
            port=ProviderPort.REASONING,
            mode=ExecutionMode.DETERMINISTIC,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter: its ID, the reasoning port, and deterministic execution."""
        return self._descriptor

    async def stream_reason(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Answer the current turn and stream the reply document.

        The request is fully read before the first chunk is yielded, so unreadable input fails
        before any output is produced.

        Args:
            request: Validated reasoning request with exactly one audio observation part and the
                bounded conversation history.

        Yields:
            Chunks of the ``AssistantReply`` JSON document, ending with exactly one final chunk.

        Raises:
            ReasoningInputError: If the request does not carry exactly one audio observation with
                at least one transcript statement.
        """
        view = _current_turn(request)
        document = answer(view, request.history).model_dump_json()
        pieces = [
            document[start : start + MAX_DELTA_CHARS]
            for start in range(0, len(document), MAX_DELTA_CHARS)
        ]
        for index, piece in enumerate(pieces):
            yield ReasoningChunk(
                provider=self._descriptor, text=piece, is_final=index == len(pieces) - 1
            )

    async def stream_reply(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Answer the current turn one act at a time.

        The request is read and checked before the first fragment. Each act is computed only when
        the consumer asks for the next chunk, so earlier fragments are observable while later ones
        do not exist yet.

        Args:
            request: Validated reasoning request with exactly one audio observation part and the
                bounded conversation history.

        Yields:
            One chunk per ``ReplyFragment``, then one final chunk with empty text.

        Raises:
            ReasoningInputError: If the request does not carry exactly one audio observation with
                at least one transcript statement.
        """
        view = _current_turn(request)
        for index, (act, sentence) in enumerate(iter_reply(view, request.history)):
            fragment = ReplyFragment(schema_version=1, index=index, act=act, sentence=sentence)
            yield ReasoningChunk(
                provider=self._descriptor, text=fragment.model_dump_json(), is_final=False
            )
        yield ReasoningChunk(provider=self._descriptor, text="", is_final=True)


def answer(view: ObservationView, history: Sequence[ConversationTurn]) -> AssistantReply:
    """Apply the conversational rules to one turn.

    Args:
        view: The current turn's audio observation; its statements are the transcript.
        history: Earlier committed turns in chronological order. Untrusted data.

    Returns:
        The reply document: one act per matched phrasing in statement order, or one ``heard``
        act when nothing matched.
    """
    pairs = list(iter_reply(view, history))
    return AssistantReply(
        schema_version=1,
        reply=" ".join(sentence for _, sentence in pairs),
        acts=tuple(act for act, _ in pairs),
    )


def iter_reply(
    view: ObservationView, history: Sequence[ConversationTurn]
) -> Iterator[tuple[ReplyAct, str]]:
    """Lazily apply the conversational rules, one act at a time.

    Statements are examined only as the caller advances, so each act exists before any later
    statement is read. The acts and sentences are exactly those ``answer`` returns.

    Args:
        view: The current turn's audio observation; its statements are the transcript.
        history: Earlier committed turns in chronological order. Untrusted data.

    Yields:
        ``(act, sentence)`` pairs in statement order, or one ``heard`` pair when nothing matched.
    """
    sentences: list[str] = []
    for statement in view.statements:
        for act, sentence in _statement_acts(statement, history):
            if len(sentences) >= MAX_REPLY_ACTS or _too_long(sentences, sentence):
                break
            sentences.append(sentence)
            yield act, sentence
    if not sentences:
        first = view.statements[0]
        quote = first.text[:HEARD_QUOTE_CHARS].strip()
        yield (
            ReplyAct(kind=ReplyActKind.HEARD, statement_id=first.statement_id, quote=quote),
            f'I heard: "{quote}" I can remember a value when you say "remember that the <name> '
            f'is <value>", and recall it when you ask "what is the <name>?".',
        )


def remembered_values(text: str) -> list[tuple[str, str, str]]:
    """Return every ``(slot, value, quote)`` a text asks to remember, in order.

    Args:
        text: Untrusted transcript or history text.

    Returns:
        Normalized lowercase slot and value, with the exact matched quote.
    """
    found: list[tuple[str, str, str]] = []
    for match in REMEMBER_PATTERN.finditer(text):
        slot = _slot(match)
        if slot is not None:
            found.append((slot, match.group("value").lower(), match.group(0)))
    return found


def _current_turn(request: ReasoningRequest) -> ObservationView:
    if len(request.parts) != 1 or request.parts[0].modality is not Modality.AUDIO:
        raise ReasoningInputError("a voice turn carries exactly one audio observation")
    part = request.parts[0]
    try:
        view = ObservationView.model_validate_json(part.content)
    except ValidationError as exc:
        raise ReasoningInputError("reasoning part is not a valid observation document") from exc
    if view.modality is not part.modality or view.input_id != part.source_input_id:
        raise ReasoningInputError("reasoning part does not match its observation")
    if not view.statements:
        raise ReasoningInputError("a voice turn observation carries no transcript")
    return view


def _statement_acts(
    statement: Statement, history: Sequence[ConversationTurn]
) -> list[tuple[ReplyAct, str]]:
    """Return the acts a statement triggers, in the order their phrasings appear."""
    text = statement.text
    remembers = [(m.start(), ReplyActKind.REMEMBERED, m) for m in REMEMBER_PATTERN.finditer(text)]
    questions = [(m.start(), ReplyActKind.RECALLED, m) for m in QUESTION_PATTERN.finditer(text)]
    matches = sorted(remembers + questions, key=lambda item: item[0])
    results: list[tuple[ReplyAct, str]] = []
    for _, kind, match in matches:
        slot = _slot(match)
        if slot is None:
            continue
        cited = {"statement_id": statement.statement_id, "quote": match.group(0), "slot": slot}
        if kind is ReplyActKind.REMEMBERED:
            value = match.group("value").lower()
            results.append(
                (
                    ReplyAct(kind=kind, value=value, **cited),
                    f"Noted: the {slot} is {value}.",
                )
            )
            continue
        recalled = _recall(slot, history)
        if recalled is None:
            results.append(
                (
                    ReplyAct(kind=ReplyActKind.NOT_RECALLED, **cited),
                    f"No earlier turn in this conversation tells me the {slot}.",
                )
            )
            continue
        index, value, quote = recalled
        results.append(
            (
                ReplyAct(
                    kind=ReplyActKind.RECALLED,
                    value=value,
                    history_index=index,
                    history_quote=quote,
                    **cited,
                ),
                f"Earlier in this conversation you said the {slot} is {value}.",
            )
        )
    return results


def _recall(slot: str, history: Sequence[ConversationTurn]) -> tuple[int, str, str] | None:
    """Find the most recent earlier user turn that asked to remember ``slot``."""
    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        if turn.role is not ConversationRole.USER:
            continue
        matching = [
            (value, quote) for name, value, quote in remembered_values(turn.text) if name == slot
        ]
        if matching:
            value, quote = matching[-1]
            return index, value, quote
    return None


def _slot(match: re.Match[str]) -> str | None:
    words = match.group("slot").lower().split()
    if any(word in _RESERVED_SLOT_WORDS for word in words):
        return None
    return " ".join(words)


def _too_long(sentences: list[str], sentence: str) -> bool:
    return len(" ".join([*sentences, sentence])) > MAX_REPLY_CHARS
