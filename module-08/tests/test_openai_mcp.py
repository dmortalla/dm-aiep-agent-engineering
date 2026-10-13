"""Integration tests for the OpenAI Agents SDK MCP boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
import uvicorn
from agents import Agent

from mcp_enterprise_integration.errors import AuthorizationError
from mcp_enterprise_integration.mcp_server import create_enterprise_mcp_server
from mcp_enterprise_integration.openai_mcp import OpenAiMcpIntegration


class _ApiHandler(BaseHTTPRequestHandler):
    """Deterministic local enterprise API fixture."""

    def do_GET(self) -> None:
        """Return a deterministic account-status response."""
        body = (
            b'{"customer_id":"CUST-001","service_tier":"gold","risk_status":"low","open_cases":2}'
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress fixture HTTP logging."""


@contextmanager
def _enterprise_api() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def _mcp_endpoint(tmp_path: Path) -> Iterator[str]:
    with _enterprise_api() as api_url:
        server = create_enterprise_mcp_server(
            database_path=tmp_path / "openai-sdk.db",
            enterprise_api_url=api_url,
        )
        app = server.streamable_http_app(
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
            host="127.0.0.1",
        )
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="error",
        )
        uvicorn_server = uvicorn.Server(config)
        thread = Thread(target=uvicorn_server.run, daemon=True)
        thread.start()

        for _ in range(100):
            if uvicorn_server.started:
                break
            thread.join(timeout=0.05)

        if not uvicorn_server.started:
            uvicorn_server.should_exit = True
            thread.join(timeout=5)
            raise RuntimeError("MCP fixture server did not start.")

        sockets = tuple(uvicorn_server.servers[0].sockets)
        port = sockets[0].getsockname()[1]

        try:
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            uvicorn_server.should_exit = True
            thread.join(timeout=5)


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio for OpenAI SDK MCP integration tests."""
    return "asyncio"


@pytest.mark.anyio
async def test_openai_agent_is_configured_with_shared_mcp_server(
    tmp_path: Path,
) -> None:
    """Configure a genuine OpenAI Agent with the enterprise MCP server."""
    with _mcp_endpoint(tmp_path) as endpoint:
        integration = OpenAiMcpIntegration(endpoint)

        assert isinstance(integration.agent, Agent)
        assert integration.agent.name == "module-08-enterprise-agent"
        assert len(integration.agent.mcp_servers) == 1


@pytest.mark.anyio
async def test_openai_sdk_discovers_enterprise_mcp_tools(
    tmp_path: Path,
) -> None:
    """Discover the shared enterprise capabilities through OpenAI SDK."""
    with _mcp_endpoint(tmp_path) as endpoint:
        async with OpenAiMcpIntegration(endpoint) as integration:
            tools = await integration.discover_tools()

    assert tools == (
        "evaluate_enterprise_policy",
        "get_account_status",
        "get_customer",
    )


@pytest.mark.anyio
async def test_openai_sdk_invokes_authorized_enterprise_tool(
    tmp_path: Path,
) -> None:
    """Invoke a real MCP enterprise capability through OpenAI SDK."""
    with _mcp_endpoint(tmp_path) as endpoint:
        async with OpenAiMcpIntegration(endpoint) as integration:
            result = await integration.invoke_authorized_tool(
                principal_role="viewer",
                name="get_customer",
                arguments={"customer_id": "CUST-001"},
            )

    assert result.authorization.allowed is True
    assert result.structured_content["result"]["customer_id"] == "CUST-001"


@pytest.mark.anyio
async def test_openai_sdk_discovery_cannot_grant_authority(
    tmp_path: Path,
) -> None:
    """Deny a discovered tool not granted by application policy."""
    with _mcp_endpoint(tmp_path) as endpoint:
        async with OpenAiMcpIntegration(endpoint) as integration:
            tools = await integration.discover_tools()
            assert "evaluate_enterprise_policy" in tools

            with pytest.raises(AuthorizationError, match="not authorized"):
                await integration.invoke_authorized_tool(
                    principal_role="viewer",
                    name="evaluate_enterprise_policy",
                    arguments={
                        "customer_id": "CUST-001",
                        "requester_role": "account_manager",
                        "action": "account_change",
                        "account_status": "active",
                    },
                )


@pytest.mark.anyio
async def test_openai_sdk_calls_enterprise_api_through_mcp(
    tmp_path: Path,
) -> None:
    """Reach the deterministic enterprise API through OpenAI SDK and MCP."""
    with _mcp_endpoint(tmp_path) as endpoint:
        async with OpenAiMcpIntegration(endpoint) as integration:
            result = await integration.invoke_authorized_tool(
                principal_role="viewer",
                name="get_account_status",
                arguments={"customer_id": "CUST-001"},
            )

    assert result.structured_content["customer_id"] == "CUST-001"
    assert result.structured_content["service_tier"] == "gold"
    assert result.structured_content["risk_status"] == "low"
    assert result.structured_content["open_cases"] == 2
