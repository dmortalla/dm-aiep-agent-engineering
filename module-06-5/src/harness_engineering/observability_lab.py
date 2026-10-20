"""Run the credential-free Story 10 lab; no hosted integration can be enabled.

Use --directory with a new artifact directory. Default one genuine local workflow
has insufficient SLO samples. --samples 20 explicitly runs twenty whole workflows;
it is a bounded demonstration, not a production or regression SLO claim.
"""

import argparse
from collections.abc import Callable
from pathlib import Path

from harness_engineering.anomaly_signals import AnomalyDetector
from harness_engineering.context import ContextCompressor, ContextItem
from harness_engineering.cost_governance import (
    FixtureLedger,
    FixtureTariff,
    LedgerPolicy,
    ProviderAlias,
    TokenPolicy,
)
from harness_engineering.domain import EvidenceClass, RuntimeBudget, TrustLevel, WorkflowIdentity
from harness_engineering.errors import BudgetExceededError
from harness_engineering.governance_facts import GovernanceKind
from harness_engineering.helicone_boundary import HeliconeOfflineConfig
from harness_engineering.latency import Cohort, LatencyWindow, Measurement, Outcome, TimingSource
from harness_engineering.observability import TelemetrySession
from harness_engineering.observability_adapters import OfflineObservabilityAdapter, Vendor
from harness_engineering.observability_report import (
    IntegrationView,
    LabConfig,
    ObservabilityReport,
)
from harness_engineering.orchestration import LifecycleInput, LifecycleRuntime, StepResult
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan
from harness_engineering.providers import ProviderRuntime
from harness_engineering.telemetry_projections import observe_step, observe_workflow
from harness_engineering.usage import UsageFacts, UsageState


def _sample(directory: Path, config: LabConfig) -> ObservabilityReport:
    identity = WorkflowIdentity()
    telemetry = TelemetrySession(identity, evidence=EvidenceClass.DETERMINISTIC)
    anomalies = AnomalyDetector(evidence=telemetry.evidence, telemetry=telemetry)
    tokens = TokenPolicy(step_count=2, input_per_call=8, output_per_call=32,
                         input_per_step=24, output_per_step=96, workflow_attempts=5)
    policy = LedgerPolicy(
        workflow_id=identity.workflow_id, thread_id=identity.thread_id, cap_units=160,
        tariff=FixtureTariff(provider=ProviderAlias.FAKE,
                             input_units_per_million=1_000_000,
                             output_units_per_million=1_000_000),
        tokens=tokens, action_ids=("first", "second"),
    )
    cost = FixtureLedger(directory / "cost.sqlite", policy, create=True,
                         telemetry=telemetry, anomalies=anomalies)
    budget = RuntimeBudget(max_context_tokens=8, max_output_tokens=32, max_provider_attempts=5)
    provider = ProviderRuntime(budget=budget, action_ids=policy.action_ids,
                               telemetry=telemetry, ledger=cost, anomalies=anomalies)
    plan = ExecutionPlan(goal="Local observability fixture", budget=budget, tasks=(
        ExecutableSubtask(task_id="first", description="Two local calls"),
        ExecutableSubtask(task_id="second", description="One local call", dependencies=("first",)),
    ))

    def execute(task: ExecutableSubtask, request: LifecycleInput) -> StepResult:
        for _ in range(2 if task.task_id == "first" else 1):
            provider.generate({"prompt": "x"}, action_id=task.task_id)
        return StepResult(text="ok")

    runtime = LifecycleRuntime(plan, observe_step(telemetry, execute, step_ids=policy.action_ids))
    result = observe_workflow(telemetry, lambda: runtime.run(LifecycleInput(text="local")))
    if result.phase.value != "completed":
        raise RuntimeError("Local lab workflow did not complete.")

    # Actual accepted ledger mechanics: an uncertain fixture attempt retains its
    # entire bound. It is not an inference request and grants no dispatch authority.
    reservation = cost.reserve(2)
    cost.settle(reservation, UsageFacts(state=UsageState.TIMEOUT))
    before = cost.snapshot()
    reopened = FixtureLedger(directory / "cost.sqlite", policy)
    recovery_preserved = reopened.snapshot() == before
    denied = False
    try:
        reopened.reserve(1)
    except BudgetExceededError:
        denied = True
    if not denied or not recovery_preserved:
        raise RuntimeError("Fixture hard cap or recovery invariant failed.")

    # Accepted context compression supplies numeric observations; content stays local.
    compression = ContextCompressor(len, lambda items: "x").summarize(
        (ContextItem(content="x" * 100, provenance="fixture://compression",
                     trust_level=TrustLevel.UNTRUSTED_AGENT),),
        max_summary_tokens=2,
    )
    advisory_failures = 0

    def advisory(operation: Callable[[], object]) -> None:
        nonlocal advisory_failures
        try:
            operation()
        except Exception:
            # Optional advisory observer boundary only; source state/ledger remain
            # authoritative and no external exception text is retained.
            advisory_failures += 1

    advisory(lambda: anomalies.observe_compression(compression.source_token_estimate,
                                                    compression.compressed_token_estimate))
    # Explicit event-stream fixtures demonstrate pipeline thresholds, not actual
    # provider failures, denials, retries or authorized tool executions.
    for kind, count in ((GovernanceKind.RETRY_BURST, 2), (GovernanceKind.DENIAL_BURST, 3),
                        (GovernanceKind.PROVIDER_FAILURE_BURST, 3),
                        (GovernanceKind.TOOL_FREQUENCY, 10)):
        for _ in range(count):
            advisory(lambda kind=kind: anomalies.observe(kind))
    integration_views = []
    for vendor in Vendor:
        adapter = OfflineObservabilityAdapter(telemetry, vendor, enabled=config.offline_sdk)
        if config.offline_sdk:
            for event in telemetry.sink.snapshot():
                adapter.enqueue(event)
            adapter.flush()
        health = adapter.health()
        adapter.close()
        integration_views.append(IntegrationView(vendor=vendor, enabled=config.offline_sdk,
                                                  health=health))
    helicone = HeliconeOfflineConfig()
    helicone.describe(telemetry)  # Validate the accepted offline header boundary; no binding.
    cohort = next(r for r in telemetry.reports()
                  if r.cohort.measurement is Measurement.WORKFLOW
                  and r.cohort.outcome is Outcome.SUCCEEDED)
    return ObservabilityReport(
        identity=identity, tokens=tokens, cost=before, usage=provider.usage_receipts,
        events=telemetry.sink.snapshot(), latency=telemetry.reports(), workflow_cohort=cohort,
        anomalies=anomalies.snapshot(), hard_cap_denied=denied,
        recovery_preserved=recovery_preserved, telemetry_failures=telemetry.failures,
        advisory_failures=advisory_failures,
        integrations=tuple(integration_views), helicone=helicone,
    )


def run_observability_lab(directory: Path, config: LabConfig | None = None) -> ObservabilityReport:
    """Run 1..20 complete local workflows in a fresh retained artifact directory.

    Args:
        directory: New isolated directory; an existing path is never overwritten.
        config: Strict finite fixture options. SDKs default disabled; opt-in remains offline.

    Returns:
        One detailed workflow and nearest-rank cohort across actual complete runs.
        No model result, prompt, path, arbitrary metadata or live billing is included.
    """
    checked = LabConfig() if config is None else LabConfig.model_validate(config)
    directory.mkdir(parents=True, exist_ok=False)
    window = LatencyWindow(Cohort(measurement=Measurement.WORKFLOW, outcome=Outcome.SUCCEEDED,
                                 evidence=EvidenceClass.DETERMINISTIC,
                                 timing=TimingSource.MONOTONIC))
    report = None
    for index in range(checked.samples):
        sample_directory = directory / str(index + 1)
        sample_directory.mkdir()
        # Only one optional SDK batch per lab, independent of sample count.
        sample_config = LabConfig(samples=1, offline_sdk=checked.offline_sdk and index == 0)
        current = _sample(sample_directory, sample_config)
        window.add(current.workflow_cohort.p50_seconds)
        if report is None:
            report = current
    return ObservabilityReport.model_validate(report.model_copy(update={
        "workflow_cohort": window.report(),
    }))


def main() -> None:
    """Render bounded Story 10 reviewer evidence without a network/UI server."""
    from harness_engineering.observability_presentation import render_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--offline-sdk", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    report = run_observability_lab(args.directory,
                                   LabConfig(samples=args.samples, offline_sdk=args.offline_sdk))
    print(render_report(report, format=args.format))


if __name__ == "__main__":
    main()
