"""Fixed local reviewer demonstrations; presentation composition, never authority.

Existing labs own all rules and execution. This module accepts only a finite demo
identifier and returns inert, bounded views. No UI value enters application policy.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from harness_engineering.domain import EvidenceClass
from harness_engineering.errors import ContractValidationError, HarnessError

# Presentation limits only: never runtime budgets or evidence/permission authority.
MAX_DISPLAY_CHARS = 65_536
_RUN_LOCK = Lock()


class Demo(StrEnum):
    """Application-owned choices; no arbitrary service, path or callback selection."""

    PLANNING = "1 · Task planning"
    CONTEXT = "2 · Context compression"
    PERMISSIONS = "3 · Tool permissions"
    RECOVERY = "4 · Crash recovery"
    APPROVAL = "5 · Human approval"
    OBSERVABILITY = "6 · Traces and cost dashboard"
    MCP = "7 · MCP capability boundary"
    REGRESSION = "8 · Evaluation and regression"


@dataclass(frozen=True)
class Guide:
    """Trusted reviewer instructions; separate from observed result data."""

    demonstrates: str
    expect: str
    safety: str
    evidence: str
    limitations: str


GUIDES = {
    Demo.PLANNING: Guide(
        "Decompose a customer brief into tasks, dependencies and priorities.",
        "Research precedes analysis, drafting and review; independent metadata waits by priority.",
        "The accepted planning engine validates the fixed plan before scheduling.",
        "Deterministic fixture, using the real planning engine.",
        "Fixed task definitions; no model-generated planning or live provider.",
    ),
    Demo.CONTEXT: Guide(
        "Construct a bounded prompt, compress history, slide the window and route memory.",
        "Context stays within its fixed budget; a shorter summary retains provenance.",
        "Retrieved and agent text remain untrusted; memory routing grants no permissions.",
        "Deterministic fixture, using the real context and memory services.",
        "Character counts are fixture token units; summarization is local; Mem0 is not called.",
    ),
    Demo.PERMISSIONS: Guide(
        "Exercise the capability registry and application-level sandbox across ten scenarios.",
        "Only the granted, in-scope search executes; denied cases record zero handler calls.",
        "Injected approvals, out-of-scope requests, blocklists and missing HITL fail closed.",
        "Deterministic fixture with actual bounded local handler execution.",
        "Application-level isolation, not an OS/container sandbox or arbitrary code execution.",
    ),
    Demo.RECOVERY: Guide(
        "Interrupt after a committed local effect; reconstruct state and resume three times.",
        "The effect commits once; checkpoints survive reconstruction and replay count stays zero.",
        "Accepted recovery contracts reconcile durable state; session state is never a checkpoint.",
        "Deterministic fixture and local integration (SQLite).",
        "Injected Python interruption, not an OS crash; local SQLite effects, not remote delivery.",
    ),
    Demo.APPROVAL: Guide(
        "Suspend work, inspect durable escalation, then exercise trusted approve/deny fixtures.",
        "Only the genuine fixture human decision resumes protected work; forged/stale ones fail.",
        "Run demonstration does not approve anything. Fixture principals and exact-action handles "
        "are owned by the accepted lab; the browser cannot supply an approval.",
        "Deterministic fixture and local integration (durable approval records).",
        "Simulated human identities and decisions; not a production identity or approval portal.",
    ),
    Demo.OBSERVABILITY: Guide(
        "Capture correlated spans and structured logs; inspect token allocations, spend alerts "
        "and hard-cap denial in the fixture cost dashboard.",
        "Local workflow completes; alerts appear, hard cap denies and recovery preserves cost.",
        "Ledger and runtime own accounting; advisory telemetry cannot grant monetary authority.",
        "Deterministic fixture; local SQLite persistence. Optional SDK exporters stay disabled.",
        "Fixture micro-USD is not verified billing. One workflow does not assess a p95 SLO.",
    ),
    Demo.MCP: Guide(
        "Discover and invoke the accepted in-process MCP SDK capability boundary.",
        "Discovery grants no authority; malformed inputs, output, scope and budgets fail closed.",
        "Only the application-owned allowlisted capability can run; tool data stays untrusted.",
        "Deterministic fixture and local integration (MCP SDK in-memory transport).",
        "No remote MCP server. Windows event-loop self-pipes may use local loopback sockets.",
    ),
    Demo.REGRESSION: Guide(
        "Run the accepted 16-case golden set with lifecycle invariants and exact comparison.",
        "Unchanged behavior yields 16 passed cases and a 20-workflow p50/p95 latency report.",
        "The trusted registry chooses probes; golden data cannot set authority or evidence. "
        "Includes off-switch cancellation, safety denials, retries and hard stops.",
        "Deterministic fixture and local integration; classifications derive from accepted cases.",
        "Golden expectations retain accepted behavior. Local latency is not production latency; "
        "no live model, hosted telemetry or verified billing.",
    ),
}


class Metric(BaseModel):
    """Small read-only dashboard value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    label: str = Field(max_length=80)
    value: str = Field(max_length=128)


class DemoView(BaseModel):
    """Bounded display data, never passed back into an application service."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    demo: Demo
    evidence: tuple[EvidenceClass, ...] = Field(min_length=1, max_length=2)
    metrics: tuple[Metric, ...] = Field(max_length=4)
    details: str = Field(max_length=MAX_DISPLAY_CHARS)
    truncated: bool


class ReviewerBusyError(HarnessError):
    """A local demonstration already owns the single process execution slot."""


def _metric(label: str, value: object) -> Metric:
    return Metric(label=label, value=str(value))


def _project(demo: Demo, directory: Path) -> tuple[object, tuple[Metric, ...]]:
    """Invoke fixed accepted services and select reviewer fields, without new rules."""
    if demo is Demo.PLANNING:
        from harness_engineering.planning_lab import run_planning_lab

        return run_planning_lab(), ()
    if demo is Demo.CONTEXT:
        from harness_engineering.context_lab import run_context_lab

        return run_context_lab(), ()
    if demo is Demo.PERMISSIONS:
        from harness_engineering.permission_lab import render_permission_lab, run_permission_lab

        return render_permission_lab(run_permission_lab()), ()
    if demo is Demo.RECOVERY:
        from harness_engineering.recovery_lab import run_recovery_lab

        result = run_recovery_lab(directory)
        return result.model_dump(mode="json", exclude={"checkpoint_file", "effect_file"}), (
            _metric("Effect commits", result.external_commits),
            _metric("Replay invocations", result.replay_invocations),
            _metric("Recovery passes", len(result.recovery_passes)),
        )
    if demo is Demo.APPROVAL:
        from harness_engineering.approval_lab import run_approval_lab

        result = run_approval_lab(directory)
        fields = {"scenario", "suspended", "authorization", "resume", "expected",
                  "executed", "execution_statuses"}
        scenarios = []
        for scenario in result.scenarios:
            row = scenario.model_dump(mode="json", include=fields)
            row["durable_after"] = (
                scenario.after.model_dump(
                    mode="json", include={"status", "audit_statuses", "pending"},
                )
                if scenario.after is not None else None
            )
            scenarios.append(row)
        return {"scenarios": scenarios, "nonclaims": result.nonclaims}, ()
    if demo is Demo.OBSERVABILITY:
        from harness_engineering.observability_lab import run_observability_lab
        from harness_engineering.observability_presentation import render_report

        result = run_observability_lab(directory)
        return render_report(result), (
            _metric("Committed fixture micro-USD", result.cost.committed_units),
            _metric("Outstanding fixture micro-USD", result.cost.outstanding_units),
            _metric("Fixture cap (micro-USD)", result.cost.cap_units),
            _metric("Hard-cap denied", result.hard_cap_denied),
        )
    if demo is Demo.MCP:
        from harness_engineering.mcp_lab import run_mcp_lab

        return run_mcp_lab(), ()
    from harness_engineering.evaluation_lab import render_text, run_regression

    result = run_regression(directory)
    return render_text(result), (
        _metric("Passed cases", result.passed),
        _metric("Regressed cases", result.regressed),
        _metric("Case errors", result.errors),
        _metric("Workflow samples", result.workflow_latency.sample_count),
    )


def run_demo(demo: Demo) -> DemoView:
    """Run one fixed local demo, clean its workspace and return bounded inert data.

    Args:
        demo: Exact application-owned enum member, not arbitrary callback/configuration.

    Returns:
        A bounded view; raw workspace paths and exception diagnostics are not included.

    Raises:
        ContractValidationError: If the selection is not an exact Demo member.
        ReviewerBusyError: If another session is running a demonstration.
        Exception: Accepted-service failures propagate to the presentation error boundary.
    """
    if type(demo) is not Demo:
        raise ContractValidationError("Choose an available reviewer demonstration.")
    if not _RUN_LOCK.acquire(blocking=False):
        raise ReviewerBusyError("A demonstration is already running; try again when it finishes.")
    try:
        with TemporaryDirectory(prefix="m65-reviewer-") as workspace:
            payload, metrics = _project(demo, Path(workspace) / "run")
            if isinstance(payload, str):
                text = payload
            elif isinstance(payload, dict):
                text = json.dumps(payload, indent=2)
            else:
                text = TypeAdapter(type(payload)).dump_json(payload, indent=2).decode("utf-8")
        evidence = (EvidenceClass.DETERMINISTIC,)
        if demo in (Demo.RECOVERY, Demo.APPROVAL, Demo.MCP, Demo.REGRESSION):
            evidence += (EvidenceClass.LOCAL_INTEGRATION,)
        return DemoView(demo=demo, evidence=evidence, metrics=metrics,
                        details=text[:MAX_DISPLAY_CHARS], truncated=len(text) > MAX_DISPLAY_CHARS)
    finally:
        _RUN_LOCK.release()
