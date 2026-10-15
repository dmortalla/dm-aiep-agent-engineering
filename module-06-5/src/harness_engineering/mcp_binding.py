"""Trusted MCP binding over accepted controls (REQ-MCP-001/003, REQ-TECH-003).

Only trusted application bootstrap may create bindings, supply current authority,
or create workflow runtimes. Data validation cannot establish that provenance.
This callable seam performs no MCP protocol or transport operations.
"""

import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from harness_engineering.capabilities import CapabilityDefinition, CapabilityRegistry
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    ToolExecutionError,
    ToolTimeoutError,
)
from harness_engineering.execution import (
    BoundedToolExecutor,
    ExecutionContext,
    ExecutionLimits,
    ToolHandler,
)
from harness_engineering.lifecycle_controls import OffSwitch
from harness_engineering.mcp_discovery import (
    MAX_SCHEMA_BYTES,
    MCPCapabilityCandidate,
    MCPServiceMetadata,
    translate_discovery,
)
from harness_engineering.permissions import (
    ActionProposal,
    AuthorizationDecision,
    AuthorizationOutcome,
    CapabilityAuthorizer,
)

CurrentAuthorizer = Callable[[], CapabilityAuthorizer]
CurrentCandidate = Callable[[], MCPCapabilityCandidate | None]


@dataclass(frozen=True, slots=True)
class TrustedMCPBinding:
    """Application bootstrap declaration, never loaded from contextual data.

    The expected service/tool is an explicit application decision, not identity
    proof. Candidate equality is not authorization. Freshness uses the original
    candidate object held by trusted application state; rediscovery requires a
    new trusted binding/runtime. Callbacks must cooperate with bounded execution.
    """

    expected_service: MCPServiceMetadata
    expected_tool: str
    candidate: MCPCapabilityCandidate
    capability: CapabilityDefinition
    handler: ToolHandler = field(repr=False)
    current_candidate: CurrentCandidate = field(repr=False)
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)


class MCPBindingHandle:
    """Opaque runtime object; only original registered object identity is accepted."""

    __slots__ = ()


class MCPBindingEventKind(StrEnum):
    """Finite sanitized audit vocabulary, with no remote or payload text."""

    REGISTERED = "registered"
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    INVOKING = "invoking"
    VALIDATED = "validated"
    DENIED = "denied"
    INVALID = "invalid"
    BUDGET = "budget"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MCPBindingAuditEvent:
    """Bounded data-only event; operation UUID is correlation, never permission."""

    operation_id: UUID
    kind: MCPBindingEventKind


@dataclass
class _Invocation:
    """Private correlation state; never returned or consumed as permission."""

    operation_id: UUID
    started: bool = False


class _Audit:
    """Thread-safe ring; denial floods cannot grow retained audit without bound."""

    def __init__(self) -> None:
        self.events: deque[MCPBindingAuditEvent] = deque(maxlen=128)
        self.lock = Lock()

    def record(self, operation: UUID, kind: MCPBindingEventKind) -> None:
        with self.lock:
            self.events.append(MCPBindingAuditEvent(operation, kind))

    def snapshot(self) -> tuple[MCPBindingAuditEvent, ...]:
        with self.lock:
            return tuple(self.events)


def _check_candidate(candidate: MCPCapabilityCandidate) -> None:
    """Revalidate constructed/forged metadata through the accepted public boundary."""
    if (
        type(candidate) is not MCPCapabilityCandidate
        or type(candidate.service) is not MCPServiceMetadata
    ):
        raise ContractValidationError("Binding requires validated MCP candidate metadata.")
    texts = (candidate.service.name, candidate.service.version, candidate.remote_name)
    if any(type(value) is not str or len(value) > 128 for value in texts):
        raise ContractValidationError("Invalid binding candidate identity.")
    if candidate.description is not None and (
        type(candidate.description) is not str or len(candidate.description) > 2000
    ):
        raise ContractValidationError("Invalid binding candidate description.")
    for schema in (candidate.input_schema_json, candidate.output_schema_json):
        if schema is not None and (type(schema) is not str or len(schema) > MAX_SCHEMA_BYTES):
            raise ContractValidationError("Invalid binding candidate schema snapshot.")
    if type(candidate.input_schema_json) is not str or candidate.trust != "untrusted_mcp":
        raise ContractValidationError("Invalid binding candidate contract.")
    # Embed schema JSON as raw JSON, allowing Slice 1 to enforce depth/size before parsing.
    service = json.dumps({"name": texts[0], "version": texts[1]}).encode()
    payload_text = (
        '{"tools":[{"name":'
        + json.dumps(texts[2])
        + ',"description":'
        + json.dumps(candidate.description)
        + ',"inputSchema":'
        + candidate.input_schema_json
        + ',"outputSchema":'
        + (candidate.output_schema_json or "null")
        + "}]}"
    )
    try:
        payload = payload_text.encode()
    except UnicodeEncodeError as exc:
        raise ContractValidationError("Binding schema snapshot must be UTF-8 JSON.") from exc
    checked = translate_discovery(service, payload).candidates[0]
    if checked != candidate:
        raise ContractValidationError("Binding candidate must retain its exact canonical snapshot.")


class MCPBindingRegistry:
    """Trusted bootstrap-only registration; immutable bindings after runtime creation.

    Owns an accepted CapabilityRegistry, with application-declared schemas only.
    There is no metadata loader, handler resolver by string, or rebinding API.
    """

    def __init__(self) -> None:
        """Create an empty application registry with no discovery side effects."""
        self._capabilities = CapabilityRegistry()
        self._bindings: dict[MCPBindingHandle, TrustedMCPBinding] = {}
        self._sealed = False
        self._audit = _Audit()

    @property
    def capabilities(self) -> CapabilityRegistry:
        """Expose accepted inert metadata for trusted application policy bootstrap."""
        return self._capabilities

    @property
    def audit(self) -> tuple[MCPBindingAuditEvent, ...]:
        """Return the bounded registration/runtime audit snapshot."""
        return self._audit.snapshot()

    def register(self, binding: TrustedMCPBinding) -> MCPBindingHandle:
        """Register an explicit trusted declaration without granting permission.

        Args:
            binding: Bootstrap-owned callable, contracts, expected identity, and limits.

        Returns:
            Original opaque handle for this exact binding; not a permission token.

        Raises:
            ContractValidationError: For malformed, mismatched, duplicate, or sealed bindings.
        """
        try:
            return self._register(binding)
        except ContractValidationError:
            self._audit.record(uuid4(), MCPBindingEventKind.INVALID)
            raise

    def _register(self, binding: TrustedMCPBinding) -> MCPBindingHandle:
        if self._sealed or type(binding) is not TrustedMCPBinding or len(self._bindings) >= 100:
            raise ContractValidationError("Register at most 100 trusted bindings before sealing.")
        _check_candidate(binding.candidate)
        if (
            type(binding.expected_service) is not MCPServiceMetadata
            or binding.expected_service != binding.candidate.service
            or type(binding.expected_tool) is not str
            or binding.expected_tool != binding.candidate.remote_name
            or not callable(binding.handler)
            or not callable(binding.current_candidate)
        ):
            raise ContractValidationError(
                "Binding identity/callbacks do not match trusted configuration."
            )
        try:
            capability = CapabilityDefinition.model_validate(binding.capability)
            limits = ExecutionLimits.model_validate(binding.limits)
        except ValidationError as exc:
            raise ContractValidationError("Invalid application MCP binding contracts.") from exc
        remote = (binding.expected_service, binding.expected_tool)
        if any(
            (item.expected_service, item.expected_tool) == remote
            for item in self._bindings.values()
        ):
            raise ContractValidationError(
                "Remote capability is already bound; replacement is forbidden."
            )
        # Construct a detached declaration; retain the original candidate and callable handles.
        accepted = TrustedMCPBinding(
            binding.expected_service,
            binding.expected_tool,
            binding.candidate,
            capability,
            binding.handler,
            binding.current_candidate,
            limits,
        )
        self._capabilities.register(capability)  # Existing duplicate/schema enforcement.
        handle = MCPBindingHandle()
        self._bindings[handle] = accepted
        self._audit.record(uuid4(), MCPBindingEventKind.REGISTERED)
        return handle

    def create_runtime(
        self, *, current_authorizer: CurrentAuthorizer, budget: RuntimeBudget, off_switch: OffSwitch
    ) -> "MCPBoundRuntime":
        """Seal once and build one workflow executor without resetting budgets.

        Args:
            current_authorizer: Trusted, bounded resolver of current accepted authorization.
            budget: Application-owned workflow budget, never caller overrides.
            off_switch: Existing application-owned one-way cancellation handle.

        Returns:
            The sole runtime for this registration set and workflow budget.

        Raises:
            ContractValidationError: If already sealed or bootstrap is invalid.
        """
        if self._sealed or not callable(current_authorizer) or type(off_switch) is not OffSwitch:
            raise ContractValidationError("Create one MCP runtime with trusted current controls.")
        runtime = MCPBoundRuntime(
            self._capabilities,
            dict(self._bindings),
            current_authorizer,
            budget,
            off_switch,
            self._audit,
        )
        self._sealed = True
        return runtime


class _CurrentAuthorizer(CapabilityAuthorizer):
    """Dispatch accepted executor authorization to the current accepted authorizer.

    This subtype implements no permission policy. All permission decisions are
    delegated; cancellation is an additional deny-only check using OffSwitch.
    """

    def __init__(self, resolve: CurrentAuthorizer, off_switch: OffSwitch) -> None:
        self._resolve = resolve
        self._off_switch = off_switch

    def authorize(self, proposal: ActionProposal) -> AuthorizationDecision:
        """Resolve current authority inside the executor's bounded worker."""
        if self._off_switch.is_active():
            return AuthorizationDecision(outcome=AuthorizationOutcome.DENY, reason="cancelled")
        current = self._resolve()
        if type(current) is not CapabilityAuthorizer:
            raise ContractValidationError("Current authority must be an application authorizer.")
        decision = current.authorize(proposal)
        if self._off_switch.is_active():
            return AuthorizationDecision(outcome=AuthorizationOutcome.DENY, reason="cancelled")
        return decision


class MCPBoundRuntime:
    """Callable integration over one accepted executor; no protocol implementation.

    Construct through MCPBindingRegistry.create_runtime from trusted bootstrap.
    Neither this Python class nor its handles isolate hostile in-process Python.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        bindings: dict[MCPBindingHandle, TrustedMCPBinding],
        current_authorizer: CurrentAuthorizer,
        budget: RuntimeBudget,
        off_switch: OffSwitch,
        audit: _Audit,
    ) -> None:
        """Snapshot bootstrap bindings and retain one executor's lifetime budgets."""
        self._bindings = bindings
        self._audit = audit
        self._gate = _CurrentAuthorizer(current_authorizer, off_switch)
        self._off_switch = off_switch
        self._operations: dict[str, _Invocation] = {}
        self._invocation_slot = Lock()
        self._executor = BoundedToolExecutor(
            registry,
            self._gate,
            {item.capability.capability_id: self._handler(item) for item in bindings.values()},
            {item.capability.capability_id: item.limits for item in bindings.values()},
            budget,
        )

    @property
    def audit(self) -> tuple[MCPBindingAuditEvent, ...]:
        """Return the most recent 128 sanitized events, including denials."""
        return self._audit.snapshot()

    def _handler(self, binding: TrustedMCPBinding) -> ToolHandler:
        def invoke(inputs: BaseModel, context: ExecutionContext) -> object:
            invocation = self._operations[binding.capability.capability_id]
            context.checkpoint()
            if binding.current_candidate() is not binding.candidate:
                raise AuthorityViolationError(
                    "MCP binding is stale; trusted re-registration required."
                )
            # Recheck after freshness lookup, immediately before the protected callable.
            decision = self._gate.authorize(context.proposal)
            if not decision.allowed:
                raise AuthorityViolationError("MCP invocation denied by current controls.")
            context.checkpoint()
            operation = invocation.operation_id
            self._audit.record(operation, MCPBindingEventKind.AUTHORIZED)
            self._audit.record(operation, MCPBindingEventKind.INVOKING)
            invocation.started = True
            try:
                output = binding.handler(inputs, context)
            except (
                ContractValidationError,
                AuthorityViolationError,
                BudgetExceededError,
            ) as exc:
                # Only known application-boundary failures are normalized here.
                # Defects remain subject to the accepted executor's worker semantics.
                error_type = next(
                    kind
                    for kind in (
                        ToolTimeoutError,
                        BudgetExceededError,
                        AuthorityViolationError,
                        ContractValidationError,
                    )
                    if isinstance(exc, kind)
                )
                raise error_type(
                    "MCP adapter rejected execution; inspect untrusted cause safely."
                ) from exc
            context.checkpoint()
            if self._off_switch.is_active():
                raise AuthorityViolationError("MCP cancelled; returned result rejected.")
            return output

        return invoke

    def execute(
        self, handle: MCPBindingHandle, proposal: ActionProposal, inputs: object
    ) -> BaseModel:
        """Validate and invoke once through current authorization and accepted bounds.

        Args:
            handle: Original registered runtime handle; never metadata or deserialized data.
            proposal: Untrusted application action/resource proposal, not remote identity.
            inputs: Untrusted inputs validated by application-declared schema.

        Returns:
            Output validated against the application-declared output schema.

        Raises:
            ContractValidationError: If proposal/input/output violates accepted contracts.
            AuthorityViolationError: For invalid handles, stale binding, or current denial.
            BudgetExceededError: For exhausted resources or concurrent invocation.
            ToolTimeoutError: For accepted bounded-wait timeout/deadline semantics.
            ToolExecutionError: For worker/handler defects, preserving accepted chained causes.
        """
        operation = uuid4()
        invocation = _Invocation(operation)
        self._audit.record(operation, MCPBindingEventKind.REQUESTED)
        if not self._invocation_slot.acquire(blocking=False):
            self._audit.record(operation, MCPBindingEventKind.BUDGET)
            raise BudgetExceededError("MCP invocation already active.")
        try:
            binding = next((item for key, item in self._bindings.items() if key is handle), None)
            if binding is None:
                raise AuthorityViolationError("Original registered MCP binding handle required.")
            try:
                requested = ActionProposal.model_validate(proposal)
            except ValidationError as exc:
                raise ContractValidationError("Invalid application MCP action proposal.") from exc
            if requested.capability_id != binding.capability.capability_id:
                raise AuthorityViolationError("MCP handle/application capability mismatch.")
            self._operations[requested.capability_id] = invocation
            output = self._executor.execute(requested, inputs)
            self._audit.record(operation, MCPBindingEventKind.VALIDATED)
            return output
        except AuthorityViolationError:
            self._audit.record(
                operation,
                MCPBindingEventKind.FAILED if invocation.started else MCPBindingEventKind.DENIED,
            )
            raise
        except ToolTimeoutError:
            self._audit.record(operation, MCPBindingEventKind.TIMEOUT)
            raise
        except BudgetExceededError:
            self._audit.record(operation, MCPBindingEventKind.BUDGET)
            raise
        except ContractValidationError:
            self._audit.record(operation, MCPBindingEventKind.INVALID)
            raise
        except ToolExecutionError:
            self._audit.record(operation, MCPBindingEventKind.FAILED)
            raise
        finally:
            self._invocation_slot.release()
