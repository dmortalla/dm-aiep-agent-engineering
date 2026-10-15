"""Native Streamlit presentation; application authority lives in module10_ai."""

import asyncio

import streamlit as st

from module10_ai.reviewer import exercise

st.set_page_config(page_title="Module 10 · System console", page_icon=":material/monitoring:",
                   layout="wide")
st.title("Production-system console")
st.caption("MODULE 10  /  LOCAL DETERMINISTIC REVIEW  /  NO KEYS OR CLOUD COST")
st.info("Exercise bounded AI execution, caching and telemetry. Cloud deployment and live AI "
        "providers remain deferred.")

with st.expander("System path & review guide", expanded=True):
    st.write("Reviewer → application service → bounded async queue → TTL cache → "
             "deterministic runtime → provider-neutral telemetry")
    st.caption("The same application interfaces sit beneath the accepted FastAPI Docker unit. "
               "This console calls them locally; it does not query a running HTTP container.")
    st.write("Run the example: expect 4 words, beta/alpha/gamma, a cold cache miss and a warm "
             "cache hit. Inspect job outcomes and correlated events below.")

demo, operations, evidence = st.tabs(["Run an exercise", "Operations", "Evidence & limits"])
with demo:
    with st.form("inference"):
        text = st.text_area("Text to analyze", "Beta alpha beta gamma", max_chars=4096,
                            help="Local lexical analysis. Do not enter sensitive data.")
        limit = st.slider("Keyword limit", 1, 10, 3)
        submitted = st.form_submit_button("Run cold + warm jobs", type="primary")
    st.caption("Each click creates one isolated queue/cache, runs exactly two sequential jobs, "
               "and closes all workers. Widget reruns only redisplay the last report.")
    st.session_state.setdefault("report", None)
    if submitted:
        with st.spinner("Running bounded local exercise…"):
            st.session_state.report = asyncio.run(exercise(text, limit))
    report = st.session_state.report
    if report:
        if "error" in report:
            st.error(report["error"])
        else:
            st.success("Two jobs completed · local deterministic evidence")
            for index, run in enumerate(report["runs"], 1):
                with st.container(border=True):
                    st.subheader(f"Execution {index}")
                    st.text(f"{run['admission']} → {run['outcome']}")
                    with st.container(horizontal=True):
                        st.metric("Words", run["result"]["word_count"])
                        st.metric("Cache hits", run["cache"]["hits"])
                        st.metric("Cache misses", run["cache"]["misses"])
                    st.caption("Keywords · user-derived data, no operational authority")
                    st.text(", ".join(run["result"]["keywords"]))
            st.caption("The warm result retains deterministic classification. Cache reuse is "
                       "measured by backend counters; no speedup or SLA is implied.")

with operations:
    st.subheader("Local application observations")
    st.caption("Snapshots from the last exercise, not continuous monitoring or container state.")
    if report:
        ready = report.get("readiness_during_exercise", False)
        st.text(f"Worker readiness during exercise: {ready}"
                f" · Accepting after cleanup: {report['accepting_after_cleanup']}")
        st.write("Liveness means a process/service is alive. Readiness means its workers are "
                 "prepared for accepted work. The exercise is intentionally closed afterward.")
        with st.expander("Queue, cache and deadline configuration"):
            st.dataframe([report.get("configuration", {})], hide_index=True,
                         alt="Actual bounded execution configuration")
        st.caption("Pending capacity is bounded separately from workers. Saturated admission "
                   "rejects work; this two-job exercise does not deliberately saturate the queue.")
        st.metric("Telemetry failures", report["metrics"]["telemetry_failures"])
        st.dataframe(report["events"], hide_index=True,
                     column_order=["event", "status", "duration_seconds", "correlation_id"],
                     alt="Actual bounded application events, latency and correlation")
        with st.expander("Aggregate metrics & cleanup snapshot"):
            st.json(report["metrics"])
            st.json(report["queue_after_cleanup"])
        with st.expander("Structured event details"):
            st.json(report["events"])
    else:
        st.info("Run an exercise to collect actual queue, cache, readiness and telemetry evidence.")
    st.warning("Azure Monitor is not connected. These are local provider-neutral events.")

with evidence:
    st.subheader("Verified locally")
    st.write("FastAPI service · deterministic AI runtime · bounded queue/concurrency · TTL cache · "
             "Docker deployment unit · provider-neutral telemetry · Streamlit reviewer console")
    with st.container(border=True):
        st.write("Recorded accepted container evidence — LOCAL CONTAINER")
        st.caption("Story 10.6 acceptance: dabccead1b19e693f60f7fd7feef72dce9a0acb7")
        st.write("Effective UID 10001; deterministic no-secret inference; health/readiness; "
                 "correlated minimized telemetry; graceful shutdown exit 0; container cleanup.")
        st.caption("Historical acceptance supplied by the reviewer. No live container status "
                   "is queried or claimed. Docker is not required for this console.")
    st.subheader("Deferred / not yet verified")
    st.warning("Azure Container Apps is the planned orchestration target; it is not deployed. "
               "Azure Monitor is the planned telemetry target; it is not connected.")
    st.write("CI/CD · production load balancing · distributed queue/cache · production traffic · "
             "SLA attainment · live provider integration · final production deployment acceptance")
    st.caption("No API-key workflow exists. E-006 dual-mode completion and C-026/C-027 final "
               "deliverables remain deferred. Local results do not prove production readiness.")
