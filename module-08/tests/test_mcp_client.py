"""Integration tests for the MCP Streamable HTTP client boundary."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from mcp_enterprise_integration.capability_policy import CapabilityPolicy
from mcp_enterprise_integration.errors import (
    AuthorizationError,
    EnterpriseIntegrationError,
)
from mcp_enterprise_integration.mcp_client import EnterpriseMcpClient
from mcp_enterprise_integration.mcp_server import create_enterprise_mcp_server


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio for MCP transport integration tests."""
    return "asyncio"


class EnterpriseApiHandler(BaseHTTPRequestHandler):
    """Serve deterministic enterprise account data."""

    def do_GET(self) -> None:
        """Return one deterministic account-status response."""
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
        """Suppress fixture HTTP logging."""
        return


def _free_port() -> int:
    """Reserve an available loopback port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    """Wait until a loopback TCP endpoint accepts connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("Loopback MCP server did not become ready.")


@pytest.fixture
def enterprise_api_url() -> Iterator[str]:
    """Run the deterministic local enterprise API."""
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


@pytest.fixture
def mcp_endpoint(
    tmp_path: Path,
    enterprise_api_url: str,
) -> Iterator[str]:
    """Run the real MCP server over loopback Streamable HTTP."""
    server = create_enterprise_mcp_server(
        database_path=tmp_path / "customers.db",
        enterprise_api_url=enterprise_api_url,
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="127.0.0.1",
    )

    port = _free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    runtime = uvicorn.Server(config)
    thread = threading.Thread(target=runtime.run, daemon=True)
    thread.start()
    _wait_for_port(port)

    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        runtime.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Loopback MCP server did not stop cleanly.")


def test_client_requires_http_transport() -> None:
    """Reject endpoints outside the Streamable HTTP boundary."""
    with pytest.raises(ValueError, match='HTTP or HTTPS'):
        EnterpriseMcpClient("stdio://local")


@pytest.mark.anyio
async def test_client_initializes_real_mcp_session(mcp_endpoint: str) -> None:
    """Exchange initialization context over real Streamable HTTP."""
    client = EnterpriseMcpClient(mcp_endpoint)

    async with client.connect() as session:
        info = session.connection_info

    assert info.server_name == "module-08-enterprise-integration"
    assert info.server_version == "0.8.0"
    assert info.protocol_version


@pytest.mark.anyio
async def test_client_discovers_capabilities_over_http(mcp_endpoint: str) -> None:
    """Discover enterprise capabilities through the MCP protocol."""
    client = EnterpriseMcpClient(mcp_endpoint)

    async with client.connect() as session:
        tools = await session.discover_tools()

    assert tools == (
        "evaluate_enterprise_policy",
        "get_account_status",
        "get_customer",
    )


@pytest.mark.anyio
async def test_client_invokes_database_over_http(mcp_endpoint: str) -> None:
    """Invoke SQLite-backed enterprise data through MCP Streamable HTTP."""
    client = EnterpriseMcpClient(mcp_endpoint)

    async with client.connect() as session:
        result = await session.invoke_tool(
            "get_customer",
            {"customer_id": "CUST-001"},
        )

    customer = result["result"]
    assert customer["customer_id"] == "CUST-001"
    assert customer["name"] == "Northstar Logistics"


@pytest.mark.anyio
async def test_client_invokes_api_over_http(mcp_endpoint: str) -> None:
    """Invoke the enterprise HTTP capability through the MCP transport."""
    client = EnterpriseMcpClient(mcp_endpoint)

    async with client.connect() as session:
        result = await session.invoke_tool(
            "get_account_status",
            {"customer_id": "CUST-001"},
        )

    assert result["service_tier"] == "gold"
    assert result["open_cases"] == 2


@pytest.mark.anyio
async def test_client_invokes_policy_over_http(mcp_endpoint: str) -> None:
    """Invoke application-owned policy through the MCP transport."""
    client = EnterpriseMcpClient(mcp_endpoint)

    async with client.connect() as session:
        result = await session.invoke_tool(
            "evaluate_enterprise_policy",
            {
                "customer_id": "CUST-001",
                "requester_role": "support_agent",
                "action": "account_change",
                "account_status": "active",
            },
        )

    assert result["decision"] == "deny"
    assert result["rule_id"] == "POL-CHANGE-ROLE"


@pytest.mark.anyio
async def test_client_translates_invalid_remote_input(mcp_endpoint: str) -> None:
    """Translate remote MCP validation failure at the client boundary."""
    client = EnterpriseMcpClient(mcp_endpoint)

    async with client.connect() as session:
        with pytest.raises(
            EnterpriseIntegrationError,
            match="returned an error result",
        ):
            await session.invoke_tool(
                "evaluate_enterprise_policy",
                {
                    "customer_id": "CUST-001",
                    "requester_role": "account_manager",
                    "action": "override_everything",
                    "account_status": "active",
                },
            )

@pytest.mark.anyio
async def test_authorized_path_allows_granted_remote_execution(
    mcp_endpoint: str,
) -> None:
    """Authorize a discovered capability before real MCP execution."""
    client = EnterpriseMcpClient(mcp_endpoint)
    policy = CapabilityPolicy()

    async with client.connect() as session:
        authorization, result = await session.invoke_authorized_tool(
            principal_role="viewer",
            name="get_customer",
            arguments={"customer_id": "CUST-001"},
            policy=policy,
        )

    assert authorization.allowed is True
    assert authorization.rule_id == "CAP-ALLOWLIST-001"
    assert result["result"]["customer_id"] == "CUST-001"


@pytest.mark.anyio
async def test_discovered_but_unauthorized_tool_never_executes(
    mcp_endpoint: str,
) -> None:
    """Deny a discovered capability before remote MCP invocation."""
    client = EnterpriseMcpClient(mcp_endpoint)
    policy = CapabilityPolicy()

    async with client.connect() as session:
        with pytest.raises(AuthorizationError, match="not authorized"):
            await session.invoke_authorized_tool(
                principal_role="viewer",
                name="evaluate_enterprise_policy",
                arguments={
                    "customer_id": "CUST-001",
                    "requester_role": "account_manager",
                    "action": "account_change",
                    "account_status": "active",
                },
                policy=policy,
            )


@pytest.mark.anyio
async def test_self_declared_admin_cannot_gain_remote_authority(
    mcp_endpoint: str,
) -> None:
    """Fail closed when an untrusted caller invents an authority role."""
    client = EnterpriseMcpClient(mcp_endpoint)
    policy = CapabilityPolicy()

    async with client.connect() as session:
        with pytest.raises(
            AuthorizationError,
            match="no application capability grants",
        ):
            await session.invoke_authorized_tool(
                principal_role="self_declared_admin",
                name="get_customer",
                arguments={"customer_id": "CUST-001"},
                policy=policy,
            )
