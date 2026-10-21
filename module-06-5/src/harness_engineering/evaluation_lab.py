"""Run the credential-free Story 11 golden-set regression harness (REQ-EVAL-002/003).

Use --directory with a new artifact directory. Every case runs accepted application
services and compares fresh observations exactly with retained golden expectations.
Use --golden with an edited copy of the packaged golden file to watch a regression
being detected. Golden files are data: they cannot add probes or change evidence.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from time import monotonic

from harness_engineering.domain import EvidenceClass, RuntimeBudget
from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.evaluation import (
    MAX_GOLDEN_CASES,
    CaseResult,
    CaseStatus,
    GoldenSet,
    RegressionReport,
    compare,
    load_golden_set,
)
from harness_engineering.evaluation_probes import REGISTRY, Probe, run_provider_workflow
from harness_engineering.latency import Cohort, LatencyWindow, Measurement, Outcome, TimingSource

DEFAULT_LATENCY_SAMPLES = 20
MAX_LATENCY_SAMPLES = 20

LIMITATIONS = (
    "Deterministic fixtures and local integrations only; no live provider or paid inference.",
    "Golden expectations are retained accepted behavior, not source-mandated thresholds.",
    "Latency covers one local plan-lifecycle-fake-provider workflow, not production traffic.",
    "Approval, recovery and cost cases reuse accepted labs and their stated non-claims.",
    "Cost units are fixture micro-USD for enforcement mechanics, not provider billing.",
    "No hosted LangSmith/Langfuse traffic, Helicone routing, deployment or production claim.",
)

GUIDANCE = (
    ("Demonstrates", "Golden-set regression checks for agent behavior across planning, "
     "context, permissions, MCP, lifecycle controls, off-switch, provider safety, "
     "recovery, approval and cost governance, with inline lifecycle invariants."),
    ("Run", "python -m harness_engineering.evaluation_lab --directory <new-path> "
     "[--format json] [--case ID] [--golden FILE]"),
    ("Action", "Run it unchanged; then copy evaluation_golden_set.json, change one "
     "expected value, and rerun with --golden <copy>."),
    ("Expect", "Unchanged: every case PASSED and exit code 0. Edited copy: that case "
     "REGRESSED with the exact field difference and exit code 1."),
    ("Proves", "Current accepted behavior still matches retained expectations; any "
     "behavior drift is reported per field, not hidden."),
)


def _check_golden(golden: GoldenSet) -> None:
    golden_ids = {case.case_id for case in golden.cases}
    if golden_ids != set(REGISTRY):
        raise ContractValidationError(
            "Golden set cases must exactly match the trusted probe registry."
        )


def _select(case_ids: Sequence[str] | None) -> tuple[Probe, ...]:
    if case_ids is None:
        return tuple(REGISTRY.values())
    chosen = tuple(case_ids)
    if not 1 <= len(chosen) <= MAX_GOLDEN_CASES or len(set(chosen)) != len(chosen):
        raise ContractValidationError("Select between 1 and 32 unique golden cases.")
    unknown = [case for case in chosen if case not in REGISTRY]
    if unknown:
        raise ContractValidationError("Selected golden case is not in the trusted registry.")
    return tuple(REGISTRY[case] for case in chosen)


def _run_case(probe: Probe, golden: GoldenSet, directory: Path) -> CaseResult:
    expected = next(case.expected for case in golden.cases if case.case_id == probe.case_id)
    started = monotonic()
    try:
        observed = probe.run(directory / probe.case_id)
    except (HarnessError, ValueError, RuntimeError, OSError) as exc:
        # Case isolation boundary: the failure is reported as an ERROR verdict (never
        # success) with only the exception type; programming defects such as
        # TypeError still propagate. Exception text is not retained (privacy).
        status, mismatches, error = CaseStatus.ERROR, (), type(exc).__name__
    else:
        mismatches = compare(expected, observed)
        status = CaseStatus.REGRESSED if mismatches else CaseStatus.PASSED
        error = None
    return CaseResult(
        case_id=probe.case_id, area=probe.area, requirements=probe.requirements,
        purpose=probe.purpose, evidence=probe.evidence, status=status,
        mismatches=mismatches, error_type=error,
        duration_seconds=min(600.0, max(0.0, monotonic() - started)),
    )


def run_regression(
    directory: Path,
    *,
    golden_path: Path | None = None,
    case_ids: Sequence[str] | None = None,
    latency_samples: int = DEFAULT_LATENCY_SAMPLES,
) -> RegressionReport:
    """Run golden cases and measure deterministic local workflow latency.

    Args:
        directory: New artifact directory; an existing path is never reused.
        golden_path: Optional reviewer golden file; None uses the packaged set.
        case_ids: Optional subset of trusted case identifiers.
        latency_samples: Complete local workflows to time (1-20). Twenty are
            required before the p95 SLO is assessed.

    Returns:
        Typed report whose verdict and evidence derive only from case results.

    Raises:
        ContractValidationError: For an invalid golden file, selection or sample count.
        EvaluationError: If the latency workflow does not complete as accepted.
        FileExistsError: If the directory already exists.
    """
    if type(latency_samples) is not int or not 1 <= latency_samples <= MAX_LATENCY_SAMPLES:
        raise ContractValidationError("Latency samples must be an integer from 1 to 20.")
    loaded = load_golden_set(golden_path)
    _check_golden(loaded.golden)
    probes = _select(case_ids)
    directory.mkdir(parents=True, exist_ok=False)
    cases = tuple(_run_case(probe, loaded.golden, directory) for probe in probes)
    window = LatencyWindow(
        Cohort(measurement=Measurement.WORKFLOW, outcome=Outcome.SUCCEEDED,
               evidence=EvidenceClass.DETERMINISTIC, timing=TimingSource.MONOTONIC),
        slo_p95_seconds=RuntimeBudget().latency_slo_p95_seconds,
    )
    for _ in range(latency_samples):
        started = monotonic()
        run_provider_workflow()
        window.add(float(monotonic() - started))
    evidence = tuple(item for item in EvidenceClass
                     if any(item in case.evidence for case in cases))
    statuses = [case.status for case in cases]
    passed = statuses.count(CaseStatus.PASSED)
    return RegressionReport(
        golden_name=loaded.golden.name, golden_sha256=loaded.sha256,
        golden_source=loaded.source, evidence=evidence, cases=cases, passed=passed,
        regressed=statuses.count(CaseStatus.REGRESSED), errors=statuses.count(CaseStatus.ERROR),
        succeeded=passed == len(cases), workflow_latency=window.report(),
        limitations=LIMITATIONS,
    )


def render_text(report: RegressionReport) -> str:
    """Render guided reviewer text from a validated report.

    Args:
        report: Result of run_regression().

    Returns:
        Text explaining the action, expectation, result meaning and evidence.
    """
    lines = ["Story 11 Golden-Set Regression Harness - REQ-EVAL-001/002/003, REQ-DEL-005"]
    lines.extend(f"{label}: {text}" for label, text in GUIDANCE)
    lines.append(f"Evidence: {', '.join(e.value for e in report.evidence)} "
                 "(derived from cases; cannot be set by golden data)")
    lines.append(f"Golden set: {report.golden_name} ({report.golden_source}) "
                 f"sha256={report.golden_sha256}")
    for case in report.cases:
        lines.extend([
            "",
            f"[{case.status.value.upper()}] {case.case_id} ({case.area.value}; "
            f"{', '.join(e.value for e in case.evidence)}; {case.duration_seconds:.2f}s)",
            f"  Guards: {case.purpose}",
            f"  Requirements: {', '.join(case.requirements)}",
        ])
        if case.error_type is not None:
            lines.append(f"  Error: {case.error_type} (details withheld)")
        lines.extend(
            f"  Diff {m.field}: {m.kind.value}; expected={m.expected!r} observed={m.observed!r}"
            for m in case.mismatches
        )
    latency = report.workflow_latency
    slo = ("not assessed (fewer than 20 samples)" if latency.slo_met is None
           else ("MET" if latency.slo_met else "MISSED"))
    lines.extend([
        "",
        f"Workflow latency: samples={latency.sample_count} p50={_seconds(latency.p50_seconds)} "
        f"p95={_seconds(latency.p95_seconds)}; SLO p95<={latency.slo_p95_seconds}s {slo}",
        f"Verdict: {report.passed} passed, {report.regressed} regressed, {report.errors} "
        f"errors -> {'PASS' if report.succeeded else 'FAIL'}",
        "Limitations:",
        *(f"- {item}" for item in report.limitations),
    ])
    return "\n".join(lines)


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}s"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the terminal reviewer surface.

    Args:
        argv: Optional argument list, otherwise process arguments.

    Returns:
        0 when every case passes, 1 on regression or case error, 2 when the
        harness cannot produce trustworthy evidence (details withheld).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--golden", type=Path, default=None)
    parser.add_argument("--case", action="append", choices=sorted(REGISTRY), default=None)
    parser.add_argument("--latency-samples", type=int, default=DEFAULT_LATENCY_SAMPLES)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        report = run_regression(args.directory, golden_path=args.golden, case_ids=args.case,
                                latency_samples=args.latency_samples)
    except HarnessError as exc:
        print(f"evaluation_failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    except FileExistsError:
        print("evaluation_failed: choose a new --directory path", file=sys.stderr)
        return 2
    print(report.model_dump_json(indent=2) if args.format == "json" else render_text(report))
    return 0 if report.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
