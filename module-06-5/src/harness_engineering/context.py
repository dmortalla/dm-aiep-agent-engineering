"""Typed context construction and token-budgeting contracts."""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from harness_engineering.domain import TrustLevel


class TokenEstimator(Protocol):
    """Estimate token usage without coupling context policy to a provider."""

    def __call__(self, text: str) -> int:
        """Estimate the number of tokens in text.

        Args:
            text: Text whose token usage should be estimated.

        Returns:
            A non-negative estimated token count.
        """
        ...


class ContextItem(BaseModel):
    """A bounded piece of contextual information with provenance and trust."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
    provenance: str = Field(min_length=1, max_length=512)
    trust_level: TrustLevel
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)


class ContextBudget(BaseModel):
    """Token limits governing deterministic context construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_context_tokens: int = Field(default=12_000, ge=1)
    reserved_output_tokens: int = Field(default=2_000, ge=0)

    @property
    def available_input_tokens(self) -> int:
        """Return the token budget available for prompt input.

        Returns:
            The non-negative number of tokens available for input context.
        """
        return max(0, self.max_context_tokens - self.reserved_output_tokens)


class ConstructedContext(BaseModel):
    """Result of deterministic context selection and prompt construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str
    selected_items: tuple[ContextItem, ...]
    estimated_input_tokens: int = Field(ge=0)
    available_input_tokens: int = Field(ge=0)
    omitted_item_count: int = Field(ge=0)


class ContextSummarizer(Protocol):
    """Summarize bounded context without coupling policy to a provider."""

    def __call__(self, items: Sequence[ContextItem]) -> str:
        """Summarize context items.

        Args:
            items: Ordered context items selected for compression.

        Returns:
            A non-empty textual summary.
        """
        ...


class CompressionResult(BaseModel):
    """Auditable result of summarization-based context compression."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    compressed_item: ContextItem
    source_items: tuple[ContextItem, ...]
    source_token_estimate: int = Field(ge=0)
    compressed_token_estimate: int = Field(ge=0)

    @property
    def tokens_saved(self) -> int:
        """Return estimated tokens removed by compression.

        Returns:
            Non-negative estimated token savings.
        """
        return max(0, self.source_token_estimate - self.compressed_token_estimate)


class ContextCompressor:
    """Apply bounded summarization and sliding-window context strategies."""

    def __init__(
        self,
        token_estimator: TokenEstimator,
        summarizer: ContextSummarizer,
    ) -> None:
        """Initialize provider-neutral compression boundaries.

        Args:
            token_estimator: Token estimator used for auditable measurements.
            summarizer: Bounded summarization implementation.

        Raises:
            ValueError: If the token estimator violates its contract.
        """
        self._token_estimator = token_estimator
        self._summarizer = summarizer
        self._estimate("")

    def summarize(
        self,
        items: Sequence[ContextItem],
        max_summary_tokens: int,
    ) -> CompressionResult:
        """Compress context while retaining source provenance and trust metadata.

        Args:
            items: Context items to summarize in their supplied order.
            max_summary_tokens: Hard maximum estimated size of the summary.

        Returns:
            Auditable compression result retaining all source items.

        Raises:
            ValueError: If no items are supplied, the summary is empty, the
                summary exceeds its token budget, or estimation is invalid.
        """
        if not items:
            raise ValueError("at least one context item is required for compression")
        if max_summary_tokens < 1:
            raise ValueError("max_summary_tokens must be at least 1")

        summary = self._summarizer(items).strip()
        if not summary:
            raise ValueError("context summarizer returned an empty summary")

        compressed_tokens = self._estimate(summary)
        if compressed_tokens > max_summary_tokens:
            raise ValueError("compressed context exceeds the summary token budget")

        source_tokens = sum(self._estimate(item.content) for item in items)
        provenance = "summary://" + ",".join(item.provenance for item in items)

        compressed_item = ContextItem(
            content=summary,
            provenance=provenance,
            trust_level=self._least_trusted(items),
            relevance=max(item.relevance for item in items),
        )

        return CompressionResult(
            compressed_item=compressed_item,
            source_items=tuple(items),
            source_token_estimate=source_tokens,
            compressed_token_estimate=compressed_tokens,
        )

    @staticmethod
    def sliding_window(
        items: Sequence[ContextItem],
        max_items: int,
    ) -> tuple[ContextItem, ...]:
        """Retain the most recent bounded context items.

        Args:
            items: Chronologically ordered context, oldest to newest.
            max_items: Maximum number of most-recent items to retain.

        Returns:
            A tuple containing at most the newest ``max_items`` entries.

        Raises:
            ValueError: If max_items is less than one.
        """
        if max_items < 1:
            raise ValueError("max_items must be at least 1")
        return tuple(items[-max_items:])

    def _estimate(self, text: str) -> int:
        estimate = self._token_estimator(text)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise ValueError("token estimator must return a non-negative integer")
        return estimate

    @staticmethod
    def _least_trusted(items: Sequence[ContextItem]) -> TrustLevel:
        if all(item.trust_level is TrustLevel.TRUSTED_APPLICATION for item in items):
            return TrustLevel.TRUSTED_APPLICATION
        return TrustLevel.UNTRUSTED_RETRIEVED

class ContextManager:
    """Construct prompts while enforcing an application-owned token budget."""

    def __init__(
        self,
        budget: ContextBudget,
        token_estimator: TokenEstimator,
    ) -> None:
        """Initialize deterministic context policy.

        Args:
            budget: Context-window limits owned by the application.
            token_estimator: Deterministic or provider-specific token estimator.

        Raises:
            ValueError: If the estimator returns an invalid token count.
        """
        self._budget = budget
        self._token_estimator = token_estimator
        self._validate_estimate("")

    def construct_prompt(
        self,
        instruction: str,
        items: Sequence[ContextItem],
    ) -> ConstructedContext:
        """Build a deterministic prompt within the configured input budget.

        Context items are considered by descending relevance with stable input-order
        tie-breaking. Items that would exceed the budget are omitted rather than
        silently overflowing the context window.

        Args:
            instruction: Trusted application instruction for the prompt.
            items: Candidate contextual information.

        Returns:
            The constructed prompt and auditable selection metadata.

        Raises:
            ValueError: If instruction is empty, the instruction alone exceeds the
                budget, or the token estimator returns an invalid value.
        """
        if not instruction.strip():
            raise ValueError("instruction must not be empty")

        available = self._budget.available_input_tokens
        base_prompt = instruction.strip()
        base_tokens = self._estimate(base_prompt)

        if base_tokens > available:
            raise ValueError("instruction exceeds the available input token budget")

        indexed_items = list(enumerate(items))
        ranked_items = sorted(indexed_items, key=lambda pair: (-pair[1].relevance, pair[0]))

        selected: list[ContextItem] = []
        prompt = base_prompt
        used_tokens = base_tokens

        for _, item in ranked_items:
            rendered = self._render_item(item)
            separator = "\n\n"
            candidate_fragment = separator + rendered
            fragment_tokens = self._estimate(candidate_fragment)

            if used_tokens + fragment_tokens <= available:
                selected.append(item)
                prompt += candidate_fragment
                used_tokens += fragment_tokens

        return ConstructedContext(
            prompt=prompt,
            selected_items=tuple(selected),
            estimated_input_tokens=used_tokens,
            available_input_tokens=available,
            omitted_item_count=len(items) - len(selected),
        )

    def _estimate(self, text: str) -> int:
        estimate = self._token_estimator(text)
        self._validate_estimate(text, estimate)
        return estimate

    def _validate_estimate(self, text: str, estimate: int | None = None) -> None:
        value = self._token_estimator(text) if estimate is None else estimate
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("token estimator must return a non-negative integer")

    @staticmethod
    def _render_item(item: ContextItem) -> str:
        return (
            f"[provenance={item.provenance}; trust={item.trust_level.value}]\n"
            f"{item.content}"
        )
