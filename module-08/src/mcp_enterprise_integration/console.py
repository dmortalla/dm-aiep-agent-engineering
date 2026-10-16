"""Streamlit presentation only: reviewer inputs and actual backend results."""

from dataclasses import asdict

import streamlit as st

from mcp_enterprise_integration.reviewer import ReviewerError, ReviewerResult, run_reviewer_demo


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
        st.caption(
            "Capability registration, typed context, orchestration and authority boundaries "
            "are AI operating-system building blocks. Independently addressed loopback "
            "services demonstrate a small distributed ecosystem. MCP is implemented; "
            "A2A is complementary agent-to-agent interoperability and is not implemented."
        )
    scenario = st.selectbox("Demonstration scenario", ["Manager review", "Support review"])
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

    st.caption(
        "Developed from Techademy AI Engineering program requirements. "
        "Independent implementation, engineering enhancements, and deployment."
    )


if __name__ == "__main__":
    main()
