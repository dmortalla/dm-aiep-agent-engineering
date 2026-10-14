"""Google ADK consumption of the shared, application-authorized MCP plane."""

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.sessions import InMemorySessionService, Session
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.tool_context import ToolContext

from mcp_enterprise_integration.capability_policy import CapabilityAuthorization, CapabilityPolicy
from mcp_enterprise_integration.errors import EnterpriseIntegrationError


@dataclass(frozen=True, slots=True)
class GoogleAdkMcpResult:
    """Application authorization evidence and validated MCP result envelope."""

    authorization: CapabilityAuthorization
    structured_content: dict[str, Any]


class GoogleAdkMcpIntegration(AbstractAsyncContextManager["GoogleAdkMcpIntegration"]):
    """Exercise ADK MCP tools without running an agent model.

    The agent is configuration for application orchestration, not an execution
    authority. Callers supply an application-authenticated role to the authorized
    invocation boundary; untrusted tool arguments never supply that role.
    """

    def __init__(self, endpoint: str, *, policy: CapabilityPolicy | None = None) -> None:
        """Configure genuine ADK primitives.

        Args:
            endpoint: HTTP(S) Streamable HTTP MCP endpoint.
            policy: Application-owned capability grants.

        Raises:
            ValueError: If the endpoint is not HTTP(S).
        """
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("MCP endpoint must use HTTP or HTTPS.")
        self._policy = policy or CapabilityPolicy()
        self._toolset = McpToolset(connection_params=StreamableHTTPConnectionParams(
            url=endpoint, timeout=5.0, sse_read_timeout=5.0,
        ))
        self._agent = Agent(
            name="module_08_enterprise_agent",
            instruction="Use only enterprise capabilities authorized by the application.",
            tools=[self._toolset],
        )

    @property
    def agent(self) -> Agent:
        """Return the configured ADK agent; this boundary never runs its model."""
        return self._agent

    async def __aenter__(self) -> "GoogleAdkMcpIntegration":
        """Connect through ADK discovery, cleaning up if initialization fails."""
        try:
            await self.discover_tools()
        except BaseException:
            await self._toolset.close()
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        """Release the SDK-owned MCP session."""
        await self._toolset.close()

    async def _get_tools(self) -> list[Any]:
        try:
            # ADK retries discovery once; the total deadline includes that retry.
            async with asyncio.timeout(10.0):
                return await self._toolset.get_tools()
        except Exception as exc:
            raise EnterpriseIntegrationError("Google ADK MCP capability discovery failed.") from exc

    async def discover_tools(self) -> tuple[str, ...]:
        """Return discovered names as availability evidence, never grants.

        Raises:
            EnterpriseIntegrationError: If ADK discovery fails.
        """
        return tuple(sorted(tool.name for tool in await self._get_tools()))

    async def invoke_authorized_tool(
        self, *, principal_role: str, name: str, arguments: dict[str, Any],
    ) -> GoogleAdkMcpResult:
        """Authorize before executing a genuine ADK McpTool.

        Args:
            principal_role: Application-authenticated role, never model input.
            name: Requested capability.
            arguments: Untrusted arguments validated by the enterprise server.

        Returns:
            Authorization and structured result with a validated MCP envelope.

        Raises:
            AuthorizationError: If application policy denies execution.
            EnterpriseIntegrationError: If discovery, execution, or envelope validation fails.
        """
        tools = await self._get_tools()
        authorization = self._policy.authorize(
            principal_role=principal_role, capability=name,
            discovered_capabilities=tuple(tool.name for tool in tools),
        )
        tool = next(tool for tool in tools if tool.name == authorization.capability)
        context = ToolContext(InvocationContext(
            invocation_id="module-08-deterministic-tool-call", agent=self._agent,
            session_service=InMemorySessionService(),
            session=Session(id="tool-call", app_name="module-08", user_id="application"),
        ))
        try:
            async with asyncio.timeout(10.0):
                result = await tool.run_async(args=arguments, tool_context=context)
        except Exception as exc:
            raise EnterpriseIntegrationError(
                f"Google ADK MCP invocation failed for {name!r}."
            ) from exc
        if (
            not isinstance(result, dict)
            or result.get("isError") is not False
            or not isinstance(result.get("structuredContent"), dict)
        ):
            raise EnterpriseIntegrationError(
                f"Google ADK MCP tool {name!r} returned an error or invalid structured content."
            )
        return GoogleAdkMcpResult(authorization, dict(result["structuredContent"]))
