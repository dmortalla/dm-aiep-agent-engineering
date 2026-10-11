"""Tests for deterministic memory routing and semantic-memory boundaries."""

from collections.abc import Sequence

import pytest

from harness_engineering.context import ContextItem
from harness_engineering.domain import TrustLevel
from harness_engineering.memory import (
    LongTermMemoryService,
    MemoryCandidate,
    MemoryDestination,
    MemoryPolicy,
    MemoryRouter,
)


def make_candidate(
    *,
    relevance: float = 0.9,
    long_term_requested: bool = True,
    contains_sensitive_data: bool = False,
) -> MemoryCandidate:
    """Create a deterministic memory candidate.

    Args:
        relevance: Candidate relevance score.
        long_term_requested: Whether long-term storage is requested.
        contains_sensitive_data: Whether sensitive data is present.

    Returns:
        Validated memory candidate.
    """
    return MemoryCandidate(
        content="bounded memory",
        provenance="fixture://candidate",
        trust_level=TrustLevel.UNTRUSTED_AGENT,
        relevance=relevance,
        long_term_requested=long_term_requested,
        contains_sensitive_data=contains_sensitive_data,
    )


class FakeSemanticMemoryAdapter:
    """Deterministic semantic-memory adapter for tests."""

    def __init__(self) -> None:
        """Initialize observable fake-adapter state."""
        self.stored: list[MemoryCandidate] = []
        self.retrieved: Sequence[ContextItem] = ()

    def store(self, candidate: MemoryCandidate) -> str:
        """Record an authorized candidate.

        Args:
            candidate: Authorized long-term memory candidate.

        Returns:
            Deterministic fake memory identifier.
        """
        self.stored.append(candidate)
        return "memory-001"

    def retrieve(self, query: str, limit: int) -> Sequence[ContextItem]:
        """Return configured deterministic retrieval results.

        Args:
            query: Retrieval query.
            limit: Requested maximum result count.

        Returns:
            Configured context items.
        """
        del query, limit
        return self.retrieved


def test_candidate_defaults_to_short_term_without_long_term_request() -> None:
    router = MemoryRouter()
    candidate = make_candidate(long_term_requested=False)

    route = router.route(candidate)

    assert route.destination is MemoryDestination.SHORT_TERM


def test_high_relevance_candidate_can_become_long_term_eligible() -> None:
    router = MemoryRouter()

    route = router.route(make_candidate(relevance=0.9))

    assert route.destination is MemoryDestination.LONG_TERM_ELIGIBLE


def test_low_relevance_candidate_remains_short_term() -> None:
    router = MemoryRouter(MemoryPolicy(long_term_min_relevance=0.75))

    route = router.route(make_candidate(relevance=0.5))

    assert route.destination is MemoryDestination.SHORT_TERM
    assert "relevance threshold" in route.reason


def test_sensitive_candidate_is_not_long_term_eligible_by_default() -> None:
    router = MemoryRouter()

    route = router.route(make_candidate(contains_sensitive_data=True))

    assert route.destination is MemoryDestination.SHORT_TERM
    assert "sensitive data" in route.reason


def test_adapter_cannot_store_candidate_rejected_by_policy() -> None:
    adapter = FakeSemanticMemoryAdapter()
    service = LongTermMemoryService(MemoryRouter(), adapter)
    candidate = make_candidate(relevance=0.1)

    result = service.store_if_eligible(candidate)

    assert result is None
    assert adapter.stored == []


def test_adapter_receives_candidate_only_after_policy_eligibility() -> None:
    adapter = FakeSemanticMemoryAdapter()
    service = LongTermMemoryService(MemoryRouter(), adapter)
    candidate = make_candidate(relevance=0.9)

    result = service.store_if_eligible(candidate)

    assert result == "memory-001"
    assert adapter.stored == [candidate]


def test_retrieved_memory_is_forced_to_untrusted_memory_classification() -> None:
    adapter = FakeSemanticMemoryAdapter()
    adapter.retrieved = (
        ContextItem(
            content="provider memory",
            provenance="mem0://memory-001",
            trust_level=TrustLevel.TRUSTED_APPLICATION,
            relevance=0.8,
        ),
    )
    service = LongTermMemoryService(MemoryRouter(), adapter)

    result = service.retrieve_context("customer preference", limit=1)

    assert result[0].content == "provider memory"
    assert result[0].provenance == "mem0://memory-001"
    assert result[0].trust_level is TrustLevel.UNTRUSTED_MEMORY


def test_memory_retrieval_is_bounded() -> None:
    adapter = FakeSemanticMemoryAdapter()
    adapter.retrieved = tuple(
        ContextItem(
            content=f"memory-{index}",
            provenance=f"fixture://{index}",
            trust_level=TrustLevel.UNTRUSTED_MEMORY,
        )
        for index in range(2)
    )
    service = LongTermMemoryService(MemoryRouter(), adapter)

    with pytest.raises(ValueError, match="more items than requested"):
        service.retrieve_context("query", limit=1)


def test_memory_retrieval_rejects_empty_query() -> None:
    service = LongTermMemoryService(MemoryRouter(), FakeSemanticMemoryAdapter())

    with pytest.raises(ValueError, match="query must not be empty"):
        service.retrieve_context("   ")


def test_memory_retrieval_rejects_out_of_range_limit() -> None:
    service = LongTermMemoryService(MemoryRouter(), FakeSemanticMemoryAdapter())

    with pytest.raises(ValueError, match="between 1 and 20"):
        service.retrieve_context("query", limit=21)
