"""Story 11 Slice 1: inline invariants, golden-set contracts and regression comparison.

REQ-EVAL-001: InlineInvariantMonitor is a trusted lifecycle boundary observer that
checks critical workflow invariants at every execution boundary and aborts the run
(fail closed) on violation. REQ-EVAL-002/003: the golden set is retained, strictly
validated data; comparison is exact and reproducible. Golden files, observations
and results are data only. They cannot select probes outside the trusted registry,
set evidence classes, or grant identity, permission, approval, budget, routing,
checkpoint or off-switch authority. No threshold here is a source requirement:
every expectation is an exact retained observation of accepted behavior.
"""

import hashlib
import json
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from harness_engineering.domain import EvidenceClass
from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.latency import LatencyReport
from harness_engineering.orchestration import BoundarySnapshot, LifecycleBounds, LifecyclePhase

# Implementation safety bound, matching the accepted MCP JSON convention.
# Counts nested containers (root container is level 1); not a source requirement.
MAX_VALUE_DEPTH = 16
MAX_GOLDEN_BYTES = 65_536
MAX_GOLDEN_CASES = 32
MAX_OBSERVATION_FIELDS = 24
MAX_SEQUENCE_ITEMS = 32
MAX_TEXT_CHARS = 256
DEFAULT_GOLDEN_RESOURCE = "evaluation_golden_set.json"
# Evidence classes a deterministic regression run may honestly report.
PERMITTED_EVIDENCE = frozenset({EvidenceClass.DETERMINISTIC, EvidenceClass.LOCAL_INTEGRATION})


class InvariantViolationError(HarnessError):
    """Raised by the inline monitor; the message names only the violated invariant."""


class EvaluationError(HarnessError):
    """Raised when evaluation cannot produce trustworthy regression evidence."""


class Invariant(StrEnum):
    """Finite inline invariants checked at each lifecycle boundary (REQ-EVAL-001)."""

    SCHEDULE_ORDER = "completed work follows trusted dependency/priority order"
    ATTEMPT_BOUND = "per-action attempts stay within the retry bound"
    ATTEMPT_ACCOUNTING = "per-action attempts sum to total attempts"
    MONOTONIC_PROGRESS = "progress, attempts and elapsed time never regress"
    TERMINAL_CLOSED = "no boundary follows a terminal phase"
    DEADLINE_STOP = "no attempt starts after the workflow deadline is exhausted"
    BOUNDARY_BOUND = "boundary count stays within the bounded attempt total"


class InlineInvariantMonitor:
    """Trusted fail-closed BoundaryObserver for LifecycleRuntime.run_observed().

    Bounds come from the trusted runtime (LifecycleRuntime.bounds()), never from
    golden data or step output. Any violation raises InvariantViolationError, which
    the accepted lifecycle propagates to abort the run without retry. The monitor
    retains only counters and the previous snapshot, so memory is bounded.
    """

    def __init__(self, bounds: LifecycleBounds) -> None:
        """Bind trusted lifecycle bounds.

        Args:
            bounds: Read-only bounds returned by the accepted runtime.

        Raises:
            ContractValidationError: If bounds are not the accepted contract type.
        """
        if type(bounds) is not LifecycleBounds:
            raise ContractValidationError("Bind trusted LifecycleBounds from the runtime.")
        self._bounds = bounds
        tasks = len(bounds.task_ids)
        # Each consumed attempt is one boundary, plus one terminal stop boundary.
        self._max_boundaries = tasks * bounds.max_attempts_per_action + 1
        self._previous: BoundarySnapshot | None = None
        self._checked = 0

    @property
    def boundaries_checked(self) -> int:
        """Return how many boundaries passed every invariant."""
        return self._checked

    def __call__(self, snapshot: BoundarySnapshot) -> None:
        """Check one validated boundary snapshot.

        Args:
            snapshot: Boundary snapshot supplied by the accepted lifecycle runtime.

        Raises:
            InvariantViolationError: If any inline invariant does not hold.
        """
        if type(snapshot) is not BoundarySnapshot:
            raise InvariantViolationError(Invariant.MONOTONIC_PROGRESS.value)
        bounds = self._bounds
        state = snapshot.lifecycle
        previous = self._previous
        _require(self._checked < self._max_boundaries, Invariant.BOUNDARY_BOUND)
        _require(
            previous is None
            or previous.lifecycle.phase not in (LifecyclePhase.COMPLETED, LifecyclePhase.SAFE_STOP),
            Invariant.TERMINAL_CLOSED,
        )
        completed = state.completed_task_ids
        _require(completed == bounds.task_ids[: len(completed)], Invariant.SCHEDULE_ORDER)
        _require(
            len(snapshot.attempts) <= len(bounds.task_ids)
            and all(0 <= n <= bounds.max_attempts_per_action for n in snapshot.attempts),
            Invariant.ATTEMPT_BOUND,
        )
        _require(sum(snapshot.attempts) == state.total_attempts, Invariant.ATTEMPT_ACCOUNTING)
        if previous is not None:
            before = previous.lifecycle
            _require(
                completed[: len(before.completed_task_ids)] == before.completed_task_ids
                and state.total_attempts >= before.total_attempts
                and snapshot.elapsed_seconds >= previous.elapsed_seconds,
                Invariant.MONOTONIC_PROGRESS,
            )
            if previous.elapsed_seconds >= bounds.deadline_seconds:
                _require(
                    state.phase is LifecyclePhase.SAFE_STOP
                    and state.total_attempts == before.total_attempts,
                    Invariant.DEADLINE_STOP,
                )
        self._previous = snapshot
        self._checked += 1


def _require(condition: bool, invariant: Invariant) -> None:
    if not condition:
        raise InvariantViolationError(invariant.value)


Text = Annotated[str, StringConstraints(max_length=MAX_TEXT_CHARS)]
Scalar = Text | bool | int | None
Value = Scalar | tuple[Scalar, ...]
FieldName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
CaseID = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,40}\.[a-z][a-z0-9-]{0,40}$")]
RequirementID = Annotated[
    str, StringConstraints(pattern=r"^(REQ-[A-Z]+-\d{3}|ENG-\d{3})$")
]


class EvaluationData(BaseModel):
    """Immutable strict evaluation data, never policy input."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always",
        hide_input_in_errors=True,
    )


class Observation(EvaluationData):
    """Bounded JSON-compatible facts observed from accepted application behavior."""

    values: dict[FieldName, Value] = Field(max_length=MAX_OBSERVATION_FIELDS)

    @model_validator(mode="after")
    def bounded_sequences(self) -> Self:
        """Bound every retained sequence."""
        for value in self.values.values():
            if isinstance(value, tuple) and len(value) > MAX_SEQUENCE_ITEMS:
                raise ValueError("Observation sequences are bounded.")
        return self


class EvaluationArea(StrEnum):
    """Architecture-named golden-set coverage areas."""

    PLANNING = "planning"
    CONTEXT = "context"
    PERMISSIONS = "permissions"
    MCP = "mcp"
    LIFECYCLE = "lifecycle"
    RECOVERY = "recovery"
    APPROVAL = "approval"
    COST = "cost"
    PROVIDER_SAFETY = "provider_safety"
    OFF_SWITCH = "off_switch"


class GoldenCase(EvaluationData):
    """One retained expectation; it names a trusted probe but cannot define one.

    Area, requirement traceability, purpose and evidence class belong to the
    trusted probe registry, so golden data cannot relabel or promote them.
    """

    case_id: CaseID
    expected: Observation


class GoldenSet(EvaluationData):
    """Versioned bounded golden set; evidence classes are deliberately absent."""

    schema_version: Literal[1]
    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
    cases: tuple[GoldenCase, ...] = Field(min_length=1, max_length=MAX_GOLDEN_CASES)

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        """Reject duplicate case identifiers."""
        ids = [case.case_id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("Golden case identifiers must be unique.")
        return self


class LoadedGoldenSet(EvaluationData):
    """Validated golden set with content provenance."""

    golden: GoldenSet
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    source: Literal["packaged", "reviewer_file"]


def load_golden_set(path: Path | None = None) -> LoadedGoldenSet:
    """Load and strictly validate a retained golden set.

    Args:
        path: Optional reviewer-supplied golden file. None loads the packaged set.

    Returns:
        The validated set and the SHA-256 of its exact bytes.

    Raises:
        ContractValidationError: If the file is missing, oversized, not UTF-8 JSON,
            or does not satisfy the golden-set contract. Content is never echoed.
    """
    try:
        if path is None:
            resource = resources.files("harness_engineering").joinpath(DEFAULT_GOLDEN_RESOURCE)
            with resource.open("rb") as handle:
                raw = handle.read(MAX_GOLDEN_BYTES + 1)
        else:
            with Path(path).open("rb") as handle:
                raw = handle.read(MAX_GOLDEN_BYTES + 1)
    except OSError as exc:
        raise ContractValidationError("Golden set file could not be read.") from exc
    if len(raw) > MAX_GOLDEN_BYTES:
        raise ContractValidationError(f"Golden set exceeds {MAX_GOLDEN_BYTES} bytes.")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
        golden = GoldenSet.model_validate(_freeze(document))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        # ValidationError and JSONDecodeError are ValueErrors; no content is echoed.
        raise ContractValidationError("Golden set does not satisfy the contract.") from exc
    return LoadedGoldenSet(
        golden=golden,
        sha256=hashlib.sha256(raw).hexdigest(),
        source="packaged" if path is None else "reviewer_file",
    )


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate JSON keys are ambiguous.")
    return dict(pairs)


def _freeze(value: object) -> object:
    """Bound parsed nesting before recursive immutable normalization."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, (list, tuple, dict)):
            if depth >= MAX_VALUE_DEPTH:
                raise ContractValidationError("Evaluation data exceeds the nesting safety bound.")
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in children)
    try:
        return _freeze_bounded(value)
    except RecursionError as exc:
        raise ContractValidationError("Evaluation data could not be normalized safely.") from exc


def _freeze_bounded(value: object) -> object:
    """Normalize only after the iterative depth guard has succeeded."""
    if isinstance(value, list):
        return tuple(_freeze_bounded(item) for item in value)
    if isinstance(value, dict):
        return {key: _freeze_bounded(item) for key, item in value.items()}
    return value


def observation(**values: object) -> Observation:
    """Build a validated observation from trusted probe facts.

    Raises:
        ContractValidationError: If a probe produced an unsupported or unbounded value.
    """
    try:
        return Observation(values={key: _freeze(value) for key, value in values.items()})
    except (ValidationError, RecursionError) as exc:
        raise ContractValidationError(
            "Probe observation violates the evaluation contract."
        ) from exc


class MismatchKind(StrEnum):
    """Finite regression difference categories."""

    CHANGED = "changed"
    MISSING = "missing"
    UNEXPECTED = "unexpected"


class Mismatch(EvaluationData):
    """One field-level difference between retained and observed behavior."""

    field: FieldName
    kind: MismatchKind
    expected: Value = None
    observed: Value = None


def compare(expected: Observation, observed: Observation) -> tuple[Mismatch, ...]:
    """Compare retained and observed facts exactly and deterministically.

    Args:
        expected: Retained golden expectation.
        observed: Fresh observation from the trusted probe.

    Returns:
        Field-level mismatches in sorted field order; empty means no regression.
    """
    left, right = expected.values, observed.values
    result: list[Mismatch] = []
    for name in sorted(set(left) | set(right)):
        if name not in right:
            result.append(Mismatch(field=name, kind=MismatchKind.MISSING, expected=left[name]))
        elif name not in left:
            result.append(Mismatch(field=name, kind=MismatchKind.UNEXPECTED,
                                   observed=right[name]))
        elif not _same(left[name], right[name]):
            result.append(Mismatch(field=name, kind=MismatchKind.CHANGED,
                                   expected=left[name], observed=right[name]))
    return tuple(result)


def _same(left: Value, right: Value) -> bool:
    """Exact typed equality: True never equals 1, and order matters."""
    if isinstance(left, tuple) or isinstance(right, tuple):
        return (isinstance(left, tuple) and isinstance(right, tuple) and len(left) == len(right)
                and all(_same(a, b) for a, b in zip(left, right, strict=True)))
    return type(left) is type(right) and left == right


class CaseStatus(StrEnum):
    """Case verdicts; only PASSED is success."""

    PASSED = "passed"
    REGRESSED = "regressed"
    ERROR = "error"


class CaseResult(EvaluationData):
    """Reviewer- and machine-readable result for one golden case."""

    case_id: CaseID
    area: EvaluationArea
    requirements: tuple[RequirementID, ...] = Field(min_length=1, max_length=12)
    purpose: Text
    evidence: tuple[EvidenceClass, ...] = Field(min_length=1, max_length=2)
    status: CaseStatus
    mismatches: tuple[Mismatch, ...] = Field(max_length=2 * MAX_OBSERVATION_FIELDS)
    error_type: Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")] | None
    duration_seconds: Annotated[float, Field(ge=0, le=600, allow_inf_nan=False)]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Keep status, mismatches, error and evidence provenance consistent."""
        if not set(self.evidence) <= PERMITTED_EVIDENCE:
            raise ValueError("Regression evidence cannot claim live or deployment evidence.")
        if (self.status is CaseStatus.ERROR) != (self.error_type is not None):
            raise ValueError("Only error results carry an error type.")
        if (self.status is CaseStatus.REGRESSED) != bool(self.mismatches):
            raise ValueError("Only regressed results carry mismatches.")
        return self


class RegressionReport(EvaluationData):
    """Complete regression run against retained golden expectations."""

    golden_name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
    golden_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    golden_source: Literal["packaged", "reviewer_file"]
    evidence: tuple[EvidenceClass, ...] = Field(min_length=1, max_length=2)
    cases: tuple[CaseResult, ...] = Field(min_length=1, max_length=MAX_GOLDEN_CASES)
    passed: int = Field(ge=0, le=MAX_GOLDEN_CASES)
    regressed: int = Field(ge=0, le=MAX_GOLDEN_CASES)
    errors: int = Field(ge=0, le=MAX_GOLDEN_CASES)
    succeeded: bool
    workflow_latency: LatencyReport
    limitations: tuple[Text, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Derive verdict and evidence from case results, never from caller labels."""
        statuses = [case.status for case in self.cases]
        if (self.passed, self.regressed, self.errors) != (
            statuses.count(CaseStatus.PASSED), statuses.count(CaseStatus.REGRESSED),
            statuses.count(CaseStatus.ERROR),
        ):
            raise ValueError("Report totals must match case results.")
        if self.succeeded != (self.passed == len(self.cases)):
            raise ValueError("Success requires every case to pass.")
        derived = {item for case in self.cases for item in case.evidence}
        if set(self.evidence) != derived or len(set(self.evidence)) != len(self.evidence):
            raise ValueError("Report evidence must equal the union of case evidence.")
        if self.workflow_latency.cohort.evidence is not EvidenceClass.DETERMINISTIC:
            raise ValueError("Workflow latency evidence must remain deterministic.")
        return self
