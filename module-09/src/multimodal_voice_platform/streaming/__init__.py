"""Streaming coordination for real-time voice turns (Story 9.7).

``StreamingVoiceCoordinator`` runs the accepted Story 9.6 voice turn stage by stage and yields a
typed update as each stage produces something observable: admission, stage timings, the final
transcript, each validated reply fragment while reasoning is still running, the completed reply,
validated output audio, and the turn record. It has no transport code; the WebSocket gateway in
``interface/`` carries its updates as protocol events.

The default reply adapter is rule-based conversation reasoning (not model inference) whose
fragments are whole reply acts (not model tokens); speech-to-text is fixture playback (not speech
recognition) and text-to-speech is a tone sequence (not speech synthesis).
"""

from multimodal_voice_platform.streaming.coordinator import (
    IncrementalReplyBinding,
    StreamingVoiceCoordinator,
)
from multimodal_voice_platform.streaming.errors import (
    StreamingConfigurationError,
    StreamingInputError,
)
from multimodal_voice_platform.streaming.limits import StreamingLimits
from multimodal_voice_platform.streaming.records import (
    AudioReadyUpdate,
    MilestoneTiming,
    ResponseCompletedUpdate,
    ResponseFragmentUpdate,
    StageTimedUpdate,
    StreamedTurnRecord,
    StreamMilestone,
    TranscriptReadyUpdate,
    TurnAcceptedUpdate,
    TurnFinished,
    TurnUpdate,
)

__all__ = [
    "AudioReadyUpdate",
    "IncrementalReplyBinding",
    "MilestoneTiming",
    "ResponseCompletedUpdate",
    "ResponseFragmentUpdate",
    "StageTimedUpdate",
    "StreamMilestone",
    "StreamedTurnRecord",
    "StreamingConfigurationError",
    "StreamingInputError",
    "StreamingLimits",
    "StreamingVoiceCoordinator",
    "TranscriptReadyUpdate",
    "TurnAcceptedUpdate",
    "TurnFinished",
    "TurnUpdate",
]
