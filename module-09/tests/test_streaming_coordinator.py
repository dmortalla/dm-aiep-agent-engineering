"""Story 9.7 streaming coordinator: genuine incremental production, state, and cancellation."""

import asyncio
import math
from collections.abc import AsyncIterator
from typing import Any

import pytest
from stream_builders import (
    coordinator,
    current_view,
    gated,
    heard_fragment,
    run,
    scripted,
)
from voice_builders import (
    REASONER_DOUBLE,
    TEST,
    TONE_WAV,
    stored_audio,
    tts_binding,
)
from voice_builders import request as voice_request

from multimodal_voice_platform.adapters.reasoning import conversation as rules
from multimodal_voice_platform.adapters.reasoning.conversation import (
    DeterministicConversationReasoner,
    answer,
)
from multimodal_voice_platform.contracts.conversation import ReplyAct, ReplyActKind, ReplyFragment
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.providers import ReasoningChunk, ReasoningRequest
from multimodal_voice_platform.crossmodal import ReasoningKind
from multimodal_voice_platform.speech.errors import SpeechProviderUnavailableError
from multimodal_voice_platform.streaming import (
    AudioReadyUpdate,
    IncrementalReplyBinding,
    ResponseCompletedUpdate,
    ResponseFragmentUpdate,
    StageTimedUpdate,
    StreamedTurnRecord,
    StreamingConfigurationError,
    StreamingVoiceCoordinator,
    StreamMilestone,
    TranscriptReadyUpdate,
    TurnAcceptedUpdate,
    TurnFinished,
)
from multimodal_voice_platform.voice import TurnStatus, VoiceStage, VoiceTurnRequest

TWO_FACTS = "Please remember that the project code word is falcon. Remember that the room is blue."
RECALL = "What is the project code word? What is the room?"


def _request(streaming: StreamingVoiceCoordinator, session_id: str, turn_id: str) -> Any:
    return voice_request(turn_id, TONE_WAV, session_id=session_id)


async def _collect(
    streaming: StreamingVoiceCoordinator, request: VoiceTurnRequest, evidence: Any = TEST
) -> list[Any]:
    return [update async for update in streaming.stream_turn(request, evidence_class=evidence)]


def _record(updates: list[Any]) -> StreamedTurnRecord:
    assert isinstance(updates[-1], TurnFinished)
    assert sum(isinstance(u, TurnFinished) for u in updates) == 1
    return updates[-1].record


# --- Committed deterministic conversation -----------------------------------------------------


def test_fixture_conversation_streams_in_pipeline_order_and_commits() -> None:
    streaming = coordinator()
    session = streaming.open_session().session_id

    async def body() -> tuple[list[Any], list[Any]]:
        first = [
            u
            async for u in streaming.stream_fixture_turn(
                session, "turn-1", "voice-remember", evidence_class=TEST
            )
        ]
        second = [
            u
            async for u in streaming.stream_fixture_turn(
                session, "turn-2", "voice-recall", evidence_class=TEST
            )
        ]
        return first, second

    first, second = run(body())
    kinds = [type(u) for u in first if not isinstance(u, StageTimedUpdate)]
    assert kinds == [
        TurnAcceptedUpdate,
        TranscriptReadyUpdate,
        ResponseFragmentUpdate,
        ResponseCompletedUpdate,
        AudioReadyUpdate,
        TurnFinished,
    ]
    record = _record(second)
    assert record.committed and record.turn.streaming_performed
    assert record.turn.evidence.story == "9.7"
    assert record.turn.reasoning_kind is ReasoningKind.DETERMINISTIC_RULE_INFERENCE
    fragments = [u.text for u in second if isinstance(u, ResponseFragmentUpdate)]
    assert fragments == ["Earlier in this conversation you said the project code word is falcon."]
    assert record.turn.reply is not None and record.turn.reply.reply == fragments[0]
    snapshot = streaming.voice.conversation(session)
    assert snapshot.committed_turns == 2


def test_streamed_reply_matches_the_synchronous_rules_exactly() -> None:
    streaming = coordinator(transcripts=[TWO_FACTS])
    session = streaming.open_session().session_id
    updates = run(_collect(streaming, _request(streaming, session, "turn-1")))
    record = _record(updates)
    texts = [u.text for u in updates if isinstance(u, ResponseFragmentUpdate)]
    assert texts == ["Noted: the project code word is falcon.", "Noted: the room is blue."]
    assert record.turn.reply is not None
    assert record.turn.reply.reply == " ".join(texts)
    assert record.turn.context is not None
    reasoner = DeterministicConversationReasoner()
    assert reasoner.descriptor.provider_id == record.turn.reasoning_provider.provider_id
    assert len(record.turn.reply.acts) == record.fragments_streamed == 2


def test_deterministic_adapter_yields_each_fragment_before_reading_later_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, ReasoningRequest] = {}
    real = DeterministicConversationReasoner()

    async def capture(request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        captured["request"] = request
        async for chunk in real.stream_reply(request):
            yield chunk.model_copy(update={"provider": REASONER_DOUBLE})

    streaming = coordinator(reply=scripted(capture), transcripts=[TWO_FACTS])
    session = streaming.open_session().session_id
    run(_collect(streaming, _request(streaming, session, "turn-1")))
    request = captured["request"]
    examined: list[str] = []
    original = rules._statement_acts

    def spy(statement: Any, history: Any) -> Any:
        examined.append(statement.statement_id)
        return original(statement, history)

    monkeypatch.setattr(rules, "_statement_acts", spy)

    async def lazily() -> None:
        stream = real.stream_reply(request)
        first = await anext(stream)
        assert ReplyFragment.model_validate_json(first.text).index == 0
        assert len(examined) == 1, "the second statement is unread when fragment 0 is yielded"
        rest = [chunk async for chunk in stream]
        assert len(examined) == 2 and rest[-1].is_final and rest[-1].text == ""

    run(lazily())
    view = current_view(request)
    document = answer(view, request.history)
    assert [a.kind for a in document.acts] == ["remembered", "remembered"]


# --- Genuine incremental streaming -------------------------------------------------------------


def test_fragment_is_observable_while_reasoning_is_still_running() -> None:
    binding, double = gated(gates=1)
    streaming = coordinator(reply=binding, transcripts=[TWO_FACTS])
    session = streaming.open_session().session_id

    async def body() -> None:
        stream = streaming.stream_turn(_request(streaming, session, "turn-1"), evidence_class=TEST)
        seen: list[Any] = []
        async for update in stream:
            seen.append(update)
            if isinstance(update, ResponseFragmentUpdate):
                break
        # The reasoner has produced exactly one fragment and is blocked on its gate: the reply
        # does not exist yet, nothing completed, and nothing is committed.
        assert len(double.produced) == 1 and not double.closed
        assert not any(isinstance(u, ResponseCompletedUpdate | TurnFinished) for u in seen)
        assert streaming.voice.conversation(session).committed_turns == 0
        double.gates[0].set()
        rest = [update async for update in stream]
        assert any(isinstance(u, ResponseCompletedUpdate) for u in rest)
        record = _record(rest)
        assert record.committed and record.fragments_streamed == 2
        first = record.time_to_first_response_ms
        completed = next(
            m.elapsed_ms
            for m in record.milestones
            if m.milestone is StreamMilestone.RESPONSE_COMPLETE
        )
        assert first is not None and first <= completed

    run(body())


def test_milestones_and_stage_timings_are_finite_ordered_and_consistent() -> None:
    streaming = coordinator(transcripts=[TWO_FACTS])
    session = streaming.open_session().session_id
    updates = run(_collect(streaming, _request(streaming, session, "turn-1")))
    record = _record(updates)
    names = [m.milestone for m in record.milestones]
    assert names == list(StreamMilestone)
    elapsed = [m.elapsed_ms for m in record.milestones]
    assert all(math.isfinite(t) and t >= 0 for t in elapsed)
    assert elapsed == sorted(elapsed)
    assert elapsed[-1] <= record.turn.end_to_end_ms
    stages = [t.stage for t in record.turn.timings]
    assert stages[-1] is VoiceStage.END_TO_END and len(stages) == len(set(stages))
    assert {VoiceStage.REASONING, VoiceStage.REPLY_VALIDATION} <= set(stages)
    assert all(math.isfinite(t.duration_ms) and t.duration_ms >= 0 for t in record.turn.timings)
    in_order = [u.elapsed_ms for u in updates if hasattr(u, "elapsed_ms")]
    assert in_order == sorted(in_order)


# --- State invariants --------------------------------------------------------------------------


def _failing_tts(*_: Any) -> Any:
    async def behavior(*_: Any) -> Any:
        raise SpeechProviderUnavailableError("text-to-speech provider is unavailable")

    return behavior


def test_tts_failure_after_streamed_fragments_is_reported_and_commits_nothing() -> None:
    from voice_builders import CATALOG, heard

    from multimodal_voice_platform.voice import VoiceAssistant

    service, _ = heard(TWO_FACTS, text_to_speech=tts_binding(_failing_tts()))
    streaming = StreamingVoiceCoordinator(VoiceAssistant(CATALOG, speech=service))
    session = streaming.open_session().session_id
    updates = run(_collect(streaming, _request(streaming, session, "turn-1")))
    record = _record(updates)
    assert sum(isinstance(u, ResponseFragmentUpdate) for u in updates) == 2
    assert record.fragments_streamed == 2 and record.response_completed
    assert record.turn.status is TurnStatus.FAILED and not record.committed
    assert record.turn.failed_stage is VoiceStage.TEXT_TO_SPEECH
    assert record.turn.error is not None
    assert record.turn.error.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert not any(isinstance(u, AudioReadyUpdate) for u in updates)
    snapshot = streaming.voice.conversation(session)
    assert snapshot.committed_turns == 0 and snapshot.retained == ()
    assert "after 2 reply fragment(s) were streamed" in record.turn.evidence.summary


def test_invalid_later_fragment_rejects_the_turn_after_partial_output() -> None:
    async def script(request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        view = current_view(request)
        yield ReasoningChunk(provider=REASONER_DOUBLE, text=heard_fragment(view), is_final=False)
        act = ReplyAct(
            kind=ReplyActKind.HEARD,
            statement_id=view.statements[0].statement_id,
            quote="words that were never spoken",
        )
        bad = ReplyFragment(schema_version=1, index=1, act=act, sentence="I heard you.")
        yield ReasoningChunk(provider=REASONER_DOUBLE, text=bad.model_dump_json(), is_final=False)
        yield ReasoningChunk(provider=REASONER_DOUBLE, text="", is_final=True)

    streaming = coordinator(reply=scripted(script), transcripts=["Hello there."])
    session = streaming.open_session().session_id
    updates = run(_collect(streaming, _request(streaming, session, "turn-1")))
    record = _record(updates)
    assert [u.index for u in updates if isinstance(u, ResponseFragmentUpdate)] == [0]
    assert record.fragments_streamed == 1 and not record.response_completed
    assert record.turn.failed_stage is VoiceStage.REPLY_VALIDATION
    assert record.turn.status is TurnStatus.FAILED
    assert streaming.voice.conversation(session).committed_turns == 0


@pytest.mark.parametrize(
    "chunks",
    [
        ["fragment", "fragment-out-of-order", "final"],
        ["fragment", "not-json", "final"],
        ["fragment"],
        ["final", "fragment"],
        ["fragment", "final-with-text"],
        ["misattributed"],
    ],
)
def test_malformed_fragment_streams_fail_safely(chunks: list[str]) -> None:
    from multimodal_voice_platform.contracts.providers import ProviderDescriptor, ProviderPort
    from multimodal_voice_platform.contracts.session import ExecutionMode

    other = ProviderDescriptor(
        provider_id="someone-else", port=ProviderPort.REASONING, mode=ExecutionMode.DETERMINISTIC
    )

    async def script(request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        view = current_view(request)
        for kind in chunks:
            text, final, provider = heard_fragment(view), False, REASONER_DOUBLE
            if kind == "fragment-out-of-order":
                text = heard_fragment(view, index=5)
            elif kind == "not-json":
                text = "{not json"
            elif kind == "final":
                text, final = "", True
            elif kind == "final-with-text":
                final = True
            elif kind == "misattributed":
                provider = other
            yield ReasoningChunk(provider=provider, text=text, is_final=final)

    streaming = coordinator(reply=scripted(script), transcripts=["Hello there."])
    session = streaming.open_session().session_id
    record = _record(run(_collect(streaming, _request(streaming, session, "turn-1"))))
    assert not record.committed
    assert record.turn.error is not None
    assert record.turn.error.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert streaming.voice.conversation(session).committed_turns == 0
    assert streaming.active_turns == 0


def test_too_many_fragments_are_refused() -> None:
    async def script(request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        view = current_view(request)
        for index in range(9):
            text = heard_fragment(view, index=min(index, 7))
            yield ReasoningChunk(provider=REASONER_DOUBLE, text=text, is_final=False)
        yield ReasoningChunk(provider=REASONER_DOUBLE, text="", is_final=True)

    streaming = coordinator(reply=scripted(script), transcripts=["Hello there."])
    session = streaming.open_session().session_id
    record = _record(run(_collect(streaming, _request(streaming, session, "turn-1"))))
    assert not record.committed and record.fragments_streamed <= 8


def test_reasoning_deadline_excludes_consumer_time_but_bounds_the_provider() -> None:
    from multimodal_voice_platform.contracts.limits import ResourceBudget

    async def slow(request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        view = current_view(request)
        yield ReasoningChunk(provider=REASONER_DOUBLE, text=heard_fragment(view), is_final=False)
        await asyncio.sleep(10)
        yield ReasoningChunk(provider=REASONER_DOUBLE, text="", is_final=True)

    streaming = coordinator(reply=scripted(slow), transcripts=["Hello there."])
    streaming.budget = ResourceBudget(request_timeout_s=0.2)
    session = streaming.open_session().session_id
    record = _record(run(_collect(streaming, _request(streaming, session, "turn-1"))))
    assert record.turn.status is TurnStatus.FAILED
    assert record.turn.error is not None and record.turn.error.code is ErrorCode.PROVIDER_TIMEOUT
    assert record.fragments_streamed == 1
    assert record.turn.end_to_end_ms < 5_000


def test_busy_session_rejects_a_concurrent_streamed_turn_without_releasing_the_first() -> None:
    binding, double = gated(gates=1)
    streaming = coordinator(reply=binding, transcripts=[TWO_FACTS, TWO_FACTS])
    session = streaming.open_session().session_id

    async def body() -> None:
        first = streaming.stream_turn(_request(streaming, session, "turn-1"), evidence_class=TEST)
        async for update in first:
            if isinstance(update, ResponseFragmentUpdate):
                break
        second = await _collect(streaming, _request(streaming, session, "turn-2"))
        record = _record(second)
        assert record.turn.failed_stage is VoiceStage.ADMISSION
        assert record.turn.status is TurnStatus.REJECTED
        assert not any(isinstance(u, TurnAcceptedUpdate) for u in second)
        double.gates[0].set()
        assert _record([u async for u in first]).committed

    run(body())


def test_replayed_turn_id_is_rejected_after_commit() -> None:
    streaming = coordinator(transcripts=[TWO_FACTS, TWO_FACTS])
    session = streaming.open_session().session_id
    assert _record(run(_collect(streaming, _request(streaming, session, "turn-1")))).committed
    replay = _record(run(_collect(streaming, _request(streaming, session, "turn-1"))))
    assert replay.turn.failed_stage is VoiceStage.ADMISSION and not replay.committed
    assert replay.turn.error is not None and "already committed" in replay.turn.error.message
    assert streaming.voice.conversation(session).committed_turns == 1


def test_sessions_are_isolated() -> None:
    streaming = coordinator(transcripts=["Please remember that the room is blue.", RECALL])
    one = streaming.open_session().session_id
    two = streaming.open_session().session_id
    assert one != two
    assert _record(run(_collect(streaming, _request(streaming, one, "turn-1")))).committed
    record = _record(run(_collect(streaming, _request(streaming, two, "turn-1"))))
    assert record.committed
    assert record.turn.reply is not None
    assert "blue" not in record.turn.reply.reply
    assert streaming.voice.conversation(two).committed_turns == 1


# --- Cancellation ----------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["aclose", "cancel"])
def test_cancellation_mid_reasoning_releases_the_session_and_commits_nothing(how: str) -> None:
    binding, double = gated(gates=1)
    streaming = coordinator(reply=binding, transcripts=[TWO_FACTS, TWO_FACTS])
    session = streaming.open_session().session_id

    async def body() -> None:
        stream = streaming.stream_turn(_request(streaming, session, "turn-1"), evidence_class=TEST)
        if how == "aclose":
            async for update in stream:
                if isinstance(update, ResponseFragmentUpdate):
                    break
            await stream.aclose()
        else:

            async def consume() -> None:
                async for _ in stream:
                    pass

            task = asyncio.create_task(consume())
            while not double.produced:
                await asyncio.sleep(0)
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert double.cancelled
        assert double.closed, "cancellation reached the reasoning adapter"
        assert streaming.active_turns == 0
        snapshot = streaming.voice.conversation(session)
        assert snapshot.committed_turns == 0 and snapshot.retained == ()
        double.gates[0].set()
        again = await _collect(streaming, _request(streaming, session, "turn-1"))
        assert _record(again).committed, "the cancelled turn ID was never committed"

    run(body())


# --- Configuration and evidence ---------------------------------------------------------------


def test_wiring_and_evidence_are_application_owned() -> None:
    binding, _ = gated()
    streaming = coordinator(reply=binding)
    session = streaming.open_session().session_id

    async def consume(evidence: EvidenceClass) -> None:
        async for _ in streaming.stream_turn(
            _request(streaming, session, "turn-1"), evidence_class=evidence
        ):
            pass

    with pytest.raises(StreamingConfigurationError):
        run(consume(EvidenceClass.DETERMINISTIC_DEMO))
    with pytest.raises(StreamingConfigurationError):
        run(consume(EvidenceClass.LIVE_INTEGRATION))
    with pytest.raises(StreamingConfigurationError):
        IncrementalReplyBinding(
            factory=DeterministicConversationReasoner, processing=ReasoningKind.MODEL_INFERENCE
        )
    with pytest.raises(StreamingConfigurationError):
        run(_collect(streaming, "not a request"))  # type: ignore[arg-type]


def test_unknown_or_non_audio_fixture_is_rejected_safely() -> None:
    streaming = coordinator()
    session = streaming.open_session().session_id

    async def body(fixture: str) -> StreamedTurnRecord:
        updates = [
            u
            async for u in streaming.stream_fixture_turn(
                session, "turn-1", fixture, evidence_class=TEST
            )
        ]
        return _record(updates)

    for fixture in ("no-such-fixture", "image-quadrants"):
        record = run(body(fixture))
        assert record.turn.status is TurnStatus.REJECTED
        assert record.turn.failed_stage is VoiceStage.ADMISSION
        assert record.turn.error is not None
        assert record.turn.error.code is ErrorCode.INPUT_REJECTED
    assert streaming.voice.conversation(session).committed_turns == 0


def test_default_coordinator_produces_deterministic_demo_records_with_tone_audio() -> None:
    streaming = StreamingVoiceCoordinator()
    session = streaming.open_session().session_id
    assert session.startswith("ws-")

    async def body() -> list[Any]:
        return [u async for u in streaming.stream_fixture_turn(session, "turn-1", "voice-remember")]

    record = _record(run(body()))
    assert record.turn.evidence.evidence_class is EvidenceClass.DETERMINISTIC_DEMO
    assert record.turn.evidence.live_provider_executed is False
    assert record.turn.speech_recognition_performed is False
    assert record.turn.speech_synthesis_performed is False
    assert record.turn.model_inference_performed is False
    assert record.turn.live_provider_called is False
    assert record.turn.output_audio is not None
    assert streaming.close_session(session) is not None
    assert streaming.close_session(session) is None


def test_streamed_records_reject_inconsistent_claims() -> None:
    streaming = coordinator(transcripts=[TWO_FACTS])
    session = streaming.open_session().session_id
    record = _record(run(_collect(streaming, _request(streaming, session, "turn-1"))))
    data = record.model_dump()
    data["turn"] = record.turn
    for change in (
        {"fragments_streamed": 0},
        {"response_completed": False},
        {"milestones": tuple(reversed(record.milestones))},
        {"turn": record.turn.model_copy(update={"streaming_performed": False})},
    ):
        with pytest.raises(ValueError):
            StreamedTurnRecord(**{**data, **change})


def test_stored_audio_double_is_reported_as_test_double_tts() -> None:
    from voice_builders import CATALOG, heard

    from multimodal_voice_platform.voice import VoiceAssistant

    service, _ = heard(
        "Hello there.", text_to_speech=tts_binding(stored_audio(TONE_WAV, duration_ms=300))
    )
    streaming = StreamingVoiceCoordinator(VoiceAssistant(CATALOG, speech=service))
    session = streaming.open_session().session_id
    record = _record(run(_collect(streaming, _request(streaming, session, "turn-1"))))
    assert record.committed
    assert record.turn.synthesis is not None
    assert record.turn.synthesis.provider_processing.value == "provider_contract_test_double"
