"""Read-only Story 10 dashboard renderer; owns no accounting or runtime policy."""

from typing import Literal

from harness_engineering.observability_report import ObservabilityReport


class PresentationError(ValueError):
    """Safe renderer boundary failure without source values or diagnostics."""


def render_report(report: ObservabilityReport, *, format: Literal["text", "json"] = "text") -> str:
    """Render validated allowlisted snapshots without invoking runtime services.

    Args:
        report: Immutable application-produced report; revalidated before display.
        format: Plain text dashboard with structured logs, or machine-readable JSON.

    Returns:
        A bounded string containing no business content, credentials or error repr.

    Raises:
        PresentationError: Report/format/serialization is unavailable or unsupported.
            The caller still owns the original result and persisted ledger.
    """
    try:
        if type(report) is not ObservabilityReport or format not in ("text", "json"):
            raise ValueError("Unsupported report or format.")
        checked = ObservabilityReport.model_validate(report)
        document = checked.model_dump_json(indent=2)
        if len(document.encode()) > 3_000_000:
            raise ValueError("Report exceeds bounded presentation profile.")
        if format == "json":
            return document
        state = checked.cost
        utilization = (state.committed_units + state.outstanding_units) * 100 // state.cap_units
        latency = checked.workflow_cohort
        status = ("insufficient_samples" if not latency.sufficient_samples else
                  "met" if latency.slo_met is True else
                  "missed" if latency.slo_met is False else "not_assessable")
        rows = [
            "Story 10 Observability and Cost Governance Lab",
            "Deterministic fixtures / generated runtime IDs / no verified billing",
            "Read cost and trace results below; --format json exposes the same closed facts.",
            f"Workflow: {checked.identity.workflow_id} | Thread: {checked.identity.thread_id}",
            f"Evidence: {checked.evidence.value}; phase: {checked.phase}",
            f"Fixture micro-USD: committed={state.committed_units} "
            f"outstanding={state.outstanding_units} cap={state.cap_units}",
            f"Utilization: {utilization}%"
            f" | warning 80%={80 in state.warnings} | warning 100%={100 in state.warnings}",
            f"Hard cap denied: {checked.hard_cap_denied}; recovery: {checked.recovery_preserved}",
            "Step | calls/reservations | allocated input/output | reported input/output | "
            "fixture committed/outstanding",
        ]
        for index in range(1, checked.tokens.step_count + 1):
            accounts = tuple(a for a in state.attempts if a.reservation.step_index == index)
            receipts = tuple(r for r in checked.usage if r.step_index == index)
            claims = tuple(a.usage for a in accounts
                           if a.usage is not None and a.usage.state.value == "reported")
            reported = (f"{sum(u.input_tokens for u in claims)}/"
                        f"{sum(u.output_tokens for u in claims)}"
                        if claims else "unavailable (local/uncertain)")
            rows.append(
                f"{index} | {len(receipts)}/{len(accounts)} | "
                f"{sum(a.allocated_input_tokens for a in accounts)}/"
                f"{sum(a.allocated_output_tokens for a in accounts)} | {reported} | "
                f"{sum(a.reservation.reserved_units for a in accounts if a.settled)}/"
                f"{sum(a.reservation.reserved_units for a in accounts if not a.settled)}"
            )
        rows.extend([
            f"Per-step token caps: input={checked.tokens.input_per_step}, "
            f"output={checked.tokens.output_per_step}; reports never refund allocations.",
            "Local input bytes and usage availability are in the structured receipts below.",
            f"Workflow cohort: {latency.cohort.model_dump_json()}",
            f"n={latency.sample_count} p50={latency.p50_seconds}s p95={latency.p95_seconds}s "
            f"SLO p95<={latency.slo_p95_seconds}s: {status}",
            "Deadline: 180s, separate safety bound. HITL/resume segments are not workflow SLOs.",
            "This measures local lifecycle invocation, not hosted availability "
            "or production latency.",
            "Anomalies (advisory): " + ", ".join(s.facts.kind.value for s in checked.anomalies),
            "Retry/denial/provider-failure/tool-frequency inputs are explicit "
            "event-stream fixtures; "
            "budget spike and compression observations come from actual local services.",
            "Optional integrations (offline only):",
        ])
        rows.extend(f"{v.vendor.value}: enabled={v.enabled} health={v.health.model_dump_json()}"
                    for v in checked.integrations)
        rows.extend([
            "Helicone: disabled offline header contract; no gateway binding or provider rerouting.",
            "Trace/span IDs, step ordinals, structured logs, receipts and latency cohorts:",
            document,
            "No hosted telemetry, inference, real tariffs, billing or deployment evidence.",
        ])
        return "\n".join(rows)
    except (ValueError, TypeError, OverflowError):
        # Renderer/serialization boundary only. Never alter persisted facts on failure.
        raise PresentationError(
            "Observability presentation unavailable; source facts retained."
        ) from None
