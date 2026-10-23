"""Story 11 Slice 2: run with streamlit run streamlit_app.py from module-06-5."""

import streamlit as st

from harness_engineering.reviewer_service import GUIDES, Demo, DemoView, ReviewerBusyError, run_demo

st.set_page_config(page_title="Module 6.5 · Harness reviewer", page_icon=":material/account_tree:")
st.title("Module 6.5 · Harness engineering")
st.write("Explore how an application controls agent planning, context, tool access, recovery, "
         "human oversight and cost. Run the six source labs, then inspect MCP and regression.")
st.info("Local demonstration · No API key or paid inference required. "
        "Application services own all decisions; the UI only requests fixed demonstrations.")

selected = st.sidebar.selectbox("Choose a demonstration", tuple(Demo),
                                format_func=lambda item: item.value, key="demo_choice")
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
st.write("Optional OpenAI, Anthropic, Mem0, Guardrails, LangSmith, Langfuse and Helicone "
         "capabilities are not exercised as live services. No credentials are requested. "
         "Fixture costs are not verified billing; local latency is not production performance.")
st.caption("Module 6.5 engineering release-readiness is independently accepted and "
           "published to GitHub. The Streamlit deployment is undergoing final live "
           "verification. No live-provider, hosted-service or production-readiness claim.")

st.divider()
st.caption(
    "Developed from Techademy AI Engineering program requirements. "
    "Independent implementation, engineering enhancements, and deployment."
)
