"""Voice-enabled assistant: orchestration and bounded conversation state (Story 9.6).

``VoiceAssistant`` runs complete, synchronous voice turns (validated audio, local audio processing,
speech-to-text, transcript validation, bounded conversational context, reasoning, reply validation,
text-to-speech, generated-audio validation, and an atomic state commit) through the accepted ports
and Story 9.4 and 9.5 components, and returns a typed ``VoiceTurnRecord`` for every outcome. The
default adapters are fixture-playback STT (not speech recognition), rule-based conversational
reasoning (not model inference), and tone-sequence TTS (not speech synthesis). Nothing is streamed.
"""

from multimodal_voice_platform.voice.errors import (
    ConversationLimitError,
    DuplicateSessionError,
    DuplicateTurnError,
    LiveVoiceUnavailableError,
    ReplyRejectedError,
    SessionBusyError,
    SessionExpiredError,
    StateCommitError,
    TranscriptRejectedError,
    TurnBudgetExhaustedError,
    UnknownSessionError,
    VoiceConfigurationError,
    VoiceSessionError,
)
from multimodal_voice_platform.voice.fixtures import VOICE_FIXTURE_IDS, load_voice_catalog
from multimodal_voice_platform.voice.limits import PROVIDER_CALLS_PER_TURN, VoiceLimits
from multimodal_voice_platform.voice.orchestrator import (
    VOICE_ASSISTANT_TASK,
    VoiceAssistant,
    VoiceTurnRequest,
)
from multimodal_voice_platform.voice.records import (
    LATENCY_STAGES,
    ConversationContext,
    TranscriptView,
    TurnStatus,
    VoiceStage,
    VoiceTiming,
    VoiceTurnRecord,
)
from multimodal_voice_platform.voice.reply import parse_reply, validate_reply
from multimodal_voice_platform.voice.state import (
    CommittedTurn,
    ConversationSnapshot,
    ConversationStore,
    SessionStatus,
    TurnReservation,
)

__all__ = [
    "LATENCY_STAGES",
    "PROVIDER_CALLS_PER_TURN",
    "VOICE_ASSISTANT_TASK",
    "VOICE_FIXTURE_IDS",
    "CommittedTurn",
    "ConversationContext",
    "ConversationLimitError",
    "ConversationSnapshot",
    "ConversationStore",
    "DuplicateSessionError",
    "DuplicateTurnError",
    "LiveVoiceUnavailableError",
    "ReplyRejectedError",
    "SessionBusyError",
    "SessionExpiredError",
    "SessionStatus",
    "StateCommitError",
    "TranscriptRejectedError",
    "TranscriptView",
    "TurnBudgetExhaustedError",
    "TurnReservation",
    "TurnStatus",
    "UnknownSessionError",
    "VoiceAssistant",
    "VoiceConfigurationError",
    "VoiceLimits",
    "VoiceSessionError",
    "VoiceStage",
    "VoiceTiming",
    "VoiceTurnRecord",
    "VoiceTurnRequest",
    "load_voice_catalog",
    "parse_reply",
    "validate_reply",
]
