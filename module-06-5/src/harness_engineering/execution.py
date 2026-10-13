"""Application-level bounds for trusted local handlers (REQ-TOOL-004).

No OS, process, filesystem, network, or memory isolation is supplied. Timeout
rejects results, not side effects. Handlers must cooperate with checkpoints and
use bounded I/O. A stuck handler occupies the single execution slot indefinitely.
Construct one executor per application-owned workflow; never from contextual data.
"""

import json
import math
from collections.abc import Callable, Mapping
from queue import Queue
from threading import Event, Lock, Thread
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness_engineering.capabilities import CapabilityRegistry
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    ToolExecutionError,
    ToolTimeoutError,
)
from harness_engineering.permissions import ActionProposal, CapabilityAuthorizer


class ExecutionLimits(BaseModel):
    """Trusted per-capability bounds, separate from discovery and permission."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    timeout_seconds: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)
    max_input_bytes: int = Field(default=16_384, ge=1, le=1_048_576, strict=True)
    max_output_bytes: int = Field(default=16_384, ge=1, le=1_048_576, strict=True)
    max_work_units: int = Field(default=100, ge=1, le=100_000, strict=True)


class ExecutionContext:
    """Exact approved target and cooperative application work/deadline budget.

    This is not a security boundary against arbitrary Python handler code.
    Exhaustion latches even if a handler catches the raised exception.
    """

    def __init__(self, proposal: ActionProposal, deadline: float, max_units: int) -> None:
        """Initialize context from executor-owned validated state."""
        self._proposal = proposal
        self._deadline = deadline
        self._remaining = max_units
        self._cancelled = Event()
        self._exhausted = False

    @property
    def proposal(self) -> ActionProposal:
        """Return the exact action/resource authorized for this invocation."""
        return self._proposal

    def checkpoint(self, units: int = 0) -> None:
        """Charge work before performing it; reject expired or exhausted work.

        Args:
            units: Nonnegative integer work units declared by the local handler.

        Raises:
            ToolTimeoutError: If cancelled or past the invocation deadline.
            BudgetExceededError: If work units are invalid or exhausted.
        """
        if self._cancelled.is_set() or monotonic() >= self._deadline:
            raise ToolTimeoutError("Tool deadline reached; stop handler work.")
        if type(units) is not int or units < 0 or units > self._remaining:
            self._exhausted = True
        if self._exhausted:
            raise BudgetExceededError("Tool work-unit budget exhausted or invalid charge.")
        self._remaining -= units


ToolHandler = Callable[[BaseModel, ExecutionContext], object]


def _payload(value: object, limit: int) -> dict[str, object]:
    """Snapshot bounded JSON objects, rejecting model-instance validation bypasses."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if type(value) is not dict:
        raise ContractValidationError("Tool payload must be a JSON object.")
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > limit:
            raise BudgetExceededError("Tool payload exceeds configured byte limit.")
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractValidationError("Tool payload must contain finite JSON data.") from exc


class BoundedToolExecutor:
    """Single-slot workflow executor enforcing accepted Slice 2 authorization.

    Bootstrap binds trusted handlers without changing capability metadata.
    No decisions, approvals, principal, grants, or budget overrides are accepted
    by execute. Failed/expired invocations consume calls; no retries are implicit.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        authorizer: CapabilityAuthorizer,
        handlers: Mapping[str, ToolHandler],
        limits: Mapping[str, ExecutionLimits],
        budget: RuntimeBudget,
    ) -> None:
        """Snapshot trusted bootstrap bindings and workflow budgets.

        Args:
            registry: Accepted metadata registry used to resolve contracts.
            authorizer: Application-owned Slice 2 authority for this workflow.
            handlers: At most 100 trusted, synchronous local handlers.
            limits: Exactly one validated resource configuration per handler.
            budget: Application-owned workflow budget; caller cannot reset it.

        Raises:
            ContractValidationError: If bootstrap configuration is invalid.
        """
        if len(handlers) > 100 or set(handlers) != set(limits):
            raise ContractValidationError("Bind at most 100 handlers with matching limits.")
        self._handlers = dict(handlers)
        self._limits: dict[str, ExecutionLimits] = {}
        try:
            self._budget = RuntimeBudget.model_validate(budget.model_dump())
            for key, handler in self._handlers.items():
                registry.lookup(key)
                if not callable(handler):
                    raise ContractValidationError("Tool binding must be callable.")
                self._limits[key] = ExecutionLimits.model_validate(limits[key])
        except (ValidationError, AttributeError) as exc:
            raise ContractValidationError("Invalid executor bootstrap configuration.") from exc
        if not all(
            math.isfinite(value)
            for value in (
                self._budget.action_timeout_seconds,
                self._budget.workflow_deadline_seconds,
            )
        ):
            raise ContractValidationError("Executor deadlines must be finite.")
        self._registry = registry
        self._authorizer = authorizer
        self._deadline = monotonic() + self._budget.workflow_deadline_seconds
        self._calls = 0
        self._slot = Lock()

    def execute(self, proposal: ActionProposal, inputs: object) -> BaseModel:
        """Validate, independently authorize, and invoke once within bounds.

        Args:
            proposal: Untrusted action proposal containing no authority metadata.
            inputs: Untrusted payload checked against the registered input schema.

        Returns:
            Fresh output validated against the registered output schema.

        Raises:
            ContractValidationError: For invalid proposals, bindings, or payloads.
            AuthorityViolationError: For DENY or APPROVAL_REQUIRED.
            BudgetExceededError: For concurrency, calls, payload, or work exhaustion.
            ToolTimeoutError: For action timeout or workflow deadline.
            ToolExecutionError: For handler exceptions, chained to the cause.
        """
        if not self._slot.acquire(blocking=False):
            raise BudgetExceededError("Executor busy; active handler must finish before reuse.")
        started = False
        try:
            try:
                requested = ActionProposal.model_validate(proposal)
            except ValidationError as exc:
                raise ContractValidationError("Invalid tool invocation proposal.") from exc
            capability = self._registry.lookup(requested.capability_id)
            if requested.capability_id not in self._handlers:
                raise ContractValidationError("Capability has no application handler binding.")
            limits = self._limits[requested.capability_id]
            try:
                validated = capability.input_schema.model_validate(
                    _payload(inputs, limits.max_input_bytes), strict=True
                )
            except ValidationError as exc:
                raise ContractValidationError("Tool input violates registered schema.") from exc
            if self._calls >= self._budget.max_tool_calls:
                raise BudgetExceededError("Workflow tool-call budget exhausted.")
            deadline = min(
                self._deadline,
                monotonic() + min(limits.timeout_seconds, self._budget.action_timeout_seconds),
            )
            context = ExecutionContext(requested, deadline, limits.max_work_units)
            context.checkpoint()
            result: Queue[BaseModel | BaseException] = Queue(maxsize=1)
            completed = Event()

            def invoke() -> None:
                try:
                    context.checkpoint()
                    decision = self._authorizer.authorize(requested)
                    if not decision.allowed:
                        raise AuthorityViolationError(f"Tool execution refused: {decision.reason}.")
                    context.checkpoint()
                    self._calls += 1
                    output = self._handlers[requested.capability_id](validated, context)
                    context.checkpoint()
                    try:
                        checked = capability.output_schema.model_validate(
                            _payload(output, limits.max_output_bytes), strict=True
                        )
                    except ValidationError as exc:
                        raise ContractValidationError(
                            "Tool output violates registered schema."
                        ) from exc
                    context.checkpoint()
                    result.put_nowait(checked)
                except BaseException as exc:
                    # Worker boundary transports failures, including thread exits.
                    result.put_nowait(exc)
                finally:
                    self._slot.release()
                    completed.set()

            worker = Thread(target=invoke, daemon=True, name="bounded-local-tool")
            try:
                worker.start()
            except RuntimeError as exc:
                raise ToolExecutionError(
                    "Cannot start tool worker; retry at application boundary."
                ) from exc
            started = True
            if not completed.wait(max(0, deadline - monotonic())) or monotonic() >= deadline:
                context._cancelled.set()
                raise ToolTimeoutError(
                    "Tool timed out; result rejected, side effects may continue."
                )
            outcome = result.get_nowait()
            if isinstance(outcome, BaseException):
                if isinstance(
                    outcome, (ContractValidationError, BudgetExceededError, AuthorityViolationError)
                ):
                    raise outcome
                raise ToolExecutionError("Tool handler failed; inspect chained cause.") from outcome
            return outcome
        finally:
            if not started:
                self._slot.release()
