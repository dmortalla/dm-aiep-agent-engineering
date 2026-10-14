"""Deterministic, no-key fixture-playback adapters (Story 9.2, ENG-001).

These adapters perform no inference. They replay scripted output for committed fixtures only, make
no network calls, and need no credentials. Their results are deterministic evidence
(``automated_test`` or ``deterministic_demo``), never ``live_integration``.
"""

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.deterministic.errors import (
    ContentNotFoundError,
    DeterministicInputError,
    FixtureBudgetError,
    FixtureIntegrityError,
    UnknownFixtureError,
)
from multimodal_voice_platform.adapters.deterministic.fixtures import FixtureCatalog, FixtureSpec
from multimodal_voice_platform.adapters.deterministic.foundation import (
    DeterministicFoundation,
    DeterministicRunRecord,
)
from multimodal_voice_platform.adapters.deterministic.providers import (
    DeterministicDocumentProvider,
    DeterministicSpeechToTextProvider,
    DeterministicVisionProvider,
)

__all__ = [
    "ContentNotFoundError",
    "DeterministicDocumentProvider",
    "DeterministicFoundation",
    "DeterministicInputError",
    "DeterministicRunRecord",
    "DeterministicSpeechToTextProvider",
    "DeterministicVisionProvider",
    "FixtureBudgetError",
    "FixtureCatalog",
    "FixtureIntegrityError",
    "FixtureSpec",
    "SessionContentStore",
    "UnknownFixtureError",
]
