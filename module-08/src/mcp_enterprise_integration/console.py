"""Streamlit presentation only: reviewer inputs and actual backend results."""

from dataclasses import asdict

import streamlit as st

from mcp_enterprise_integration.errors import ConfigurationError
from mcp_enterprise_integration.live_provider import (
    GEMINI_LIVE_MODELS,
    MAX_ADK_MODEL_CALLS,
    MAX_OPENAI_MODEL_CALLS,
    MAX_OUTPUT_TOKENS,
    OPENAI_LIVE_MODELS,
    STAGE_TIMEOUT_SECONDS,
    WORKFLOW_TIMEOUT_SECONDS,
    LiveConsent,
    LiveProviderSelection,
    ProviderCredential,
    ProviderName,
)
from mcp_enterprise_integration.reviewer import (
    LiveReviewerResult,
    ReviewerError,
    ReviewerResult,
    run_live_provider_demo,
    run_reviewer_demo,
)

MODES = ("Deterministic Demo", "Live Provider Demo (opt-in)")
SCENARIOS = ["Manager review", "Support review"]


def render_result(result: ReviewerResult) -> None:
    """Present structured backend evidence without deriving business decisions."""
    st.success("Local enterprise execution completed and results validated.")
    columns = st.columns(3)
    columns[0].metric("Discovered capabilities", len(result.capabilities))
    columns[1].metric("Workflow MCP stages", len(result.workflow.stages))
    columns[2].metric("Model calls", 0)
    st.caption("Deterministic fixtures · local-integration evidence · zero paid provider calls")
    discovery, enterprise, workflow, evidence = st.tabs(
        ["Discovery & authority", "Enterprise results", "Interoperable workflow", "Evidence"]
    )
    with discovery:
        st.write(
            "Real MCP initialization and discovery returned these capabilities. "
            "Discovery describes availability; application policy controls execution."
        )
        st.dataframe([{"Capability": name} for name in result.capabilities], hide_index=True)
        st.success(f"Viewer customer read allowed: {result.allowed.rule_id}")
        if result.denied:
            st.warning(
                "Viewer policy evaluation denied before remote invocation. "
                "A discovered capability cannot grant its caller authority."
            )
        st.caption("Viewer is a fixed demonstration identity, not an authenticated user.")
    with enterprise:
        st.write(
            "SQLite customer and enterprise HTTP account results were obtained through MCP. "
            "The internal policy service evaluates a proposal; it executes no account change."
        )
        st.dataframe([result.customer.model_dump()], hide_index=True)
        st.dataframe([result.workflow.account.model_dump()], hide_index=True)
        st.dataframe([result.workflow.policy_result.model_dump(mode="json")], hide_index=True)
        st.info(
            "Direct-versus-MCP comparison passed for the same seeded customer. "
            "Direct access uses the Python repository; MCP consumers use protocol capabilities. "
            "This is a direct application call comparison, not a model performance benchmark."
        )
    with workflow:
        st.write(
            "Story 8 executes OpenAI SDK → Google ADK → OpenAI SDK over the shared MCP plane. "
            "SDK tool integrations run; neither model runner runs."
        )
        st.dataframe(
            [
                {
                    "Stage": index,
                    "SDK": stage.framework.value,
                    "Capability": stage.authorization.capability,
                    "Authorized": stage.authorization.allowed,
                    "Transport": stage.transport.value,
                    "Evidence": stage.evidence.evidence_class.value,
                }
                for index, stage in enumerate(result.workflow.stages, start=1)
            ],
            hide_index=True,
        )
        st.write("Validated cross-stage context sent to the internal policy service:")
        st.dataframe([result.workflow.policy_request.model_dump(mode="json")], hide_index=True)
        decision = result.workflow.policy_result
        st.info(f"Proposed account change: {decision.decision.value}. {decision.reason}")
        st.caption("Business policy denial is a valid result, separate from capability denial.")
    with evidence:
        st.dataframe([asdict(result.connection)], hide_index=True)
        st.dataframe(
            [
                result.discovery_evidence.model_dump(mode="json"),
                *[stage.evidence.model_dump(mode="json") for stage in result.workflow.stages],
            ],
            hide_index=True,
        )
        st.write(
            "Local integration proves working loopback transport and backend participation. "
            "It does not establish live-provider, multi-host, cloud, or deployment readiness."
        )
        with st.expander("Structured execution detail"):
            st.json(result.workflow.model_dump(mode="json"))


def _deterministic_demo() -> None:
    """Run the accepted default key-free demonstration."""
    scenario = st.selectbox("Demonstration scenario", SCENARIOS)
    st.caption("Seeded customer: CUST-001 · no API key · no external model/provider calls")
    if st.button("Run enterprise demonstration", type="primary"):
        st.session_state.pop("reviewer_result", None)
        st.session_state.pop("reviewer_scenario", None)
        try:
            with st.spinner("Executing real local MCP services and SDK workflow…"):
                result = run_reviewer_demo(scenario)
            st.session_state["reviewer_result"] = result
            st.session_state["reviewer_scenario"] = scenario
        except ReviewerError as exc:
            st.error(str(exc))
    if "reviewer_result" in st.session_state:
        st.caption(
            f"Captured execution: {st.session_state['reviewer_scenario']}. "
            "Run again to capture results for a different scenario."
        )
        render_result(st.session_state["reviewer_result"])


def _selection(
    enabled: bool, key: str, model: str, provider: ProviderName
) -> LiveProviderSelection | None:
    """Build a provider selection only when the reviewer explicitly enabled it."""
    if not enabled:
        return None  # A pasted key without selection is ignored, never used.
    return LiveProviderSelection(ProviderCredential.from_user_input(key, provider=provider), model)


def _live_demo() -> None:
    """Collect explicit consent and ephemeral keys, then run one bounded live demonstration."""
    st.subheader("Live Provider Demo (optional, opt-in)")
    st.warning(
        "This mode contacts external model providers (OpenAI and/or Google Gemini) with the "
        "keys you paste below and can incur charges on your provider account. The seeded "
        "synthetic record CUST-001 is sent to each selected provider. Deterministic Demo "
        "remains available without keys."
    )
    st.write(
        "What happens: each selected model, through its own SDK, sees only the one MCP "
        "capability the application authorized for that stage and must call it with the "
        "application-bound customer. OpenAI drives stage 1 (get_customer); Gemini through "
        "Google ADK drives stage 2 (get_account_status). Unselected stages use the "
        "deterministic SDK path. Stage 3, the enterprise policy decision, never uses a model."
    )
    st.caption(
        f"Bounds: at most {MAX_OPENAI_MODEL_CALLS} OpenAI and {MAX_ADK_MODEL_CALLS} Gemini model "
        f"calls, {MAX_OUTPUT_TOKENS} output tokens per call, one MCP tool call per stage, no "
        f"retries, {STAGE_TIMEOUT_SECONDS:.0f}s per stage and {WORKFLOW_TIMEOUT_SECONDS:.0f}s per "
        "run, one live run at a time. These are call, token and time bounds, not a billing "
        "guarantee; your provider bills by its own pricing."
    )
    st.caption(
        "Keys are session-only: used for this one run, never stored, logged, shown or placed "
        "in evidence, and erased from the form when you submit. Each run needs fresh consent. "
        "A key never grants authority."
    )
    with st.form("live_provider_form", clear_on_submit=True):
        st.selectbox("Demonstration scenario", SCENARIOS, key="live_scenario")
        st.checkbox("Run stage 1 live with OpenAI", key="live_use_openai")
        st.selectbox("OpenAI model", OPENAI_LIVE_MODELS, key="live_openai_model")
        st.text_input("OpenAI API key", type="password", key="live_openai_key")
        st.checkbox("Run stage 2 live with Gemini (Google ADK)", key="live_use_gemini")
        st.selectbox("Gemini model", GEMINI_LIVE_MODELS, key="live_gemini_model")
        st.text_input("Gemini API key", type="password", key="live_gemini_key")
        st.checkbox(
            "I understand this run contacts external model providers.", key="live_ack_external"
        )
        st.checkbox("I understand my provider account may be charged.", key="live_ack_charges")
        st.form_submit_button(
            "Run live provider demonstration", type="primary", on_click=_submit_live_run
        )
    if "live_error" in st.session_state:
        st.error(st.session_state["live_error"])
    if "live_result" in st.session_state:
        render_live_result(st.session_state["live_result"])


def _submit_live_run() -> None:
    """Run one live demonstration from the submitted form, then erase keys and consent.

    Executing in the submit callback lets the application overwrite the masked key
    widgets before the page renders, so keys never outlive this single run in
    server-side session state. Consent is also reset: every run needs a new opt-in.
    """
    state = st.session_state
    state.pop("live_result", None)
    state.pop("live_error", None)
    try:
        openai = _selection(
            state["live_use_openai"],
            state["live_openai_key"],
            state["live_openai_model"],
            ProviderName.OPENAI,
        )
        gemini = _selection(
            state["live_use_gemini"],
            state["live_gemini_key"],
            state["live_gemini_model"],
            ProviderName.GOOGLE_GEMINI,
        )
        with st.spinner("Contacting the selected providers within fixed bounds…"):
            state["live_result"] = run_live_provider_demo(
                state["live_scenario"],
                consent=LiveConsent(state["live_ack_external"], state["live_ack_charges"]),
                openai=openai,
                google_adk=gemini,
            )
    except (ConfigurationError, ReviewerError) as exc:
        # Both carry fixed application text; neither can contain a key.
        state["live_error"] = str(exc)
    finally:
        for key in ("live_openai_key", "live_gemini_key"):
            state[key] = ""
        for key in ("live_ack_external", "live_ack_charges"):
            state[key] = False


def render_live_result(result: LiveReviewerResult) -> None:
    """Present actual live-mode results and their evidence classification."""
    workflow = result.workflow
    provider_stages = [stage for stage in workflow.stages if stage.provider is not None]
    live = [stage for stage in provider_stages if stage.evidence.live_provider_executed]
    st.success("Live-mode workflow completed and application validation passed.")
    columns = st.columns(3)
    columns[0].metric("Provider-driven stages", len(provider_stages))
    calls = sum(stage.provider.model_calls for stage in provider_stages)
    columns[1].metric("Model calls made", calls)
    columns[2].metric("Model-call bound", workflow.max_model_calls)
    st.caption(
        f"Captured execution: {result.scenario} · {len(live)} live-provider stage(s) · "
        "live-provider means a genuine external model executed; mocked-provider means an "
        "injected test double ran and is never live evidence."
    )
    st.dataframe(
        [
            {
                "Stage": index,
                "SDK": stage.framework.value,
                "Capability": stage.authorization.capability,
                "Driven by": stage.provider.provider.value if stage.provider else "application",
                "Model": stage.provider.model if stage.provider else "none",
                "External provider executed": bool(
                    stage.provider and stage.provider.external_provider_executed
                ),
                "Model calls": stage.provider.model_calls if stage.provider else 0,
                "Evidence": stage.evidence.evidence_class.value,
            }
            for index, stage in enumerate(workflow.stages, start=1)
        ],
        hide_index=True,
    )
    for stage in provider_stages:
        provider = stage.provider.provider.value
        st.write(f"Untrusted {provider} narrative (display only, no authority):")
        st.text(stage.provider.narrative)
    st.write("Application-validated enterprise results from MCP:")
    st.dataframe([workflow.customer.model_dump()], hide_index=True)
    st.dataframe([workflow.account.model_dump()], hide_index=True)
    decision = workflow.policy_result
    st.info(
        f"Proposed account change for {workflow.principal_role}: {decision.decision.value}. "
        f"{decision.reason} Decided by application policy without a model."
    )
    if provider_stages:
        st.write(f"Proves: {provider_stages[0].provider.proves}")
        st.write(f"Does not prove: {provider_stages[0].provider.does_not_prove}")
    with st.expander("Structured live execution detail (credential-free)"):
        st.json(workflow.model_dump(mode="json"))


def main() -> None:
    """Run the unified reviewer console with bounded presentation state."""
    st.set_page_config(page_title="Module 8 | Infrastructure Console", layout="wide")
    st.title("MCP Enterprise Infrastructure")
    st.write("Module 8 · shared enterprise capabilities across independent SDK ecosystems")
    with st.expander("System overview & reviewer guide", expanded=True):
        st.write(
            "The MCP server owns SQLite, enterprise HTTP API and internal policy capabilities. "
            "The MCP client, OpenAI Agents SDK and Google ADK consume the same protocol plane. "
            "Enterprise capabilities belong to the protocol boundary, not an AI vendor."
        )
        st.write(
            "Choose a fixed demonstration scenario and run the console. Expect real discovery, "
            "an allowed customer read, a denied viewer request and three validated workflow "
            "stages. Manager review permits the proposed change; Support review denies it. "
            "Neither scenario changes an account or authenticates a real user."
        )
        st.write(
            "Deterministic Demo is the default: no key and zero model calls. Live Provider "
            "Demo is optional: with your own keys and explicit consent, real OpenAI and/or "
            "Gemini models use the same application-authorized MCP capabilities."
        )
        st.caption(
            "Capability registration, typed context, orchestration and authority boundaries "
            "are AI operating-system building blocks. Independently addressed loopback "
            "services demonstrate a small distributed ecosystem. MCP is implemented; "
            "A2A is complementary agent-to-agent interoperability and is not implemented."
        )
    mode = st.radio(
        "Reviewer mode",
        MODES,
        horizontal=True,
        help="Deterministic Demo is the default and needs no keys. Live mode is optional.",
    )
    if mode == MODES[0]:
        _deterministic_demo()
    else:
        _live_demo()

    st.caption(
        "Developed from Techademy AI Engineering program requirements. "
        "Independent implementation, engineering enhancements, and deployment."
    )


if __name__ == "__main__":
    main()
