"""Story 11 Slice 2: run with streamlit run streamlit_app.py from module-06-5."""

import streamlit as st

from harness_engineering.config import SUPPORTED_LIVE_MODELS
from harness_engineering.errors import HarnessError
from harness_engineering.live_readiness import live_evidence_caption, provider_readiness
from harness_engineering.live_session import (
    LIVE_PROMPTS,
    MAX_LIVE_CALLS_PER_SESSION,
    LiveCheckView,
    LiveSession,
    run_live_check,
    server_credential_path_enabled,
    server_credentials_available,
)
from harness_engineering.reviewer_service import GUIDES, Demo, DemoView, ReviewerBusyError, run_demo

DETERMINISTIC_MODE = "Deterministic (default, no key)"
LIVE_MODE = "Live provider (explicit opt-in)"
PATH_LABELS = {"byok": "Temporary BYOK key (this session only)",
               "server": "Trusted server-side configuration"}

st.set_page_config(page_title="Module 6.5 · Harness reviewer", page_icon=":material/account_tree:")
st.title("Module 6.5 · Harness engineering")
st.write("Explore how an application controls agent planning, context, tool access, recovery, "
         "human oversight and cost. Run the six source labs, then inspect MCP and regression.")
st.info("Local demonstration · No API key or paid inference required in the default "
        "deterministic mode. Application services own all decisions; the UI only requests "
        "fixed demonstrations.")

selected = st.sidebar.selectbox("Choose a demonstration", tuple(Demo),
                                format_func=lambda item: item.value, key="demo_choice")
live_mode = st.sidebar.selectbox(
    "Provider mode", (DETERMINISTIC_MODE, LIVE_MODE), key="provider_mode") == LIVE_MODE
guide = GUIDES[selected]
st.header(selected.value)
st.write(guide.demonstrates)
with st.container(border=True):
    st.markdown("**Action:** Select **Run local demonstration** once, then inspect the result.")
    st.markdown("**Expected result:** " + guide.expect)
    st.markdown("**Safety and authority:** " + guide.safety)
    st.markdown("**Evidence:** " + guide.evidence)
    st.markdown("**Limitations:** " + guide.limitations)

# Finite enum keys, one bounded result per choice, no execution on ordinary reruns.
# Browser/session values are display state and are never runtime authority.
st.session_state.setdefault("demo_results", {})
results = st.session_state["demo_results"]
completed = selected.value in results
if st.button("Run local demonstration", key="run_demo", type="primary", disabled=completed) \
        and not completed:
    with st.spinner("Running the fixed local services…"):
        try:
            view = run_demo(selected)
        except ReviewerBusyError:
            st.warning("Another local demonstration is running. Try again after it finishes.")
        except Exception:
            # Intentional final UI boundary: domain defects still propagate from
            # the service, but no framework traceback/exception text reaches a browser.
            results[selected.value] = None
        else:
            results[selected.value] = view
    completed = selected.value in results

if completed:
    view = results[selected.value]
    if view is None:
        st.error("Demonstration unavailable. Check that the locked module extras are installed "
                 "and local temporary storage is writable, then start a new session to retry. "
                 "No successful evidence is claimed.")
    elif type(view) is DemoView and view.demo is selected:
        st.subheader("Observed result")
        st.caption("Evidence: " + ", ".join(item.value for item in view.evidence))
        if view.metrics:
            columns = st.columns(len(view.metrics))
            for column, metric in zip(columns, view.metrics, strict=True):
                column.metric(metric.label, metric.value)
        if view.truncated:
            st.warning("Display limited to 65,536 characters. Use the CLI for full detail.")
        # Results, including injected fixture content, are literal text, never HTML/Markdown.
        st.code(view.details, language="text", wrap_lines=True)
        st.caption("This session retains one result per demonstration. Selecting another view "
                   "does not rerun work. Temporary lab files were cleaned after the run.")
    else:
        st.error("Stored display data is unavailable. Start a new session. No work was requested.")
else:
    st.caption("Ready when you are. Nothing runs until you press the button.")

st.divider()
st.subheader("Evidence boundaries")
st.write("Deterministic means fixed local fixtures exercising accepted services. Local integration "
         "means SQLite persistence or the in-process MCP SDK. Approval identities and decisions "
         "are simulated fixtures. Application sandboxing is not OS isolation.")
st.write("The demonstrations on this page do not call live services: Mem0, Guardrails, "
         "LangSmith, Langfuse and Helicone are not exercised as live services here, and no "
         "provider is called. No credentials are requested unless you explicitly opt in to "
         "live provider mode. Fixture costs are not verified billing; local latency is not "
         "production performance.")

st.subheader("Provider modes")
st.write("**Deterministic mode (default)** runs fixed local fixtures through the accepted "
         "services: no key, no provider call, no cost, safe for public review. **Live provider "
         "mode** makes one bounded call to OpenAI or Anthropic to show the same governed path "
         "with a real model. Live mode requires explicit opt-in and an approved credential "
         "source. You may provide a temporary BYOK credential for this session or use trusted "
         "server-side configuration when available. Credentials provide connectivity only and "
         "never grant application authority.")
if live_mode:
    st.warning("Live mode: a call may incur charges on the provider account whose key is "
               "used. Providers, models and prompts come from application-owned allowlists. "
               "Every call is capped by application-owned limits (about 768 input tokens, 256 "
               "output tokens, 4,096 reply bytes, USD 0.001, one attempt, no retry, 20 s) "
               f"and at most {MAX_LIVE_CALLS_PER_SESSION} calls per session. Your key is used "
               "only for this live session and is not written to disk, logs, evidence, "
               "prompts, or durable application storage, and it is sent only to the chosen "
               "provider. Streamlit may temporarily retain widget state in server memory "
               "until the session/rerun lifecycle clears it.")
    provider = st.sidebar.selectbox("Provider", tuple(SUPPORTED_LIVE_MODELS), key="live_provider")
    model = st.sidebar.selectbox("Model", SUPPORTED_LIVE_MODELS[provider], key="live_model")
    prompt_id = st.sidebar.selectbox("Prompt", tuple(LIVE_PROMPTS), key="live_prompt",
                                     format_func=lambda item: LIVE_PROMPTS[item])
    paths = ["byok", *(["server"] if server_credentials_available(provider) else [])]
    path = st.sidebar.selectbox("Credential source", paths, key="live_path",
                                format_func=lambda item: PATH_LABELS[item])
    st.session_state.setdefault("live_session", LiveSession())
    with st.form("live_form", clear_on_submit=True):
        typed_key = (st.text_input("Your provider API key (this session only)",
                                   type="password", autocomplete="off")
                     if path == "byok" else None)
        acknowledged = st.checkbox("I understand this call may incur provider charges.")
        submitted = st.form_submit_button("Run one bounded live call")
    if submitted:
        try:
            st.session_state["live_view"] = run_live_check(
                live_mode=True, acknowledged_charges=acknowledged, provider=provider,
                model=model, prompt_id=prompt_id, path=path, byok_key=typed_key,
                session=st.session_state["live_session"],
            )
        except HarnessError as error:
            st.session_state.pop("live_view", None)
            st.warning(f"Live call not made: {error}")
        # Drop our local reference. The browser-side form resets on submit, but Streamlit may
        # keep the widget value in server memory until its session/rerun lifecycle clears it.
        typed_key = None
    view = st.session_state.get("live_view")
    if type(view) is LiveCheckView:
        with st.container(border=True):
            st.markdown(f"**{view.provider} · {view.model}** · `{view.status}` · "
                        f"credential path `{view.path}` · evidence class `{view.evidence_class}`")
            if view.text is not None:
                st.code(view.text, language="text", wrap_lines=True)  # Literal, untrusted.
            else:
                st.error(f"Live call failed: {view.failure_category}"
                         + (f" ({view.rejection_point})" if view.rejection_point else ""))
            st.caption(f"Tokens in/out: {view.input_tokens}/{view.output_tokens} · conservative "
                       f"exposure USD {view.exposure_usd} · This session call is adapter-class "
                       "and is not accepted live-provider evidence.")
# Readiness is derived by the application from classified evidence, not by the UI.
with st.container(border=True):
    for item in provider_readiness(server_path_enabled=server_credential_path_enabled()):
        evidence = item.evidence.value if item.evidence else "configuration"
        st.markdown(f"**{item.capability}** · `{item.status.value}` · {evidence}  \n"
                    f"{item.summary}")
st.caption(live_evidence_caption())  # Derived from the same records as the rows above.
st.caption("Module 6.5 engineering release-readiness is independently accepted and "
           "published to GitHub. The Streamlit deployment is undergoing final live "
           "verification and is not yet verified. No hosted-service, deployment or "
           "production-readiness claim is made.")

st.divider()
st.caption(
    "Developed from Techademy AI Engineering program requirements. "
    "Independent implementation, engineering enhancements, and deployment."
)
