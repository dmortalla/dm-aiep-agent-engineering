"""Story 6 dataset tests: committed canonical facts, no code, model-defended."""

import pytest
from pydantic import ValidationError

from reliability_safety_observability.domain import EvidenceClass
from reliability_safety_observability.errors import ContractValidationError
from reliability_safety_observability.evaluation_dataset import (
    COMMITTED_DATASET_VERSION,
    ScenarioSpec,
    load_benchmark_dataset,
    scenario_input_digest,
)

ADEQUATE_SPEC = ScenarioSpec(content="Example synthetic evaluation content.")


def test_committed_dataset_loads_with_pinned_and_canonical_view() -> None:
    """Load the committed dataset with its canonical, digest-pinned view."""
    dataset = load_benchmark_dataset()
    assert dataset.scenario_ids == (
        "AUTH-001", "AUTH-002", "COST-001", "IDEM-001", "IDEM-002", "RED-001",
        "REL-001", "REL-002", "REL-003", "REL-004", "SAFE-001", "SAFE-002",
    )
    assert dataset.dataset_version == COMMITTED_DATASET_VERSION
    assert dataset.dataset_id == "module7-benchmark"
    assert len(dataset.digest) == 64


def test_dataset_view_exposes_expected_facts_and_scenario_evidence() -> None:
    """Expose authored expected facts and evidence derived from the spec."""
    dataset = load_benchmark_dataset()
    scenario = dataset.get("AUTH-001")
    assert scenario.expected == dataset.expected_facts("AUTH-001")
    assert scenario.scenario_evidence() is EvidenceClass.DETERMINISTIC_FIXTURE
    assert dataset.get("REL-001").scenario_evidence() is EvidenceClass.SIMULATED_FAILURE


def test_scenario_input_digest_is_stable_and_content_sensitive() -> None:
    """Digest the canonical specification serialization only, deterministically."""
    spec = ScenarioSpec(content="Deterministic sentence.")
    persisted = spec.model_dump(mode="json")
    assert scenario_input_digest(spec) == scenario_input_digest(spec)
    other = ScenarioSpec(content="Different deterministic sentence.")
    assert scenario_input_digest(other) != scenario_input_digest(spec)
    assert isinstance(persisted, dict)


def test_canary_id_is_a_documented_synthetic_marker() -> None:
    """Return the fixed canary marker; it never appears in real fixtures."""
    dataset = load_benchmark_dataset()
    marker = dataset.get("SAFE-001").canary_id()
    assert marker == "module7::canary::SAFE-001"


def test_unknown_dataset_get_fails_with_contract_error() -> None:
    """Refuse unknown scenario identifiers with a documented error class."""
    dataset = load_benchmark_dataset()
    with pytest.raises(ContractValidationError):
        dataset.get("NOT-001")


def test_unknown_dataset_version_is_refused() -> None:
    """Only the reviewed committed dataset version is loadable."""
    with pytest.raises(ContractValidationError):
        load_benchmark_dataset(version=COMMITTED_DATASET_VERSION + 1)


def test_spec_rejects_unsafe_content_and_bad_bounds() -> None:
    """The typed spec refuses control characters and out-of-bound attempts."""
    with pytest.raises(ValidationError):
        ScenarioSpec(content="bad\x0bcontent")
    with pytest.raises(ValidationError):
        ScenarioSpec(content="ok", max_attempts=0)
    with pytest.raises(ValidationError):
        ScenarioSpec(content="ok", reservation_usd=float("nan"))
