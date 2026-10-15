"""Validate untrusted assistant replies against the turn they answer (Story 9.6).

Reasoning output is ``untrusted_model_output`` whichever adapter produced it. Before a reply is
spoken or committed, every act's citations are checked against what the reasoning call was given:
the cited statement must exist in the current observation and contain the quote; a recalled value
must come from an earlier *user* turn in the supplied history window that contains the quote, the
name, and the value; and the reply text must actually say every value it claims to recall. A single
bad citation rejects the whole reply. Nothing in a reply can change configuration or authority.
"""

from collections.abc import Sequence

from pydantic import ValidationError

from multimodal_voice_platform.contracts.conversation import AssistantReply, ReplyAct, ReplyActKind
from multimodal_voice_platform.contracts.reasoning import ObservationView
from multimodal_voice_platform.contracts.session import ConversationRole, ConversationTurn
from multimodal_voice_platform.crossmodal.errors import ReasoningOutputError
from multimodal_voice_platform.voice.errors import ReplyRejectedError


def parse_reply(text: str, *, max_reply_chars: int) -> AssistantReply:
    """Parse the provider's streamed document into the typed reply contract.

    Args:
        text: The concatenated chunk text.
        max_reply_chars: Longest reply the assistant will speak, from application limits.

    Returns:
        The typed reply.

    Raises:
        ReasoningOutputError: If the text is not a valid reply document. The provider's payload
            is never echoed.
        ReplyRejectedError: If the reply is longer than the assistant will speak.
    """
    try:
        reply = AssistantReply.model_validate_json(text)
    except ValidationError as exc:
        raise ReasoningOutputError(
            "reasoning provider returned output that is not a valid reply document"
        ) from exc
    if len(reply.reply) > max_reply_chars:
        raise ReplyRejectedError("the assistant reply exceeds its length limit")
    return reply


def validate_reply(
    reply: AssistantReply, view: ObservationView, history: Sequence[ConversationTurn]
) -> AssistantReply:
    """Check every act's citations against the current observation and the history window.

    Args:
        reply: Typed provider output.
        view: The current turn's observation the reasoning call received.
        history: The exact history window the reasoning call received.

    Returns:
        The reply, unchanged, once every citation is verified.

    Raises:
        ReasoningOutputError: If any citation is missing, misattributed, or inconsistent.
    """
    statements = {statement.statement_id: statement.text for statement in view.statements}
    spoken = reply.reply.casefold()
    for act in reply.acts:
        _check(act, statements, history, spoken)
    return reply


def _fail(message: str) -> ReasoningOutputError:
    return ReasoningOutputError(f"assistant reply failed provenance checks: {message}")


def _contains(text: str, part: str) -> bool:
    return " ".join(part.casefold().split()) in " ".join(text.casefold().split())


def _check(
    act: ReplyAct,
    statements: dict[str, str],
    history: Sequence[ConversationTurn],
    spoken: str,
) -> None:
    statement = statements.get(act.statement_id)
    if statement is None:
        raise _fail("an act cites a statement the turn does not contain")
    if not _contains(statement, act.quote):
        raise _fail("an act quote does not appear in its statement")
    if act.slot is not None and not _contains(act.quote, act.slot):
        raise _fail("an act names an item its quote does not mention")
    remembered = act.kind is ReplyActKind.REMEMBERED and act.value is not None
    if remembered and not _contains(act.quote, act.value or ""):
        raise _fail("a remembered value does not appear in its quote")
    if act.kind is not ReplyActKind.RECALLED:
        return
    index, quote, slot, value = act.history_index, act.history_quote, act.slot, act.value
    if index is None or quote is None or slot is None or value is None:
        raise _fail("a recalled value carries no history citation")
    if index >= len(history):
        raise _fail("a recalled value cites a turn outside the supplied history")
    turn = history[index]
    if turn.role is not ConversationRole.USER:
        raise _fail("a recalled value must come from an earlier user turn")
    if not _contains(turn.text, quote):
        raise _fail("a history quote does not appear in its turn")
    if not (_contains(quote, slot) and _contains(quote, value)):
        raise _fail("a history quote does not state the recalled item and value")
    if not _contains(spoken, value):
        raise _fail("the reply does not say the value it claims to recall")
