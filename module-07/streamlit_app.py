"""Module 7's explicit Streamlit reviewer-console entry point."""

import asyncio

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
from streamlit.runtime.state import SafeSessionState, SessionState

from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.console_presenter import (
    BenchmarkEvidence,
    BenchmarkReceipt,
    ConsoleBoundary,
    LiveAuthorizationReceipt,
    LiveGrant,
    evidence_badge,
    lab_projection,
    recovery_projection,
    safe_error,
)


def guidance(demonstrates: str, action: str, expected: str, proves: str) -> None:
    """Render the required concise four-part reviewer guidance."""
    with st.container(border=True):
        st.markdown(f"**Demonstrates:** {demonstrates}")
        st.markdown(f"**Do this:** {action}")
        st.markdown(f"**Expect:** {expected}")
        st.markdown(f"**Proves:** {proves}")


_BOUNDARY_KEY = "_console_boundary"
_SUPPORTED_STREAMLIT_VERSION = "1.66.1"


def _session_anchor() -> object:
    """Return a validated server-owned session state anchor.

    Streamlit exposes no public server-side session identity suitable for this
    ownership boundary: ``st.context`` intentionally contains only client
    context.  Only the pinned Streamlit 1.66.1 runtime is supported: its local
    ``AppSession`` source constructs one concrete ``SessionState`` per session,
    and its ``ScriptRunner`` wraps that state in ``SafeSessionState`` on each
    rerun.  This narrow private compatibility boundary validates that exact
    runtime version and both exact runtime types before returning the stable
    inner state.  Missing, substituted, sentinel-shaped, or unvalidated-version
    internals therefore fail closed before any boundary authority is recovered.
    """
    if st.__version__ != _SUPPORTED_STREAMLIT_VERSION:
        raise RuntimeError("Reviewer session ownership is unavailable.")
    ctx = get_script_run_ctx()
    if ctx is None:
        raise RuntimeError("No reviewer session is active.")
    safe_state = getattr(ctx, "session_state", None)
    if type(safe_state) is not SafeSessionState:
        raise RuntimeError("Reviewer session ownership is unavailable.")
    try:
        state = object.__getattribute__(safe_state, "_state")
    except AttributeError as exc:
        raise RuntimeError("Reviewer session ownership is unavailable.") from exc
    if type(state) is not SessionState:
        raise RuntimeError("Reviewer session ownership is unavailable.")
    return state


def boundary() -> ConsoleBoundary:
    """Return the composition owned by exactly this reviewer session.

    The boundary lives only as long as its session and holds bounded
    registries, so there is no process-global retention.  A boundary that was
    not created for this exact session is foreign and is replaced, failing
    closed rather than transferring another session's authority.
    """
    anchor = _session_anchor()
    console = st.session_state.get(_BOUNDARY_KEY)
    if not isinstance(console, ConsoleBoundary) or not console.owned_by(anchor):
        console = ConsoleBoundary(RuntimeSettings(), session_anchor=anchor)
        st.session_state[_BOUNDARY_KEY] = console
    return console


def _state() -> None:
    """Initialize bounded, display-only session values once."""
    for name in (
        "workflow",
        "benchmark",
        "before",
        "after",
        "selected_lab",
        "full_lab",
        "live_result",
    ):
        st.session_state.setdefault(name, None)
    st.session_state.setdefault("_live_confirmation", None)


def _refresh_live_confirmation(console: ConsoleBoundary) -> None:
    """Store only a reference to a boundary-owned acknowledgement receipt."""
    if not st.session_state.get("live_confirmation", False):
        console.invalidate_live_confirmation()
        st.session_state._live_confirmation = None
        return
    st.session_state._live_confirmation = console.issue_live_confirmation(
        st.session_state.live_provider
    )


def _invalidate_live_confirmation(console: ConsoleBoundary) -> None:
    """Invalidate a held receipt before a provider-selection rerun."""
    console.invalidate_live_confirmation()
    st.session_state.live_confirmation = False
    st.session_state._live_confirmation = None


def _current_confirmation(
    console: ConsoleBoundary, provider: str
) -> LiveAuthorizationReceipt | None:
    """Return a display-held reference only when the boundary still recognizes it."""
    confirmation = st.session_state.get("_live_confirmation")
    if not console.live_confirmation_is_current(confirmation, provider):
        return None
    return confirmation


def _badge(value: object) -> None:
    st.badge(evidence_badge(value), color="blue")


def synchronize_comparison(
    console: ConsoleBoundary,
) -> tuple[BenchmarkReceipt, BenchmarkReceipt] | None:
    """Synchronize display references with the boundary's bounded receipt window."""
    return console.comparison_receipts()


def run_live_verifier(grant: LiveGrant) -> dict[str, object]:
    """Call one existing verifier with a consumed boundary grant only.

    The grant carries the exact configuration the human confirmed.  The
    verifiers own all configuration, authorization, endpoint, timeout, cost,
    provenance, redaction, and lifecycle decisions. This function does not
    create a provider client or transport and never displays a secret.
    """
    provider, runtime, settings = grant.provider, grant.runtime, grant.settings
    if provider == "Langfuse":
        from reliability_safety_observability.langfuse_adapter import run_live_verification
        from reliability_safety_observability.langfuse_config import LangfuseSettings

        if not isinstance(settings, LangfuseSettings):
            raise TypeError("The confirmed configuration is unavailable.")
        result = asyncio.run(run_live_verification(runtime, settings, opt_in=True))
        return {
            "provider": provider,
            "outcome": result.outcome.value,
            "evidence_class": evidence_badge(result.evidence_class),
            "trace_id": result.trace_id,
            "confirmed_observations": result.confirmed_observations,
            "close_state": result.close_state.value,
        }
    if provider == "LangSmith":
        from reliability_safety_observability.langsmith_adapter import (
            run_live_langsmith_verification,
        )
        from reliability_safety_observability.langsmith_config import LangSmithSettings

        if not isinstance(settings, LangSmithSettings):
            raise TypeError("The confirmed configuration is unavailable.")
        result = run_live_langsmith_verification(runtime, settings, opt_in=True)
        return {
            "provider": provider,
            "outcome": result.outcome,
            "evidence_class": evidence_badge(result.evidence_class),
            "run_id": str(result.run_id),
            "report_digest": result.report_digest,
            "confirmed_examples": result.confirmed_examples,
            "confirmed_feedback": result.confirmed_feedback,
            "close_state": result.close_state,
        }
    if provider == "Helicone":
        from reliability_safety_observability.helicone_adapter import run_live_helicone_verification
        from reliability_safety_observability.helicone_config import HeliconeSettings

        if not isinstance(settings, HeliconeSettings):
            raise TypeError("The confirmed configuration is unavailable.")
        result = run_live_helicone_verification(runtime, settings, opt_in=True)
        return {
            "provider": provider,
            "outcome": result.outcome,
            "evidence_class": evidence_badge(result.evidence_class),
            "request_id": result.request_id,
            "session_id": result.session_id,
            "workflow_id": result.workflow_id,
            "confirmed_readback": result.confirmed_readback,
            "close_state": result.close_state,
        }
    raise ValueError("The selected provider verifier is unavailable.")


def overview(console: ConsoleBoundary) -> None:
    st.header("Start here")
    st.write("A credential-free, deterministic reviewer console for Module 7.")
    st.info(
        "Default mode is deterministic and network-free. "
        "Evidence labels describe what a result proves.",
        title=f"Execution mode: {console.mode}",
    )
    guidance(
        "The complete observability and evaluation journey.",
        "Start with Workflow, then Evaluation, then the Failure-recovery lab.",
        "Typed, local results with a visible evidence label.",
        "The console renders existing Module 7 behavior rather than static claims.",
    )
    st.subheader("Evidence legend")
    st.table(
        [
            {
                "class": "deterministic_fixture",
                "boundary": "Local deterministic evidence; not live vendor/model behavior.",
            },
            {
                "class": "simulated_failure",
                "boundary": "Controlled recovery evidence; not a live incident.",
            },
            {
                "class": "mocked_provider_contract",
                "boundary": "Adapter-contract evidence; not provider ingestion.",
            },
            {"class": "live_vendor", "boundary": "Only the exact qualified provider verification."},
            {"class": "live_model", "boundary": "Only the exact qualified model-backed result."},
        ]
    )


def workflow(console: ConsoleBoundary) -> None:
    st.header("Workflow and observability")
    guidance(
        "A fixed approved workflow through authorization, safety, reliability, and telemetry.",
        "Select Run deterministic workflow.",
        "Correlation IDs, decisions, recovery facts, and minimized telemetry.",
        "The existing controls execute locally and their returned facts are visible.",
    )
    if st.button("Run deterministic workflow", key="run_workflow", width="content"):
        try:
            st.session_state.workflow = console.run_workflow()
        except Exception as exc:  # Browser boundary: never render error details.
            st.error(safe_error(exc), title="Workflow unavailable")
    result = st.session_state.workflow
    if result is None:
        st.caption("No workflow has been run.")
        return
    view = recovery_projection(result.recovery)
    _badge(view["evidence_class"])
    st.json(view)
    st.subheader("Normalized telemetry")
    st.dataframe(result.records, hide_index=True, alt="Redacted normalized workflow telemetry")


def evaluation(console: ConsoleBoundary) -> None:
    st.header("Evaluation and regression")
    guidance(
        "The committed deterministic dataset, evaluator, benchmark, and regression comparison.",
        "Select Run deterministic benchmark; run a second benchmark if you want a comparison.",
        "A verdict, digest, regression result, and optional human-review-only improvement context.",
        "Evaluation evidence is real and bounded; no baseline or policy is changed.",
    )
    if st.button("Run deterministic benchmark", key="run_benchmark", width="content"):
        try:
            result = console.run_benchmark()
            st.session_state.benchmark = result
            comparison = synchronize_comparison(console)
            if comparison is None:
                st.session_state.before = None
                st.session_state.after = None
            else:
                st.session_state.before, st.session_state.after = comparison
        except Exception as exc:
            st.error(safe_error(exc), title="Benchmark unavailable")
    result: BenchmarkEvidence | None = st.session_state.benchmark
    if result is None:
        st.caption("No benchmark has been run.")
    else:
        output = result.output
        st.json(
            {
                "verdict": output.verdict.value,
                "report_digest": output.report_digest,
                "dataset": output.run.result.identity.dataset_id,
                "dataset_version": output.run.result.identity.dataset_version,
                "subset": "full" if output.subset is None else list(output.subset),
                "regression": output.regression.outcome.value
                if output.regression
                else "unavailable",
                "evidence_class": "deterministic_fixture",
            }
        )
        st.dataframe(
            [
                {
                    "scenario": row.scenario_id,
                    "evaluator": row.evaluator_id,
                    "metric": row.metric,
                    "score": row.score,
                    "passed": row.passed,
                    "evidence_class": row.evidence_class.value,
                }
                for row in output.run.result.evaluations
            ],
            hide_index=True,
            alt="Authoritative benchmark evaluator outcomes",
        )
    before: BenchmarkReceipt | None = st.session_state.before
    after: BenchmarkReceipt | None = st.session_state.after
    if before is None or after is None:
        st.info(
            "Run two benchmarks to make an improvement comparison available.",
            title="Comparison unavailable",
        )
        return
    cycle = console.improvement(before, after)
    if cycle is None:
        st.warning(
            "The selected benchmark references are invalid or incompatible.",
            title="Comparison unavailable",
        )
        return
    st.subheader("Improvement-cycle evidence")
    st.caption(
        f"Before benchmark {before.ordinal}; after benchmark {after.ordinal}. "
        "Pending human review only."
    )
    st.json(cycle.model_dump(mode="json"))


def failure_lab(console: ConsoleBoundary) -> None:
    st.header("Failure-recovery lab")
    guidance(
        "The accepted Story 8 S01-S20 failure taxonomy and real recovery boundaries.",
        "Choose one scenario or run the complete fixed matrix.",
        "Typed pass/fail, retry, fallback, budget, authority, safety, and evidence facts.",
        "Failure recovery is deterministic, bounded, and does not grant authority.",
    )
    selected = st.selectbox(
        "Scenario", options=tuple(f"s{number:02}" for number in range(1, 21)), key="scenario"
    )
    left, right = st.columns(2)
    with left:
        if st.button("Run selected scenario", key="run_selected_lab", width="stretch"):
            try:
                st.session_state.selected_lab = console.run_selected_lab(selected)
            except Exception as exc:
                st.error(safe_error(exc), title="Lab unavailable")
    with right:
        if st.button("Run complete matrix", key="run_full_lab", width="stretch"):
            try:
                st.session_state.full_lab = console.run_full_lab()
            except Exception as exc:
                st.error(safe_error(exc), title="Lab unavailable")
    if st.session_state.selected_lab is not None:
        st.json(lab_projection(st.session_state.selected_lab))
    if st.session_state.full_lab is not None:
        rows, summary = st.session_state.full_lab
        st.json(
            {
                "digest": summary.digest,
                "passed": summary.passed_count,
                "failed": summary.failed_count,
                "evidence_counts": dict(summary.evidence_counts),
            }
        )
        st.dataframe(
            [lab_projection(row) for row in rows],
            hide_index=True,
            alt="Complete failure lab results",
        )


def providers(console: ConsoleBoundary) -> None:
    st.header("Provider evidence")
    guidance(
        "The distinction between local evidence and an optional separately verified "
        "provider interaction.",
        "Inspect status; configure live evidence only through the external approved "
        "configuration path.",
        "Live evidence remains unavailable by default and no network request is made here.",
        "Credentials never grant authority and deterministic results are never upgraded.",
    )
    status = "configuration-gated" if console.live_available else "live evidence unavailable"
    st.info("No provider verifier has been run by this page.", title=status)
    selected = st.selectbox(
        "Existing verifier",
        options=("Langfuse", "LangSmith", "Helicone"),
        key="live_provider",
        on_change=_invalidate_live_confirmation,
        args=(console,),
    )
    confirmed = st.checkbox(
        "I confirm this bounded live evidence request.",
        key="live_confirmation",
        disabled=not console.live_available,
        on_change=_refresh_live_confirmation,
        args=(console,),
    )
    confirmation = _current_confirmation(console, selected)
    confirmation_ready = confirmation is not None
    if confirmed and confirmation is None:
        st.warning(
            "This confirmation was consumed or invalidated by a different live action or "
            "configuration. Clear it and explicitly confirm the current request.",
            title="Fresh confirmation required",
        )
    if st.button(
        "Generate bounded live evidence",
        key="run_live_verifier",
        disabled=not (console.live_available and confirmation_ready),
        width="content",
    ):
        # Consume at the authoritative boundary before invoking.  A restored,
        # copied, forged, or concurrent presentation reference cannot replay it.
        grant = console.consume_live_confirmation(confirmation, selected)
        st.session_state._live_confirmation = None
        if grant is not None:
            try:
                st.session_state.live_result = run_live_verifier(grant)
            except Exception as exc:
                st.error(safe_error(exc), title="Live evidence unavailable")
        else:
            st.warning(
                "A fresh confirmation is required before generating live evidence.",
                title="Confirmation unavailable",
            )
    if st.session_state.live_result is not None:
        st.json(st.session_state.live_result)
    st.caption(
        "The action is a one-time delegation to an existing public verifier after its "
        "gates pass. The console does not create a provider transport."
    )


def main() -> None:
    """Render the explicit, no-key reviewer console."""
    st.set_page_config(
        page_title="Module 7 reviewer console", page_icon=":material/monitoring:", layout="wide"
    )
    _state()
    console = boundary()
    st.title("Module 7 observability and evaluation console")
    pages = st.tabs(
        ["Overview", "Workflow", "Evaluation", "Failure-recovery lab", "Provider evidence"]
    )
    with pages[0]:
        overview(console)
    with pages[1]:
        workflow(console)
    with pages[2]:
        evaluation(console)
    with pages[3]:
        failure_lab(console)
    with pages[4]:
        providers(console)


if __name__ == "__main__":
    main()
