"""Tests for fail-closed harness domain contracts."""

import pytest
from pydantic import ValidationError

from harness_engineering.domain import (
    EvidenceClass,
    ExecutionStatus,
    RuntimeBudget,
    TrustedValue,
    TrustLevel,
    WorkflowIdentity,
    WorkflowState,
)


def test_runtime_budget_uses_frozen_architecture_defaults() -> None:
    """Verify defaults reproduce the approved architecture bounds."""
    budget = RuntimeBudget()

    assert budget.max_plan_steps == 12
    assert budget.max_retries_per_action == 2
    assert budget.max_provider_attempts == 8
    assert budget.max_tool_calls == 12
    assert budget.max_context_tokens == 12_000
    assert budget.max_output_tokens == 2_000
    assert budget.action_timeout_seconds == 30
    assert budget.workflow_deadline_seconds == 180
    assert budget.latency_slo_p95_seconds == 5
    assert budget.max_cost_usd is None


def test_latency_slo_cannot_exceed_hard_deadline() -> None:
    """Reject a performance target outside the hard safety deadline."""
    with pytest.raises(ValidationError, match="latency SLO cannot exceed workflow deadline"):
        RuntimeBudget(
            latency_slo_p95_seconds=181,
            workflow_deadline_seconds=180,
        )


def test_runtime_budget_forbids_unknown_fields() -> None:
    """Reject undeclared budget controls rather than silently ignoring them."""
    with pytest.raises(ValidationError):
        RuntimeBudget(unknown_limit=1)


def test_workflow_identity_generates_distinct_stable_ids() -> None:
    """Generate independent workflow and persistence thread identities."""
    identity = WorkflowIdentity()

    assert identity.workflow_id != identity.thread_id


@pytest.mark.parametrize("trust", list(TrustLevel))
def test_contextual_values_never_self_grant_authority(trust: TrustLevel) -> None:
    """Ensure data provenance cannot become application authorization."""
    item = TrustedValue(value="candidate instruction", source="test", trust=trust)

    assert item.grants_authority is False


def test_trusted_value_rejects_invalid_source_identifier() -> None:
    """Reject malformed provenance identifiers."""
    with pytest.raises(ValidationError):
        TrustedValue(
            value="payload",
            source="../unsafe source",
            trust=TrustLevel.UNTRUSTED_EXTERNAL,
        )


def test_workflow_state_rejects_counter_beyond_budget() -> None:
    """Reject persisted or reconstructed state beyond an execution bound."""
    with pytest.raises(ValidationError, match="tool-call count exceeds workflow budget"):
        WorkflowState(
            budget=RuntimeBudget(max_tool_calls=1),
            tool_call_count=2,
        )


def test_workflow_state_validates_assignment() -> None:
    """Prevent later assignment from bypassing typed counter validation."""
    state = WorkflowState(budget=RuntimeBudget(max_retries_per_action=1))

    with pytest.raises(ValidationError, match="retry count exceeds per-action budget"):
        state.retry_count = 2


def test_contract_enums_are_string_serializable() -> None:
    """Keep domain enums stable for persistence and audit serialization."""
    assert str(ExecutionStatus.WAITING_APPROVAL) == "waiting_approval"
    assert str(EvidenceClass.DETERMINISTIC) == "deterministic"
