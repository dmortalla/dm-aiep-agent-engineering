"""Tests for deterministic context construction and token budgeting."""

import pytest
from pydantic import ValidationError

from harness_engineering.context import ContextBudget, ContextItem, ContextManager
from harness_engineering.domain import TrustLevel


def character_estimator(text: str) -> int:
    """Return one deterministic token unit per character for tests.

    Args:
        text: Text to measure.

    Returns:
        Character count used as deterministic test token units.
    """
    return len(text)


def make_item(
    content: str,
    provenance: str,
    relevance: float,
) -> ContextItem:
    """Create an untrusted retrieved context item for tests.

    Args:
        content: Context content.
        provenance: Source identifier.
        relevance: Deterministic relevance score.

    Returns:
        A validated context item.
    """
    return ContextItem(
        content=content,
        provenance=provenance,
        trust_level=TrustLevel.UNTRUSTED_RETRIEVED,
        relevance=relevance,
    )


def test_budget_reserves_output_capacity() -> None:
    budget = ContextBudget(max_context_tokens=100, reserved_output_tokens=25)

    assert budget.available_input_tokens == 75


def test_context_item_retains_provenance_and_trust() -> None:
    item = make_item("customer context", "fixture://customer", 0.8)

    assert item.provenance == "fixture://customer"
    assert item.trust_level is TrustLevel.UNTRUSTED_RETRIEVED


def test_construct_prompt_includes_context_with_audit_metadata() -> None:
    manager = ContextManager(
        ContextBudget(max_context_tokens=500, reserved_output_tokens=0),
        character_estimator,
    )
    item = make_item("alpha", "fixture://alpha", 0.9)

    result = manager.construct_prompt("Answer safely.", [item])

    assert result.selected_items == (item,)
    assert "fixture://alpha" in result.prompt
    assert TrustLevel.UNTRUSTED_RETRIEVED.value in result.prompt
    assert "alpha" in result.prompt


def test_higher_relevance_context_is_selected_first() -> None:
    manager = ContextManager(
        ContextBudget(max_context_tokens=110, reserved_output_tokens=0),
        character_estimator,
    )
    low = make_item("L" * 30, "low", 0.1)
    high = make_item("H" * 30, "high", 0.9)

    result = manager.construct_prompt("task", [low, high])

    assert result.selected_items
    assert result.selected_items[0] is high


def test_context_budget_omits_items_that_do_not_fit() -> None:
    manager = ContextManager(
        ContextBudget(max_context_tokens=90, reserved_output_tokens=0),
        character_estimator,
    )
    first = make_item("A" * 20, "a", 1.0)
    second = make_item("B" * 20, "b", 0.5)

    result = manager.construct_prompt("task", [first, second])

    assert result.estimated_input_tokens <= result.available_input_tokens
    assert result.omitted_item_count >= 1


def test_instruction_that_exceeds_budget_fails_closed() -> None:
    manager = ContextManager(ContextBudget(max_context_tokens=5), character_estimator)

    with pytest.raises(ValueError, match="instruction exceeds"):
        manager.construct_prompt("too long", [])


def test_empty_instruction_is_rejected() -> None:
    manager = ContextManager(ContextBudget(max_context_tokens=100), character_estimator)

    with pytest.raises(ValueError, match="must not be empty"):
        manager.construct_prompt("   ", [])


def test_invalid_token_estimator_fails_closed() -> None:
    def invalid_estimator(text: str) -> int:
        """Return an intentionally invalid estimate for the failure-path test.

        Args:
            text: Ignored input text.

        Returns:
            A negative value that violates the estimator contract.
        """
        del text
        return -1

    with pytest.raises(ValueError, match="non-negative integer"):
        ContextManager(ContextBudget(max_context_tokens=100), invalid_estimator)


def test_context_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ContextItem(
            content="data",
            provenance="fixture://data",
            trust_level=TrustLevel.UNTRUSTED_RETRIEVED,
            unexpected=True,
        )
