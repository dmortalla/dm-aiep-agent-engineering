"""Local integration and failure evidence for genuine Google ADK MCP tools."""

from unittest.mock import AsyncMock

import pytest
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_tool import McpTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from test_mcp_client import enterprise_api_url as enterprise_api_url
from test_mcp_client import mcp_endpoint as adk_endpoint_fixture

from mcp_enterprise_integration.errors import AuthorizationError, EnterpriseIntegrationError
from mcp_enterprise_integration.google_adk_mcp import GoogleAdkMcpIntegration

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
) -> None:
    """Execute SQLite, loopback HTTP API, and internal policy via ADK/MCP."""
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        result = await integration.invoke_authorized_tool(
            principal_role=role, name=name, arguments=args,
        )
    assert result.authorization.allowed
    if key == "result":
        assert result.structured_content[key]["name"] == "Northstar Logistics"
    else:
        assert result.structured_content[key] == value


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["viewer", "self_declared_admin"])
async def test_discovery_never_authorizes_execution(
    adk_endpoint: str, role: str, monkeypatch: pytest.MonkeyPatch,
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
async def test_discovery_failure_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve SDK failure context and close a failed initialization."""
    failure = ConnectionError("injected transport failure")
    monkeypatch.setattr(McpToolset, "get_tools", AsyncMock(side_effect=failure))
    close = AsyncMock()
    monkeypatch.setattr(McpToolset, "close", close)
    with pytest.raises(EnterpriseIntegrationError) as caught:
        async with GoogleAdkMcpIntegration("http://127.0.0.1:1/mcp"):
            pytest.fail("Failed connection entered")
    assert caught.value.__cause__ is failure
    close.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("response", [{"error": "SDK error"}, {"isError": False},
                                      {"isError": False, "structuredContent": []}])
async def test_invalid_sdk_result(
    adk_endpoint: str, monkeypatch: pytest.MonkeyPatch, response: dict,
) -> None:
    """Reject SDK error dictionaries and malformed untrusted result envelopes."""
    async with GoogleAdkMcpIntegration(adk_endpoint) as integration:
        monkeypatch.setattr(McpTool, "run_async", AsyncMock(return_value=response))
        with pytest.raises(EnterpriseIntegrationError, match="invalid structured"):
            await integration.invoke_authorized_tool(
                principal_role="viewer", name="get_customer",
                arguments={"customer_id": "CUST-001"},
            )
