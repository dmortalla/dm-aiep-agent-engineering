"""Deterministic evaluation engine: sequential scenario runs and verdicts.

The engine runs scenarios sequentially in canonical order (concurrency 1),
enforces per-scenario timeouts and a run deadline, catches failures only at
the evaluator and target boundaries, and records fixed safe status codes. No
exception text, traceback, raw input or raw output enters any result. It never
calls a model or a vendor.
"""

import asyncio
import math
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Final
from uuid import UUID, uuid4

from .domain import EvidenceClass, UsageRecord
from .errors import ModuleSevenError
from .evaluation_contracts import (
    METRIC_BY_EVALUATOR,
    Completeness,
    EvaluationCounts,
    EvaluationStatus,
    ObservedFacts,
    RunAggregate,
    RunArtifact,
    RunIdentity,
    RunResult,
    ScenarioEvaluation,
    ThresholdPolicy,
    Verdict,
    identity_uuid,
    score_meets_threshold,
)
from .evaluation_dataset import DatasetView, Scenario
from .evaluation_evaluators import (
    EVALUATOR_SUITE_VERSION,
    Evaluator,
    evaluator_suite,
)
from .evaluation_target import ScenarioCorrelation
from .telemetry import (
    Code,
    Component,
    CostBasis,
    Event,
    Observation,
    TelemetryLimits,
    TelemetryPipeline,
    TelemetryRecord,
)

DEFAULT_SCENARIO_TIMEOUT_SECONDS: Final = 10.0
MAX_SCENARIO_TIMEOUT_SECONDS: Final = 10.0
DEFAULT_RUN_DEADLINE_SECONDS: Final = 120.0
MAX_RUN_DEADLINE_SECONDS: Final = 120.0

# Fixed-safe not-run row identity for an evaluator absent from the bound
# suite: stable suite version, a marked placeholder metric and a zero
# threshold; a not-run row never passes and never invents an authority.
_NOT_RUN_METRIC: Final = "metric_not_committed"
_NOT_RUN_THRESHOLD: Final = Fraction(0)

CorrelationMap = Mapping[str, ScenarioCorrelation]


class RunInterruptedError(ModuleSevenError):
    """Raised after recording an interrupted run as incomplete.

    Attributes:
        artifact: The bounded partial run artifact recorded before propagating.
    """

    def __init__(self, artifact: RunArtifact) -> None:
        super().__init__("Evaluation run was cancelled; recorded as incomplete.")
        self.artifact = artifact


@dataclass(frozen=True)
class EngineBounds:
    """Finite engine bounds validated within the contract ceilings.

    Attributes:
        scenario_timeout_seconds: Hard per-scenario wall bound, at most 10.
        run_deadline_seconds: Hard per-run wall bound, at most 120.
        max_scenarios: Maximum scenarios in one run, at most 256.
    """

    scenario_timeout_seconds: float = DEFAULT_SCENARIO_TIMEOUT_SECONDS
    run_deadline_seconds: float = DEFAULT_RUN_DEADLINE_SECONDS
    max_scenarios: int = 256

    def __post_init__(self) -> None:
        if not 0.0 < self.scenario_timeout_seconds <= MAX_SCENARIO_TIMEOUT_SECONDS:
            raise ValueError("Per-scenario timeout requires 0 < bound <= 10 seconds.")
        if not 0.0 < self.run_deadline_seconds <= MAX_RUN_DEADLINE_SECONDS:
            raise ValueError("Run deadline requires 0 < bound <= 120 seconds.")
        if not 1 <= self.max_scenarios <= 256:
            raise ValueError("Run size requires 1 <= max scenarios <= 256.")


def scenario_correlations(
    identity: RunIdentity, scenario_ids: tuple[str, ...]
) -> dict[str, ScenarioCorrelation]:
    """Derive deterministic per-scenario workflow identities for one run.

    Args:
        identity: The committed run identity tuple.
        scenario_ids: Scenario identifiers in canonical order.

    Returns:
        Correlation map keyed by scenario identifier; workflow and trace
        identities are UUIDv5 over (run id, scenario id) and every duplicate
        replay within one scenario shares the story 3 idempotency key.
    """
    run_id = identity.run_id()
    return {
        scenario_id: ScenarioCorrelation(
            workflow_id=identity_uuid((run_id, scenario_id, "workflow")),
            trace_id=identity_uuid((run_id, scenario_id, "trace")),
            action_id=identity_uuid((run_id, scenario_id, "action")),
        )
        for scenario_id in scenario_ids
    }


class EvaluationEngine:
    """Local, deterministic, concurrency-1 evaluation of a dataset.

    Attributes:
        policy: The committed threshold policy; never changed by a run.
        bounds: Validated finite engine bounds.
    """

    def __init__(
        self,
        *,
        policy: ThresholdPolicy | None = None,
        evaluators: Mapping[str, Evaluator] | None = None,
        bounds: EngineBounds | None = None,
        telemetry_exporter: object | None = None,
    ) -> None:
        """Construct the bounded engine bound to committed policy/suite.

        Args:
            policy: Committed threshold policy; defaults to committed.
            evaluators: Committed evaluators; defaults to the full suite.
            bounds: Validated finite bounds; defaults to committed bounds.
            telemetry_exporter: Optional accepted ``NeutralSink`` attached
                beside the capturing sink so Story 5 exports (for example
                ``LangfuseSink`` over a trusted transport) observe the same
                evaluation observations. Attached exporters are
                non-authoritative: their failures never change a result.

        Raises:
            ValueError: If bounds or the evaluator suite are malformed.
        """
        self.policy = policy or ThresholdPolicy.committed()
        resolved = evaluators if evaluators is not None else {
            item.evaluator_id: item for item in evaluator_suite()
        }
        self._evaluators: dict[str, Evaluator] = dict(resolved)
        self.bounds = bounds or EngineBounds()
        self._telemetry_exporter = telemetry_exporter

    async def run(
        self,
        dataset: DatasetView,
        *,
        target_id: str,
        target_version: int,
        target_factory: Callable[[CorrelationMap], object],
        run_ordinal: int = 0,
        scenario_ids: tuple[str, ...] | None = None,
    ) -> RunArtifact:
        """Run every selected scenario deterministically, in canonical order.

        Args:
            dataset: Validated dataset view.
            target_id: Identity of the system under evaluation.
            target_version: Identity version of the system under evaluation.
            target_factory: Deterministic target factory bound to derived
                correlations; never a vendor, never configuration-selected.
            run_ordinal: Caller-supplied nonnegative run ordinal (default 0).
            scenario_ids: Optional canonical selection to run (a declared
                subset); defaults to every dataset scenario.

        Returns:
            The bounded run artifact with local evaluation telemetry records.

        Raises:
            RunInterruptedError: Records a bounded interrupted run artifact
                and reports the cancellation to the caller.
        """
        chosen = dataset.scenario_ids if scenario_ids is None else tuple(scenario_ids)
        for scenario_id in chosen:
            dataset.get(scenario_id)
        identity = RunIdentity(
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            dataset_digest=dataset.digest,
            evaluator_suite_version=self._suite_version(),
            threshold_policy_version=self.policy.policy_version,
            target_id=target_id,
            target_version=target_version,
            run_ordinal=run_ordinal,
        )
        run_id = identity.run_id()
        correlations = scenario_correlations(identity, chosen)
        target = target_factory(correlations)
        self._verify_target(identity, target)
        pipeline, sink = self._pipeline()
        self._delivery_counts: Counter[str] = Counter()
        evaluations: list[ScenarioEvaluation] = []
        missing: list[str] = []
        started = time.monotonic()
        try:
            for scenario_id in chosen:
                if time.monotonic() - started >= self.bounds.run_deadline_seconds:
                    missing.append(scenario_id)
                    continue
                scenario = dataset.get(scenario_id)
                observed, target_error = await self._run_scenario(target, scenario)
                if target_error or observed is None:
                    missing.append(scenario_id)
                    continue
                evaluations.extend(
                    await self._evaluate_scenario(
                        identity, run_id, scenario, observed, pipeline, correlations
                    )
                )
        except asyncio.CancelledError:
            artifact = self._finalize(
                pipeline,
                sink,
                identity,
                run_id,
                evaluations,
                missing + [item for item in chosen if item not in {
                    row.scenario_id for row in evaluations
                }],
            )
            raise RunInterruptedError(artifact) from None
        artifact = self._finalize(
            pipeline, sink, identity, run_id, evaluations, missing
        )
        return artifact

    def _verify_target(self, identity: RunIdentity, target: object) -> None:
        """Verify the constructed target identity matches the run identity.

        Args:
            identity: The bound run identity tuple.
            target: The constructed evaluation target.

        Raises:
            ValueError: If the target identity does not match the declared one.
        """
        observed_target_id = getattr(target, "target_id", None)
        observed_target_version = getattr(target, "target_version", None)
        if (
            observed_target_id != identity.target_id
            or type(observed_target_version) is not int
            or observed_target_version != identity.target_version
        ):
            raise ValueError("Constructed target identity does not match the run.")

    def _pipeline(self) -> tuple[TelemetryPipeline, object]:
        """Create the real story 4 pipeline used for evaluation observations.

        An attached exporter (constructor seam) observes the same minimized
        records beside the capturing sink; it never replaces the local
        capture and its failures stay non-authoritative.
        """
        sink = _CapturingSink()
        exporter: _CapturingSink | _AttachedTelemetrySink = sink
        if self._telemetry_exporter is not None:
            exporter = _AttachedTelemetrySink(sink, self._telemetry_exporter)
        pipeline = TelemetryPipeline(
            limits=TelemetryLimits(max_events=4096), exporter=exporter
        )
        return pipeline, sink

    def _suite_version(self) -> int:
        """Return the committed evaluator suite version from the bound suite."""
        versions = {item.evaluator_version for item in self._evaluators.values()}
        if len(versions) != 1:
            raise ValueError("The bound evaluator suite requires one shared version.")
        return versions.pop()

    async def _run_scenario(
        self, target: object, scenario: Scenario
    ) -> tuple[ObservedFacts | None, bool]:
        """Run one scenario under a bounded timeout; errors are target errors.

        Args:
            target: The system under evaluation bound to this run.
            scenario: A validated dataset scenario.

        Returns:
            The observed facts with target_error False on success; None with
            target_error True when the target raised, timed out, returned a
            malformed result or was cancelled at the engine boundary.
        """
        task: asyncio.Task = asyncio.ensure_future(target.run(scenario))
        done, _ = await asyncio.wait({task}, timeout=self.bounds.scenario_timeout_seconds)
        if not done:
            task.cancel()
            return None, True
        if task.cancelled():
            return None, True
        error = task.exception()
        if error is not None:
            # Target boundary: never expose exception text or chain into facts.
            del error
            return None, True
        facts = task.result()
        if not isinstance(facts, ObservedFacts):
            return None, True
        return facts, False

    async def _evaluate_scenario(
        self,
        identity: RunIdentity,
        run_id: UUID,
        scenario: Scenario,
        observed: ObservedFacts,
        pipeline: TelemetryPipeline,
        correlations: CorrelationMap,
    ) -> list[ScenarioEvaluation]:
        """Evaluate one scenario with every committed evaluator in order.

        Args:
            identity: The bound run identity tuple.
            run_id: The bound deterministic run identifier.
            scenario: The validated scenario.
            observed: The observed facts from the scenario run.
            pipeline: The real story 4 pipeline for evaluation observations.
            correlations: Deterministic per-scenario workflow identities.

        Returns:
            Every evaluator result, in the scenario's committed order.
        """
        correlation = correlations[scenario.scenario_id]
        critical = self.policy.is_critical(scenario.category)
        results: list[ScenarioEvaluation] = []
        for evaluator_id in scenario.evaluators:
            evaluator = self._evaluators.get(evaluator_id)
            status, score = self._apply_evaluator(evaluator, scenario, observed)
            if evaluator is None:
                # Fixed-safe not-run identity: the stable suite identity and
                # the committed metric for that evaluator ID (never a new
                # vocabulary) with the committed threshold; the row keeps
                # status ``not_run`` and can never pass by absence. Only an
                # evaluator ID outside the committed vocabulary entirely
                # keeps the marked placeholder identity.
                metric = METRIC_BY_EVALUATOR.get(evaluator_id, _NOT_RUN_METRIC)
                if metric is _NOT_RUN_METRIC:
                    threshold = _NOT_RUN_THRESHOLD
                else:
                    threshold = self.policy.metric_threshold(metric)
                evaluator_version = EVALUATOR_SUITE_VERSION
            else:
                metric = evaluator.metric
                threshold = self.policy.metric_threshold(metric)
                evaluator_version = evaluator.evaluator_version
            row = self._result(
                identity,
                run_id,
                scenario,
                correlation,
                evaluator_id,
                metric,
                status,
                score,
                threshold,
                critical,
                observed,
                evaluator_version=evaluator_version,
            )
            results.append(row)
            await self._emit_evaluation(pipeline, row)
        return results

    def _apply_evaluator(
        self, evaluator: Evaluator | None, scenario: Scenario, observed: ObservedFacts
    ) -> tuple[EvaluationStatus, float]:
        """Apply one evaluator at its failure boundary with fixed safe codes.

        Args:
            evaluator: The committed evaluator, or None when not committed.
            scenario: The validated scenario.
            observed: The observed facts.

        Returns:
            The evaluation status and score; a malformed, non-finite or
            out-of-range result and a raised evaluator both score 0.0.
        """
        if evaluator is None:
            return EvaluationStatus.NOT_RUN, 0.0
        try:
            score = evaluator.evaluate(scenario, observed)
        except Exception:
            # Evaluator boundary: fixed status only; no exception text enters
            # results and the remaining evaluators still run deterministically.
            return EvaluationStatus.EVALUATOR_ERROR, 0.0
        if type(score) is not float:
            return EvaluationStatus.MALFORMED_RESULT, 0.0
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            return EvaluationStatus.MALFORMED_RESULT, 0.0
        return EvaluationStatus.EVALUATED, score

    def _result(
        self,
        identity: RunIdentity,
        run_id: UUID,
        scenario: Scenario,
        correlation: ScenarioCorrelation,
        evaluator_id: str,
        metric: str,
        status: EvaluationStatus,
        score: float,
        threshold: Fraction,
        critical: bool,
        observed: ObservedFacts,
        *,
        evaluator_version: int | None = None,
    ) -> ScenarioEvaluation:
        """Build one immutable scenario evaluation row for the run."""
        threshold_pair = (threshold.numerator, threshold.denominator)
        passed = (
            score_meets_threshold(score, threshold)
            if status is EvaluationStatus.EVALUATED
            else False
        )
        if evaluator_version is None:
            evaluator_version = self._evaluators[evaluator_id].evaluator_version
        return ScenarioEvaluation(
            evaluation_id=identity_uuid(
                (run_id, scenario.scenario_id, evaluator_id, metric)
            ),
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            category=scenario.category,
            workflow_id=correlation.workflow_id,
            trace_id=correlation.trace_id,
            action_id=correlation.action_id,
            evaluator_id=evaluator_id,
            evaluator_version=evaluator_version,
            metric=metric,
            score=score,
            threshold=threshold_pair,
            passed=passed,
            status=status,
            critical=critical,
            evidence_class=EvidenceClass.DETERMINISTIC_FIXTURE,
            scenario_evidence=scenario.scenario_evidence(),
            observed=observed,
        )

    async def _emit_evaluation(
        self, pipeline: TelemetryPipeline, row: ScenarioEvaluation
    ) -> None:
        """Emit one story 4 evaluation observation; delivery is non-authoritative.

        Args:
            pipeline: The bound real story 4 pipeline.
            row: The scenario evaluation row.
        """
        telemetry = TelemetryRecord(
            workflow_id=row.workflow_id,
            trace_id=row.trace_id,
            span_id=uuid4(),
            operation=row.evaluator_id,
            status=(
                Code.SUCCEEDED if row.status is EvaluationStatus.EVALUATED
                else Code.MALFORMED_RESULT
                if row.status is EvaluationStatus.MALFORMED_RESULT
                else Code.FAILED
            ),
            duration_ms=0.0,
            usage=UsageRecord(),
            evidence_class=EvidenceClass.DETERMINISTIC_FIXTURE,
        )
        observation = Observation(
            telemetry=telemetry,
            action_id=row.action_id,
            event=Event.EVALUATION,
            component=Component.EVALUATION,
            cost_basis=CostBasis.FIXTURE,
            source_evidence=row.scenario_evidence,
            evaluation_id=row.evaluation_id,
        )
        delivery = await pipeline.emit(observation)
        self._delivery_counts[delivery.value] += 1

    def _finalize(
        self,
        pipeline: TelemetryPipeline,
        sink: object,
        identity: RunIdentity,
        run_id: UUID,
        evaluations: list[ScenarioEvaluation],
        missing: list[str],
    ) -> RunArtifact:
        """Complete the run artifact from the recorded bounded state."""
        completeness = (
            Completeness.COMPLETE if not missing else Completeness.INCOMPLETE
        )
        verdict = (
            self._verdict(evaluations) if not missing else Verdict.FAIL
        )
        result = RunResult(
            identity=identity,
            run_id=run_id,
            evaluations=tuple(evaluations),
            aggregate=self._aggregate(evaluations),
            missing_scenario_ids=tuple(dict.fromkeys(missing)),
            completeness=completeness,
            verdict=verdict,
            cost_used_usd=0.0,
            cost_basis="none",
            evidence_class=EvidenceClass.DETERMINISTIC_FIXTURE,
        )
        return RunArtifact(
            result=result,
            evaluation_records=tuple(sink.records),
            pipeline_delivery_counts=dict(self._delivery_counts),
        )

    def _verdict(self, evaluations: list[ScenarioEvaluation]) -> Verdict:
        """Compute the application verdict from policy and evaluation rows.

        Args:
            evaluations: All evaluation rows of the run.

        Returns:
            pass only when no scenario is missing, every evaluation is
            evaluated and passed, every critical category passes in full,
            and every category aggregate meets its exact threshold.
        """
        if not evaluations:
            return Verdict.FAIL
        if any(
            not row.passed or row.status is not EvaluationStatus.EVALUATED
            for row in evaluations
        ):
            return Verdict.FAIL
        for category in self.policy.critical_categories:
            rows = [row for row in evaluations if row.category == category]
            if rows and any(not row.passed for row in rows):
                return Verdict.FAIL
        counts: dict[str, _MutableCounts] = {}
        for row in evaluations:
            counts.setdefault(row.category, _MutableCounts()).record(row)
        for category, counter in counts.items():
            threshold = self.policy.category_threshold(category)
            if not _meets_threshold(counter.passed, counter.total, threshold):
                return Verdict.FAIL
        return Verdict.PASS

    def _aggregate(self, evaluations: list[ScenarioEvaluation]) -> RunAggregate:
        """Build exact integer aggregates for one run.

        Args:
            evaluations: All evaluation rows.

        Returns:
            The frozen per-metric and per-category aggregate model.
        """
        metrics: dict[str, _MutableCounts] = {}
        categories: dict[str, _MutableCounts] = {}
        for row in evaluations:
            metrics.setdefault(row.metric, _MutableCounts()).record(row)
            categories.setdefault(row.category, _MutableCounts()).record(row)
        return RunAggregate(
            metric_counts={name: counter.snapshot() for name, counter in metrics.items()},
            category_counts={
                name: counter.snapshot() for name, counter in categories.items()
            },
        )


class _MutableCounts:
    """Internal counter builder projecting onto the frozen counts model."""

    def __init__(self) -> None:
        self.total = 0
        self.evaluated = 0
        self.passed = 0
        self.failed = 0
        self.errored = 0

    def record(self, row: ScenarioEvaluation) -> None:
        """Record one evaluation row into the counters.

        Args:
            row: A scenario evaluation row.
        """
        self.total += 1
        if row.status is EvaluationStatus.EVALUATED:
            self.evaluated += 1
            if row.passed:
                self.passed += 1
            else:
                self.failed += 1
        elif row.status is EvaluationStatus.MALFORMED_RESULT:
            self.failed += 1
        else:
            self.errored += 1

    def snapshot(self) -> EvaluationCounts:
        """Project the counters onto the frozen evaluation counts model."""
        return EvaluationCounts(
            total=self.total,
            evaluated=self.evaluated,
            passed=self.passed,
            failed=self.failed,
            errored=self.errored,
        )


def _meets_threshold(count: int, total: int, threshold: Fraction) -> bool:
    """Compare aggregated pass counts against an exact rational threshold."""
    if total == 0:
        return True
    return count * threshold.denominator >= threshold.numerator * total


class _CapturingSink:
    """Capturing ``NeutralSink`` for run-local records; never interprets."""

    def __init__(self) -> None:
        self._records: list[str] = []

    @property
    def records(self) -> tuple[str, ...]:
        """Return captured minimized records as an immutable snapshot."""
        return tuple(self._records)

    async def send(self, record: str) -> None:
        """Capture one record without interpretation.

        Args:
            record: Minimized JSON record from the telemetry pipeline.
        """
        self._records.append(record)

    def append(self, record: str) -> None:
        """Append one record on behalf of the fan-out sink boundary."""
        self._records.append(record)


class _AttachedTelemetrySink:
    """Fan-out sink: captures locally and forwards to an attached exporter.

    The attached Story 5 exporter is strictly non-authoritative: whatever it
    raises while mapping or submitting never reaches the evaluation results;
    delivery remains application-observed through the pipeline.
    """

    def __init__(self, capture: _CapturingSink, attached: object) -> None:
        self._capture = capture
        self._attached = attached

    @property
    def records(self) -> tuple[str, ...]:
        """Return the local captured records snapshot."""
        return self._capture.records

    async def send(self, record: str) -> None:
        """Capture first, then hand the same record to the attached exporter.

        Args:
            record: Minimized JSON record from the telemetry pipeline.
        """
        self._capture.append(record)
        await self._attached.send(record)


__all__ = [
    "DEFAULT_RUN_DEADLINE_SECONDS",
    "DEFAULT_SCENARIO_TIMEOUT_SECONDS",
    "EngineBounds",
    "EvaluationEngine",
    "RunInterruptedError",
    "scenario_correlations",
]
