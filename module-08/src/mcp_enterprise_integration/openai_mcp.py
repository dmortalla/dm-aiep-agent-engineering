"""OpenAI Agents SDK integration with the shared enterprise MCP plane."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from agents import Agent
from agents.mcp import MCPServerStreamableHttp

from mcp_enterprise_integration.capability_policy import (
    CapabilityAuthorization,
    CapabilityPolicy,
)
from mcp_enterprise_integration.errors import EnterpriseIntegrationError


@dataclass(frozen=True, slots=True)
class OpenAiMcpResult:
    """Result of an application-authorized OpenAI SDK MCP invocation."""

    authorization: CapabilityAuthorization
    structured_content: dict[str, Any]


class OpenAiMcpIntegration(AbstractAsyncContextManager["OpenAiMcpIntegration"]):
    """Expose enterprise MCP capabilities through the OpenAI Agents SDK.

    This integration exercises the OpenAI Agents SDK MCP implementation
    directly while keeping application authorization separate from MCP
    discovery. It does not execute an OpenAI model.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        policy: CapabilityPolicy | None = None,
    ) -> None:
        """Initialize the OpenAI MCP integration.

        Args:
            endpoint: Streamable HTTP MCP endpoint.
            policy: Application-owned authorization policy.

        Raises:
            ValueError: If the endpoint is not HTTP or HTTPS.
        """
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("MCP endpoint must use HTTP or HTTPS.")

        self._policy = policy or CapabilityPolicy()
        self._server = MCPServerStreamableHttp(
            name="module-08-enterprise-mcp",
            params={
                "url": endpoint,
                "timeout": 5.0,
            },
            cache_tools_list=True,
            client_session_timeout_seconds=5.0,
            max_retry_attempts=0,
            use_structured_content=True,
        )
        self._agent = Agent(
            name="module-08-enterprise-agent",
            instructions=(
                "Use only enterprise capabilities authorized by the application."
            ),
            mcp_servers=[self._server],
        )

    @property
    def agent(self) -> Agent[Any]:
        """Return the configured OpenAI Agents SDK agent.

        Returns:
            Agent configured with the shared MCP server.
        """
        return self._agent

    async def __aenter__(self) -> "OpenAiMcpIntegration":
        """Connect the OpenAI SDK MCP server.

        Returns:
            Connected integration.

        Raises:
            EnterpriseIntegrationError: If MCP connection fails.
        """
        try:
            await self._server.connect()
        except Exception as exc:
            raise EnterpriseIntegrationError(
                "OpenAI SDK could not connect to the enterprise MCP server."
            ) from exc
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        """Clean up the OpenAI SDK MCP connection."""
        await self._server.cleanup()

    async def discover_tools(self) -> tuple[str, ...]:
        """Discover enterprise tools through the OpenAI Agents SDK.

        Returns:
            Sorted MCP tool names exposed through the SDK.

        Raises:
            EnterpriseIntegrationError: If discovery fails.
        """
        try:
            tools = await self._server.list_tools()
        except Exception as exc:
            raise EnterpriseIntegrationError(
                "OpenAI SDK MCP capability discovery failed."
            ) from exc

        return tuple(sorted(tool.name for tool in tools))

    async def invoke_authorized_tool(
        self,
        *,
        principal_role: str,
        name: str,
        arguments: dict[str, Any],
    ) -> OpenAiMcpResult:
        """Authorize and invoke one tool through the OpenAI Agents SDK.

        Args:
            principal_role: Application-authenticated caller role.
            name: Requested MCP capability.
            arguments: Arguments passed to the MCP tool.

        Returns:
            Authorization evidence and structured tool result.

        Raises:
            AuthorizationError: If application policy denies execution.
            EnterpriseIntegrationError: If discovery or MCP invocation fails.
        """
        discovered = await self.discover_tools()
        authorization = self._policy.authorize(
            principal_role=principal_role,
            capability=name,
            discovered_capabilities=discovered,
        )

        try:
            result = await self._server.call_tool(name, arguments)
        except Exception as exc:
            raise EnterpriseIntegrationError(
                f"OpenAI SDK MCP invocation failed for {name!r}."
            ) from exc

        if result.is_error:
            raise EnterpriseIntegrationError(
                f"OpenAI SDK MCP tool {name!r} returned an error."
            )

        if result.structured_content is None:
            raise EnterpriseIntegrationError(
                f"OpenAI SDK MCP tool {name!r} returned no structured content."
            )

        return OpenAiMcpResult(
            authorization=authorization,
            structured_content=dict(result.structured_content),
        )
