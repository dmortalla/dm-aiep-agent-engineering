"""Local integration and failure evidence for genuine Google ADK MCP tools."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_tool import McpTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from test_mcp_client import enterprise_api_url as enterprise_api_url
from test_mcp_client import mcp_endpoint as adk_endpoint_fixture

from mcp_enterprise_integration import reviewer
from mcp_enterprise_integration.capability_policy import CapabilityPolicy
from mcp_enterprise_integration.errors import AuthorizationError, EnterpriseIntegrationError
from mcp_enterprise_integration.google_adk_mcp import GoogleAdkMcpIntegration
from mcp_enterprise_integration.workflow import EnterpriseWorkflow

adk_endpoint = adk_endpoint_fixture


@pytest.fixture
def anyio_backend() -> str:
    """Use the installed ADK's asyncio runtime without model execution."""
    return "asyncio"


@pytest.mark.anyio
async def test_adk_agent_and_discovery(adk_endpoint: str) -> None:
    """Configure genuine ADK primitives and discover the shared three tools."""
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        assert isinstance(integration.agent, Agent)
        assert isinstance(integration.agent.tools[0], McpToolset)
        assert await integration.discover_tools() == (
            "evaluate_enterprise_policy", "get_account_status", "get_customer",
        )


@pytest.mark.anyio
@pytest.mark.parametrize("name,role,args,key,value", [
    ("get_customer", "viewer", {"customer_id": "CUST-001"}, "result", None),
    ("get_account_status", "viewer", {"customer_id": "CUST-001"}, "service_tier", "gold"),
    ("evaluate_enterprise_policy", "account_manager", {
        "customer_id": "CUST-001", "requester_role": "account_manager",
        "action": "account_change", "account_status": "active",
    }, "decision", "allow"),
])
async def test_adk_enterprise_paths(
    adk_endpoint: str, name: str, role: str, args: dict, key: str, value: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Execute SQLite, loopback HTTP API, and internal policy via ADK/MCP."""
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        result = await integration.invoke_authorized_tool(
            principal_role=role, name=name, arguments=args,
        )
    assert not [record for record in caplog.records
                if record.name == "mcp_enterprise_integration.google_adk_mcp"]
    assert result.authorization.allowed
    if key == "result":
        assert result.structured_content[key]["name"] == "Northstar Logistics"
    else:
        assert result.structured_content[key] == value


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["viewer", "self_declared_admin"])
async def test_discovery_never_authorizes_execution(
    adk_endpoint: str, role: str, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Prove denial precedes McpTool execution, including forged argument roles."""
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        assert "evaluate_enterprise_policy" in await integration.discover_tools()
        execute = AsyncMock(side_effect=AssertionError("Unauthorized execution"))
        monkeypatch.setattr(McpTool, "run_async", execute)
        with pytest.raises(AuthorizationError):
            await integration.invoke_authorized_tool(
                principal_role=role, name="evaluate_enterprise_policy",
                arguments={"requester_role": "account_manager"},
            )
        execute.assert_not_awaited()
    assert not [record for record in caplog.records
                if record.name == "mcp_enterprise_integration.google_adk_mcp"]


@pytest.mark.anyio
async def test_remote_validation_failure(adk_endpoint: str) -> None:
    """Translate a real MCP error result from invalid enterprise input."""
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        with pytest.raises(EnterpriseIntegrationError, match="error or invalid"):
            await integration.invoke_authorized_tool(
                principal_role="account_manager", name="evaluate_enterprise_policy",
                arguments={"customer_id": "CUST-001", "requester_role": "account_manager",
                           "action": "override_everything", "account_status": "active"},
            )


@pytest.mark.anyio
async def test_discovery_failure_cleanup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve SDK failure context and close a failed initialization."""
    failure = ConnectionError("sensitive exception", {"payload": "private MCP output"})
    monkeypatch.setattr(McpToolset, "get_tools", AsyncMock(side_effect=failure))
    close = AsyncMock()
    monkeypatch.setattr(McpToolset, "close", close)
    with pytest.raises(EnterpriseIntegrationError) as caught:
        async with GoogleAdkMcpIntegration("http://127.0.0.1:1/mcp"):
            pytest.fail("Failed connection entered")
    assert caught.value.__cause__ is failure
    close.assert_awaited_once()
    _assert_safe_diagnostic(caplog, "adk_discovery")


@pytest.mark.anyio
@pytest.mark.parametrize("response", [{"error": "SDK error"}, {"isError": False},
                                      {"isError": False, "structuredContent": []},
                                      {"isError": True, "structuredContent": {
                                          "customer": "private customer",
                                          "payload": "private MCP output",
                                      }}])
async def test_invalid_sdk_result(
    adk_endpoint: str, monkeypatch: pytest.MonkeyPatch, response: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject SDK error dictionaries and malformed untrusted result envelopes."""
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        monkeypatch.setattr(McpTool, "run_async", AsyncMock(return_value=response))
        with pytest.raises(EnterpriseIntegrationError, match="invalid structured"):
            await integration.invoke_authorized_tool(
                principal_role="viewer", name="get_customer",
                arguments={"customer_id": "CUST-001"},
            )
    _assert_safe_diagnostic(caplog, "adk_envelope_validation")


def _assert_safe_diagnostic(caplog: pytest.LogCaptureFixture, stage: str) -> None:
    """Check exact fixed metadata and absence of injected or real sensitive data."""
    records = [record for record in caplog.records
               if record.name == "mcp_enterprise_integration.google_adk_mcp"]
    assert [record.getMessage() for record in records] == [
        f"Module 8 Google ADK backend failed: {stage}",
    ]
    assert records[0].args == ()
    assert records[0].exc_info is None and records[0].stack_info is None
    for sensitive in (
        "sensitive exception", "private MCP output", "private customer", "secret token",
        "CUST-001", "Northstar Logistics", "http://", "54321", "/private/path", "Traceback",
    ):
        assert sensitive not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("boundary", ["authorization", "execution"])
async def test_adk_failure_boundary_preserves_exception(
    adk_endpoint: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    boundary: str,
) -> None:
    """Inject expected boundary failures without changing genuine discovery behavior."""
    failure = RuntimeError(
        "sensitive exception /private/path Traceback secret token",
        {"payload": "private MCP output", "customer": "private customer",
         "endpoint": "http://127.0.0.1:54321/mcp"},
    )
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        execute = AsyncMock(side_effect=failure)
        monkeypatch.setattr(McpTool, "run_async", execute)
        if boundary == "authorization":
            def fail_authorize(self: CapabilityPolicy, **kwargs: object) -> None:
                raise failure

            monkeypatch.setattr(CapabilityPolicy, "authorize", fail_authorize)
            expected_type = RuntimeError
        else:
            expected_type = EnterpriseIntegrationError
        with pytest.raises(expected_type) as caught:
            await integration.invoke_authorized_tool(
                principal_role="viewer", name="get_customer",
                arguments={"customer_id": "CUST-001"},
            )
        if boundary == "authorization":
            assert caught.value is failure
            execute.assert_not_awaited()
        else:
            assert caught.value.__cause__ is failure
            execute.assert_awaited_once()
    stage = "adk_authorization" if boundary == "authorization" else "adk_tool_execution"
    _assert_safe_diagnostic(caplog, stage)


@pytest.mark.anyio
@pytest.mark.parametrize("through_reviewer", [False, True])
async def test_adk_diagnostic_preserves_outer_boundaries(
    adk_endpoint: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    through_reviewer: bool,
) -> None:
    """Keep the real workflow's ADK attribution and the reviewer's safe error boundary."""
    failure = ConnectionError("sensitive exception", {"payload": "private MCP output"})
    monkeypatch.setattr(McpToolset, "get_tools", AsyncMock(side_effect=failure))
    workflow = EnterpriseWorkflow(adk_endpoint)
    if through_reviewer:
        async def execute(endpoint: str, database: Path, scenario: str) -> object:
            return await workflow.run(customer_id="CUST-001", principal_role="account_manager")

        monkeypatch.setattr(reviewer, "_execute", execute)
        # Run the synchronous reviewer in a worker while the fixture's MCP loop stays active.
        with pytest.raises(reviewer.ReviewerError) as caught:
            await asyncio.to_thread(reviewer.run_reviewer_demo)
        assert str(caught.value) == (
            "Backend execution failed. Retry or ask the maintainer to inspect it."
        )
        assert isinstance(caught.value.__cause__, EnterpriseIntegrationError)
        assert caught.value.__cause__.__cause__ is failure
    else:
        with pytest.raises(EnterpriseIntegrationError) as caught:
            await workflow.run(customer_id="CUST-001", principal_role="account_manager")
        assert caught.value.__cause__ is failure
    _assert_safe_diagnostic(caplog, "adk_discovery")
    records = [record for record in caplog.records if record.name in {
        "mcp_enterprise_integration.workflow", reviewer.__name__,
    }]
    expected = ["Module 8 workflow backend failed: google_adk_account"]
    if through_reviewer:
        expected.append("Module 8 reviewer backend failed: EnterpriseIntegrationError")
    assert [record.getMessage() for record in records] == expected
    assert all(record.exc_info is None and record.stack_info is None for record in records)
