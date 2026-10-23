"""Versioned regression baseline: loading, exact comparisons and reporting.

Regression decisions are computed entirely locally before any export and never
depend on, wait for or change because of a LangSmith response. Only a complete
run with verdict pass may become a baseline, and only through a human commit
after review; candidate artifacts are written exclusively to caller-supplied
paths outside the repository.
"""

import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from .errors import ContractValidationError
from .evaluation_contracts import (
    EVALUATOR_IDS,
    METRIC_BY_EVALUATOR,
    BaselineEntry,
    BaselineRecord,
    Completeness,
    RegressionFinding,
    RegressionKind,
    RegressionOutcome,
    RegressionReport,
    RunResult,
    ScenarioEvaluation,
    ThresholdPolicy,
    Verdict,
    canonical_digest,
    canonical_json,
)
from .evaluation_dataset import DatasetView
from .evaluation_evaluators import EVALUATOR_SUITE_VERSION

BASELINE_SCHEMA_VERSION: Final = 1
COMMITTED_BASELINE_VERSION: Final = 1
BASELINE_TARGET_ID: Final = "reference_default"
BASELINE_TARGET_VERSION: Final = 1

_BASELINE_DIGESTS: Final[dict[int, str]] = {}
"""Digest over canonical baseline content excluding the digest field itself,
pinned in application code per baseline version; populated below."""

# v1: module7-baseline-v1.json, generated from the deterministic passing
# reference run over the committed dataset version (no provider involvement).
_BASELINE_DIGESTS[COMMITTED_BASELINE_VERSION] = (
    "82a1a4af465d19835bd0fabe4df47f248ec201e51bed9b1a1455d31e249acd01"
)

_MODULE_ROOT: Final = Path(__file__).resolve().parents[2]


def baseline_digest(content: Mapping[str, object]) -> str:
    """Return the SHA-256 digest of canonical baseline content minus its digest.

    Args:
        content: The candidate baseline content mapping.

    Returns:
        The SHA-256 hex digest over the canonical serialization of the mapping
        after removing the ``baseline_digest`` field.
    """
    normalized = {
        key: value for key, value in content.items() if key != "baseline_digest"
    }
    return canonical_digest(normalized)


def load_committed_baseline(dataset: DatasetView) -> BaselineRecord:
    """Load and validate the committed baseline for one dataset version.

    Args:
        dataset: The validated committed dataset view.

    Returns:
        The validated, digest-verified committed baseline record.

    Raises:
        ContractValidationError: For any corruption, version, digest or
            coverage defect, naming the defect class only.
    """
    if dataset.dataset_version != COMMITTED_BASELINE_VERSION:
        raise ContractValidationError(
            "No committed baseline exists for this dataset version."
        )
    files = resources.files(__package__) / "evaluation_data"
    source = files / f"module7-baseline-v{dataset.dataset_version}.json"
    try:
        parsed = json.loads(source.read_bytes().decode("utf-8-sig"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise ContractValidationError(
            "Committed baseline is unreadable or malformed; refusing it."
        ) from exc
    try:
        record = BaselineRecord.model_validate(parsed)
    except ValidationError as exc:
        raise ContractValidationError(
            "Committed baseline violates the baseline schema."
        ) from exc
    digest = baseline_digest(parsed)
    if record.baseline_digest != digest:
        raise ContractValidationError(
            "Committed baseline digest does not match its canonical content."
        )
    pinned = _BASELINE_DIGESTS.get(COMMITTED_BASELINE_VERSION)
    if pinned is None or pinned != digest:
        raise ContractValidationError(
            "Committed baseline digest is not pinned in application code."
        )
    if record.dataset_id != dataset.dataset_id:
        raise ContractValidationError("Baseline dataset identifier mismatch.")
    if record.dataset_version != dataset.dataset_version:
        raise ContractValidationError("Baseline dataset version mismatch.")
    if record.dataset_digest != dataset.digest:
        raise ContractValidationError("Baseline dataset digest mismatch.")
    if record.evaluator_suite_version != EVALUATOR_SUITE_VERSION:
        raise ContractValidationError("Baseline evaluator suite version mismatch.")
    versions = record.evaluator_versions
    if set(versions) != set(EVALUATOR_IDS) or any(
        versions.get(item) != EVALUATOR_SUITE_VERSION for item in EVALUATOR_IDS
    ):
        raise ContractValidationError("Baseline evaluator versions mismatch.")
    if (
        record.target_id != BASELINE_TARGET_ID
        or record.target_version != BASELINE_TARGET_VERSION
    ):
        raise ContractValidationError("Baseline target identity mismatch.")
    _validate_baseline_coverage(record, dataset)
    return record


def _validate_baseline_coverage(record: BaselineRecord, dataset: DatasetView) -> None:
    """Verify every dataset scenario/evaluator pair has exactly one entry.

    Args:
        record: The validated baseline record.
        dataset: The validated committed dataset view.

    Raises:
        ContractValidationError: For repeated, unknown or absent entries.
    """
    expected: set[tuple[str, str, str]] = set()
    for scenario in dataset.scenarios:
        for evaluator_id in scenario.evaluators:
            expected.add(
                (scenario.scenario_id, evaluator_id, METRIC_BY_EVALUATOR[evaluator_id])
            )
    seen: set[tuple[str, str, str]] = set()
    for entry in record.scores:
        key = (entry.scenario_id, entry.evaluator_id, entry.metric)
        if key in seen:
            raise ContractValidationError("Baseline repeats a metric entry.")
        if key not in expected:
            raise ContractValidationError("Baseline contains an unexpected metric entry.")
        seen.add(key)
    if seen != expected:
        raise ContractValidationError("Baseline is missing committed metric entries.")


def _baseline_integrity(baseline: BaselineRecord) -> set[str]:
    """Verify the baseline record's own integrity before any comparison.

    A caller-supplied candidate baseline is never trusted on its face: its
    digest is recomputed over its canonical content and its entries are
    checked for duplicates, unknown evaluators and metric renames, so a
    tampered, stale, repeated or reshaped baseline yields an
    ``incompatible_baseline`` report without any per-metric comparison.

    Args:
        baseline: The baseline record proposed for comparison.

    Returns:
        The set of unusable baseline field/defect names.
    """
    defects: set[str] = set()
    computed = baseline_digest(baseline.model_dump(mode="json"))
    if baseline.baseline_digest != computed:
        defects.add("baseline_digest")
    seen: set[tuple[str, str, str]] = set()
    for entry in baseline.scores:
        key = (entry.scenario_id, entry.evaluator_id, entry.metric)
        if key in seen:
            defects.add("baseline_metric_coverage")
        if (
            entry.evaluator_id not in EVALUATOR_IDS
            or METRIC_BY_EVALUATOR.get(entry.evaluator_id) != entry.metric
        ):
            defects.add("baseline_metric_identity")
        seen.add(key)
    entries = {(entry.scenario_id, entry.evaluator_id) for entry in baseline.scores}
    if len(entries) != len(baseline.scores):
        defects.add("baseline_metric_coverage")
    return defects


def _incompatible_fields(run: RunResult, baseline: BaselineRecord) -> set[str]:
    """Collect identity field names that differ; never their values.

    Args:
        run: The compared run result.
        baseline: The digest-verified committed baseline record.

    Returns:
        Differing field names; a target identity difference is the comparison
        itself and is never an incompatibility.
    """
    names: set[str] = set()
    identity = run.identity
    if baseline.baseline_schema_version != BASELINE_SCHEMA_VERSION:
        names.add("baseline_schema_version")
    if baseline.dataset_id != identity.dataset_id:
        names.add("dataset_id")
    if baseline.dataset_version != identity.dataset_version:
        names.add("dataset_version")
    if baseline.dataset_digest != identity.dataset_digest:
        names.add("dataset_digest")
    if baseline.evaluator_suite_version != identity.evaluator_suite_version:
        names.add("evaluator_suite_version")
    if baseline.threshold_policy_version != identity.threshold_policy_version:
        names.add("threshold_policy_version")
    for evaluator_id in EVALUATOR_IDS:
        if baseline.evaluator_versions.get(evaluator_id) != identity.evaluator_suite_version:
            names.add("evaluator_versions")
            break
    return names


def compare_to_baseline(
    run: RunResult,
    baseline: BaselineRecord,
    dataset: DatasetView,
    policy: ThresholdPolicy,
) -> RegressionReport:
    """Compare a run result to a compatible baseline with exact semantics.

    Args:
        run: The class A run result to compare.
        baseline: The digest-verified baseline record (loader or candidate).
        dataset: The committed dataset view (category facts for findings).
        policy: The committed threshold policy for exact metric thresholds.

    Returns:
        The deterministic regression report; the decision of record. No
        per-metric comparison exists when the baseline is incompatible.

    Raises:
        ContractValidationError: For a malformed comparison input.

    Notes:
        A run whose scenario set is below its baseline's scenario coverage is
        handled at runtime: any baseline entry not evaluated in this run is
        reported as a ``missing`` regression. A current-only scenario is
        refused as ``incompatible_baseline`` without any comparison.
    """
    incompatible = _baseline_integrity(baseline)
    incompatible |= _incompatible_fields(run, baseline)
    common = {
        "dataset_id": baseline.dataset_id,
        "dataset_version": baseline.dataset_version,
        "dataset_digest": baseline.dataset_digest,
        "evaluator_suite_version": baseline.evaluator_suite_version,
        "threshold_policy_version": baseline.threshold_policy_version,
        "baseline_target_id": baseline.target_id,
        "baseline_target_version": baseline.target_version,
        "current_target_id": run.identity.target_id,
        "current_target_version": run.identity.target_version,
    }
    if incompatible:
        return RegressionReport(
            outcome=RegressionOutcome.INCOMPATIBLE_BASELINE,
            incompatible_fields=tuple(sorted(incompatible)),
            findings=(),
            **common,
        )
    baseline_rows: dict[tuple[str, str], BaselineEntry] = {
        (entry.scenario_id, entry.evaluator_id): entry for entry in baseline.scores
    }
    run_rows: dict[tuple[str, str], ScenarioEvaluation] = {
        (row.scenario_id, row.evaluator_id): row for row in run.evaluations
    }
    extra_current = set(run_rows) - set(baseline_rows)
    if extra_current:
        return RegressionReport(
            outcome=RegressionOutcome.INCOMPATIBLE_BASELINE,
            incompatible_fields=("current_only_metrics",),
            findings=(),
            **common,
        )
    findings: list[RegressionFinding] = []
    for row_key in sorted(baseline_rows):
        finding = _finding(
            row_key, baseline_rows[row_key], run_rows, dataset, policy, baseline
        )
        if finding is not None:
            findings.append(finding)
    regressed = any(
        finding.kind in {RegressionKind.REGRESSED, RegressionKind.MISSING}
        for finding in findings
    )
    return RegressionReport(
        outcome=RegressionOutcome.FAIL if regressed else RegressionOutcome.PASS,
        findings=tuple(findings),
        **common,
    )


def _finding(
    row_key: tuple[str, str],
    entry: BaselineEntry,
    run_rows: Mapping[tuple[str, str], ScenarioEvaluation],
    dataset: DatasetView,
    policy: ThresholdPolicy,
    baseline: BaselineRecord,
) -> RegressionFinding | None:
    """Build one comparison finding, or None for an unchanged entry.

    Args:
        row_key: The (scenario, evaluator) compared pair.
        entry: The committed baseline entry.
        run_rows: The current run evaluation rows by (scenario, evaluator).
        dataset: The committed dataset view.
        policy: The committed threshold policy.
        baseline: The digest-verified baseline record.

    Returns:
        A missing, regressed or improved finding; None for unchanged.
    """
    scenario_id, evaluator_id = row_key
    row = run_rows.get(row_key)
    if row is None:
        category = dataset.get(scenario_id).category
        return RegressionFinding(
            scenario_id=scenario_id,
            category=category,
            evaluator_id=evaluator_id,
            evaluator_version=baseline.evaluator_versions[evaluator_id],
            metric=entry.metric,
            baseline_score=entry.score,
            baseline_passed=entry.passed,
            current_score=None,
            threshold=_entry_threshold(entry.metric, policy),
            kind=RegressionKind.MISSING,
        )
    if row.score < entry.score or (entry.passed and not row.passed):
        kind = RegressionKind.REGRESSED
    elif row.score > entry.score:
        kind = RegressionKind.IMPROVED
    else:
        kind = RegressionKind.UNCHANGED
    if kind is RegressionKind.UNCHANGED:
        return None
    return RegressionFinding(
        scenario_id=scenario_id,
        category=row.category,
        evaluator_id=evaluator_id,
        evaluator_version=row.evaluator_version,
        metric=entry.metric,
        baseline_score=entry.score,
        baseline_passed=entry.passed,
        current_score=row.score,
        threshold=(row.threshold[0], row.threshold[1]),
        kind=kind,
    )


def _entry_threshold(metric: str, policy: ThresholdPolicy) -> tuple[int, int]:
    """Return the exact committed threshold pair for one metric.

    Args:
        metric: The compared metric name.
        policy: The committed threshold policy.

    Returns:
        The exact (numerator, denominator) threshold pair.
    """
    threshold = policy.metric_threshold(metric)
    return (threshold.numerator, threshold.denominator)


def candidate_baseline(run: RunResult, path: Path) -> Path:
    """Write one candidate baseline artifact to a caller-supplied external path.

    Only a complete run with verdict pass may produce a candidate; the system
    never writes into the repository and never commits a baseline.

    Args:
        run: The class A run result.
        path: A caller-supplied write path outside the repository.

    Returns:
        The written path.

    Raises:
        ContractValidationError: When the run is not a committable baseline
            candidate, or the path lies inside the repository.
    """
    _refuse_repository_path(path)
    if run.completeness is not Completeness.COMPLETE:
        raise ContractValidationError(
            "Only complete runs can become baseline candidates."
        )
    if run.verdict is not Verdict.PASS:
        raise ContractValidationError(
            "Only passing runs can become baseline candidates."
        )
    entries = sorted(
        (
            BaselineEntry(
                scenario_id=row.scenario_id,
                evaluator_id=row.evaluator_id,
                metric=row.metric,
                score=row.score,
                passed=row.passed,
            )
            for row in run.evaluations
        ),
        key=lambda entry: (entry.scenario_id, entry.evaluator_id, entry.metric),
    )
    content: dict[str, object] = {
        "baseline_schema_version": BASELINE_SCHEMA_VERSION,
        "dataset_id": run.identity.dataset_id,
        "dataset_version": run.identity.dataset_version,
        "dataset_digest": run.identity.dataset_digest,
        "evaluator_suite_version": run.identity.evaluator_suite_version,
        "evaluator_versions": {
            evaluator_id: run.identity.evaluator_suite_version
            for evaluator_id in sorted(row.evaluator_id for row in run.evaluations)
        },
        "threshold_policy_version": run.identity.threshold_policy_version,
        "target_id": run.identity.target_id,
        "target_version": run.identity.target_version,
        "scores": [json.loads(entry.model_dump_json()) for entry in entries],
    }
    content["baseline_digest"] = baseline_digest(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(content), encoding="utf-8")
    return path


def _refuse_repository_path(path: Path) -> None:
    """Refuse write paths inside the module repository.

    Args:
        path: Candidate write path.

    Raises:
        ContractValidationError: If the path is inside the repository.
    """
    resolved = path.resolve()
    if resolved == _MODULE_ROOT or _MODULE_ROOT in resolved.parents:
        raise ContractValidationError(
            "Candidate baselines are never written inside the repository."
        )


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "COMMITTED_BASELINE_VERSION",
    "baseline_digest",
    "candidate_baseline",
    "compare_to_baseline",
    "load_committed_baseline",
]
