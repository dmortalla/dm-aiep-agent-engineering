"""Tests for evidence classification contracts."""

import pytest
from pydantic import ValidationError

from mcp_enterprise_integration.evidence import EvidenceClass, ExecutionEvidence


def test_all_approved_evidence_classes_are_explicit() -> None:
    """Keep the frozen evidence vocabulary complete and auditable."""
    assert {item.value for item in EvidenceClass} == {
        "deterministic",
        "mocked",
        "adapter",
        "local-integration",
        "live-provider",
        "deployment",
    }


def test_deterministic_evidence_requires_no_live_execution() -> None:
    """Represent deterministic evidence without inflating its strength."""
    evidence = ExecutionEvidence(
        evidence_id="ev-001",
        evidence_class=EvidenceClass.DETERMINISTIC,
        capability_id="contract_validation",
        summary="Validated locally with deterministic inputs.",
    )

    assert evidence.live_provider_executed is False
    assert evidence.deployment_executed is False


def test_live_provider_claim_requires_live_execution() -> None:
    """Reject unsupported live-provider claims."""
    with pytest.raises(ValidationError, match="requires actual live-provider execution"):
        ExecutionEvidence(
            evidence_id="ev-002",
            evidence_class=EvidenceClass.LIVE_PROVIDER,
            capability_id="agent",
            summary="Unsupported live claim.",
        )


def test_deployment_claim_requires_deployment_execution() -> None:
    """Reject unsupported deployment claims."""
    with pytest.raises(ValidationError, match="requires actual deployment execution"):
        ExecutionEvidence(
            evidence_id="ev-003",
            evidence_class=EvidenceClass.DEPLOYMENT,
            capability_id="mcp_server",
            summary="Unsupported deployment claim.",
        )


def test_execution_flags_cannot_be_hidden_by_weaker_classification() -> None:
    """Prevent real execution flags from being mislabeled."""
    with pytest.raises(ValidationError, match="must be classified as live-provider"):
        ExecutionEvidence(
            evidence_id="ev-004",
            evidence_class=EvidenceClass.DETERMINISTIC,
            capability_id="agent",
            summary="Incorrect classification.",
            live_provider_executed=True,
        )


def test_evidence_rejects_unknown_fields() -> None:
    """Reject uncontracted evidence metadata."""
    with pytest.raises(ValidationError):
        ExecutionEvidence(
            evidence_id="ev-005",
            evidence_class=EvidenceClass.MOCKED,
            capability_id="fixture",
            summary="Mocked execution.",
            secret="must-not-exist",
        )
