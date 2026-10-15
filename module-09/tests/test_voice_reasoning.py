"""Story 9.6 conversational rules, reply contract and validation, state, and records."""

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError
from voice_builders import fixture_turn, started

from multimodal_voice_platform.adapters.reasoning import (
    DeterministicConversationReasoner,
    ReasoningInputError,
)
from multimodal_voice_platform.adapters.reasoning.conversation import answer, remembered_values
from multimodal_voice_platform.contracts.conversation import (
    MAX_REPLY_ACTS,
    MAX_REPLY_CHARS,
    AssistantReply,
    ReplyAct,
    ReplyActKind,
)
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.modality import InputSource, Modality, TrustLevel
from multimodal_voice_platform.contracts.providers import ReasoningPart, ReasoningRequest
from multimodal_voice_platform.contracts.reasoning import FactOrigin, ObservationView, Statement
from multimodal_voice_platform.contracts.session import (
    ConversationRole,
    ConversationTurn,
    SessionConfig,
)
from multimodal_voice_platform.crossmodal import ReasoningOutputError
from multimodal_voice_platform.voice import (
    ConversationStore,
    StateCommitError,
    TurnStatus,
    VoiceLimits,
    VoiceStage,
    VoiceTurnRecord,
    parse_reply,
    validate_reply,
)


def _view(*texts: str, modality: Modality = Modality.AUDIO) -> ObservationView:
    origin = FactOrigin.FIXTURE_PLAYBACK if modality is Modality.AUDIO else FactOrigin.USER_PROVIDED
    return ObservationView(
        observation_id="obs-1",
        modality=modality,
        input_id="input-0123456789abcdef",
        source=InputSource.USER_UPLOAD,
        trust=(
            TrustLevel.UNTRUSTED_MODEL_OUTPUT
            if modality is Modality.AUDIO
            else TrustLevel.UNTRUSTED_EXTERNAL
        ),
        statements=tuple(
            Statement(statement_id=f"obs-1-s{n}", text=text, origin=origin)
            for n, text in enumerate(texts, start=1)
        ),
    )


def _user(text: str) -> ConversationTurn:
    return ConversationTurn(
        role=ConversationRole.USER, text=text, trust=TrustLevel.UNTRUSTED_EXTERNAL
    )


def _assistant(text: str) -> ConversationTurn:
    return ConversationTurn(
        role=ConversationRole.ASSISTANT, text=text, trust=TrustLevel.UNTRUSTED_MODEL_OUTPUT
    )


# --- Closed-vocabulary rules -----------------------------------------------------------------


def test_remember_and_recall_phrasings_are_the_whole_vocabulary() -> None:
    assert remembered_values("Please remember that the project code word is falcon.") == [
        ("project code word", "falcon", "remember that the project code word is falcon")
    ]
    assert remembered_values("REMEMBER my locker number is B-12") == [
        ("locker number", "b-12", "REMEMBER my locker number is B-12")
    ]
    for ignored in (
        "Note the code word is falcon.",
        "remember that the is is falcon",
        "I remember nothing.",
        "remember that the code word is",
    ):
        assert remembered_values(ignored) == [], ignored
    reply = answer(_view("Store this: the code word is falcon. What does falcon mean?"), ())
    assert [act.kind for act in reply.acts] == [ReplyActKind.HEARD]


def test_recall_reads_only_earlier_user_turns_and_prefers_the_newest() -> None:
    history = (
        _user("Remember that the code word is falcon."),
        _assistant("Noted: the code word is falcon."),
        _user("Remember that the code word is owl."),
        _assistant("Remember that the code word is kestrel."),
    )
    reply = answer(_view("What is the code word?"), history)
    act = reply.acts[0]
    assert (act.kind, act.value, act.history_index) == (ReplyActKind.RECALLED, "owl", 2)
    assert act.history_quote == "Remember that the code word is owl"
    assert reply.reply == "Earlier in this conversation you said the code word is owl."
    only_assistant = answer(_view("What is the code word?"), history[3:])
    assert only_assistant.acts[0].kind is ReplyActKind.NOT_RECALLED


def test_a_turn_cannot_recall_what_it_states_itself() -> None:
    reply = answer(_view("Remember that the code word is owl. What is the code word?"), ())
    assert [act.kind for act in reply.acts] == [ReplyActKind.REMEMBERED, ReplyActKind.NOT_RECALLED]


def test_replies_are_bounded_in_acts_and_characters() -> None:
    many = " ".join(
        f"Remember that the item {chr(97 + n)}{chr(97 + n)} is v{n}." for n in range(20)
    )
    reply = answer(_view(many), ())
    assert 1 <= len(reply.acts) <= MAX_REPLY_ACTS
    assert len(reply.reply) <= MAX_REPLY_CHARS
    heard = answer(_view("z" * 900), ())
    assert len(heard.acts[0].quote) == 200 and len(heard.reply) <= MAX_REPLY_CHARS


def test_reasoner_accepts_only_one_audio_observation_with_a_transcript() -> None:
    reasoner = DeterministicConversationReasoner()

    def run(*parts: ReasoningPart) -> Any:
        request = ReasoningRequest(
            session_id="sess-voice", task="Answer.", parts=parts, max_output_tokens=64
        )

        async def collect() -> list[Any]:
            return [chunk async for chunk in reasoner.stream_reason(request)]

        return asyncio.run(collect())

    audio = _view("Hello.")
    part = ReasoningPart(
        modality=Modality.AUDIO,
        source_input_id=audio.input_id,
        content=audio.model_dump_json(),
        trust=audio.trust,
    )
    chunks = run(part)
    assert chunks[-1].is_final and chunks[0].provider == reasoner.descriptor
    text = _view("Hello.", modality=Modality.TEXT)
    text_part = ReasoningPart(
        modality=Modality.TEXT,
        source_input_id=text.input_id,
        content=text.model_dump_json(),
        trust=text.trust,
    )
    for bad in ((part, part), (text_part,)):
        with pytest.raises(ReasoningInputError):
            run(*bad)
    garbled = part.model_copy(update={"content": "not json"})
    with pytest.raises(ReasoningInputError):
        run(garbled)
    mismatched = part.model_copy(update={"source_input_id": "input-other"})
    with pytest.raises(ReasoningInputError):
        run(mismatched)


# --- Reply contract and validation -----------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "remembered", "slot": "code word"},
        {"kind": "recalled", "slot": "code word", "value": "owl"},
        {"kind": "recalled", "slot": "code word", "value": "owl", "history_index": 0},
        {"kind": "not_recalled", "slot": "code word", "value": "owl"},
        {"kind": "heard", "slot": "code word"},
        {"kind": "remembered", "slot": "Code Word", "value": "owl"},
        {"kind": "remembered", "slot": "code word", "value": "two words"},
        {"kind": "heard", "grant": "admin"},
    ],
)
def test_reply_acts_must_carry_exactly_the_citations_their_kind_needs(
    fields: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        ReplyAct.model_validate({"statement_id": "obs-1-s1", "quote": "x", **fields})


def _validate(
    document: dict[str, Any], view: ObservationView, history: tuple[Any, ...] = ()
) -> Any:
    reply = parse_reply(
        AssistantReply.model_validate(document).model_dump_json(), max_reply_chars=600
    )
    return validate_reply(reply, view, history)


def test_reply_validation_checks_every_citation() -> None:
    view = _view("What is the code word?")
    history = (_user("Remember that the code word is owl."), _assistant("Noted."))
    act = {
        "kind": "recalled",
        "statement_id": "obs-1-s1",
        "quote": "What is the code word?",
        "slot": "code word",
        "value": "owl",
        "history_index": 0,
        "history_quote": "Remember that the code word is owl",
    }
    good = {"schema_version": 1, "reply": "You said the code word is owl.", "acts": [act]}
    assert _validate(good, view, history).acts[0].value == "owl"
    for change, message in (
        ({"statement_id": "obs-1-s2"}, "does not contain"),
        ({"quote": "What is the pin?"}, "does not appear"),
        ({"history_index": 1}, "earlier user turn"),
        ({"history_index": 5}, "outside the supplied history"),
        ({"history_quote": "Remember that the code word is emu"}, "does not appear in its turn"),
        ({"slot": "pin"}, "does not mention"),
    ):
        forged = {**good, "acts": [{**act, **change}]}
        with pytest.raises(ReasoningOutputError, match=message):
            _validate(forged, view, history)
    silent = {**good, "reply": "I know the answer."}
    with pytest.raises(ReasoningOutputError, match="does not say"):
        _validate(silent, view, history)
    with pytest.raises(ReasoningOutputError, match="outside the supplied history"):
        _validate(good, view, ())


def test_parse_reply_rejects_invalid_documents_without_echoing_them() -> None:
    for text in (
        "",
        "[]",
        '{"schema_version": 2}',
        '{"schema_version": 1, "reply": "x", "acts": []}',
    ):
        with pytest.raises(ReasoningOutputError) as raised:
            parse_reply(text, max_reply_chars=600)
        assert text not in raised.value.safe_message or not text


# --- State store and limits ------------------------------------------------------------------


def test_voice_limits_reject_contradictory_or_excessive_bounds() -> None:
    for fields in (
        {"max_context_turns": 7},
        {"max_context_chars": 13_000},
        {"max_history_chars": 1_000},
        {"max_retained_turns": 26},
        {"max_reply_chars": 1_001},
        {"max_active_sessions": 0},
    ):
        with pytest.raises(ValidationError):
            VoiceLimits(**fields)


def test_store_commits_atomically_and_refuses_stale_reservations() -> None:
    store = ConversationStore(VoiceLimits())
    config = SessionConfig(session_id="sess-store")
    store.open(config)
    reservation = store.begin_turn("sess-store", "turn-1")
    snapshot = store.commit(reservation, "Hello.", "Hi.")
    assert snapshot.committed_turns == 1 and snapshot.version == 1
    with pytest.raises(StateCommitError):
        store.commit(reservation, "Again.", "Again.")
    second = store.begin_turn("sess-store", "turn-2")
    store.release(second)
    with pytest.raises(StateCommitError):
        store.commit(second, "Late.", "Late.")
    third = store.begin_turn("sess-store", "turn-3")
    store.close("sess-store")
    store.open(config)
    with pytest.raises(StateCommitError):
        store.commit(third, "Ghost.", "Ghost.")
    assert store.snapshot("sess-store").committed_turns == 0


# --- Records reject claims beyond what ran ------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"speech_recognition_performed": True},
        {"speech_synthesis_performed": True},
        {"model_inference_performed": True},
        {"live_provider_called": True},
        {"streaming_performed": True},
        {"committed": False},
        {"status": TurnStatus.FAILED},
        {"reply": None},
        {"synthesis": None},
        {"sequence": None},
        {"reasoning_kind": "model_inference"},
        {"timings": ()},
    ],
)
def test_records_reject_claims_beyond_what_ran(overrides: dict[str, Any]) -> None:
    voice, _ = started()
    record = fixture_turn(voice, "turn-1", "voice-remember")
    data = {name: getattr(record, name) for name in VoiceTurnRecord.model_fields} | overrides
    with pytest.raises(ValidationError):
        VoiceTurnRecord.model_validate(data)


def test_records_reject_stronger_or_mismatched_evidence() -> None:
    voice, _ = started()
    record = fixture_turn(voice, "turn-1", "voice-remember")
    fields = {name: getattr(record, name) for name in VoiceTurnRecord.model_fields}
    demo = record.evidence.model_copy(update={"evidence_class": EvidenceClass.DETERMINISTIC_DEMO})
    for evidence in (
        demo,
        record.evidence.model_copy(update={"story": "9.5"}),
    ):
        with pytest.raises(ValidationError):
            VoiceTurnRecord.model_validate(fields | {"evidence": evidence})
    failed = fields | {
        "status": TurnStatus.FAILED,
        "committed": False,
        "sequence": None,
        "failed_stage": VoiceStage.END_TO_END,
        "error": {"code": "internal_error", "message": "x"},
    }
    with pytest.raises(ValidationError):
        VoiceTurnRecord.model_validate(failed)
