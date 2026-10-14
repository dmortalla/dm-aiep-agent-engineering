"""Tests for evidence classification and resource budget contracts."""

from typing import Any

import pytest
from pydantic import ValidationError

from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.limits import MAX_RETRIES, ResourceBudget
from multimodal_voice_platform.contracts.session import ExecutionMode


def _record(**overrides: Any) -> EvidenceRecord:
    fields: dict[str, Any] = {
        "evidence_id": "ev-1",
        "evidence_class": EvidenceClass.DESIGN_DOCUMENTATION,
        "story": "9.1",
        "requirement_ids": ("SRC-001",),
        "summary": "Architecture documented.",
    }
    fields.update(overrides)
    return EvidenceRecord(**fields)


def test_story_9_1_design_evidence_claims_no_runtime() -> None:
    record = _record()
    assert record.runtime_executed is False
    assert record.live_provider_executed is False
    with pytest.raises(ValidationError):
        _record(runtime_executed=True)
    with pytest.raises(ValidationError):
        _record(execution_mode=ExecutionMode.DETERMINISTIC)


def test_runtime_classes_require_runtime_execution() -> None:
    for evidence_class in (
        EvidenceClass.AUTOMATED_TEST,
        EvidenceClass.DETERMINISTIC_DEMO,
        EvidenceClass.DEPLOYMENT_RELEASE,
    ):
        with pytest.raises(ValidationError, match="runtime_executed"):
            _record(evidence_class=evidence_class, story="9.2")


def test_only_live_integration_records_live_execution() -> None:
    _record(
        evidence_class=EvidenceClass.LIVE_INTEGRATION,
        story="9.8",
        runtime_executed=True,
        live_provider_executed=True,
        execution_mode=ExecutionMode.LIVE,
    )
    with pytest.raises(ValidationError, match="live"):
        _record(
            evidence_class=EvidenceClass.DETERMINISTIC_DEMO,
            story="9.2",
            runtime_executed=True,
            live_provider_executed=True,
            execution_mode=ExecutionMode.DETERMINISTIC,
        )
    with pytest.raises(ValidationError, match="live"):
        _record(
            evidence_class=EvidenceClass.LIVE_INTEGRATION,
            story="9.8",
            runtime_executed=True,
            live_provider_executed=True,
            execution_mode=ExecutionMode.DETERMINISTIC,
        )


def test_live_mode_cannot_be_labelled_deterministic_demo() -> None:
    with pytest.raises(ValidationError, match="deterministic execution mode"):
        _record(
            evidence_class=EvidenceClass.DETERMINISTIC_DEMO,
            story="9.2",
            runtime_executed=True,
            execution_mode=ExecutionMode.LIVE,
        )


@pytest.mark.parametrize("story", ["9.0", "9.11", "8.1"])
def test_evidence_story_must_be_a_module_9_story(story: str) -> None:
    with pytest.raises(ValidationError):
        _record(story=story)


def test_default_budget_is_within_ceilings() -> None:
    budget = ResourceBudget()
    assert budget.max_retries <= MAX_RETRIES
    assert budget.max_retries < budget.max_provider_calls_per_session


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_retries": MAX_RETRIES + 1},
        {"max_retries": 5, "max_provider_calls_per_session": 5},
        {"request_timeout_s": 61.0},
        {"request_timeout_s": 30.0, "session_timeout_s": 10.0},
        {"max_image_bytes": 0},
        {"unbounded": True},
    ],
)
def test_budgets_cannot_exceed_ceilings_or_contradict(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ResourceBudget(**overrides)
