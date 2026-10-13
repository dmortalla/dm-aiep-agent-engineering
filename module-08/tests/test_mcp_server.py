"""Integration tests for the MCP enterprise server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_enterprise_integration.mcp_server import create_enterprise_mcp_server


@pytest.fixture
def anyio_backend() -> str:
    """Use the installed asyncio backend for MCP async integration tests."""
    return "asyncio"

class EnterpriseApiHandler(BaseHTTPRequestHandler):
    """Serve the deterministic enterprise HTTP dependency."""

    def do_GET(self) -> None:
        """Return deterministic account-status data."""
        payload = json.dumps(
            {
                "customer_id": "CUST-001",
                "service_tier": "gold",
                "risk_status": "low",
                "open_cases": 2,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress deterministic fixture logging."""
        return


@pytest.fixture
def enterprise_api_url() -> str:
    """Run the deterministic enterprise HTTP dependency."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), EnterpriseApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.anyio
async def test_mcp_discovers_three_enterprise_tools(
    tmp_path: Path,
    enterprise_api_url: str,
) -> None:
    """Discover all enterprise capabilities through MCP."""
    server = create_enterprise_mcp_server(
        database_path=tmp_path / "customers.db",
        enterprise_api_url=enterprise_api_url,
    )

    tools = await server.list_tools()

    assert {tool.name for tool in tools} == {
        "get_customer",
        "get_account_status",
        "evaluate_enterprise_policy",
    }


@pytest.mark.anyio
async def test_mcp_discovery_exposes_typed_contracts(
    tmp_path: Path,
    enterprise_api_url: str,
) -> None:
    """Expose descriptions plus MCP input and output schemas."""
    server = create_enterprise_mcp_server(
        database_path=tmp_path / "customers.db",
        enterprise_api_url=enterprise_api_url,
    )

    tools = {tool.name: tool for tool in await server.list_tools()}

    for tool in tools.values():
        assert tool.description
        assert tool.input_schema["type"] == "object"
        assert tool.output_schema is not None

    assert "customer_id" in tools["get_customer"].input_schema["properties"]
    policy = tools["evaluate_enterprise_policy"].input_schema["properties"]
    assert "requester_role" in policy
    assert "action" in policy
    assert "account_status" in policy


@pytest.mark.anyio
async def test_mcp_invokes_database_capability(
    tmp_path: Path,
    enterprise_api_url: str,
) -> None:
    """Invoke the real SQLite capability through MCP."""
    server = create_enterprise_mcp_server(
        database_path=tmp_path / "customers.db",
        enterprise_api_url=enterprise_api_url,
    )

    result = await server.call_tool(
        "get_customer",
        {"customer_id": "CUST-001"},
    )

    assert result.is_error is False
    assert result.structured_content is not None
    customer = result.structured_content
    if "result" in customer:
        customer = customer["result"]
    assert customer["customer_id"] == "CUST-001"
    assert customer["name"] == "Northstar Logistics"


@pytest.mark.anyio
async def test_mcp_invokes_http_api_capability(
    tmp_path: Path,
    enterprise_api_url: str,
) -> None:
    """Invoke the real local HTTP capability through MCP."""
    server = create_enterprise_mcp_server(
        database_path=tmp_path / "customers.db",
        enterprise_api_url=enterprise_api_url,
    )

    result = await server.call_tool(
        "get_account_status",
        {"customer_id": "CUST-001"},
    )

    assert result.is_error is False
    assert result.structured_content["service_tier"] == "gold"
    assert result.structured_content["open_cases"] == 2


@pytest.mark.anyio
async def test_mcp_invokes_application_policy(
    tmp_path: Path,
    enterprise_api_url: str,
) -> None:
    """Invoke application-owned policy through MCP without transferring authority."""
    server = create_enterprise_mcp_server(
        database_path=tmp_path / "customers.db",
        enterprise_api_url=enterprise_api_url,
    )

    result = await server.call_tool(
        "evaluate_enterprise_policy",
        {
            "customer_id": "CUST-001",
            "requester_role": "support_agent",
            "action": "account_change",
            "account_status": "active",
        },
    )

    assert result.is_error is False
    assert result.structured_content["decision"] == "deny"
    assert result.structured_content["rule_id"] == "POL-CHANGE-ROLE"


@pytest.mark.anyio
async def test_mcp_rejects_invalid_policy_action(
    tmp_path: Path,
    enterprise_api_url: str,
) -> None:
    """Reject invalid untrusted input at the MCP tool contract."""
    server = create_enterprise_mcp_server(
        database_path=tmp_path / "customers.db",
        enterprise_api_url=enterprise_api_url,
    )

    with pytest.raises(ToolError, match="Input should be"):
        await server.call_tool(
            "evaluate_enterprise_policy",
            {
                "customer_id": "CUST-001",
                "requester_role": "account_manager",
                "action": "override_everything",
                "account_status": "active",
            },
        )
