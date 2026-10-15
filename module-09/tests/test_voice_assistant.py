"""Story 9.6 voice-assistant orchestration, multi-turn conversation, and session-state tests."""

import asyncio
import json
import math

import pytest
from voice_builders import (
    CATALOG,
    TEST,
    TONE_WAV,
    assistant,
    fixture_turn,
    request,
    session,
    small_limits,
    started,
    talking,
    turn,
)

from multimodal_voice_platform.adapters.reasoning import CONVERSATION_REASONER_ID
from multimodal_voice_platform.adapters.speech.tone_synthesis import TONE_TTS_ID
from multimodal_voice_platform.contracts.conversation import ReplyActKind
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import LatencyStage, ResourceBudget
from multimodal_voice_platform.contracts.modality import Modality, TrustLevel
from multimodal_voice_platform.contracts.providers import ProviderPort
from multimodal_voice_platform.contracts.session import ConversationRole, ExecutionMode
from multimodal_voice_platform.crossmodal import ReasoningKind
from multimodal_voice_platform.speech import SpeechProcessingKind, SpeechStatus
from multimodal_voice_platform.voice import (
    PROVIDER_CALLS_PER_TURN,
    ConversationLimitError,
    DuplicateSessionError,
    SessionStatus,
    TurnStatus,
    UnknownSessionError,
    VoiceStage,
    VoiceTurnRecord,
)

REMEMBER = "Please remember that the project code word is falcon."
RECALL = "What is the project code word?"
EXPECTED_STAGES = [
    VoiceStage.ADMISSION,
    VoiceStage.AUDIO_VALIDATION,
    VoiceStage.AUDIO_PROCESSING,
    VoiceStage.SPEECH_TO_TEXT,
    VoiceStage.TRANSCRIPT_VALIDATION,
    VoiceStage.CONTEXT_CONSTRUCTION,
    VoiceStage.REASONING,
    VoiceStage.REPLY_VALIDATION,
    VoiceStage.TEXT_TO_SPEECH,
    VoiceStage.OUTPUT_AUDIO_VALIDATION,
    VoiceStage.STATE_COMMIT,
    VoiceStage.END_TO_END,
]


def _acts(record: VoiceTurnRecord) -> list[ReplyActKind]:
    assert record.reply is not None
    return [act.kind for act in record.reply.acts]


# --- End-to-end turn -------------------------------------------------------------------------


def test_default_turn_runs_every_stage_and_returns_a_typed_committed_record() -> None:
    voice, config = started()
    record = fixture_turn(voice, "turn-1", "voice-remember")
    assert record.status is TurnStatus.COMMITTED and record.committed is True
    assert (record.session_id, record.turn_id, record.sequence) == (config.session_id, "turn-1", 1)
    assert [timing.stage for timing in record.timings] == EXPECTED_STAGES
    audio = record.input_audio
    assert audio is not None and audio.modality is Modality.AUDIO
    assert audio.trust is TrustLevel.UNTRUSTED_EXTERNAL and audio.duration_ms == 1_000
    transcription = record.transcription
    assert transcription is not None and transcription.status is SpeechStatus.SUCCEEDED
    assert transcription.audio is not None and transcription.audio.sample_rate_hz == 8_000
    assert record.transcript is not None
    assert record.transcript.text.endswith(REMEMBER)
    assert record.transcript.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    assert record.transcript.processing is SpeechProcessingKind.FIXTURE_PLAYBACK
    assert record.reasoning_provider is not None
    assert record.reasoning_provider.provider_id == CONVERSATION_REASONER_ID
    assert record.reasoning_kind is ReasoningKind.DETERMINISTIC_RULE_INFERENCE
    assert record.reply is not None
    assert record.reply.reply == "Noted: the project code word is falcon."
    assert _acts(record) == [ReplyActKind.REMEMBERED]
    synthesis = record.synthesis
    assert synthesis is not None and synthesis.status is SpeechStatus.SUCCEEDED
    assert synthesis.provider is not None and synthesis.provider.provider_id == TONE_TTS_ID
    assert synthesis.provider_processing is SpeechProcessingKind.DETERMINISTIC_TONE_SYNTHESIS
    assert synthesis.input is not None and synthesis.input.text == record.reply.reply
    output = record.output_audio
    assert output is not None and output.wav_bytes.startswith(b"RIFF")
    assert synthesis.audio is not None and synthesis.audio.duration_ms == output.audio.duration_ms
    assert record.error is None and record.failed_stage is None


def test_timings_are_finite_non_negative_and_map_onto_latency_stages() -> None:
    voice, _ = started()
    record = fixture_turn(voice, "turn-1", "voice-recall")
    assert all(math.isfinite(t.duration_ms) and t.duration_ms >= 0 for t in record.timings)
    stage_sum = sum(t.duration_ms for t in record.timings if t.stage is not VoiceStage.END_TO_END)
    assert record.end_to_end_ms >= stage_sum * 0.5
    metrics = dict(record.latency_metrics())
    assert set(metrics) == {
        LatencyStage.INGESTION,
        LatencyStage.SPEECH_TO_TEXT,
        LatencyStage.REASONING,
        LatencyStage.TEXT_TO_SPEECH,
        LatencyStage.END_TO_END,
    }
    assert metrics[LatencyStage.END_TO_END] == record.end_to_end_ms


def test_evidence_is_classified_truthfully() -> None:
    voice, _ = started()
    demo = asyncio.run(voice.run_fixture_turn("sess-voice", "turn-1", "voice-remember"))
    assert demo.evidence.evidence_class is EvidenceClass.DETERMINISTIC_DEMO
    assert demo.evidence.story == "9.6"
    assert demo.evidence.execution_mode is ExecutionMode.DETERMINISTIC
    assert demo.evidence.runtime_executed is True and demo.evidence.live_provider_executed is False
    assert set(demo.evidence.requirement_ids) == {
        "SRC-008",
        "SRC-009",
        "SRC-013",
        "SRC-014",
        "SRC-017",
        "ENG-006",
        "ENG-007",
    }
    summary = demo.evidence.summary
    for phrase in (
        "not speech recognition",
        "not model inference",
        "not speech synthesis",
        "nothing was streamed",
    ):
        assert phrase in summary, phrase
    assert demo.speech_recognition_performed is False
    assert demo.speech_synthesis_performed is False
    assert demo.model_inference_performed is False
    assert demo.live_provider_called is False and demo.streaming_performed is False
    for embedded in (demo.transcription, demo.synthesis):
        assert embedded is not None
        assert embedded.evidence.evidence_class is EvidenceClass.DETERMINISTIC_DEMO
        assert embedded.speech_recognition_performed is False
        assert embedded.speech_synthesis_performed is False


def test_turn_records_serialize_for_reviewers_without_raw_audio() -> None:
    voice, _ = started()
    record = fixture_turn(voice, "turn-1", "voice-remember")
    payload = record.model_dump_json()
    data = json.loads(payload)
    assert data["reply"]["reply"] == "Noted: the project code word is falcon."
    assert data["conversation"]["committed_turns"] == 1
    assert data["transcript"]["processing"] == "fixture_playback"
    assert {t["stage"] for t in data["timings"]} == {stage.value for stage in EXPECTED_STAGES}
    assert "wav_bytes" not in payload and "RIFF" not in payload
    assert record.output_audio is not None
    assert record.output_audio.audio_sha256 in payload
    assert "data" not in request("t", TONE_WAV).model_dump()
    assert "data=" not in repr(request("t", TONE_WAV))


# --- Multi-turn conversation ----------------------------------------------------------------


def test_committed_conversation_recalls_what_an_earlier_turn_established() -> None:
    voice, _ = started()
    asked_first = fixture_turn(voice, "turn-1", "voice-recall")
    remembered = fixture_turn(voice, "turn-2", "voice-remember")
    recalled = fixture_turn(voice, "turn-3", "voice-recall")
    assert _acts(asked_first) == [ReplyActKind.NOT_RECALLED]
    assert asked_first.reply is not None
    assert "No earlier turn" in asked_first.reply.reply
    assert _acts(remembered) == [ReplyActKind.REMEMBERED]
    assert _acts(recalled) == [ReplyActKind.RECALLED]
    assert recalled.reply is not None
    assert (
        recalled.reply.reply
        == "Earlier in this conversation you said the project code word is falcon."
    )
    act = recalled.reply.acts[0]
    assert recalled.context is not None and recalled.context.history_exchanges == 2
    assert act.history_index == 2 and act.value == "falcon"
    assert act.history_quote == "remember that the project code word is falcon"
    assert [r.sequence for r in (asked_first, remembered, recalled)] == [1, 2, 3]


def test_state_matters_the_same_audio_without_history_cannot_recall() -> None:
    voice, _ = started()
    fixture_turn(voice, "turn-1", "voice-remember")
    with_history = fixture_turn(voice, "turn-2", "voice-recall")
    fresh, _ = started()
    without_history = fixture_turn(fresh, "turn-1", "voice-recall")
    assert with_history.transcript == without_history.transcript
    assert with_history.input_audio is not None and without_history.input_audio is not None
    assert with_history.input_audio.input_id == without_history.input_audio.input_id
    assert _acts(with_history) == [ReplyActKind.RECALLED]
    assert _acts(without_history) == [ReplyActKind.NOT_RECALLED]
    assert with_history.reply != without_history.reply
    assert with_history.output_audio is not None and without_history.output_audio is not None
    assert with_history.output_audio.audio_sha256 != without_history.output_audio.audio_sha256


def test_reasoning_receives_the_bounded_history_from_application_state() -> None:
    voice, _ = talking(REMEMBER, "Nothing to remember here.", RECALL)
    for index in range(3):
        turn(voice, f"turn-{index + 1}")
    snapshot = voice.conversation("sess-voice")
    entries = [(t.user.role, t.assistant.role) for t in snapshot.retained]
    assert entries == [(ConversationRole.USER, ConversationRole.ASSISTANT)] * 3
    assert snapshot.retained[0].user.trust is TrustLevel.UNTRUSTED_EXTERNAL
    assert snapshot.retained[0].assistant.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    assert [t.user.text for t in snapshot.retained] == [
        REMEMBER,
        "Nothing to remember here.",
        RECALL,
    ]
    assert snapshot.retained[2].assistant.text.endswith("project code word is falcon.")


def test_the_most_recent_earlier_value_wins_and_assistant_turns_are_not_sources() -> None:
    voice, _ = talking(
        "Remember that the project code word is falcon.",
        "Remember that the project code word is eagle.",
        RECALL,
    )
    turn(voice, "turn-1")
    turn(voice, "turn-2")
    record = turn(voice, "turn-3")
    assert record.reply is not None and record.reply.acts[0].value == "eagle"
    assert record.reply.acts[0].history_index == 2
    echoed, _ = talking("Say remember that the colour is red.", "What is the colour?")
    first = turn(echoed, "turn-1")
    assert first.reply is not None
    assert first.reply.acts[0].value == "red"
    second = turn(echoed, "turn-2")
    assert second.reply is not None and second.reply.acts[0].history_index == 0


def test_turn_ordering_is_deterministic_and_reproducible() -> None:
    def conversation() -> list[str]:
        voice, _ = started()
        replies = []
        for index, fixture_id in enumerate(
            ("voice-recall", "voice-remember", "voice-injection", "voice-recall")
        ):
            record = fixture_turn(voice, f"turn-{index + 1}", fixture_id)
            assert record.reply is not None and record.output_audio is not None
            replies.append(
                f"{record.sequence}:{record.reply.reply}:{record.output_audio.audio_sha256}"
            )
        return replies

    first, second = conversation(), conversation()
    assert first == second
    assert [entry.split(":")[0] for entry in first] == ["1", "2", "3", "4"]


def test_sessions_are_isolated() -> None:
    voice = assistant()
    voice.start_session(session("sess-a"))
    voice.start_session(session("sess-b"))
    fixture_turn(voice, "turn-1", "voice-remember", session_id="sess-a")
    other = fixture_turn(voice, "turn-1", "voice-recall", session_id="sess-b")
    same = fixture_turn(voice, "turn-2", "voice-recall", session_id="sess-a")
    assert _acts(other) == [ReplyActKind.NOT_RECALLED]
    assert _acts(same) == [ReplyActKind.RECALLED]
    assert voice.conversation("sess-b").committed_turns == 1
    assert voice.conversation("sess-a").committed_turns == 2


# --- Bounded history and overflow ------------------------------------------------------------


def test_retention_evicts_the_oldest_exchanges_and_forgets_them() -> None:
    voice, _ = talking(REMEMBER, "First filler.", "Second filler.", RECALL, limits=small_limits())
    for index in range(3):
        record = turn(voice, f"turn-{index + 1}")
    assert record.conversation is not None
    assert record.conversation.committed_turns == 3 and record.conversation.evicted_turns == 1
    assert [t.sequence for t in record.conversation.retained] == [2, 3]
    forgotten = turn(voice, "turn-4")
    assert _acts(forgotten) == [ReplyActKind.NOT_RECALLED]
    assert forgotten.context is not None and forgotten.context.history_exchanges == 2


def test_context_window_is_bounded_separately_from_retention() -> None:
    limits = small_limits(max_retained_turns=4, max_context_turns=1)
    voice, _ = talking(REMEMBER, "Filler.", RECALL, limits=limits)
    turn(voice, "turn-1")
    turn(voice, "turn-2")
    record = turn(voice, "turn-3")
    assert record.context is not None
    assert (record.context.history_exchanges, record.context.retained_exchanges) == (1, 2)
    assert _acts(record) == [ReplyActKind.NOT_RECALLED]
    assert voice.conversation("sess-voice").retained[0].user.text == REMEMBER


def test_context_honours_the_session_history_budget_and_character_bound() -> None:
    budget = ResourceBudget(max_history_turns=1)
    voice, _ = talking(REMEMBER, RECALL, session_config=session(budget=budget))
    turn(voice, "turn-1")
    record = turn(voice, "turn-2")
    assert record.context is not None and record.context.history_entries == 0
    assert _acts(record) == [ReplyActKind.NOT_RECALLED]
    tight = small_limits(max_context_chars=40)
    voice, _ = talking(REMEMBER, RECALL, limits=tight)
    turn(voice, "turn-1")
    record = turn(voice, "turn-2")
    assert record.context is not None and record.context.history_exchanges == 0


def test_retention_is_bounded_by_characters() -> None:
    limits = small_limits(
        max_retained_turns=6,
        max_context_turns=2,
        max_history_chars=1_200,
        max_context_chars=1_000,
        max_transcript_chars=600,
        max_reply_chars=600,
    )
    voice, _ = talking("a" * 500, "b" * 500, "c" * 500, limits=limits)
    for index in range(3):
        record = turn(voice, f"turn-{index + 1}")
    snapshot = record.conversation
    assert snapshot is not None
    assert snapshot.retained_chars <= 1_200 and snapshot.evicted_turns >= 1


# --- Session lifecycle, replay, and budgets ---------------------------------------------------


def test_duplicate_turn_ids_are_rejected_without_re_execution() -> None:
    voice, _ = talking(REMEMBER, RECALL)
    first = turn(voice, "turn-1")
    replay = turn(voice, "turn-1")
    assert first.committed is True
    assert replay.status is TurnStatus.REJECTED and replay.committed is False
    assert replay.failed_stage is VoiceStage.ADMISSION
    assert replay.error is not None and replay.error.code is ErrorCode.INPUT_REJECTED
    assert replay.transcription is None
    assert voice.conversation("sess-voice").committed_turns == 1


def test_concurrent_turns_on_one_session_are_serialized_by_rejection() -> None:
    voice, _ = talking(REMEMBER, RECALL)

    async def both() -> list[VoiceTurnRecord]:
        return list(
            await asyncio.gather(
                voice.run_turn(request("turn-1"), evidence_class=TEST),
                voice.run_turn(request("turn-2"), evidence_class=TEST),
            )
        )

    records = asyncio.run(both())
    statuses = sorted(record.status for record in records)
    assert statuses == [TurnStatus.COMMITTED, TurnStatus.REJECTED]
    rejected = next(r for r in records if not r.committed)
    assert rejected.error is not None and "still running" in rejected.error.message
    assert voice.conversation("sess-voice").committed_turns == 1
    assert turn(voice, "turn-3").committed is True


def test_unknown_closed_and_duplicate_sessions_are_rejected() -> None:
    voice, config = started()
    with pytest.raises(DuplicateSessionError):
        voice.start_session(config)
    unknown = turn(voice, "turn-1", session_id="sess-unknown")
    assert unknown.status is TurnStatus.REJECTED
    assert unknown.conversation is None and unknown.failed_stage is VoiceStage.ADMISSION
    fixture_turn(voice, "turn-1", "voice-remember")
    closed = voice.end_session(config.session_id)
    assert closed.status is SessionStatus.CLOSED
    assert closed.retained == () and closed.committed_turns == 1
    after = fixture_turn(voice, "turn-2", "voice-recall")
    assert after.status is TurnStatus.REJECTED and after.conversation is None
    with pytest.raises(UnknownSessionError):
        voice.end_session(config.session_id)
    voice.start_session(config)
    reopened = fixture_turn(voice, "turn-2", "voice-recall")
    assert _acts(reopened) == [ReplyActKind.NOT_RECALLED]


def test_turn_and_active_session_limits_are_enforced() -> None:
    voice, _ = talking(REMEMBER, RECALL, RECALL, limits=small_limits(max_turns_per_session=2))
    assert turn(voice, "turn-1").committed and turn(voice, "turn-2").committed
    limited = turn(voice, "turn-3")
    assert limited.error is not None and limited.error.code is ErrorCode.LIMIT_EXCEEDED
    few = assistant(limits=small_limits(max_active_sessions=1))
    few.start_session(session("sess-a"))
    with pytest.raises(ConversationLimitError):
        few.start_session(session("sess-b"))
    few.end_session("sess-a")
    few.start_session(session("sess-b"))


def test_provider_call_budget_is_reserved_per_turn_and_never_refunded() -> None:
    budget = ResourceBudget(
        max_provider_calls_per_session=2 * PROVIDER_CALLS_PER_TURN, max_retries=1
    )
    voice, _ = talking(REMEMBER, RECALL, session_config=session(budget=budget))
    failed = turn(voice, "turn-1", b"not audio at all")
    assert failed.committed is False
    assert voice.conversation("sess-voice").provider_calls_reserved == PROVIDER_CALLS_PER_TURN
    assert turn(voice, "turn-2").committed is True
    exhausted = turn(voice, "turn-3")
    assert exhausted.error is not None and exhausted.error.code is ErrorCode.BUDGET_EXHAUSTED
    assert exhausted.transcription is None
    snapshot = voice.conversation("sess-voice")
    assert snapshot.provider_calls_reserved == snapshot.provider_call_budget


def test_expired_sessions_are_closed_and_rejected() -> None:
    now = [0.0]
    budget = ResourceBudget(session_timeout_s=60.0)
    voice = assistant(clock=lambda: now[0])
    voice.start_session(session(budget=budget))
    assert fixture_turn(voice, "turn-1", "voice-remember").committed
    now[0] = 61.0
    expired = fixture_turn(voice, "turn-2", "voice-recall")
    assert expired.status is TurnStatus.REJECTED
    assert expired.error is not None and expired.error.code is ErrorCode.LIMIT_EXCEEDED
    assert expired.conversation is None
    with pytest.raises(UnknownSessionError):
        voice.conversation("sess-voice")


def test_fixture_turns_require_audio_fixtures() -> None:
    voice, _ = started()
    from multimodal_voice_platform.voice import VoiceConfigurationError

    with pytest.raises(VoiceConfigurationError):
        fixture_turn(voice, "turn-1", "text-brief")
    assert CATALOG.get("voice-remember").modality is Modality.AUDIO
    assert voice.conversation("sess-voice").committed_turns == 0
    assert ProviderPort.REASONING.value == "reasoning"
