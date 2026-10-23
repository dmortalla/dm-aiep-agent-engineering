"""Deterministic benchmark execution: canonical reports and declared subsets.

Two runs with identical inputs produce byte-identical canonical reports and
identical SHA-256 digests; no wall-clock data enters the digested content.
Deterministic benchmark reports are ``deterministic_fixture``; scenarios with
injected failures keep ``scenario_evidence=simulated_failure``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from .evaluation_contracts import (
    BaselineRecord,
    RegressionOutcome,
    RegressionReport,
    RunArtifact,
    RunResult,
    Verdict,
    canonical_digest,
    canonical_json,
)
from .evaluation_dataset import DatasetView
from .evaluation_engine import EvaluationEngine
from .evaluation_regression import compare_to_baseline
from .evaluation_target import ScenarioCorrelation

# Benchmarks enforce an explicitly declared subset for the exported scenario
# selection; unknown truncation of a claimed full-run report is refused.
MAX_EXPORTED_SCENARIOS: Final = 64

TargetFactory = Callable[[dict[str, ScenarioCorrelation]], object]


@dataclass(frozen=True)
class BenchmarkOutput:
    """Immutable outcome of one deterministic benchmark execution.

    Attributes:
        run: The bounded run artifact with its evaluation telemetry records.
        subset: Declared exported scenario selection; None means full.
        regression: Local regression report when a baseline was supplied.
        report_json: Canonical UTF-8 JSON benchmark report.
        report_digest: SHA-256 digest of the canonical benchmark report.
        verdict: Final application verdict, including baseline comparison.
    """

    run: RunArtifact
    subset: tuple[str, ...] | None
    regression: RegressionReport | None
    report_json: str
    report_digest: str
    verdict: Verdict


def run_report(run: RunResult) -> dict[str, object]:
    """Project one run result into its canonical JSON-ready record."""
    return run.model_dump(mode="json")


def benchmark_report(
    run: RunArtifact, subset: tuple[str, ...] | None,
    regression: RegressionReport | None,
) -> str:
    """Serialize the canonical benchmark report over already-decided facts.

    Args:
        run: The bounded run artifact.
        subset: The explicitly declared subset or None for a full run.
        regression: The local regression report or None.

    Returns:
        Canonical UTF-8 JSON with sorted keys and no wall-clock fields.
    """
    return canonical_json({
        "run": run_report(run.result),
        "subset": list(subset) if subset is not None else None,
        "regression": (
            regression.model_dump(mode="json") if regression is not None else None
        ),
    })


def select_export_subset(
    dataset: DatasetView, limit: int
) -> tuple[str, ...] | None:
    """Return the first N canonical scenarios, or None for a full dataset.

    Args:
        dataset: The validated committed dataset view.
        limit: Explicitly configured exported-scenario limit; the ceiling is
            64 and the selection is recorded as a declared subset.

    Returns:
        The declared subset identifiers, or None when the limit covers all.

    Raises:
        ValueError: For a non-positive or oversize limit.
    """
    if not 1 <= limit <= MAX_EXPORTED_SCENARIOS:
        raise ValueError("Export limits require 1 <= limit <= 64.")
    if limit >= len(dataset.scenario_ids):
        return None
    return tuple(sorted(dataset.scenario_ids)[:limit])


class BenchmarkRunner:
    """Human-independent deterministic benchmark execution over a dataset."""

    def __init__(self, engine: EvaluationEngine) -> None:
        """Bind a committed evaluation engine to the runner.

        Args:
            engine: The bounded deterministic evaluation engine.
        """
        self._engine = engine

    async def run_full(
        self,
        dataset: DatasetView,
        *,
        target_factory: TargetFactory,
        target_id: str,
        target_version: int,
        run_ordinal: int = 0,
        baseline: BaselineRecord | None = None,
    ) -> BenchmarkOutput:
        """Run the complete versioned dataset in canonical scenario order.

        Args:
            dataset: The validated committed dataset view.
            target_factory: Deterministic system-under-evaluation factory.
            target_id: Target identity used by the run identity.
            target_version: Target version used by the run identity.
            run_ordinal: Caller-supplied nonnegative run ordinal.
            baseline: Optional digest-verified baseline to compare against.

        Returns:
            The benchmark output with its canonical report and final verdict.
        """
        artifact = await self._engine.run(
            dataset,
            target_id=target_id,
            target_version=target_version,
            target_factory=target_factory,
            run_ordinal=run_ordinal,
        )
        return self._report(artifact, None, dataset, baseline)

    def _report(
        self,
        artifact: RunArtifact,
        subset: tuple[str, ...] | None,
        dataset: DatasetView,
        baseline: BaselineRecord | None,
    ) -> BenchmarkOutput:
        """Compute the regression report, canonical report and final verdict."""
        regression: RegressionReport | None = None
        if baseline is not None:
            regression = compare_to_baseline(
                artifact.result,
                baseline,
                dataset,
                self._engine.policy,
            )
        report = benchmark_report(artifact, subset, regression)
        verdict = artifact.result.verdict
        if regression is not None and regression.outcome is not RegressionOutcome.PASS:
            verdict = Verdict.FAIL
        return BenchmarkOutput(
            run=artifact,
            subset=subset,
            regression=regression,
            report_json=report,
            report_digest=canonical_digest(report),
            verdict=verdict,
        )


__all__ = [
    "MAX_EXPORTED_SCENARIOS",
    "BenchmarkOutput",
    "BenchmarkRunner",
    "benchmark_report",
    "select_export_subset",
]
