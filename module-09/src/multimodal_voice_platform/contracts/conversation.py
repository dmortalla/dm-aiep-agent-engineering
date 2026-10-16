"""Structured voice-assistant reply contract (Story 9.6, ADR-009-003/006/007).

``ReasoningPort`` streams text. For a voice-assistant turn the request carries one canonical
``ObservationView`` of the current turn's processed audio and transcript, plus the bounded
conversation history in ``ReasoningRequest.history``. A reasoning adapter streams back one
``AssistantReply`` JSON document. Both directions are untrusted data.

Story 9.7 adds an incremental form of the same reply: an ``IncrementalReplyPort`` adapter streams
one ``ReplyFragment`` per reply act, each produced before the next act is computed, and ends with
one empty final chunk. Each fragment is one act and the sentence that speaks it; the full reply is
the fragments' sentences joined by single spaces.

These models define shapes and invariants only. Whether a reply act's citations exist in the
current observation or the history it was given is checked by the application core
(``voice.reply``), never assumed.
"""

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from multimodal_voice_platform.contracts.limits import MAX_DELTA_CHARS, MAX_HISTORY_TURNS
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ReasoningChunk,
    ReasoningRequest,
)
from multimodal_voice_platform.contracts.reasoning import MAX_QUOTE_CHARS, StatementId

MAX_REPLY_CHARS: Final = 1_000
"""Hard ceiling on the assistant reply text that is spoken by text-to-speech."""
MAX_REPLY_ACTS: Final = 8

SlotName = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,20}( [a-z]{2,20}){0,2}$")]
"""A remembered item's name: one to three lowercase words, such as ``project code word``."""
SlotValue = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]{1,24}(-[a-z0-9]{1,24})?$")]
"""A remembered item's value: one lowercase token, optionally hyphenated."""
Quote = Annotated[str, StringConstraints(min_length=1, max_length=MAX_QUOTE_CHARS)]


class ReplyActKind(StrEnum):
    """What one part of a reply does. Kept explicit so reviewers can check every claim."""

    REMEMBERED = "remembered"
    """The current transcript asked the assistant to remember a named value."""
    RECALLED = "recalled"
    """The current transcript asked for a named value, answered from an earlier user turn."""
    NOT_RECALLED = "not_recalled"
    """The current transcript asked for a named value that no earlier user turn supplies."""
    HEARD = "heard"
    """Nothing in the closed vocabulary matched; the reply acknowledges what was heard."""


class ReplyAct(BaseModel):
    """One cited part of an assistant reply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ReplyActKind
    statement_id: StatementId
    quote: Quote
    slot: SlotName | None = None
    value: SlotValue | None = None
    history_index: int | None = Field(default=None, ge=0, lt=MAX_HISTORY_TURNS)
    history_quote: Quote | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        """Require exactly the citations each kind of act needs.

        Returns:
            The validated act.

        Raises:
            ValueError: If the slot, value, or history citation does not fit the kind.
        """
        has_slot, has_value = self.slot is not None, self.value is not None
        has_history = self.history_index is not None or self.history_quote is not None
        if has_history and (self.history_index is None or self.history_quote is None):
            raise ValueError("a history citation needs both an index and a quote")
        kind = self.kind
        if kind is ReplyActKind.REMEMBERED:
            valid = has_slot and has_value and not has_history
        elif kind is ReplyActKind.RECALLED:
            valid = has_slot and has_value and has_history
        elif kind is ReplyActKind.NOT_RECALLED:
            valid = has_slot and not has_value and not has_history
        else:
            valid = not has_slot and not has_value and not has_history
        if not valid:
            raise ValueError(f"{kind} reply acts do not carry the citations they require")
        return self


class AssistantReply(BaseModel):
    """The structured document a voice-reasoning adapter streams back. Untrusted model output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    reply: str = Field(min_length=1, max_length=MAX_REPLY_CHARS)
    acts: tuple[ReplyAct, ...] = Field(min_length=1, max_length=MAX_REPLY_ACTS)


class ReplyFragment(BaseModel):
    """One act of an incrementally produced reply and the sentence that speaks it (Story 9.7).

    Untrusted model output, like the whole reply. ``index`` orders fragments from zero.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    index: int = Field(ge=0, lt=MAX_REPLY_ACTS)
    act: ReplyAct
    sentence: str = Field(min_length=1, max_length=min(MAX_REPLY_CHARS, MAX_DELTA_CHARS))


class IncrementalReplyPort(Protocol):
    """Reasoning capability that produces a voice reply one act at a time (Story 9.7)."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter."""
        ...

    def stream_reply(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Stream reply fragments as they are produced.

        Args:
            request: Validated reasoning request for one voice turn.

        Returns:
            Async iterator of chunks: one ``ReplyFragment`` JSON document per non-final chunk,
            then exactly one final chunk with empty text.
        """
        ...
