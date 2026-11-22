"""Module 7's explicit Streamlit reviewer-console entry point."""

import sys
from pathlib import Path

# Deployment bootstrap (Step 284.2, F4): when this file is executed
# directly from a checkout (for example by Streamlit Community Cloud
# with main file module-07/streamlit_app.py), the src-layout package is
# not installed, so its source directory is added to sys.path before
# any package import.  The guard keeps installed/venv environments
# unchanged and never duplicates an existing entry.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import asyncio  # noqa: E402  (imported after the sys.path bootstrap)

import streamlit as st  # noqa: E402
from streamlit.runtime.scriptrunner import get_script_run_ctx  # noqa: E402
from streamlit.runtime.state import SafeSessionState, SessionState  # noqa: E402

from reliability_safety_observability.byok_evaluation import (  # noqa: E402
    ALLOWED_BYOK_MODELS,
    BYOK_CASES,
    MAX_OUTPUT_TOKENS,
    MIN_OUTPUT_TOKENS,
    PROVIDER_NAME,
    LiveRunRequest,
    OpenAITransport,
    SessionRunGuard,
    execute_live_run,
)
from reliability_safety_observability.config import RuntimeSettings  # noqa: E402
from reliability_safety_observability.console_presenter import (  # noqa: E402
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
from reliability_safety_observability.failure_lab import (  # noqa: E402
    _SLUGS,
    ScenarioKind,
)

_APPLICATION_TITLE = "Module 7 Observation and Evaluation Console"
_ATTRIBUTION = (
    "Developed from Techademy AI Engineering program requirements. "
    "Independent implementation, engineering enhancements, and deployment."
)


def attribution_footer() -> None:
    """Render the required attribution once, at a tab's bottom."""
    st.caption(_ATTRIBUTION)


def scenario_label(scenario_id: str) -> str:
    """Return the human-facing label for one underlying scenario id.

    Args:
        scenario_id: The lowercase execution identifier (``s01``..``s20``).

    Returns:
        ``SNN - Description`` derived word-for-word from the
        authoritative Story 8 taxonomy; the underlying identifier and
        execution behavior are unchanged.
    """
    kind = ScenarioKind(scenario_id)
    number = int(kind.value[1:])
    description = " ".join(word.capitalize() for word in _SLUGS[kind].split("-"))
    return f"S{number:02d} - {description}"


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
    st.session_state.setdefault("_live_attempt_status", None)
    st.session_state.setdefault("_byok_guard", SessionRunGuard())
    st.session_state.setdefault("_byok_result", None)
    st.session_state.setdefault("_byok_notice", None)


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
        "Scenario",
        options=tuple(f"s{number:02}" for number in range(1, 21)),
        key="scenario",
        format_func=scenario_label,
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


def _byok_request() -> LiveRunRequest | None:
    """Build the run request from the current widgets, or None when invalid.

    Returns:
        The caller-confirmed run request, or None when the current
        widget state cannot form a valid request (the caller must fail
        closed without any invocation).
    """
    try:
        return LiveRunRequest(
            model=st.session_state.byok_model,
            case_ids=tuple(st.session_state.byok_cases),
            max_requests=min(len(st.session_state.byok_cases), 5),
            max_output_tokens=int(st.session_state.byok_tokens),
        )
    except Exception:
        return None


def _byok_current() -> LiveRunRequest | None:
    """Build the current-widget request for invalidation comparisons."""
    try:
        return LiveRunRequest(
            model=st.session_state.byok_model,
            case_ids=tuple(st.session_state.byok_cases),
            max_requests=min(len(st.session_state.byok_cases), 5),
            max_output_tokens=int(st.session_state.byok_tokens),
        )
    except Exception:
        return None


def _invalidate_byok_pending() -> None:
    """Drop the pending authorization when run inputs changed."""
    guard: SessionRunGuard = st.session_state._byok_guard
    request = _byok_current()
    # When the current widget state cannot form a valid run configuration
    # (for example every evaluation case was cleared), cancellation is
    # expressed by dropping the pending grant itself; a fabricated request
    # would be rejected by its own validation before the guard could react,
    # and could leave the grant armed.
    dropped = guard.invalidate(request) if request is not None else guard.drop_pending()
    if dropped:
        # The operator's confirmation applied to the previous configuration.
        # Clearing it keeps the displayed state truthful: a changed input
        # needs a fresh, explicit confirmation before any run is authorized.
        st.session_state["byok_confirm"] = False


def _prepare_byok_authorization() -> None:
    """Prepare a fresh per-run authorization when the confirmation is set."""
    guard: SessionRunGuard = st.session_state._byok_guard
    request = _byok_request()
    if request is None:
        return
    pending = guard.pending
    if pending is None or pending.binding_digest != request.binding_digest:
        guard.prepare(request)


def _invalidate_byok_confirmation() -> None:
    """Reset the one-shot grant when the confirmation changes.

    A fresh confirmation binds a fresh authorization to the configuration
    that is current at the moment of confirmation.  The authorization is not
    re-prepared on later reruns, so any subsequent input change really does
    invalidate it and a new confirmation is required.
    """
    st.session_state._byok_guard = SessionRunGuard()
    if st.session_state.get("byok_confirm"):
        _prepare_byok_authorization()


def byok_model_check(console: ConsoleBoundary) -> None:
    """Render the bounded BYOK live-model evaluation tab.

    Deterministic mode is the default: no API key, no external calls,
    and the existing local functionality stays authoritative.  BYOK
    live mode requires an explicit per-run confirmation; a submitted
    run is consumed once within this session, duplicate or overlapping
    submissions are rejected, and any input change invalidates a
    pending authorization.  Returned model text is treated as
    untrusted data and is never executed.
    """
    st.header("BYOK model check")
    if st.session_state.pop("_byok_wipe_credential", False):
        # A completed live run already consumed the credential; remove it
        # before the widget is recreated so it does not outlive the run.
        st.session_state.pop("byok_api_key", None)
    mode = st.radio(
        "Execution mode",
        options=("Deterministic mode (no API key)", "BYOK live mode"),
        key="byok_mode",
        horizontal=True,
    )
    if mode != "BYOK live mode":
        st.write(
            "**Deterministic mode.** No API key is required, no external "
            "provider is called, and every result in the other tabs is "
            "deterministic/local."
        )
        st.caption("Switch to BYOK live mode to configure a bounded live check.")
        return
    guard: SessionRunGuard = st.session_state._byok_guard
    st.caption(
        "BYOK live mode: your key is used transiently in memory for the "
        "confirmed run only; it is never persisted to disk and is "
        "dropped from the session after the run completes. An estimated "
        "cost appears only when you supply documented unit prices; it "
        "is an estimate, never a guaranteed spending limit."
    )
    st.selectbox(
        "Provider",
        options=(PROVIDER_NAME,),
        key="byok_provider",
        disabled=True,
    )
    st.selectbox(
        "Model (allowlisted)",
        options=ALLOWED_BYOK_MODELS,
        key="byok_model",
        on_change=_invalidate_byok_pending,
    )
    st.multiselect(
        "Evaluation cases",
        options=[case.case_id for case in BYOK_CASES],
        default=[BYOK_CASES[0].case_id],
        key="byok_cases",
        max_selections=5,
        on_change=_invalidate_byok_pending,
        help="Each selected case is one real provider request.",
    )
    for case in BYOK_CASES:
        st.caption(f"{case.case_id} ({case.category}): {case.criterion_description}")
    st.number_input(
        "Maximum output tokens per request",
        min_value=MIN_OUTPUT_TOKENS,
        max_value=MAX_OUTPUT_TOKENS,
        value=200,
        step=25,
        key="byok_tokens",
        on_change=_invalidate_byok_pending,
    )
    with_price = st.checkbox(
        "Show estimated cost (I supply documented unit prices)",
        key="byok_price_enabled",
    )
    pricing = None
    if with_price:
        left, right = st.columns(2)
        with left:
            input_price = st.number_input(
                "Input USD per 1k tokens", min_value=0.0, value=0.0, key="byok_price_in"
            )
        with right:
            output_price = st.number_input(
                "Output USD per 1k tokens", min_value=0.0, value=0.0, key="byok_price_out"
            )
        pricing = {
            st.session_state.byok_model: {
                "input_per_1k": input_price,
                "output_per_1k": output_price,
            }
        }
    st.text_input(
        "API key (BYOK, masked)",
        type="password",
        key="byok_api_key",
        help="Transient in-memory use only; cleared after the run.",
    )
    st.checkbox(
        "I authorize exactly one bounded live evaluation run with the "
        "settings above.",
        key="byok_confirm",
        on_change=_invalidate_byok_confirmation,
    )
    request = _byok_current()
    pending = guard.pending
    stale = (
        pending is not None
        and request is not None
        and pending.binding_digest != request.binding_digest
    )
    if stale:
        st.warning(
            "Run inputs changed; the pending authorization was "
            "invalidated. Re-confirm to authorize the new configuration.",
            title="Fresh authorization required",
        )
    if st.button(
        "Run authorized live evaluation",
        key="byok_submit",
        width="content",
    ):
        if guard.running:
            st.session_state._byok_notice = (
                "A live run is already executing in this session; "
                "overlapping or duplicate submissions are rejected."
            )
        elif not st.session_state.byok_confirm or pending is None:
            st.session_state._byok_notice = (
                "No pending authorization. Confirm the run first; a "
                "fresh confirmation is required after any input change."
            )
        elif request is None or pending.binding_digest != request.binding_digest:
            st.session_state._byok_notice = (
                "The pending authorization does not match the current "
                "inputs and was invalidated. Re-confirm to proceed."
            )
            _invalidate_byok_pending()
        elif not guard.begin(pending):
            st.session_state._byok_notice = (
                "This authorization was already consumed in this "
                "session. Confirm again for a new run."
            )
        else:
            api_key = st.session_state.get("byok_api_key", "") or ""
            try:
                st.session_state._byok_result = execute_live_run(
                    request,
                    api_key=api_key,
                    transport=OpenAITransport(),
                    pricing=pricing,
                )
                guard.complete()
                st.session_state._byok_notice = None
            except Exception as exc:
                guard.complete()
                st.session_state._byok_notice = None
                st.error(safe_error(exc), title="Live evaluation unavailable")
            finally:
                # The credential is wiped from the session as soon as the run
                # completes: the next render deletes the widget value before
                # the widget is recreated.  Deleting it in this run would
                # desynchronize Streamlit's own widget state.
                st.session_state["_byok_wipe_credential"] = True
                api_key = ""
            st.rerun()
    notice = st.session_state._byok_notice
    if notice:
        st.warning(notice, title="Authorization boundary")
    result = st.session_state._byok_result
    if result is None:
        st.caption("No live evaluation has been run in this session.")
        return
    if result.blocked_category is not None:
        st.warning(
            {
                "missing_credentials": (
                    "No API key was supplied; the run failed closed and "
                    "no provider request was made."
                )
            }.get(
                result.blocked_category.value,
                "The run was blocked before any provider request.",
            ),
            title="Run blocked",
        )
        return
    evaluated = [
        row for row in result.case_results if row.outcome.value in {"pass", "fail"}
    ]
    st.json(
        {
            "provider": result.provider,
            "model": result.model,
            "run_id": str(result.run_id),
            "invocations": result.invocations,
            "failure_categories": [
                category.value for category in result.failure_categories
            ],
            "evidence_class": "live_model",
        }
    )
    st.dataframe(
        [
            {
                "case": row.case_id,
                "criterion": row.criterion,
                "outcome": row.outcome.value,
                "evidence_class": row.evidence_class.value if row.evidence_class else "none",
                "latency_ms": row.elapsed_ms,
                "usage": row.usage_source.value,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "estimated_cost_usd": row.estimated_cost_usd,
                "failure_category": (
                    row.failure_category.value if row.failure_category else "none"
                ),
            }
            for row in result.case_results
        ],
        hide_index=True,
        alt="Sanitized BYOK live evaluation outcomes",
    )
    if not evaluated:
        st.warning(
            "No case produced a grounded evaluation outcome; see the "
            "per-case rows and failure categories above.",
            title="No grounded evaluation",
        )
    st.caption(
        "Returned model text is untrusted data: it is only displayed "
        "safely and evaluated against explicit textual criteria. It is "
        "never executed, and API success is not evaluation success."
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
    attempt_notice = st.empty()
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
            st.session_state._live_attempt_status = "attempted"
            try:
                st.session_state.live_result = run_live_verifier(grant)
                st.session_state._live_attempt_status = (
                    "confirmed"
                    if st.session_state.live_result.get("outcome") == "confirmed"
                    else "unsuccessful"
                )
            except Exception as exc:
                st.session_state._live_attempt_status = "unavailable"
                st.error(safe_error(exc), title="Live evidence unavailable")
        else:
            st.warning(
                "A fresh confirmation is required before generating live evidence.",
                title="Confirmation unavailable",
            )
    attempt_notice.info(
        {
            None: "No provider verifier has been run by this page.",
            "attempted": "Verification was attempted; no completed result is available.",
            "confirmed": (
                "Verification returned a confirmed result. Its evidence scope is shown below."
            ),
            "unsuccessful": (
                "Verification did not confirm a result. See the returned outcome below."
            ),
            "unavailable": (
                "Verification failed or was unavailable. No successful result is claimed."
            ),
        }.get(st.session_state._live_attempt_status, "Verification status is unavailable."),
        title=status,
    )
    if st.session_state.live_result is not None:
        if st.session_state._live_attempt_status == "unavailable":
            st.caption("Previous returned result; the latest attempt did not return a result.")
        st.json(st.session_state.live_result)
    st.caption(
        "The action is a one-time delegation to an existing public verifier after its "
        "gates pass. The console does not create a provider transport."
    )


def main() -> None:
    """Render the explicit, no-key reviewer console."""
    st.set_page_config(
        page_title=_APPLICATION_TITLE, page_icon=":material/monitoring:", layout="wide"
    )
    _state()
    console = boundary()
    st.title(_APPLICATION_TITLE)
    pages = st.tabs(
        [
            "Overview",
            "Workflow",
            "Evaluation",
            "Failure-recovery lab",
            "Provider evidence",
            "BYOK model check",
        ]
    )
    with pages[0]:
        overview(console)
        attribution_footer()
    with pages[1]:
        workflow(console)
        attribution_footer()
    with pages[2]:
        evaluation(console)
        attribution_footer()
    with pages[3]:
        failure_lab(console)
        attribution_footer()
    with pages[4]:
        providers(console)
        attribution_footer()
    with pages[5]:
        byok_model_check(console)
        attribution_footer()


if __name__ == "__main__":
    main()
