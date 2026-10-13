"""Application-owned client boundary for MCP Streamable HTTP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_enterprise_integration.capability_policy import (
    CapabilityAuthorization,
    CapabilityPolicy,
)
from mcp_enterprise_integration.errors import EnterpriseIntegrationError


@dataclass(frozen=True, slots=True)
class McpConnectionInfo:
    """Validated metadata returned during MCP initialization."""

    server_name: str
    server_version: str
    protocol_version: str


class EnterpriseMcpSession:
    """Initialized MCP session used by application orchestration."""

    def __init__(
        self,
        session: ClientSession,
        connection_info: McpConnectionInfo,
    ) -> None:
        """Initialize an application-owned MCP session wrapper.

        Args:
            session: Initialized official MCP client session.
            connection_info: Metadata negotiated during initialization.
        """
        self._session = session
        self.connection_info = connection_info

    async def discover_tools(self) -> tuple[str, ...]:
        """Discover tool names exposed by the connected MCP server.

        Returns:
            Sorted immutable tuple of discovered MCP tool names.

        Raises:
            EnterpriseIntegrationError: If MCP discovery fails.
        """
        try:
            result = await self._session.list_tools()
        except Exception as exc:
            raise EnterpriseIntegrationError(
                "MCP capability discovery failed."
            ) from exc

        return tuple(sorted(tool.name for tool in result.tools))

    async def invoke_authorized_tool(
        self,
        *,
        principal_role: str,
        name: str,
        arguments: dict[str, Any],
        policy: CapabilityPolicy,
    ) -> tuple[CapabilityAuthorization, dict[str, Any]]:
        """Authorize and invoke one discovered MCP capability.

        Discovery proves only that a capability exists. Application-owned
        policy must independently authorize execution before the MCP call.

        Args:
            principal_role: Application-authenticated caller role.
            name: Requested MCP capability name.
            arguments: Untrusted arguments validated by the MCP server.
            policy: Application-owned capability authorization policy.

        Returns:
            Authorization evidence and structured MCP result.

        Raises:
            AuthorizationError: If application policy denies execution.
            EnterpriseIntegrationError: If discovery or invocation fails.
        """
        discovered = await self.discover_tools()
        authorization = policy.authorize(
            principal_role=principal_role,
            capability=name,
            discovered_capabilities=discovered,
        )
        result = await self.invoke_tool(name, arguments)
        return authorization, result

    async def invoke_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke an MCP tool and return validated structured content.

        Args:
            name: Discovered MCP tool name.
            arguments: Untrusted tool arguments sent for server-side validation.

        Returns:
            Structured MCP result content.

        Raises:
            EnterpriseIntegrationError: If invocation fails, the server reports
                an error, or no structured result is returned.
        """
        if not name.strip():
            raise EnterpriseIntegrationError("MCP tool name must not be empty.")

        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:
            raise EnterpriseIntegrationError(
                f"MCP tool invocation failed for {name!r}."
            ) from exc

        if result.is_error:
            raise EnterpriseIntegrationError(
                f"MCP tool {name!r} returned an error result."
            )

        if result.structured_content is None:
            raise EnterpriseIntegrationError(
                f"MCP tool {name!r} returned no structured content."
            )

        return dict(result.structured_content)


class EnterpriseMcpClient:
    """Connect application orchestration to an MCP Streamable HTTP server."""

    def __init__(self, endpoint: str) -> None:
        """Initialize the MCP client boundary.

        Args:
            endpoint: MCP Streamable HTTP endpoint.

        Raises:
            ValueError: If endpoint is not an HTTP(S) URL.
        """
        normalized = endpoint.strip()
        if not normalized.startswith(('http://', 'https://')):
            raise ValueError("MCP endpoint must use HTTP or HTTPS.")
        self._endpoint = normalized

    @property
    def endpoint(self) -> str:
        """Return the configured MCP endpoint."""
        return self._endpoint

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[EnterpriseMcpSession]:
        """Open, initialize, and safely close an MCP protocol session.

        Yields:
            Initialized application-owned MCP session wrapper.

        Raises:
            EnterpriseIntegrationError: If transport or initialization fails.
        """
        try:
            async with streamable_http_client(self._endpoint) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await session.initialize()
                    info = McpConnectionInfo(
                        server_name=initialized.server_info.name,
                        server_version=initialized.server_info.version,
                        protocol_version=initialized.protocol_version,
                    )
                    yield EnterpriseMcpSession(session, info)
        except EnterpriseIntegrationError:
            raise
        except Exception as exc:
            raise EnterpriseIntegrationError(
                f"MCP connection failed for {self._endpoint!r}."
            ) from exc
