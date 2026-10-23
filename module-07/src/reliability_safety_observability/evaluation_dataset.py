"""Versioned benchmark dataset: strict schema, digest pinning and loading.

The dataset is application-owned, committed, versioned and synthetic. It is
trusted only as test data: no field can define or alter evaluator semantics,
thresholds, regression policy,_criticality, budgets, authorization, evidence
classes or verdicts, and such fields are refused if present.
"""

import json
from importlib import resources
from typing import Annotated, Final

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from .domain import EvidenceClass
from .errors import ContractValidationError
from .evaluation_contracts import (
    CATEGORIES,
    EVALUATOR_IDS,
    ExpectedFacts,
    canonical_digest,
    canonical_json,
)
from .logging import _is_sensitive_key
from .reliability import Failure

DATASET_ID: Final = "module7-benchmark"
COMMITTED_DATASET_VERSION: Final = 1
SCHEMA_VERSION: Final = 1

DATASET_DIGESTS: Final[dict[int, str]] = {}
"""SHA-256 digest of canonical dataset content, pinned per dataset version.

Populated below for the committed version; changing dataset content requires
a deliberate, reviewed version or digest change, never a silent edit."""

# v1: module7-benchmark-v1.json, reviewed synthetic content, requirements
# authored from accepted Story 2-4 semantics (no provider or run output).
DATASET_DIGESTS[COMMITTED_DATASET_VERSION] = (
    "a9995476f75db567f5b7f3ac63279ad82ac7160281c590f101fcb6d3445eff9c"
)

# Fixed required coverage capacities; the loader refuses absent capacities.
COVERAGE_IDS: Final = (
    "transient_recovered",
    "terminal_failure",
    "timeout_unresolved",
    "fallback_success",
    "replay_no_duplicate_effect",
    "conflict_denied",
    "budget_before_invocation",
    "tool_not_allowlisted",
    "forged_authority_ineffective",
    "prompt_injection_contained",
    "policy_injection_ineffective",
    "canary_absent",
)
MIN_SCENARIOS: Final = 12
MAX_SCENARIOS: Final = 256
MAX_EVALUATORS_PER_SCENARIO: Final = 8
MAX_SCENARIO_BYTES: Final = 16_384
MAX_TITLE_LENGTH: Final = 96
MAX_CONTENT_LENGTH: Final = 2_048

ScenarioId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,8}-[0-9]{3}$")]
Title = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        pattern=r"^[A-Za-z0-9 .,:()_-]+$",
    ),
]


class ScenarioSpec(BaseModel):
    """Typed scenario specification for the application scenario runner.

    The spec drives only the trusted reference target (Story 2-4 composition):
    which principal and tools run, which scripted Story 3 failures the target
    adapters return, budget/reservation values, replay/variant flags, untrusted
    input text, and whether a synthetic redaction canary participates.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_id: str = "scenario_principal"
    tool_name: str = "scenario_tool"
    fallback_tool_name: str | None = None
    allowlisted: bool = True
    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    primary_failures: tuple[Failure, ...] = ()
    fallback_failures: tuple[Failure, ...] = ()
    max_attempts: int = Field(default=3, ge=1, le=1000)
    attempts_per_target: int = Field(default=2, ge=1, le=1000)
    max_fallbacks: int = Field(default=1, ge=0, le=100)
    duplicate_replay: bool = False
    conflicting_replay: bool = False
    budget_limit_usd: float = Field(default=1.0, ge=0.0, allow_inf_nan=False)
    reservation_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    canary_enabled: bool = False

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """Reject untrusted scenario text containing control characters.

        Args:
            value: Candidate untrusted text.

        Returns:
            The validated text.

        Raises:
            ValueError: If the text carries control characters.
        """
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("Scenario content must not contain control characters.")
        return value


class Scenario(BaseModel):
    """One benchmark scenario with authored expected facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: ScenarioId
    category: str
    title: Title
    coverage: str
    spec: ScenarioSpec
    evaluators: tuple[str, ...]
    expected: ExpectedFacts

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        """Refuse categories outside the fixed vocabulary.

        Args:
            value: Candidate category.

        Returns:
            The validated category.

        Raises:
            ValueError: If the category is not committed.
        """
        if value not in CATEGORIES:
            raise ValueError("Unknown category vocabulary.")
        return value

    @field_validator("coverage")
    @classmethod
    def validate_coverage(cls, value: str) -> str:
        """Refuse coverage labels outside the fixed vocabulary.

        Args:
            value: Candidate coverage label.

        Returns:
            The validated coverage label.

        Raises:
            ValueError: If the coverage label is not committed.
        """
        if value not in COVERAGE_IDS:
            raise ValueError("Unknown coverage vocabulary.")
        return value

    @field_validator("title")
    @classmethod
    def validate_title_safety(cls, value: str) -> str:
        """Refuse titles that could carry sensitive keys or canary material.

        Args:
            value: Candidate title.

        Returns:
            The validated title.

        Raises:
            ValueError: If the title is unsafe or padded.
        """
        if _is_sensitive_key(value) or "canary" in value.casefold():
            raise ValueError("Scenario title must not contain sensitive markers.")
        return value

    @field_validator("evaluators")
    @classmethod
    def validate_evaluator_subset(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require a non-empty bounded subset of the fixed evaluator vocabulary.

        Args:
            value: Candidate evaluator references.

        Returns:
            The subset in canonical committed order.

        Raises:
            ValueError: For empty, oversize, duplicated or unknown references.
        """
        if not value or len(value) > MAX_EVALUATORS_PER_SCENARIO:
            raise ValueError("Scenarios require one to eight committed evaluators.")
        if len(set(value)) != len(value):
            raise ValueError("Scenario evaluator references must be unique.")
        if any(item not in EVALUATOR_IDS for item in value):
            raise ValueError("Unknown evaluator identifier.")
        committed_order = {name: rank for rank, name in enumerate(EVALUATOR_IDS)}
        return tuple(sorted(value, key=committed_order.__getitem__))

    def scenario_evidence(self) -> EvidenceClass:
        """Derive scenario evidence from the specification, never from the file.

        Returns:
            ``simulated_failure`` when the spec injects Story 3 failures.
        """
        if self.spec.primary_failures or self.spec.fallback_failures:
            return EvidenceClass.SIMULATED_FAILURE
        return EvidenceClass.DETERMINISTIC_FIXTURE

    def canary_id(self) -> str:
        """Return the synthetic, documented canary marker for this scenario."""
        return f"module7::canary::{self.scenario_id}"


class BenchmarkDataset(BaseModel):
    """Strict, digest-pinned dataset content; unknown fields are refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    dataset_id: str
    dataset_version: int = Field(ge=1)
    scenarios: tuple[Scenario, ...]


class DatasetView:
    """Immutable, canonically ordered accessor over a validated dataset.

    Attributes:
        dataset: Associated validated dataset content.
        digest: The pinned dataset digest binding this dataset content.
    """

    __slots__ = ("_by_id", "dataset", "digest")

    def __init__(self, dataset: BenchmarkDataset, digest: str) -> None:
        ordered = {
            scenario.scenario_id: scenario
            for scenario in sorted(dataset.scenarios, key=lambda item: item.scenario_id)
        }
        self.dataset = dataset
        self.digest = digest
        self._by_id = ordered

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        """Return every scenario identifier in canonical order."""
        return tuple(self._by_id)

    @property
    def scenarios(self) -> tuple[Scenario, ...]:
        """Return all scenarios in canonical scenario-identifier order."""
        return tuple(self._by_id.values())

    @property
    def dataset_id(self) -> str:
        """Return the committed dataset identifier."""
        return self.dataset.dataset_id

    @property
    def dataset_version(self) -> int:
        """Return the committed dataset version."""
        return self.dataset.dataset_version

    def get(self, scenario_id: str) -> Scenario:
        """Return one scenario by identifier.

        Args:
            scenario_id: Committed scenario identifier.

        Returns:
            The scenario.

        Raises:
            ContractValidationError: For an unknown scenario identifier.
        """
        scenario = self._by_id.get(scenario_id)
        if scenario is None:
            raise ContractValidationError(f"Unknown scenario {scenario_id!r}.")
        return scenario

    def expected_facts(self, scenario_id: str) -> ExpectedFacts:
        """Return the authored expected facts committed for one scenario."""
        return self.get(scenario_id).expected


def scenario_input_digest(spec: ScenarioSpec) -> str:
    """Return the SHA-256 input digest of one scenario specification.

    Args:
        spec: A validated scenario specification.

    Returns:
        The digest of the canonical specification serialization; scenario text
        itself is never exported, only this digest.
    """
    return canonical_digest(spec.model_dump(mode="json"))


def load_benchmark_dataset(version: int = COMMITTED_DATASET_VERSION) -> DatasetView:
    """Load, validate and digest the committed benchmark dataset.

    Args:
        version: Committed dataset version to load.

    Returns:
        The canonically ordered dataset view bound to its pinned digest.

    Raises:
        ContractValidationError: For any corruption, schema, digest, size,
            ordering or coverage defect, with a defect-class message only.
    """
    if version != COMMITTED_DATASET_VERSION:
        raise ContractValidationError(
            "Unknown dataset version; only the reviewed committed version is loadable."
        )
    dataset_files = resources.files(__package__) / "evaluation_data"
    source = dataset_files / f"module7-benchmark-v{version}.json"
    raw = source.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise ContractValidationError(
            f"Dataset v{version} is unreadable or malformed; refusing it."
        ) from exc
    if not isinstance(parsed, dict) or parsed.get("dataset_id") != DATASET_ID:
        raise ContractValidationError("Dataset identifier mismatch; refusing dataset.")
    if parsed.get("dataset_version") != version:
        raise ContractValidationError("Dataset version mismatch; refusing dataset.")
    digest = canonical_digest(parsed)
    if _pinned_digest(version) != digest:
        raise ContractValidationError(
            f"Dataset v{version} digest does not match the pinned reviewed content."
        )

    for raw_scenario in parsed.get("scenarios", []):
        scenario_bytes = len(canonical_json(raw_scenario).encode("utf-8"))
        if scenario_bytes > MAX_SCENARIO_BYTES:
            raise ContractValidationError(
                "At least one scenario exceeds the committed 16 KiB serialized bound."
            )
        try:
            Scenario.model_validate(raw_scenario)
        except ValidationError as exc:
            raise ContractValidationError(
                f"Scenario {raw_scenario.get('scenario_id', '?')!r} violates the "
                "committed dataset schema."
            ) from exc
    try:
        dataset = BenchmarkDataset.model_validate(parsed)
    except ValidationError as exc:
        raise ContractValidationError(
            f"Dataset v{version} violates the committed schema."
        ) from exc
    view = DatasetView(dataset, digest)
    _validate_view(dataset)
    return view


def _pinned_digest(version: int) -> str:
    """Return the digest pinned in application code for one dataset version.

    Args:
        version: Committed dataset version.

    Returns:
        The pinned SHA-256 hex digest.

    Raises:
        ContractValidationError: If no digest is pinned for the version.
    """
    try:
        return DATASET_DIGESTS[version]
    except KeyError:
        raise ContractValidationError(
            f"No reviewed dataset digest is pinned for version {version}."
        ) from None


def _reject_constant(token: str) -> float:
    """Refuse NaN/Infinity JSON constants instead of silently parsing them.

    Args:
        token: The offending JSON constant token.

    Raises:
        ValueError: Always; non-finite values are refused, never coerced.
    """
    raise ValueError(f"Non-finite JSON constant {token!r} is refused.")


def _validate_view(dataset: BenchmarkDataset) -> None:
    """Enforce schema, ordering, size, uniqueness and coverage bounds.

    Args:
        dataset: The parsed dataset record.

    Raises:
        ContractValidationError: Naming the defect class without values.
    """
    if dataset.schema_version != SCHEMA_VERSION:
        raise ContractValidationError("Unknown dataset schema version.")
    ordered_ids = [scenario.scenario_id for scenario in dataset.scenarios]
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ContractValidationError("Dataset scenarios repeat a scenario identifier.")
    if sorted(ordered_ids) != ordered_ids:
        raise ContractValidationError("Dataset scenarios require canonical ordering.")
    if not MIN_SCENARIOS <= len(ordered_ids) <= MAX_SCENARIOS:
        raise ContractValidationError(
            "Dataset requires at least twelve and at most 256 scenarios."
        )
    for category in CATEGORIES:
        if not any(scenario.category == category for scenario in dataset.scenarios):
            raise ContractValidationError(
                f"Dataset coverage requires at least one {category} scenario."
            )
    covered = {scenario.coverage for scenario in dataset.scenarios}
    for capacity in COVERAGE_IDS:
        if capacity not in covered:
            raise ContractValidationError(
                f"Dataset minimum coverage requires a {capacity} scenario."
            )
    for scenario in dataset.scenarios:
        if scenario.title != scenario.title.strip():
            raise ContractValidationError(
                f"Scenario {scenario.scenario_id} title padding is refused."
            )


__all__ = [
    "COMMITTED_DATASET_VERSION",
    "COVERAGE_IDS",
    "DATASET_ID",
    "MAX_EVALUATORS_PER_SCENARIO",
    "MAX_SCENARIO_BYTES",
    "BenchmarkDataset",
    "DatasetView",
    "Scenario",
    "ScenarioSpec",
    "load_benchmark_dataset",
    "scenario_input_digest",
]
