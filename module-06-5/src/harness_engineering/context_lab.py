"""Deterministic lab integrating Story 3 context and memory controls."""

from dataclasses import dataclass

from harness_engineering.context import (
    CompressionResult,
    ConstructedContext,
    ContextBudget,
    ContextCompressor,
    ContextItem,
    ContextManager,
)
from harness_engineering.domain import TrustLevel
from harness_engineering.memory import (
    MemoryCandidate,
    MemoryRoute,
    MemoryRouter,
)


@dataclass(frozen=True)
class ContextLabResult:
    """Auditable result of the deterministic context-compression lab."""

    constructed_context: ConstructedContext
    compression: CompressionResult
    sliding_window: tuple[ContextItem, ...]
    short_term_route: MemoryRoute
    long_term_route: MemoryRoute


def character_estimator(text: str) -> int:
    """Measure text deterministically for the credential-free lab.

    Args:
        text: Text to measure.

    Returns:
        Character count used as deterministic token units.
    """
    return len(text)


def deterministic_summarizer(items: tuple[ContextItem, ...]) -> str:
    """Compress lab context without an external model.

    Args:
        items: Ordered context items selected for compression.

    Returns:
        Stable bounded summary.
    """
    del items
    return "customer prefers concise technical updates"


def run_context_lab() -> ContextLabResult:
    """Run the integrated deterministic Story 3 lab.

    Returns:
        Evidence for budgeting, compression, provenance, sliding-window
        behavior, and bounded memory routing.
    """
    items = (
        ContextItem(
            content="historic preference " + ("A" * 35),
            provenance="fixture://history-1",
            trust_level=TrustLevel.UNTRUSTED_RETRIEVED,
            relevance=0.4,
        ),
        ContextItem(
            content="recent preference " + ("B" * 35),
            provenance="fixture://history-2",
            trust_level=TrustLevel.UNTRUSTED_RETRIEVED,
            relevance=0.8,
        ),
        ContextItem(
            content="current request " + ("C" * 35),
            provenance="fixture://current",
            trust_level=TrustLevel.UNTRUSTED_AGENT,
            relevance=1.0,
        ),
    )

    manager = ContextManager(
        ContextBudget(max_context_tokens=170, reserved_output_tokens=20),
        character_estimator,
    )
    constructed = manager.construct_prompt(
        "Prepare a response.",
        items,
    )

    compressor = ContextCompressor(
        character_estimator,
        deterministic_summarizer,
    )
    compression = compressor.summarize(items[:2], max_summary_tokens=50)
    window = compressor.sliding_window(items, max_items=2)

    router = MemoryRouter()
    short_term_route = router.route(
        MemoryCandidate(
            content="ephemeral request detail",
            provenance="fixture://ephemeral",
            trust_level=TrustLevel.UNTRUSTED_AGENT,
            relevance=0.9,
            long_term_requested=False,
        )
    )
    long_term_route = router.route(
        MemoryCandidate(
            content="stable communication preference",
            provenance="fixture://preference",
            trust_level=TrustLevel.UNTRUSTED_AGENT,
            relevance=0.95,
            long_term_requested=True,
        )
    )

    return ContextLabResult(
        constructed_context=constructed,
        compression=compression,
        sliding_window=window,
        short_term_route=short_term_route,
        long_term_route=long_term_route,
    )
