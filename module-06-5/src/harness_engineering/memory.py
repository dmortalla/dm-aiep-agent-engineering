"""Deterministic memory routing and optional semantic-memory boundaries."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from harness_engineering.context import ContextItem
from harness_engineering.domain import TrustLevel


class MemoryDestination(StrEnum):
    """Application-owned destinations for bounded memory routing."""

    SHORT_TERM = "short_term"
    LONG_TERM_ELIGIBLE = "long_term_eligible"
    DISCARD = "discard"


class MemoryCandidate(BaseModel):
    """Information proposed for deterministic memory routing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
    provenance: str = Field(min_length=1, max_length=512)
    trust_level: TrustLevel
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    long_term_requested: bool = False
    contains_sensitive_data: bool = False


class MemoryRoute(BaseModel):
    """Auditable deterministic routing decision for a memory candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: MemoryCandidate
    destination: MemoryDestination
    reason: str = Field(min_length=1, max_length=512)


class MemoryPolicy(BaseModel):
    """Application-owned bounds for short- and long-term memory routing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    long_term_min_relevance: float = Field(default=0.75, ge=0.0, le=1.0)
    allow_sensitive_long_term_storage: bool = False


class SemanticMemoryAdapter(Protocol):
    """Optional boundary implemented by semantic-memory providers such as Mem0."""

    def store(self, candidate: MemoryCandidate) -> str:
        """Store an application-authorized long-term memory candidate.

        Args:
            candidate: Candidate already authorized by deterministic policy.

        Returns:
            Provider-specific memory identifier.
        """
        ...

    def retrieve(self, query: str, limit: int) -> Sequence[ContextItem]:
        """Retrieve bounded semantic memories as contextual data.

        Args:
            query: Semantic retrieval query.
            limit: Maximum number of memories to return.

        Returns:
            Retrieved memories represented as context items.
        """
        ...


class MemoryRouter:
    """Route memory using deterministic application-owned policy."""

    def __init__(self, policy: MemoryPolicy | None = None) -> None:
        """Initialize memory routing policy.

        Args:
            policy: Optional deterministic routing policy.
        """
        self._policy = policy or MemoryPolicy()

    def route(self, candidate: MemoryCandidate) -> MemoryRoute:
        """Choose a bounded memory destination without granting authority.

        Args:
            candidate: Information proposed for memory.

        Returns:
            Auditable deterministic routing decision.
        """
        if not candidate.long_term_requested:
            return MemoryRoute(
                candidate=candidate,
                destination=MemoryDestination.SHORT_TERM,
                reason="long-term storage was not requested",
            )

        if (
            candidate.contains_sensitive_data
            and not self._policy.allow_sensitive_long_term_storage
        ):
            return MemoryRoute(
                candidate=candidate,
                destination=MemoryDestination.SHORT_TERM,
                reason="sensitive data is not eligible for long-term storage",
            )

        if candidate.relevance < self._policy.long_term_min_relevance:
            return MemoryRoute(
                candidate=candidate,
                destination=MemoryDestination.SHORT_TERM,
                reason="candidate is below the long-term relevance threshold",
            )

        return MemoryRoute(
            candidate=candidate,
            destination=MemoryDestination.LONG_TERM_ELIGIBLE,
            reason="candidate satisfies deterministic long-term eligibility policy",
        )


class LongTermMemoryService:
    """Mediate optional semantic memory behind deterministic authorization."""

    def __init__(
        self,
        router: MemoryRouter,
        adapter: SemanticMemoryAdapter,
    ) -> None:
        """Initialize the optional long-term memory boundary.

        Args:
            router: Deterministic application-owned memory router.
            adapter: Optional semantic-memory provider adapter.
        """
        self._router = router
        self._adapter = adapter

    def store_if_eligible(self, candidate: MemoryCandidate) -> str | None:
        """Store only candidates authorized for long-term memory.

        Args:
            candidate: Candidate proposed for long-term storage.

        Returns:
            Provider memory identifier when eligible, otherwise ``None``.
        """
        route = self._router.route(candidate)
        if route.destination is not MemoryDestination.LONG_TERM_ELIGIBLE:
            return None
        return self._adapter.store(candidate)

    def retrieve_context(self, query: str, limit: int = 5) -> tuple[ContextItem, ...]:
        """Retrieve bounded memory while preserving an untrusted boundary.

        Args:
            query: Non-empty semantic retrieval query.
            limit: Maximum number of memories to retrieve.

        Returns:
            Retrieved memory converted to untrusted contextual data.

        Raises:
            ValueError: If query is empty or limit is outside the supported bound.
        """
        if not query.strip():
            raise ValueError("memory retrieval query must not be empty")
        if limit < 1 or limit > 20:
            raise ValueError("memory retrieval limit must be between 1 and 20")

        retrieved = tuple(self._adapter.retrieve(query.strip(), limit))
        if len(retrieved) > limit:
            raise ValueError("memory adapter returned more items than requested")

        return tuple(
            ContextItem(
                content=item.content,
                provenance=item.provenance,
                trust_level=TrustLevel.UNTRUSTED_MEMORY,
                relevance=item.relevance,
            )
            for item in retrieved
        )
