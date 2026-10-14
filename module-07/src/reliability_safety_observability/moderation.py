"""Application-owned deterministic moderation policy.

Moderation classifies content against committed prohibited categories. Its
result is a safety signal only and never confers authorization.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from pydantic import TypeAdapter, ValidationError

from .domain import Decision, EvidenceClass, Identifier
from .errors import ConfigurationError
from .injection import normalize_for_inspection
from .safety_types import SafetyCheckResult

_IDENTIFIER: Final = TypeAdapter(Identifier)

DEFAULT_PROHIBITED_CATEGORIES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "violent_weapons": (
            r"\bhow (do i|to) (make|build|assemble) (a |an )?(bomb|explosive|pipe bomb)\b",
        ),
        "self_harm": (
            r"\b(kill|hurt|harm) (yourself|myself)\b",
            r"\bways to (die|end my life)\b",
        ),
        "harassment": (
            r"\byou are (worthless|garbage|subhuman)\b",
            r"\bi will (find|hurt) you\b",
        ),
    }
)


class ModerationPolicy:
    """Deterministic, committed moderation rules for input and output text."""

    check_name: Final = "moderation"

    def __init__(
        self, categories: Mapping[str, tuple[str, ...]] = DEFAULT_PROHIBITED_CATEGORIES
    ) -> None:
        """Compile committed prohibited-content categories.

        Args:
            categories: Category identifiers mapped to regular expressions that
                are matched against normalized text.

        Raises:
            ConfigurationError: If a category is unnamed, empty, or invalid.
        """
        compiled: dict[str, tuple[re.Pattern[str], ...]] = {}
        for name, patterns in categories.items():
            try:
                category = _IDENTIFIER.validate_python(name)
                compiled[category] = tuple(re.compile(pattern) for pattern in patterns)
            except (ValidationError, re.error) as exc:
                raise ConfigurationError(
                    "Moderation policy contains an invalid category definition."
                ) from exc
            if not compiled[category]:
                raise ConfigurationError(
                    f"Moderation category {category!r} must define at least one rule."
                )
        if not compiled:
            raise ConfigurationError("Moderation policy must define at least one category.")
        self._categories: Mapping[str, tuple[re.Pattern[str], ...]] = MappingProxyType(compiled)

    def moderate(self, text: str) -> SafetyCheckResult:
        """Classify text against the prohibited categories.

        Args:
            text: Untrusted text to moderate.

        Returns:
            A deny result naming the first matched category, or an allow result.
        """
        normalized = normalize_for_inspection(text)
        for category, patterns in self._categories.items():
            if any(pattern.search(normalized) for pattern in patterns):
                return SafetyCheckResult(
                    check=self.check_name,
                    decision=Decision.DENY,
                    reason=f"moderation_{category}",
                    evidence_class=EvidenceClass.DETERMINISTIC_FIXTURE,
                )
        return SafetyCheckResult(
            check=self.check_name,
            decision=Decision.ALLOW,
            reason="moderation_permitted",
            evidence_class=EvidenceClass.DETERMINISTIC_FIXTURE,
        )
