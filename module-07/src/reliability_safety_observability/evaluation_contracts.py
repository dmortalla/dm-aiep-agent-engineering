"""Typed evaluation contracts for Story 6 automated evaluation.

Application-owned, immutable, primitive-only records with canonical JSON
serialization. LangSmith and Langfuse SDK types never appear here; vendor
deliverables live only in their narrow adapters. Application evaluation
results (class A) are always ``deterministic_fixture`` and are never upgraded
by vendor confirmation, a live run, configuration or caller assertion.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from typing import Final, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import MAX_COUNTER, Decision, EvaluationResult, EvidenceClass
from .telemetry import Code

MODULE7_EVALUATION_NAMESPACE: Final = UUID("ade9b2ab-5b31-5407-ada0-dd5ba009c488")
"""Fixed application namespace for every deterministic Story 6 identifier."""

# Minimum deterministic evaluator suite (fixed evaluator identifier vocabulary).
EVALUATOR_IDS: Final = (
    "outcome.classification_exact",
    "reliability.attempt_accounting",
    "idempotency.effect_count",
    "authority.no_unauthorized_effect",
    "cost.budget_respected",
    "redaction.canary_absent",
)
METRIC_BY_EVALUATOR: Final[Mapping[str, str]] = {
    "outcome.classification_exact": "classification_match",
    "reliability.attempt_accounting": "attempts_match",
    "idempotency.effect_count": "effect_count_match",
    "authority.no_unauthorized_effect": "authority_preserved",
    "cost.budget_respected": "budget_respected",
    "redaction.canary_absent": "canary_absent",
}


class Category(StrEnum):
    """Fixed benchmark scenario categories."""

    RELIABILITY = "reliability"
    IDEMPOTENCY = "idempotency"
    COST = "cost"
    AUTHORIZATION = "authorization"
    SAFETY_INJECTION = "safety_injection"
    REDACTION = "redaction"


CATEGORIES: Final = tuple(Category)


class EvaluationStatus(StrEnum):
    """Per-evaluation execution status recorded by the engine."""

    EVALUATED = "evaluated"
    EVALUATOR_ERROR = "evaluator_error"
    MALFORMED_RESULT = "malformed_result"
    NOT_RUN = "not_run"


class Completeness(StrEnum):
    """Run completeness over the declared scenario set."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class Verdict(StrEnum):
    """Application-owned pass/fail verdict; never supplied by a vendor."""

    PASS = "pass"
    FAIL = "fail"


class BudgetOutcome(StrEnum):
    """Fixed-vocabulary budget outcome recorded from application facts."""

    WITHIN_BUDGET = "within_budget"
    BUDGET_EXHAUSTED = "budget_exhausted"


class RegressionKind(StrEnum):
    """Per-metric comparison outcome against a compatible baseline."""

    REGRESSED = "regressed"
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    MISSING = "missing"


class RegressionOutcome(StrEnum):
    """Regression evaluation outcome; never derived from vendor responses."""

    PASS = "pass"
    FAIL = "fail"
    INCOMPATIBLE_BASELINE = "incompatible_baseline"
    NOT_COMPARABLE = "not_comparable"


class ImprovementDecision(StrEnum):
    """Improvement decisions are never set automatically."""

    PENDING_HUMAN_REVIEW = "pending_human_review"


class CycleStatus(StrEnum):
    """Improvement-cycle comparability status."""

    COMPARABLE = "comparable"
    NOT_COMPARABLE = "not_comparable"


class ModelEvaluationStatus(StrEnum):
    """Bounded status of an optional model-backed evaluation port."""

    UNAVAILABLE = "unavailable"


OWNING_AREA_BY_CATEGORY: Final[Mapping[str, str]] = {
    "reliability": "story3_reliability_controller_policy",
    "idempotency": "story3_idempotency_protection",
    "cost": "story3_budget_reservation",
    "authorization": "story2_authorization_allowlist",
    "safety_injection": "story2_safety_pipeline",
    "redaction": "story4_telemetry_minimization",
}


def canonical_json(value: object) -> str:
    """Return canonical UTF-8 JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


def canonical_digest(value: object) -> str:
    """Return the SHA-256 digest of the canonical JSON serialization."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def identity_uuid(values: tuple[object, ...]) -> UUID:
    """Return a fixed-namespace UUIDv5 over the canonical serialization of values."""
    normalized = tuple(
        str(item) if isinstance(item, UUID) else item for item in values
    )
    return uuid5(MODULE7_EVALUATION_NAMESPACE, canonical_json(normalized))


def meets_threshold(count: int, total: int, threshold: Fraction) -> bool:
    """Compare pass counts to an exact threshold with integer arithmetic.

    Args:
        count: Passing count.
        total: Considered count.
        threshold: Exact rational pass-rate threshold in [0, 1].

    Returns:
        Whether ``count / total`` meets or exceeds the exact threshold.
    """
    if total <= 0:
        raise ValueError("Threshold comparison requires a positive total.")
    return count * threshold.denominator >= threshold.numerator * total


def score_meets_threshold(score: float, threshold: Fraction) -> bool:
    """Compare one finite score in [0, 1] to an exact rational threshold."""
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("Scores require finite values within [0, 1].")
    if threshold.numerator == 0:
        return True
    return score >= threshold.numerator / threshold.denominator


class ObservedFacts(BaseModel):
    """Bounded fixed-vocabulary observation projection of one scenario run.

    Attributes:
        classification: Observed Story 2/3 outcome code.
        attempts: Observed invocation attempts.
        fallbacks: Observed fallback switches.
        replayed: Whether the runner observed a duplicate-key replay.
        effect_count: Observed side-effect invocation count.
        authorization: Observed final authorization decision, if any.
        safety: Observed final safety decision, if any.
        budget_used_usd: Observed budget cost used.
        budget_limit_usd: Observed budget cost limit.
        budget_outcome: Observed budget outcome.
        canaries_observed: Canary identifiers found in captured records.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    classification: Code
    attempts: int = Field(default=0, ge=0, le=MAX_COUNTER)
    fallbacks: int = Field(default=0, ge=0, le=MAX_COUNTER)
    replayed: bool = False
    effect_count: int = Field(default=0, ge=0, le=MAX_COUNTER)
    authorization: Decision | None = None
    safety: Decision | None = None
    budget_used_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    budget_limit_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    budget_outcome: BudgetOutcome = BudgetOutcome.WITHIN_BUDGET
    canaries_observed: tuple[str, ...] = ()


class ExpectedFacts(BaseModel):
    """Typed expected facts authored from accepted Story 2-4 semantics.

    Expected facts are labels, not evaluator semantics: no dataset field can
    define or alter evaluator behavior, thresholds or regression policy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    classification: Code
    attempts: int = Field(default=0, ge=0, le=MAX_COUNTER)
    fallbacks: int = Field(default=0, ge=0, le=MAX_COUNTER)
    replayed: bool = False
    effect_count: int = Field(default=0, ge=0, le=MAX_COUNTER)
    authorization: Decision = Decision.ALLOW
    safety: Decision = Decision.ALLOW
    budget_outcome: BudgetOutcome = BudgetOutcome.WITHIN_BUDGET
    absent_canaries: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThresholdPolicy:
    """Committed, versioned evaluation thresholds and criticality policy.

    Thresholds are exact rationals compared with integer arithmetic; no
    provider output, dataset field, evaluator output, environment variable or
    evaluation result can alter this policy.
    """

    policy_version: int
    metric_thresholds: Mapping[str, Fraction] = field(default_factory=dict)
    category_thresholds: Mapping[str, Fraction] = field(default_factory=dict)
    critical_categories: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for _name, thresholds in (
            ("thresholds", self.metric_thresholds | self.category_thresholds),
        ):
            for key, value in thresholds.items():
                if not isinstance(key, str) or not key:
                    raise ValueError("Threshold keys must be non-empty identifiers.")
                if not isinstance(value, Fraction) or not 0 <= value <= 1:
                    raise ValueError("Thresholds require exact fractions within [0, 1].")

    @staticmethod
    def committed() -> "ThresholdPolicy":
        """Return the committed defaults; changes require a policy version bump."""
        return ThresholdPolicy(
            policy_version=1,
            metric_thresholds={metric: Fraction(1) for metric in
                               METRIC_BY_EVALUATOR.values()},
            category_thresholds={category: Fraction(1) for category in CATEGORIES},
            critical_categories=frozenset(
                {"authorization", "safety_injection", "redaction"}
            ),
        )

    def metric_threshold(self, metric: str) -> Fraction:
        """Return the exact threshold for one evaluated metric."""
        threshold = self.metric_thresholds.get(metric)
        if threshold is None:
            raise ValueError(f"No committed threshold for metric {metric!r}.")
        return threshold

    def category_threshold(self, category: str) -> Fraction:
        """Return the exact aggregate pass-rate threshold for one category."""
        threshold = self.category_thresholds.get(category)
        if threshold is None:
            raise ValueError(f"No committed threshold for category {category!r}.")
        return threshold

    def is_critical(self, category: str) -> bool:
        """Return whether one failure in the category fails the run."""
        return category in self.critical_categories


class RunIdentity(BaseModel):
    """Deterministic run identity derived from committed input identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    dataset_version: int = Field(ge=1)
    dataset_digest: str
    evaluator_suite_version: int = Field(ge=1)
    threshold_policy_version: int = Field(ge=1)
    target_id: str
    target_version: int = Field(ge=1)
    run_ordinal: int = Field(default=0, ge=0, le=MAX_COUNTER)

    def run_id(self) -> UUID:
        """Return the deterministic run identifier (never caller supplied)."""
        return identity_uuid((
            self.dataset_id, self.dataset_version, self.dataset_digest,
            self.evaluator_suite_version, self.threshold_policy_version,
            self.target_id, self.target_version, self.run_ordinal,
        ))


class EvaluationCounts(BaseModel):
    """Integer evaluation counts for one metric or category slice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(default=0, ge=0)
    evaluated: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    errored: int = Field(default=0, ge=0)

    def pass_fraction(self) -> Fraction:
        """Return the exact pass rate; zero totals report a full pass rate."""
        if self.total == 0:
            return Fraction(1)
        return Fraction(self.passed, self.total)


class ScenarioEvaluation(BaseModel):
    """One deterministic evaluator result over one scenario.

    Projects losslessly onto the accepted ``domain.EvaluationResult``; the
    frozen domain schema is unchanged and never redefined here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: UUID
    run_id: UUID
    scenario_id: str
    category: Category
    workflow_id: UUID
    trace_id: UUID
    action_id: UUID
    evaluator_id: str
    evaluator_version: int = Field(ge=1)
    metric: str
    score: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    threshold: tuple[int, int]
    passed: bool
    status: EvaluationStatus
    critical: bool = False
    evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_FIXTURE
    scenario_evidence: EvidenceClass = EvidenceClass.DETERMINISTIC_FIXTURE
    observed: ObservedFacts = Field(default_factory=ObservedFacts)

    @model_validator(mode="after")
    def validate_consistency(self) -> "ScenarioEvaluation":
        """Enforce applied evidence classes and engine-computed pass outcomes.

        Returns:
            The validated evaluation.

        Raises:
            ValueError: If class A evidence is upgraded or pass tracking is
                inconsistent with the threshold.
        """
        if self.evidence_class is not EvidenceClass.DETERMINISTIC_FIXTURE:
            raise ValueError("Class A evaluation evidence is always deterministic.")
        if self.scenario_evidence not in {
            EvidenceClass.DETERMINISTIC_FIXTURE,
            EvidenceClass.SIMULATED_FAILURE,
        }:
            raise ValueError("Scenario evidence is a fixture or a simulated failure.")
        numerator, denominator = self.threshold
        if denominator <= 0 or numerator < 0 or numerator > denominator:
            raise ValueError("Thresholds require valid exact fractions.")
        expected_pass = score_meets_threshold(self.score, Fraction(*self.threshold))
        if self.status is EvaluationStatus.EVALUATED and self.passed != expected_pass:
            raise ValueError("Pass outcome must follow the engine threshold check.")
        if self.status is EvaluationStatus.EVALUATED:
            if self.score == 0.0 and self.passed and Fraction(*self.threshold) > 0:
                raise ValueError("A zero score cannot pass a positive threshold.")
        else:
            if self.passed or self.score:
                raise ValueError("Non-evaluated results score 0.0 and never pass.")
        return self

    def project(self) -> EvaluationResult:
        """Project onto the accepted provider-neutral evaluation contract."""
        return EvaluationResult(
            evaluator=self.evaluator_id,
            metric=self.metric,
            score=self.score,
            passed=self.passed,
            evidence_class=self.evidence_class,
        )


class RunAggregate(BaseModel):
    """Bounded integer aggregates over one run result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_counts: Mapping[str, EvaluationCounts] = Field(default_factory=dict)
    category_counts: Mapping[str, EvaluationCounts] = Field(default_factory=dict)


class RunResult(BaseModel):
    """Immutable deterministic evaluation run result (class A evidence).

    Attributes:
        identity: The committed identity tuple this run derives from.
        run_id: The deterministic run identifier.
        evaluations: Ordered per-evaluator results in canonical order.
        aggregate: Integer per-metric and per-category counts.
        missing_scenario_ids: Scenarios not run or errored at the target.
        completeness: Complete means every scenario every evaluator evaluated.
        verdict: Application pass/fail verdict without vendor responses.
        cost_used_usd: Deterministic runs bill nothing; live runs account.
        cost_basis: Fixed basis marker; ``none`` for deterministic evidence.
        evidence_class: Always ``deterministic_fixture`` for class A results.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: RunIdentity
    run_id: UUID
    evaluations: tuple[ScenarioEvaluation, ...] = ()
    aggregate: RunAggregate = Field(default_factory=RunAggregate)
    missing_scenario_ids: tuple[str, ...] = ()
    completeness: Completeness
    verdict: Verdict
    cost_used_usd: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    cost_basis: str = "none"
    evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_FIXTURE

    @model_validator(mode="after")
    def validate_consistency(self) -> "RunResult":
        """Enforce evidence and verdict invariants without vendor upgrading.

        Returns:
            The validated run result.

        Raises:
            ValueError: If class A evidence is upgraded or the verdict does not
                follow run completeness and evaluation outcomes exactly.
        """
        if self.evidence_class is not EvidenceClass.DETERMINISTIC_FIXTURE:
            raise ValueError("Class A run evidence is always deterministic.")
        if self.cost_basis not in {"none", "configured_reservation"}:
            raise ValueError("Cost basis must be a fixed accounting vocabulary value.")
        if self.completeness is Completeness.INCOMPLETE and self.verdict is Verdict.PASS:
            raise ValueError("Incomplete runs can never pass.")
        all_pass = all(
            evaluation.passed and evaluation.status is EvaluationStatus.EVALUATED
            for evaluation in self.evaluations
        )
        if self.verdict is Verdict.PASS and not all_pass:
            raise ValueError("A verdict of pass requires every evaluation to pass.")
        if self.verdict is Verdict.FAIL and (
            self.completeness is Completeness.COMPLETE and all_pass
        ):
            raise ValueError("A fully passing complete run cannot fail.")
        return self


class BaselineEntry(BaseModel):
    """One baseline score and pass outcome per scenario and evaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    evaluator_id: str
    metric: str
    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    passed: bool


class BaselineRecord(BaseModel):
    """Committed, digest-pinned baseline for one dataset version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_schema_version: int = Field(ge=1)
    dataset_id: str
    dataset_version: int = Field(ge=1)
    dataset_digest: str
    evaluator_suite_version: int = Field(ge=1)
    evaluator_versions: Mapping[str, int]
    threshold_policy_version: int = Field(ge=1)
    target_id: str
    target_version: int = Field(ge=1)
    scores: tuple[BaselineEntry, ...]
    baseline_digest: str


class RegressionFinding(BaseModel):
    """Identified regression, improvement or missing metric; never a verdict.

    Attributes:
        scenario_id: Regressed scenario identifier.
        category: Scenario category.
        evaluator_id: Evaluator that identified the metric.
        evaluator_version: Suite version of that evaluator.
        metric: Evaluated metric name.
        baseline_score: Compatible baseline score, when evaluated there.
        baseline_passed: Baseline pass outcome, when present.
        current_score: Current run score, when evaluated.
        threshold: Exact committed threshold for the metric.
        kind: regressed, improved, unchanged or missing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    category: Category
    evaluator_id: str
    evaluator_version: int = Field(ge=1)
    metric: str
    baseline_score: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False,
    )
    baseline_passed: bool | None = None
    current_score: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False,
    )
    threshold: tuple[int, int]
    kind: RegressionKind


class RegressionReport(BaseModel):
    """Local regression report; the decision of record for regression.

    Attributes:
        outcome: Local outcome from application-only comparison.
        incompatible_fields: Field names (not values) that differed.
        findings: Ordered deterministic comparison findings.
        baseline_target_id: Baseline target identity compared against.
        baseline_target_version: Baseline target version compared against.
        dataset_id / dataset_version / dataset_digest: matching dataset facts.
        evaluator_suite_version/threshold_policy_version: compared versions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: RegressionOutcome
    incompatible_fields: tuple[str, ...] = ()
    findings: tuple[RegressionFinding, ...] = ()
    dataset_id: str = ""
    dataset_version: int = 0
    dataset_digest: str = ""
    evaluator_suite_version: int = 0
    threshold_policy_version: int = 0
    baseline_target_id: str = ""
    baseline_target_version: int = 0
    current_target_id: str = ""
    current_target_version: int = 0


class ImprovementProposal(BaseModel):
    """Non-executable human-review record; the system never applies it.

    Attributes:
        run_id: Run whose failures motivated this proposal.
        scenario_id: Affected scenario.
        category: Affected category.
        evaluator_id: Evaluator that observed the failure.
        evaluator_version: Suite version of that evaluator.
        metric: Evaluated metric.
        threshold: Exact committed threshold.
        observed: Observed fixed-vocabulary facts.
        expected: Expected fixed-vocabulary facts.
        owning_area: Owning application area from the fixed mapping.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    scenario_id: str
    category: Category
    evaluator_id: str
    evaluator_version: int = Field(ge=1)
    metric: str
    threshold: tuple[int, int]
    observed: ObservedFacts
    expected: ExpectedFacts
    owning_area: str


class MetricDelta(BaseModel):
    """One per-metric delta between a before and an after run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    category: Category
    evaluator_id: str
    evaluator_version: int = Field(ge=1)
    metric: str
    before_score: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False,
    )
    after_score: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False,
    )
    kind: RegressionKind


class ImprovementCycle(BaseModel):
    """Immutable human-controlled before/after comparison record.

    Attributes:
        before_run_id / after_run_id: Compared deterministic run identifiers.
        before_report_digest / after_report_digest: Digests of compared runs.
        compatibility: How before and after runs compare.
        deltas: Ordered per-metric deltas.
        new_regressions: Deltas that regressed after the change attempt.
        decision: Always ``pending_human_review``; acceptance is never set here.
        status: comparable or not_comparable; only comparable supports claims.
        evidence_class: Always ``deterministic_fixture``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    before_run_id: UUID
    before_report_digest: str
    after_run_id: UUID
    after_report_digest: str
    compatibility: RegressionOutcome
    deltas: tuple[MetricDelta, ...] = ()
    new_regressions: tuple[MetricDelta, ...] = ()
    decision: ImprovementDecision = ImprovementDecision.PENDING_HUMAN_REVIEW
    status: CycleStatus = CycleStatus.COMPARABLE
    evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_FIXTURE


class ModelEvaluationRecord(BaseModel):
    """Optional model-backed port record; unavailable statuses report no score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluator_id: str
    evaluator_version: int = Field(ge=1)
    metric: str
    status: ModelEvaluationStatus
    score: None = None


@dataclass(frozen=True)
class EvaluationTargetDefinition:
    """Identity snapshot of a testable system-under-evaluation target."""

    target_id: str
    target_version: int


@dataclass(frozen=True)
class RunArtifact:
    """Run result with its locally emitted evaluation telemetry records.

    Attributes:
        result: Immutable class A run result.
        evaluation_records: Captured local story 4 records for evaluation
            events; local evidence delivery outcomes are non-authoritative.
        pipeline_delivery_counts: Bounded counts of delivery statuses.
    """

    result: RunResult
    evaluation_records: tuple[str, ...] = ()
    pipeline_delivery_counts: Mapping[str, int] = field(default_factory=dict)


class ModelEvaluationPort(Protocol):
    """Optional model-backed evaluator port (class C, never critical).

    Implementations receive only minimized, contained content and report a
    typed status; a live model remains future work requiring approval.
    """

    evaluator_id: str
    evaluator_version: int
    metric: str

    def evaluate(self) -> ModelEvaluationRecord:
        """Return an untrusted typed record validated by the engine."""
        ...
