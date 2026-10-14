"""Immutable validated text-analysis contracts with explicit evidence."""

from dataclasses import dataclass, field
from enum import StrEnum

from module10_ai.errors import ContractError

MAX_TEXT_CHARACTERS = 4096
MAX_KEYWORDS = 10


class EvidenceClass(StrEnum):
    """Execution provenance labels, never deployment or quality claims."""

    DETERMINISTIC = "deterministic"
    LOCAL_RUNTIME = "local-runtime"
    LIVE_CLOUD = "live-cloud"


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    """Bounded text for deterministic lexical analysis, not live generation.

    Args:
        text: Nonblank text of at most 4096 Unicode characters.
        keyword_limit: Maximum keywords to return, from one through ten.

    Raises:
        ContractError: Input violates type or size bounds.
    """

    text: str = field(repr=False)
    keyword_limit: int = 5

    def __post_init__(self) -> None:
        """Validate without echoing potentially sensitive input."""
        if type(self.text) is not str or not 1 <= len(self.text) <= MAX_TEXT_CHARACTERS:
            raise ContractError("Text must be a string of 1 through 4096 characters.")
        if not self.text.strip():
            raise ContractError("Text must contain non-whitespace characters.")
        if type(self.keyword_limit) is not int or not 1 <= self.keyword_limit <= MAX_KEYWORDS:
            raise ContractError("Keyword limit must be an integer from 1 through 10.")


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """Structured untrusted analysis data with explicit execution provenance.

    Args:
        word_count: Number of lexical words recognized.
        keywords: Unique normalized words, ordered by frequency then alphabetically.
        evidence: Actual execution classification.

    Raises:
        ContractError: Result violates structural bounds or provenance types.
    """

    word_count: int
    keywords: tuple[str, ...] = field(repr=False)
    evidence: EvidenceClass

    def __post_init__(self) -> None:
        """Reject malformed provider output before application consumption."""
        if type(self.word_count) is not int or not 0 <= self.word_count <= MAX_TEXT_CHARACTERS:
            raise ContractError("Word count must be a bounded nonnegative integer.")
        if type(self.keywords) is not tuple or len(self.keywords) > MAX_KEYWORDS:
            raise ContractError("Keywords must be a tuple of at most ten words.")
        if any(type(word) is not str or not word or not word.isalpha()
               or word != word.lower() or len(word) > MAX_TEXT_CHARACTERS
               for word in self.keywords):
            raise ContractError("Keywords must contain bounded lowercase alphabetic words.")
        if len(set(self.keywords)) != len(self.keywords) or len(self.keywords) > self.word_count:
            raise ContractError("Keywords must be unique and consistent with word count.")
        if not isinstance(self.evidence, EvidenceClass):
            raise ContractError("Evidence must use an explicit execution classification.")
