"""Exit-contract tests for the integrated Story 3 context lab."""

from harness_engineering.context_lab import run_context_lab
from harness_engineering.domain import TrustLevel
from harness_engineering.memory import MemoryDestination


def test_context_lab_enforces_input_budget() -> None:
    result = run_context_lab()

    assert (
        result.constructed_context.estimated_input_tokens
        <= result.constructed_context.available_input_tokens
    )
    assert result.constructed_context.available_input_tokens == 150
    assert result.constructed_context.omitted_item_count > 0


def test_context_lab_demonstrates_compression() -> None:
    result = run_context_lab()

    assert result.compression.compressed_token_estimate <= 50
    assert result.compression.tokens_saved > 0


def test_context_lab_retains_compression_provenance() -> None:
    result = run_context_lab()

    provenance = result.compression.compressed_item.provenance
    assert "fixture://history-1" in provenance
    assert "fixture://history-2" in provenance
    assert result.compression.compressed_item.trust_level is TrustLevel.UNTRUSTED_RETRIEVED


def test_context_lab_demonstrates_sliding_window_behavior() -> None:
    result = run_context_lab()

    assert len(result.sliding_window) == 2
    assert [item.provenance for item in result.sliding_window] == [
        "fixture://history-2",
        "fixture://current",
    ]


def test_context_lab_demonstrates_bounded_memory_routing() -> None:
    result = run_context_lab()

    assert result.short_term_route.destination is MemoryDestination.SHORT_TERM
    assert (
        result.long_term_route.destination
        is MemoryDestination.LONG_TERM_ELIGIBLE
    )


def test_context_lab_is_deterministic() -> None:
    first = run_context_lab()
    second = run_context_lab()

    assert first == second
