"""Cross-modal reasoning workflow (Story 9.5).

Inputs from at least two modalities are processed through the accepted Story 9.3 and 9.4 paths,
normalized into typed observations, combined into one bounded reasoning context, and related by a
``ReasoningPort`` adapter whose cited findings are validated before they are recorded. The default
adapter is deterministic rule-based reasoning, which is not model inference.
"""

from multimodal_voice_platform.crossmodal.context import (
    REASONING_TASK,
    ContextStats,
    CrossModalContext,
    build_context,
    reasoning_request,
    render_view,
)
from multimodal_voice_platform.crossmodal.errors import (
    CrossModalConfigurationError,
    CrossModalInputError,
    CrossModalLimitError,
    InsufficientModalitiesError,
    LiveReasoningUnavailableError,
    ReasoningOutputError,
    ReasoningProviderTimeoutError,
    ReasoningProviderUnavailableError,
)
from multimodal_voice_platform.crossmodal.findings import (
    Consistency,
    CrossModalConclusion,
    conclude,
    parse_reasoner_output,
    validate_findings,
)
from multimodal_voice_platform.crossmodal.limits import CrossModalLimits
from multimodal_voice_platform.crossmodal.observations import (
    ModalityObservation,
    ObservationPath,
    ObservationProvenance,
    observe_speech,
    observe_text,
    observe_understanding,
)
from multimodal_voice_platform.crossmodal.records import (
    CrossModalRecord,
    CrossModalStage,
    CrossModalStatus,
    CrossModalTiming,
    ModalityOutcome,
    OutcomeStatus,
    ReasoningKind,
)
from multimodal_voice_platform.crossmodal.service import (
    CrossModalWorkflow,
    ModalitySubmission,
    ReasoningBinding,
)

__all__ = [
    "REASONING_TASK",
    "Consistency",
    "ContextStats",
    "CrossModalConclusion",
    "CrossModalConfigurationError",
    "CrossModalContext",
    "CrossModalInputError",
    "CrossModalLimitError",
    "CrossModalLimits",
    "CrossModalRecord",
    "CrossModalStage",
    "CrossModalStatus",
    "CrossModalTiming",
    "CrossModalWorkflow",
    "InsufficientModalitiesError",
    "LiveReasoningUnavailableError",
    "ModalityObservation",
    "ModalityOutcome",
    "ModalitySubmission",
    "ObservationPath",
    "ObservationProvenance",
    "OutcomeStatus",
    "ReasoningBinding",
    "ReasoningKind",
    "ReasoningOutputError",
    "ReasoningProviderTimeoutError",
    "ReasoningProviderUnavailableError",
    "build_context",
    "conclude",
    "observe_speech",
    "observe_text",
    "observe_understanding",
    "parse_reasoner_output",
    "reasoning_request",
    "render_view",
    "validate_findings",
]
