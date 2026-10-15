"""Story 9.6 failure and transaction semantics: a failed turn never changes conversation history.

Every scenario first commits one good exchange, then fails a turn at one precise stage, and checks
that the record is safe and uncommitted, that history is exactly as it was, that the reserved
provider calls stay spent, and that the session accepts the next turn.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from voice_builders import (
    REASONER_DOUBLE,
    TEST,
    TONE_WAV,
    assistant,
    heard,
    reasoning_double,
    request,
    session,
    small_limits,
    started,
    stored_audio,
    streams,
    talking,
    tts_binding,
    turn,
)

from multimodal_voice_platform.adapters.reasoning import DeterministicConversationReasoner
from multimodal_voice_platform.audio.errors import MalformedAudioError
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    ReasoningChunk,
    ReasoningRequest,
    TranscriptionRequest,
    TranscriptSegment,
)
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.crossmodal import (
    CrossModalConfigurationError,
    ReasoningBinding,
    ReasoningKind,
    ReasoningProviderUnavailableError,
)
from multimodal_voice_platform.speech import (
    SpeechProcessingKind,
    SpeechProviderUnavailableError,
    SpeechService,
    SpeechStatus,
    SpeechToTextBinding,
)
from multimodal_voice_platform.voice import (
    PROVIDER_CALLS_PER_TURN,
    TurnStatus,
    VoiceAssistant,
    VoiceConfigurationError,
    VoiceStage,
    VoiceTurnRecord,
)

GOOD = "Remember that the project code word is falcon."
HELLO = "Hello there."


def _assert_isolated_failure(
    voice: VoiceAssistant,
    record: VoiceTurnRecord,
    stage: VoiceStage,
    code: ErrorCode,
    *,
    before_retained: tuple[Any, ...],
    before_version: int,
) -> None:
    assert record.status in {TurnStatus.REJECTED, TurnStatus.FAILED}
    assert record.committed is False and record.sequence is None
    assert record.failed_stage is stage
    assert record.error is not None and record.error.code is code
    assert len(record.error.message) <= 300
    assert record.timings[-1].stage is VoiceStage.END_TO_END
    after = voice.conversation("sess-voice")
    assert after.retained == before_retained and after.version == before_version
    assert after.committed_turns == len(before_retained)
    assert after.provider_calls_reserved == 2 * PROVIDER_CALLS_PER_TURN
    assert record.conversation == after


def _primed(voice: VoiceAssistant) -> tuple[tuple[Any, ...], int]:
    first = turn(voice, "turn-1")
    assert first.committed, first.error
    snapshot = voice.conversation("sess-voice")
    return snapshot.retained, snapshot.version


# --- Audio, speech-to-text, and transcript stages ---------------------------------------------


@pytest.mark.parametrize(
    ("data", "media_type", "name", "code"),
    [
        (b"not audio at all", "audio/wav", "turn.wav", ErrorCode.INPUT_REJECTED),
        (b"ID3" + bytes(64), "audio/mpeg", "turn.mp3", ErrorCode.UNSUPPORTED_MODALITY),
        (TONE_WAV, "audio/wav", "../turn.wav", ErrorCode.INPUT_REJECTED),
    ],
)
def test_audio_validation_failures_leave_history_unchanged(
    data: bytes, media_type: str, name: str, code: ErrorCode
) -> None:
    voice, _ = talking(GOOD, HELLO)
    retained, version = _primed(voice)
    record = turn(voice, "turn-2", data, media_type=media_type, name=name)
    _assert_isolated_failure(
        voice,
        record,
        VoiceStage.AUDIO_VALIDATION,
        code,
        before_retained=retained,
        before_version=version,
    )
    assert record.transcript is None and record.reply is None and record.synthesis is None
    assert turn(voice, "turn-3").committed


def test_audio_processing_failure_leaves_history_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    voice, _ = talking(GOOD, HELLO)
    retained, version = _primed(voice)

    def malformed(*_: Any) -> Any:
        raise MalformedAudioError("audio data is malformed")

    monkeypatch.setattr("multimodal_voice_platform.speech.service.analyze_wav", malformed)
    record = turn(voice, "turn-2")
    monkeypatch.undo()
    _assert_isolated_failure(
        voice,
        record,
        VoiceStage.AUDIO_PROCESSING,
        ErrorCode.INPUT_REJECTED,
        before_retained=retained,
        before_version=version,
    )
    assert record.input_audio is not None and record.transcript is None
    assert turn(voice, "turn-3").committed


class _FlakySpeechToText:
    """STT double: first call hears a transcript, later calls misbehave as scripted."""

    def __init__(self, behavior: Callable[[TranscriptionRequest], AsyncIterator[Any]]) -> None:
        self.behavior = behavior
        self.calls = 0
        self._descriptor = ProviderDescriptor(
            provider_id="test-double-stt",
            port=ProviderPort.SPEECH_TO_TEXT,
            mode=ExecutionMode.DETERMINISTIC,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def transcribe(self, request: TranscriptionRequest) -> AsyncIterator[Any]:
        self.calls += 1
        if self.calls == 1 or self.calls == 3:
            return self._say(GOOD if self.calls == 1 else HELLO, request)
        return self.behavior(request)

    async def _say(self, text: str, request: TranscriptionRequest) -> AsyncIterator[Any]:
        yield TranscriptSegment(
            provider=self._descriptor,
            text=text,
            is_final=True,
            start_ms=0,
            end_ms=request.audio.duration_ms or 1,
        )


async def _stt_unavailable(_: TranscriptionRequest) -> AsyncIterator[Any]:
    raise SpeechProviderUnavailableError("speech-to-text provider is unavailable")
    yield  # pragma: no cover


async def _stt_never_final(request: TranscriptionRequest) -> AsyncIterator[Any]:
    yield TranscriptSegment(
        provider=ProviderDescriptor(
            provider_id="test-double-stt",
            port=ProviderPort.SPEECH_TO_TEXT,
            mode=ExecutionMode.DETERMINISTIC,
        ),
        text="partial only",
        is_final=False,
        start_ms=0,
        end_ms=request.audio.duration_ms or 1,
    )


async def _stt_wrong_provider(request: TranscriptionRequest) -> AsyncIterator[Any]:
    yield TranscriptSegment(
        provider=REASONER_DOUBLE.model_copy(update={"port": ProviderPort.SPEECH_TO_TEXT}),
        text="I am someone else",
        is_final=True,
        start_ms=0,
        end_ms=request.audio.duration_ms or 1,
    )


@pytest.mark.parametrize(
    ("behavior", "status", "retryable"),
    [
        (_stt_unavailable, TurnStatus.FAILED, True),
        (_stt_never_final, TurnStatus.FAILED, False),
        (_stt_wrong_provider, TurnStatus.FAILED, False),
    ],
)
def test_speech_to_text_failures_leave_history_unchanged(
    behavior: Callable[[TranscriptionRequest], AsyncIterator[Any]],
    status: TurnStatus,
    retryable: bool,
) -> None:
    double = _FlakySpeechToText(behavior)
    service = SpeechService(
        speech_to_text=SpeechToTextBinding(
            lambda _: double, SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
        )
    )
    voice, _ = started(speech=service)
    retained, version = _primed(voice)
    record = turn(voice, "turn-2")
    _assert_isolated_failure(
        voice,
        record,
        VoiceStage.SPEECH_TO_TEXT,
        ErrorCode.PROVIDER_UNAVAILABLE,
        before_retained=retained,
        before_version=version,
    )
    assert record.status is status and record.error is not None
    assert record.error.retryable is retryable
    assert (
        record.transcription is not None
        and record.transcription.status is not SpeechStatus.SUCCEEDED
    )
    assert turn(voice, "turn-3").committed


def test_fixture_playback_rejects_audio_it_has_no_script_for() -> None:
    voice, _ = started()
    record = turn(voice, "turn-1")
    assert record.status is TurnStatus.REJECTED
    assert record.failed_stage is VoiceStage.SPEECH_TO_TEXT
    assert voice.conversation("sess-voice").committed_turns == 0


@pytest.mark.parametrize(
    "transcript",
    ["   ", "bell \x07 character", "x" * 81],
)
def test_unsafe_or_oversized_transcripts_are_rejected_before_reasoning(transcript: str) -> None:
    voice, _ = talking(GOOD, transcript, HELLO, limits=small_limits(max_transcript_chars=80))
    retained, version = _primed(voice)
    record = turn(voice, "turn-2")
    _assert_isolated_failure(
        voice,
        record,
        VoiceStage.TRANSCRIPT_VALIDATION,
        ErrorCode.INPUT_REJECTED,
        before_retained=retained,
        before_version=version,
    )
    assert record.transcript is None and record.context is None
    assert record.reasoning_provider is None
    assert turn(voice, "turn-3").committed


# --- Reasoning and reply validation --------------------------------------------------------------


def _then(misbehave: Callable[[ReasoningRequest], AsyncIterator[Any]]) -> Callable[..., Any]:
    """Reason honestly on the first call, then misbehave."""
    real = DeterministicConversationReasoner()
    calls = [0]

    def script(request: ReasoningRequest) -> AsyncIterator[Any]:
        calls[0] += 1
        if calls[0] == 1 or calls[0] == 3:
            return _relabel(real.stream_reason(request))
        return misbehave(request)

    return script


async def _relabel(stream: AsyncIterator[ReasoningChunk]) -> AsyncIterator[ReasoningChunk]:
    async for chunk in stream:
        yield chunk.model_copy(update={"provider": REASONER_DOUBLE})


async def _reasoner_unavailable(_: ReasoningRequest) -> AsyncIterator[Any]:
    raise ReasoningProviderUnavailableError("reasoning provider is unavailable")
    yield  # pragma: no cover


async def _reasoner_hangs(_: ReasoningRequest) -> AsyncIterator[Any]:
    await asyncio.sleep(30)
    yield  # pragma: no cover


async def _reasoner_misattributed(_: ReasoningRequest) -> AsyncIterator[Any]:
    yield ReasoningChunk(
        provider=REASONER_DOUBLE.model_copy(update={"provider_id": "impostor"}),
        text="{}",
        is_final=True,
    )


def _reply(**fields: Any) -> str:
    import json

    document = {
        "schema_version": 1,
        "reply": "Hello.",
        "acts": [{"kind": "heard", "statement_id": "obs-1-s1", "quote": HELLO}],
    }
    document.update(fields)
    return json.dumps(document)


@pytest.mark.parametrize(
    ("misbehave", "stage", "code", "status"),
    [
        (_reasoner_unavailable, VoiceStage.REASONING, ErrorCode.PROVIDER_UNAVAILABLE, "failed"),
        (_reasoner_hangs, VoiceStage.REASONING, ErrorCode.PROVIDER_TIMEOUT, "failed"),
        (_reasoner_misattributed, VoiceStage.REASONING, ErrorCode.PROVIDER_UNAVAILABLE, "failed"),
        (
            streams(_reply(), final=False),
            VoiceStage.REASONING,
            ErrorCode.PROVIDER_UNAVAILABLE,
            "failed",
        ),
        (
            streams("not json"),
            VoiceStage.REPLY_VALIDATION,
            ErrorCode.PROVIDER_UNAVAILABLE,
            "failed",
        ),
        (
            streams(_reply(grant="admin", mode="live")),
            VoiceStage.REPLY_VALIDATION,
            ErrorCode.PROVIDER_UNAVAILABLE,
            "failed",
        ),
        (
            streams(_reply(acts=[{"kind": "heard", "statement_id": "obs-1-s9", "quote": HELLO}])),
            VoiceStage.REPLY_VALIDATION,
            ErrorCode.PROVIDER_UNAVAILABLE,
            "failed",
        ),
        (
            streams(
                _reply(acts=[{"kind": "heard", "statement_id": "obs-1-s1", "quote": "Goodbye."}])
            ),
            VoiceStage.REPLY_VALIDATION,
            ErrorCode.PROVIDER_UNAVAILABLE,
            "failed",
        ),
        (
            streams(_reply(reply="x" * 601)),
            VoiceStage.REPLY_VALIDATION,
            ErrorCode.LIMIT_EXCEEDED,
            "rejected",
        ),
        (
            streams(_reply(reply="Hello \x07 there.")),
            VoiceStage.TEXT_TO_SPEECH,
            ErrorCode.INPUT_REJECTED,
            "rejected",
        ),
    ],
)
def test_reasoning_and_reply_failures_leave_history_unchanged(
    misbehave: Callable[[ReasoningRequest], AsyncIterator[Any]],
    stage: VoiceStage,
    code: ErrorCode,
    status: str,
) -> None:
    binding, _ = reasoning_double(_then(misbehave))
    budget = ResourceBudget(request_timeout_s=0.2)
    voice, _ = talking(
        GOOD,
        HELLO,
        HELLO,
        reasoning=binding,
        session_config=session(budget=budget),
    )
    retained, version = _primed(voice)
    record = turn(voice, "turn-2")
    _assert_isolated_failure(
        voice, record, stage, code, before_retained=retained, before_version=version
    )
    assert record.status.value == status
    assert record.transcript is not None and record.context is not None
    assert record.reasoning_kind is ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
    assert turn(voice, "turn-3").committed


def test_recalled_values_must_cite_real_user_history() -> None:
    forged_history = _reply(
        reply="You said the code word is owl.",
        acts=[
            {
                "kind": "recalled",
                "statement_id": "obs-1-s1",
                "quote": "What is the code word?",
                "slot": "code word",
                "value": "owl",
                "history_index": 0,
                "history_quote": "remember that the code word is owl",
            }
        ],
    )
    binding, _ = reasoning_double(_then(streams(forged_history)))
    voice, _ = talking(GOOD, "What is the code word?", HELLO, reasoning=binding)
    retained, version = _primed(voice)
    record = turn(voice, "turn-2")
    _assert_isolated_failure(
        voice,
        record,
        VoiceStage.REPLY_VALIDATION,
        ErrorCode.PROVIDER_UNAVAILABLE,
        before_retained=retained,
        before_version=version,
    )


# --- Text-to-speech, output audio, and state commit ------------------------------------------


async def _tts_unavailable(*_: Any) -> Any:
    raise SpeechProviderUnavailableError("text-to-speech provider is unavailable")


def _tts_after_first(
    failing: Callable[..., Any],
) -> Callable[..., Any]:
    good = stored_audio(TONE_WAV, duration_ms=300)
    calls = [0]

    async def behavior(store: Any, req: Any) -> Any:
        calls[0] += 1
        if calls[0] == 2:
            return await failing(store, req)
        return await good(store, req)

    return behavior


@pytest.mark.parametrize(
    ("failing", "stage", "status"),
    [
        (_tts_unavailable, VoiceStage.TEXT_TO_SPEECH, TurnStatus.FAILED),
        (
            stored_audio(b"RIFF" + bytes(40), duration_ms=300),
            VoiceStage.OUTPUT_AUDIO_VALIDATION,
            TurnStatus.FAILED,
        ),
        (
            stored_audio(TONE_WAV, duration_ms=900),
            VoiceStage.OUTPUT_AUDIO_VALIDATION,
            TurnStatus.FAILED,
        ),
    ],
)
def test_speech_output_failures_leave_history_unchanged(
    failing: Callable[..., Any], stage: VoiceStage, status: TurnStatus
) -> None:
    voice, _ = talking(GOOD, HELLO, HELLO, text_to_speech=tts_binding(_tts_after_first(failing)))
    retained, version = _primed(voice)
    record = turn(voice, "turn-2")
    _assert_isolated_failure(
        voice,
        record,
        stage,
        ErrorCode.PROVIDER_UNAVAILABLE,
        before_retained=retained,
        before_version=version,
    )
    assert record.status is status
    assert record.reply is not None and record.output_audio is None
    assert turn(voice, "turn-3").committed


def test_state_commit_fails_safely_when_the_session_closes_mid_turn() -> None:
    holder: dict[str, VoiceAssistant] = {}
    real = DeterministicConversationReasoner()

    def script(request: ReasoningRequest) -> AsyncIterator[Any]:
        holder["voice"].end_session(request.session_id)
        return _relabel(real.stream_reason(request))

    binding, _ = reasoning_double(script)
    voice, _ = talking(GOOD, reasoning=binding)
    holder["voice"] = voice
    record = turn(voice, "turn-1")
    assert record.status is TurnStatus.FAILED and record.committed is False
    assert record.failed_stage is VoiceStage.STATE_COMMIT
    assert record.error is not None and record.error.code is ErrorCode.INTERNAL_ERROR
    assert record.synthesis is not None and record.synthesis.status is SpeechStatus.SUCCEEDED
    assert record.conversation is None


def test_unexpected_provider_exceptions_propagate_and_release_the_session() -> None:
    async def defect(_: ReasoningRequest) -> AsyncIterator[Any]:
        raise RuntimeError("adapter defect")
        yield  # pragma: no cover

    binding, _ = reasoning_double(_then(defect))
    voice, _ = talking(GOOD, HELLO, HELLO, reasoning=binding)
    retained, version = _primed(voice)
    with pytest.raises(RuntimeError, match="adapter defect"):
        turn(voice, "turn-2")
    after = voice.conversation("sess-voice")
    assert after.retained == retained and after.version == version
    assert turn(voice, "turn-3").committed


# --- Configuration defects are raised, not recorded ------------------------------------------


def test_wiring_and_evidence_misuse_is_raised_not_recorded() -> None:
    voice, _ = started()
    with pytest.raises(VoiceConfigurationError):
        asyncio.run(
            voice.run_fixture_turn(
                "sess-voice", "t", "voice-remember", evidence_class=EvidenceClass.LIVE_INTEGRATION
            )
        )
    binding, _ = reasoning_double(streams(_reply()))
    doubled = assistant(reasoning=binding)
    doubled.start_session(session())
    with pytest.raises(VoiceConfigurationError, match="automated_test"):
        asyncio.run(doubled.run_fixture_turn("sess-voice", "t", "voice-remember"))
    live = REASONER_DOUBLE.model_copy(update={"mode": ExecutionMode.LIVE})
    live_binding, _ = reasoning_double(streams(_reply()), live)
    pretender = assistant(reasoning=live_binding)
    pretender.start_session(session())
    with pytest.raises(VoiceConfigurationError, match="deterministic"):
        asyncio.run(pretender.run_turn(request("t"), evidence_class=TEST))
    with pytest.raises(CrossModalConfigurationError):
        ReasoningBinding(
            factory=DeterministicConversationReasoner, processing=ReasoningKind.MODEL_INFERENCE
        )
    with pytest.raises(VoiceConfigurationError):
        asyncio.run(voice.run_turn({"session_id": "sess-voice"}, evidence_class=TEST))  # type: ignore[arg-type]
    service, _ = heard(HELLO)
    demo = assistant(speech=service)
    demo.start_session(session())
    with pytest.raises(Exception, match="automated_test"):
        asyncio.run(demo.run_turn(request("t")))
    for each in (voice, doubled, pretender, demo):
        assert each.conversation("sess-voice").committed_turns == 0
    assert turn(demo, "after").committed is True
