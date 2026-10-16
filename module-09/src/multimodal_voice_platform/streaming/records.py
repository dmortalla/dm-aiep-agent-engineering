"""Progress updates and the reviewer-displayable record of one streamed voice turn (Story 9.7).

The coordinator yields one ``TurnUpdate`` each time a stage produces something observable, in the
order it happens. The last update of every turn is ``TurnFinished`` with a ``StreamedTurnRecord``.
Every ``elapsed_ms`` is wall-clock time since the coordinator began the turn; it is a local
measurement, not a service-level objective.

A ``StreamedTurnRecord`` wraps the Story 9.6 ``VoiceTurnRecord`` (with ``streaming_performed`` set
and Story 9.7 evidence) and adds what streaming changed: how many response fragments were produced
before the reply was complete, whether the response completed, and when each milestone occurred.
"""

from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.contracts.conversation import MAX_REPLY_ACTS, MAX_REPLY_CHARS
from multimodal_voice_platform.contracts.limits import MAX_AUDIO_BYTES, MAX_AUDIO_DURATION_MS
from multimodal_voice_platform.contracts.modality import Identifier
from multimodal_voice_platform.speech.records import SpeechProcessingKind
from multimodal_voice_platform.voice.records import TurnStatus, VoiceStage, VoiceTurnRecord

_ELAPSED: Final = {"ge": 0, "le": 3_600_000, "allow_inf_nan": False}


class StreamMilestone(StrEnum):
    """Observable points of a streamed turn, in the only order they can occur."""

    TURN_ACCEPTED = "turn_accepted"
    TRANSCRIPT_READY = "transcript_ready"
    FIRST_RESPONSE = "first_response"
    RESPONSE_COMPLETE = "response_complete"
    AUDIO_READY = "audio_ready"


_ORDER: Final = tuple(StreamMilestone)


class MilestoneTiming(BaseModel):
    """When one milestone occurred, relative to the start of the turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    milestone: StreamMilestone
    elapsed_ms: float = Field(**_ELAPSED)


class _Update(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: Identifier


class TurnAcceptedUpdate(_Update):
    """The turn passed admission and holds the session."""

    kind: Literal["turn_accepted"] = "turn_accepted"
    elapsed_ms: float = Field(**_ELAPSED)


class StageTimedUpdate(_Update):
    """A pipeline stage finished; its measured duration."""

    kind: Literal["stage_timed"] = "stage_timed"
    stage: VoiceStage
    duration_ms: float = Field(**_ELAPSED)


class TranscriptReadyUpdate(_Update):
    """The final transcript passed validation. Untrusted data, never instructions."""

    kind: Literal["transcript_ready"] = "transcript_ready"
    text: str = Field(min_length=1)
    processing: SpeechProcessingKind
    elapsed_ms: float = Field(**_ELAPSED)


class ResponseFragmentUpdate(_Update):
    """One validated reply fragment, produced before the reply as a whole exists."""

    kind: Literal["response_fragment"] = "response_fragment"
    index: int = Field(ge=0, lt=MAX_REPLY_ACTS)
    text: str = Field(min_length=1, max_length=MAX_REPLY_CHARS)
    elapsed_ms: float = Field(**_ELAPSED)


class ResponseCompletedUpdate(_Update):
    """Every fragment arrived and the assembled reply passed validation."""

    kind: Literal["response_completed"] = "response_completed"
    fragment_count: int = Field(ge=1, le=MAX_REPLY_ACTS)
    elapsed_ms: float = Field(**_ELAPSED)


class AudioReadyUpdate(_Update):
    """The reply's generated audio passed validation. Tone audio by default, not speech."""

    kind: Literal["audio_ready"] = "audio_ready"
    audio_ref: Identifier
    media_type: str
    duration_ms: int = Field(gt=0, le=MAX_AUDIO_DURATION_MS)
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=MAX_AUDIO_BYTES)
    elapsed_ms: float = Field(**_ELAPSED)


class StreamedTurnRecord(BaseModel):
    """Typed record of one streamed voice turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn: VoiceTurnRecord
    fragments_streamed: int = Field(ge=0, le=MAX_REPLY_ACTS)
    response_completed: bool
    milestones: tuple[MilestoneTiming, ...] = Field(max_length=len(StreamMilestone))

    @property
    def committed(self) -> bool:
        """Whether the turn committed to conversation state."""
        return self.turn.committed

    @property
    def time_to_first_response_ms(self) -> float | None:
        """Time from the start of the turn to its first response fragment, if one was produced."""
        return self._elapsed(StreamMilestone.FIRST_RESPONSE)

    def _elapsed(self, milestone: StreamMilestone) -> float | None:
        return next((m.elapsed_ms for m in self.milestones if m.milestone is milestone), None)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        """Keep milestones ordered and consistent with what the turn actually produced.

        Returns:
            The validated record.

        Raises:
            ValueError: If milestones are out of order, after the turn ended, or contradict the
                fragments, the response, the output audio, or the commit state.
        """
        turn = self.turn
        if not turn.streaming_performed:
            raise ValueError("a streamed turn record wraps a streamed voice turn")
        names = [m.milestone for m in self.milestones]
        if names != [name for name in _ORDER if name in names]:
            raise ValueError("milestones occur once each, in pipeline order")
        times = [m.elapsed_ms for m in self.milestones]
        if times != sorted(times) or any(t > turn.end_to_end_ms for t in times):
            raise ValueError("milestones are non-decreasing and within the turn")
        present = set(names)
        if (StreamMilestone.FIRST_RESPONSE in present) != (self.fragments_streamed > 0):
            raise ValueError("first_response is recorded exactly when a fragment was streamed")
        if (StreamMilestone.RESPONSE_COMPLETE in present) != self.response_completed:
            raise ValueError("response_complete is recorded exactly when the response completed")
        if self.response_completed and turn.reply is None:
            raise ValueError("a completed response carries the validated reply")
        if (StreamMilestone.TRANSCRIPT_READY in present) != (turn.transcript is not None):
            raise ValueError("transcript_ready is recorded exactly when a transcript was accepted")
        audio = turn.output_audio is not None
        if (StreamMilestone.AUDIO_READY in present) != audio:
            raise ValueError("audio_ready is recorded exactly when output audio was validated")
        admitted = turn.failed_stage is not VoiceStage.ADMISSION
        if (StreamMilestone.TURN_ACCEPTED in present) != admitted:
            raise ValueError("turn_accepted is recorded exactly when the turn passed admission")
        if turn.status is TurnStatus.COMMITTED and not (self.response_completed and audio):
            raise ValueError("a committed streamed turn completed its response and audio")
        if turn.reply is not None and self.fragments_streamed != len(turn.reply.acts):
            raise ValueError("a completed reply was streamed as one fragment per act")
        return self


class TurnFinished(_Update):
    """The turn ended. Always the last update."""

    kind: Literal["turn_finished"] = "turn_finished"
    record: StreamedTurnRecord


TurnUpdate = (
    TurnAcceptedUpdate
    | StageTimedUpdate
    | TranscriptReadyUpdate
    | ResponseFragmentUpdate
    | ResponseCompletedUpdate
    | AudioReadyUpdate
    | TurnFinished
)
