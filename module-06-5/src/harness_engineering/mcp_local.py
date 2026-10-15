"""Genuine SDK in-memory integration over accepted MCP authority boundaries.

Trusted bootstrap supplies the local SDK server. No socket, subprocess, provider,
credential, dynamic handler loader, reconnect, retry, or remote authority exists.
"""

import json
import math
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from typing import Any

import anyio
from anyio.from_thread import BlockingPortal, start_blocking_portal
from mcp import ClientSession, types
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from pydantic import BaseModel, ValidationError

from harness_engineering.capabilities import CapabilityDefinition, CapabilityRegistry
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    ContractValidationError,
    ToolExecutionError,
    ToolTimeoutError,
)
from harness_engineering.execution import ExecutionContext, ExecutionLimits
from harness_engineering.lifecycle_controls import OffSwitch
from harness_engineering.mcp_binding import (
    CurrentAuthorizer,
    MCPBindingHandle,
    MCPBindingRegistry,
    MCPBoundRuntime,
    TrustedMCPBinding,
)
from harness_engineering.mcp_discovery import (
    MAX_CAPABILITIES,
    MCPCapabilityCandidate,
    MCPDiscoverySnapshot,
    MCPServiceMetadata,
    translate_discovery,
)


class LocalMCPError(ToolExecutionError):
    """Sanitized expected protocol/session/remote failure; diagnostic causes are untrusted."""


def _result(result: object) -> dict[str, Any]:
    """Accept complete structured-object results with no content or extension metadata.

    SDK object construction already occurred: these are application acceptance
    bounds, not transport deserialization/memory isolation guarantees.
    """
    if type(result) is not types.CallToolResult:
        raise ContractValidationError("Unsupported MCP result type.")
    if result.is_error:
        raise LocalMCPError("Local MCP tool reported failure; remote content rejected.")
    if (
        result.content
        or result.meta is not None
        or result.model_extra
        or result.result_type != "complete"
    ):
        raise ContractValidationError("MCP result must contain only complete structured data.")
    data = result.structured_content
    if type(data) is not dict:
        raise ContractValidationError("MCP structured result must be an object.")
    pending = [(data, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 4096 or depth > 16:
            raise ContractValidationError("MCP result exceeds structural limits.")
        if type(item) is dict:
            if len(item) > 4096 or any(type(key) is not str or len(key) > 128 for key in item):
                raise ContractValidationError("Unsupported MCP result object keys.")
            pending.extend((value, depth + 1) for value in item.values())
        elif type(item) is list:
            if len(item) > 4096:
                raise ContractValidationError("MCP result array exceeds limits.")
            pending.extend((value, depth + 1) for value in item)
        elif type(item) is str:
            if len(item) > 16_384:
                raise ContractValidationError("MCP result string exceeds limits.")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ContractValidationError("MCP result must contain finite data.")
        elif item is not None and type(item) not in {int, bool}:
            raise ContractValidationError("MCP result contains unsupported values.")
    try:
        encoded = json.dumps(data, allow_nan=False, ensure_ascii=True).encode()
        if len(encoded) > 65_536:
            raise ContractValidationError("MCP result exceeds byte limit.")
        return json.loads(encoded)
    except (ValueError, TypeError) as exc:
        raise ContractValidationError("MCP result must be finite JSON data.") from exc


@asynccontextmanager
async def _session(server: Server[Any], timeout: float) -> AsyncIterator[ClientSession]:
    """Own streams, server task, and client in one portal task; cancel/join on exit."""
    async with (
        create_client_server_memory_streams() as (client, remote),
        anyio.create_task_group() as tasks,
    ):
        tasks.start_soon(server.run, *remote, server.create_initialization_options())
        try:
            async with ClientSession(*client, read_timeout_seconds=timeout) as session:
                yield session
        finally:
            tasks.cancel_scope.cancel()


class LocalMCPIntegration:
    """Single-use local SDK connection plus trusted Slice 2 registration bridge.

    Use as a synchronous context manager. Its portal owns async resources while
    accepted executor workers submit SDK requests to that portal. Only trusted
    bootstrap may call register/create_runtime. Returned candidates stay inert.
    """

    def __init__(self, server: Server[Any], *, io_timeout_seconds: float = 2.0) -> None:
        """Configure a trusted cooperative local server and bounded protocol waits.

        Args:
            server: Actual installed SDK Server with trusted local fixture callbacks.
            io_timeout_seconds: Initialize/discovery/call bound, at most 30 seconds.

        Raises:
            ContractValidationError: If bootstrap types or bounds are invalid.
        """
        if not isinstance(server, Server) or type(io_timeout_seconds) not in {float, int}:
            raise ContractValidationError("Provide an SDK server and finite local timeout.")
        if not math.isfinite(io_timeout_seconds) or not 0 < io_timeout_seconds <= 30:
            raise ContractValidationError("Local MCP timeout must be within (0, 30] seconds.")
        self._server = server
        self._timeout = float(io_timeout_seconds)
        self._registry = MCPBindingRegistry()
        self._snapshot: MCPDiscoverySnapshot | None = None
        self._used = False
        self._active = False
        self._discovery_remaining = 2

    def __enter__(self) -> "LocalMCPIntegration":
        """Initialize genuine SDK protocol once; failed starts also cannot reconnect."""
        if self._used:
            raise AuthorityViolationError(
                "Local MCP connection cannot restart or reset a workflow."
            )
        self._used = True
        with ExitStack() as stack:
            self._portal: BlockingPortal = stack.enter_context(
                start_blocking_portal(name="module-06-5-mcp-portal")
            )
            owner = self._portal.wrap_async_context_manager(_session(self._server, self._timeout))
            self._session = owner.__enter__()
            # Do not inject caller exceptions into the SDK task-group cleanup scope.
            stack.callback(owner.__exit__, None, None, None)
            self._initialization = self._portal.call(self._initialize)
            self._stack = stack.pop_all()
        self._active = True
        return self

    def __exit__(self, *exc: object) -> None:
        """Invalidate bindings, close session/streams, cancel server tasks, join portal.

        Local fixture callbacks must cooperate with cancellation. No forced
        termination guarantee is supplied for arbitrary synchronous Python.
        """
        self._active = False
        self._snapshot = None
        self._stack.close()

    async def _initialize(self) -> types.InitializeResult:
        try:
            with anyio.fail_after(self._timeout):
                return await self._session.initialize()
        except TimeoutError as exc:
            raise ToolTimeoutError("Local MCP initialization timed out.") from exc
        except (
            MCPError,
            anyio.BrokenResourceError,
            anyio.ClosedResourceError,
            anyio.EndOfStream,
        ) as exc:
            raise LocalMCPError("Local MCP initialization failed.") from exc

    def _require_active(self) -> None:
        if not self._active:
            raise AuthorityViolationError("Local MCP session is closed or not initialized.")

    @property
    def capabilities(self) -> CapabilityRegistry:
        """Expose application metadata only, for trusted permission bootstrap."""
        return self._registry.capabilities

    def discover(self) -> MCPDiscoverySnapshot:
        """Request one real SDK tool listing and translate through accepted Slice 1.

        Every refresh invalidates old candidate object identities, even if the
        response is identical or invalid. No continuation pages are requested.

        Returns:
            Inert SDK-derived candidates; registration/authority are unchanged.

        Raises:
            ContractValidationError: For unsupported discovery metadata.
            LocalMCPError: For expected protocol/session failure.
            ToolTimeoutError: If the discovery bound expires.
        """
        self._require_active()
        self._snapshot = None
        if self._discovery_remaining == 0:
            raise AuthorityViolationError(
                "Local MCP permits initial discovery and one refresh only."
            )
        self._discovery_remaining -= 1
        listing = self._portal.call(self._discover)
        if (
            len(listing.tools) > MAX_CAPABILITIES
            or listing.ttl_ms != 0
            or listing.cache_scope != "private"
        ):
            raise ContractValidationError("Unsupported MCP discovery count/cache profile.")
        data = listing.model_dump(by_alias=True, exclude_none=True)
        # SDK 2.3.0 emits these defaults on the wire; validate before projection.
        del data["ttlMs"], data["cacheScope"]
        info = self._initialization.server_info.model_dump(by_alias=True, exclude_none=True)
        self._snapshot = translate_discovery(json.dumps(info).encode(), json.dumps(data).encode())
        return self._snapshot

    async def _discover(self) -> types.ListToolsResult:
        try:
            with anyio.fail_after(self._timeout):
                return await self._session.list_tools()
        except TimeoutError as exc:
            raise ToolTimeoutError("Local MCP discovery timed out.") from exc
        except (
            MCPError,
            ValidationError,
            anyio.BrokenResourceError,
            anyio.ClosedResourceError,
            anyio.EndOfStream,
        ) as exc:
            raise LocalMCPError("Local MCP discovery failed.") from exc

    def _current(self, candidate: MCPCapabilityCandidate) -> MCPCapabilityCandidate | None:
        if self._active and self._snapshot is not None:
            return next((item for item in self._snapshot.candidates if item is candidate), None)
        return None

    def register(
        self,
        candidate: MCPCapabilityCandidate,
        *,
        expected_service: MCPServiceMetadata,
        expected_tool: str,
        capability: CapabilityDefinition,
        limits: ExecutionLimits,
    ) -> MCPBindingHandle:
        """Trusted bootstrap binds an original candidate to explicit application contracts.

        Args:
            candidate: Original candidate from this connection's latest discovery.
            expected_service: Application-configured expected advertised identity.
            expected_tool: Application-configured exact remote name.
            capability: Independent application identity and Pydantic contracts.
            limits: Accepted application execution limits.

        Returns:
            Slice 2 original handle, which still grants no execution permission.

        Raises:
            AuthorityViolationError: For foreign, stale, copied, or closed candidates.
            ContractValidationError: For invalid/duplicate trusted binding configuration.
        """
        self._require_active()
        if self._current(candidate) is None:
            raise AuthorityViolationError("Original current local MCP candidate required.")

        def invoke(inputs: BaseModel, context: ExecutionContext) -> object:
            return self._portal.call(
                self._invoke, candidate, inputs.model_dump(mode="json"), context
            )

        return self._registry.register(
            TrustedMCPBinding(
                expected_service,
                expected_tool,
                candidate,
                capability,
                invoke,
                lambda: self._current(candidate),
                limits,
            )
        )

    def create_runtime(
        self,
        *,
        current_authorizer: CurrentAuthorizer,
        budget: RuntimeBudget,
        off_switch: OffSwitch,
    ) -> MCPBoundRuntime:
        """Create the sole accepted runtime, requiring the frozen <=12 MCP-call bound."""
        self._require_active()
        checked = RuntimeBudget.model_validate(budget.model_dump())
        if checked.max_tool_calls > 12:
            raise ContractValidationError("Local MCP workflow permits at most 12 tool calls.")
        return self._registry.create_runtime(
            current_authorizer=current_authorizer, budget=checked, off_switch=off_switch
        )

    async def _invoke(
        self,
        candidate: MCPCapabilityCandidate,
        arguments: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        if self._current(candidate) is None:
            raise AuthorityViolationError(
                "Local MCP binding became stale before protocol invocation."
            )
        context.checkpoint()
        try:
            with anyio.fail_after(self._timeout):
                result = await self._session.call_tool(
                    candidate.remote_name,
                    arguments,
                    read_timeout_seconds=self._timeout,
                    allow_input_required=True,
                    allow_claimed=True,
                )
        except TimeoutError as exc:
            raise ToolTimeoutError(
                "Local MCP invocation timed out; effects may have occurred."
            ) from exc
        except (
            MCPError,
            ValidationError,
            anyio.BrokenResourceError,
            anyio.ClosedResourceError,
            anyio.EndOfStream,
        ) as exc:
            raise LocalMCPError(
                "Local MCP invocation failed; remote diagnostics rejected."
            ) from exc
        context.checkpoint()
        return _result(result)
