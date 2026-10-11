"""Tests for context compression and sliding-window behavior."""

import pytest

from harness_engineering.context import ContextCompressor, ContextItem
from harness_engineering.domain import TrustLevel


def character_estimator(text: str) -> int:
    """Use characters as deterministic test token units.

    Args:
        text: Text to measure.

    Returns:
        Character count.
    """
    return len(text)


def deterministic_summarizer(items: tuple[ContextItem, ...]) -> str:
    """Return a deterministic bounded summary for tests.

    Args:
        items: Context items supplied for summarization.

    Returns:
        Stable summary text.
    """
    del items
    return "bounded summary"


def make_item(
    content: str,
    provenance: str,
    trust_level: TrustLevel = TrustLevel.UNTRUSTED_RETRIEVED,
    relevance: float = 0.5,
) -> ContextItem:
    """Create deterministic context for compression tests.

    Args:
        content: Context content.
        provenance: Source identifier.
        trust_level: Trust classification.
        relevance: Relevance score.

    Returns:
        Validated context item.
    """
    return ContextItem(
        content=content,
        provenance=provenance,
        trust_level=trust_level,
        relevance=relevance,
    )


def test_summary_compression_reduces_estimated_tokens() -> None:
    compressor = ContextCompressor(character_estimator, deterministic_summarizer)
    items = (
        make_item("A" * 40, "fixture://a"),
        make_item("B" * 40, "fixture://b"),
    )

    result = compressor.summarize(items, max_summary_tokens=20)

    assert result.compressed_item.content == "bounded summary"
    assert result.compressed_token_estimate == len("bounded summary")
    assert result.source_token_estimate == 80
    assert result.tokens_saved > 0


def test_compression_retains_source_provenance() -> None:
    compressor = ContextCompressor(character_estimator, deterministic_summarizer)
    items = (
        make_item("alpha", "fixture://alpha"),
        make_item("beta", "fixture://beta"),
    )

    result = compressor.summarize(items, max_summary_tokens=20)

    assert result.source_items == items
    assert "fixture://alpha" in result.compressed_item.provenance
    assert "fixture://beta" in result.compressed_item.provenance


def test_compression_does_not_upgrade_untrusted_context() -> None:
    compressor = ContextCompressor(character_estimator, deterministic_summarizer)
    items = (
        make_item(
            "trusted",
            "application://trusted",
            TrustLevel.TRUSTED_APPLICATION,
        ),
        make_item("retrieved", "fixture://retrieved"),
    )

    result = compressor.summarize(items, max_summary_tokens=20)

    assert result.compressed_item.trust_level is TrustLevel.UNTRUSTED_RETRIEVED


def test_all_trusted_sources_remain_trusted_after_compression() -> None:
    compressor = ContextCompressor(character_estimator, deterministic_summarizer)
    items = (
        make_item("one", "application://one", TrustLevel.TRUSTED_APPLICATION),
        make_item("two", "application://two", TrustLevel.TRUSTED_APPLICATION),
    )

    result = compressor.summarize(items, max_summary_tokens=20)

    assert result.compressed_item.trust_level is TrustLevel.TRUSTED_APPLICATION


def test_summary_that_exceeds_budget_fails_closed() -> None:
    compressor = ContextCompressor(character_estimator, deterministic_summarizer)
    items = (make_item("source", "fixture://source"),)

    with pytest.raises(ValueError, match="exceeds the summary token budget"):
        compressor.summarize(items, max_summary_tokens=5)


def test_empty_summary_fails_closed() -> None:
    def empty_summarizer(items: tuple[ContextItem, ...]) -> str:
        """Return empty output for failure-path verification.

        Args:
            items: Ignored context items.

        Returns:
            Empty summary.
        """
        del items
        return ""

    compressor = ContextCompressor(character_estimator, empty_summarizer)

    with pytest.raises(ValueError, match="empty summary"):
        compressor.summarize(
            (make_item("source", "fixture://source"),),
            max_summary_tokens=20,
        )


def test_compression_requires_source_context() -> None:
    compressor = ContextCompressor(character_estimator, deterministic_summarizer)

    with pytest.raises(ValueError, match="at least one context item"):
        compressor.summarize((), max_summary_tokens=20)


def test_sliding_window_retains_most_recent_items_in_order() -> None:
    items = (
        make_item("oldest", "fixture://1"),
        make_item("middle", "fixture://2"),
        make_item("newest", "fixture://3"),
    )

    window = ContextCompressor.sliding_window(items, max_items=2)

    assert [item.content for item in window] == ["middle", "newest"]
    assert [item.provenance for item in window] == ["fixture://2", "fixture://3"]


def test_sliding_window_larger_than_context_retains_all_items() -> None:
    items = (
        make_item("one", "fixture://1"),
        make_item("two", "fixture://2"),
    )

    assert ContextCompressor.sliding_window(items, max_items=5) == items


def test_sliding_window_rejects_non_positive_bound() -> None:
    with pytest.raises(ValueError, match="max_items must be at least 1"):
        ContextCompressor.sliding_window((), max_items=0)


def test_invalid_estimator_fails_closed() -> None:
    def invalid_estimator(text: str) -> int:
        """Return an invalid estimate for failure-path verification.

        Args:
            text: Ignored text.

        Returns:
            Negative invalid estimate.
        """
        del text
        return -1

    with pytest.raises(ValueError, match="non-negative integer"):
        ContextCompressor(invalid_estimator, deterministic_summarizer)
