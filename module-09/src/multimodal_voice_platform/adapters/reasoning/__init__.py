"""Deterministic rule-based reasoning adapters (Stories 9.5 and 9.6).

``DeterministicCrossModalReasoner`` (Story 9.5) implements ``ReasoningPort`` with a small, fixed
lexicon and fixed tolerances that relate observations from different modalities.
``DeterministicConversationReasoner`` (Story 9.6) answers voice-assistant turns from the current
transcript and the bounded conversation history with two fixed phrasings. Both are reproducible,
inspectable inference, not model inference: no language or multimodal model runs.
"""

from multimodal_voice_platform.adapters.reasoning.claims import (
    COLOR_WORDS,
    Claim,
    content_terms,
    extract_claims,
)
from multimodal_voice_platform.adapters.reasoning.conversation import (
    CONVERSATION_REASONER_ID,
    DeterministicConversationReasoner,
)
from multimodal_voice_platform.adapters.reasoning.errors import ReasoningInputError
from multimodal_voice_platform.adapters.reasoning.rule_reasoner import (
    RULE_REASONER_ID,
    DeterministicCrossModalReasoner,
)
from multimodal_voice_platform.adapters.reasoning.rules import reason

__all__ = [
    "COLOR_WORDS",
    "CONVERSATION_REASONER_ID",
    "RULE_REASONER_ID",
    "Claim",
    "DeterministicConversationReasoner",
    "DeterministicCrossModalReasoner",
    "ReasoningInputError",
    "content_terms",
    "extract_claims",
    "reason",
]
