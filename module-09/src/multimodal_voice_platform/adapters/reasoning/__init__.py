"""Deterministic rule-based reasoning adapter (Story 9.5).

``DeterministicCrossModalReasoner`` implements ``ReasoningPort`` with a small, fixed lexicon and
fixed tolerances that relate observations from different modalities. It is reproducible,
inspectable inference, not model inference: no language or multimodal model runs.
"""

from multimodal_voice_platform.adapters.reasoning.claims import (
    COLOR_WORDS,
    Claim,
    content_terms,
    extract_claims,
)
from multimodal_voice_platform.adapters.reasoning.errors import ReasoningInputError
from multimodal_voice_platform.adapters.reasoning.rule_reasoner import (
    RULE_REASONER_ID,
    DeterministicCrossModalReasoner,
)
from multimodal_voice_platform.adapters.reasoning.rules import reason

__all__ = [
    "COLOR_WORDS",
    "RULE_REASONER_ID",
    "Claim",
    "DeterministicCrossModalReasoner",
    "ReasoningInputError",
    "content_terms",
    "extract_claims",
    "reason",
]
