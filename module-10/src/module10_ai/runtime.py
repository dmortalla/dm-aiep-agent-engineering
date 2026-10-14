"""Asynchronous provider contract and bounded deterministic lexical runtime."""

from collections import Counter
from itertools import groupby
from typing import Protocol

from module10_ai.contracts import EvidenceClass, InferenceRequest, InferenceResult
from module10_ai.errors import ContractError


class InferenceRuntime(Protocol):
    """Explicit provider interface independent of transport and presentation."""

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Execute a validated inference request.

        Args:
            request: Bounded validated domain input.

        Returns:
            Structured analysis with actual execution evidence.

        Raises:
            RuntimeFailure: Provider encounters an expected execution failure.
            ContractError: Input or output violates the domain contract.
        """
        ...


class DeterministicRuntime:
    """No-network lexical analysis fixture; does not emulate a live model."""

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Count Unicode alphabetic words and rank by frequency then lexical order.

        Args:
            request: Validated bounded text and keyword limit.

        Returns:
            Reproducible structured result labeled deterministic.

        Raises:
            ContractError: Request is not the expected validated contract.
        """
        if type(request) is not InferenceRequest:
            raise ContractError("Runtime requires an InferenceRequest.")
        request.__post_init__()
        words = ["".join(group) for alphabetic, group in
                 groupby(request.text.lower(), key=str.isalpha) if alphabetic]
        counts = Counter(words)
        keywords = tuple(sorted(counts, key=lambda word: (-counts[word], word))
                         [:request.keyword_limit])
        return InferenceResult(len(words), keywords, EvidenceClass.DETERMINISTIC)
