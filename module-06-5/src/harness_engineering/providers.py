"""Story 9 Slice 1: bounded provider-neutral text boundary and deterministic fake.

Trusted bootstrap binds one runtime per workflow and its finite action IDs.
Only the local fake is executable in this slice. No SDK, key/environment lookup,
network, automatic retry, tool routing, or authority deserialization occurs.
Python callbacks are trusted code; timeout rejects results, not external effects.
"""

from collections import deque
from enum import StrEnum
from math import isfinite
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
)
from harness_engineering.lifecycle_controls import OffSwitch


class ProviderTimeoutError(BudgetExceededError):
    """Provider action/workflow time expired; rejected results grant nothing."""


class ProviderOutputRejected(ContractValidationError):
    """Provider output violates the application text profile or content filter."""


class _Data(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class ModelRequest(_Data):
    """Bounded contextual input only, without model, routing, or authority fields."""

    prompt: str = Field(min_length=1, max_length=12_000, repr=False)


class ModelResult(_Data):
    """Validated untrusted text, never an instruction to the control plane."""

    text: str = Field(max_length=20_000, repr=False)
    trust: Literal["untrusted_model"] = "untrusted_model"

    @property
    def grants_authority(self) -> bool:
        """Return False regardless of the generated text's instructions."""
        return False


class _TextResponse(_Data):
    text: str = Field(max_length=20_000, repr=False)


class OutputFilter(_Data):
    """Trusted literal substring rejection policy, not a prompt-injection detector.

    Empty policy permits schema-valid text. Matching is case-insensitive;
    rejected content is never returned or included in a diagnostic.
    """

    blocked_terms: tuple[str, ...] = Field(default=(), max_length=32)


class ProviderEvent(StrEnum):
    """Finite audit vocabulary without prompts, output, secrets, or raw errors."""

    STARTED = "started"
    VALIDATED = "validated"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEFECT = "defect"


class ProviderCallContext:
    """Cooperative invocation checks supplied only by the application runtime."""

    def __init__(self, deadline: float, off_switch: OffSwitch) -> None:
        """Bind an absolute monotonic deadline and application cancellation."""
        self._deadline = deadline
        self._off_switch = off_switch
        self._cancelled = Event()

    def checkpoint(self) -> None:
        """Deny cancelled or expired work without resetting consumed budgets."""
        if self._off_switch.is_active():
            raise AuthorityViolationError("Provider execution cancelled by application.")
        if self._cancelled.is_set() or monotonic() >= self._deadline:
            raise ProviderTimeoutError("Provider deadline reached; discard the result.")


class ModelProvider(Protocol):
    """Application-owned adapter seam; SDK objects never cross this boundary."""

    def generate(self, request: ModelRequest, context: ProviderCallContext) -> object:
        """Return untrusted data for application validation, never privileged work."""
        ...


class FakeProvider:
    """Credential-free deterministic provider with no prompt interpretation."""

    def generate(self, request: ModelRequest, context: ProviderCallContext) -> object:
        """Produce fixed local text after checking the cooperative deadline."""
        context.checkpoint()
        return {"text": "Deterministic provider response."}


class ProviderRuntime:
    """One single-slot workflow owner for provider attempts and output filtering.

    Each explicit call consumes an attempt, including failures. No retries are
    implicit. Repeated calls for a bound action share its 1 + retry limit and
    the workflow attempt limit; neither is caller-supplied at invocation.
    Do not reconstruct this runtime from generated or checkpoint data to reset
    accounting. Recovery and vendor integrations are later slices.
    """

    def __init__(
        self,
        *,
        budget: RuntimeBudget | None = None,
        action_ids: tuple[str, ...] = ("model",),
        provider: FakeProvider | None = None,
        output_filter: OutputFilter | None = None,
        off_switch: OffSwitch | None = None,
    ) -> None:
        """Snapshot trusted configuration; live adapters are unavailable in Slice 1.

        Args:
            budget: Accepted workflow controls, which may only tighten frozen caps.
            action_ids: Finite application-owned work IDs; not model-selected routes.
            provider: Deterministic fake only. SDK/live bindings remain deferred.
            output_filter: Optional trusted literal output rejection policy.
            off_switch: Shared one-way application cancellation source.

        Raises:
            ContractValidationError: For invalid bootstrap or unsupported adapters.
        """
        try:
            supplied = RuntimeBudget() if budget is None else budget
            self._budget = RuntimeBudget.model_validate(supplied.model_dump(), strict=True)
            policy = OutputFilter.model_validate(
                OutputFilter() if output_filter is None else output_filter
            )
        except (ValidationError, AttributeError) as exc:
            raise ContractValidationError("Invalid provider bootstrap configuration.") from exc
        b = self._budget
        if (
            b.max_provider_attempts > 8
            or b.max_retries_per_action > 2
            or b.max_output_tokens > 2_000
            or b.max_context_tokens > 12_000
            or b.workflow_deadline_seconds > 180
            or b.action_timeout_seconds > 30
            or not all(
                isfinite(v)
                for v in (
                    b.workflow_deadline_seconds,
                    b.action_timeout_seconds,
                    b.latency_slo_p95_seconds,
                )
            )
        ):
            raise ContractValidationError("Provider limits must fit the frozen workflow caps.")
        if (
            type(action_ids) is not tuple
            or not 1 <= len(action_ids) <= b.max_plan_steps
            or any(type(v) is not str or not 1 <= len(v) <= 128 for v in action_ids)
            or len(set(action_ids)) != len(action_ids)
        ):
            raise ContractValidationError("Bind unique bounded application action IDs.")
        if any(type(t) is not str or not 1 <= len(t) <= 128 for t in policy.blocked_terms):
            raise ContractValidationError("Output filter terms must contain 1 to 128 characters.")
        if provider is not None and type(provider) is not FakeProvider:
            raise ContractValidationError("Slice 1 supports only the deterministic fake provider.")
        if off_switch is not None and type(off_switch) is not OffSwitch:
            raise ContractValidationError("Bind an application OffSwitch.")
        self._provider: ModelProvider = FakeProvider() if provider is None else provider
        self._off_switch = OffSwitch() if off_switch is None else off_switch
        self._terms = tuple(term.casefold() for term in policy.blocked_terms)
        self._deadline = monotonic() + b.workflow_deadline_seconds
        self._attempts = 0
        self._actions = dict.fromkeys(action_ids, 0)
        self._slot = Lock()
        self._audit: deque[ProviderEvent] = deque(maxlen=128)

    @property
    def attempts(self) -> int:
        """Return measured consumed attempts, never a writable budget token."""
        return self._attempts

    @property
    def audit(self) -> tuple[ProviderEvent, ...]:
        """Return bounded sanitized observations without executable authority."""
        return tuple(self._audit)

    def generate(self, request: object, *, action_id: str = "model") -> ModelResult:
        """Validate input, invoke once, filter output and return untrusted text.

        Args:
            request: ModelRequest or plain application-input dictionary.
            action_id: An already bound application work ID, never a callable name.

        Returns:
            Fresh application-owned ModelResult that grants no authority.

        Raises:
            ContractValidationError: For malformed input or unsupported output.
            ProviderOutputRejected: For filtered or malformed provider content.
            AuthorityViolationError: When the application off-switch is active.
            BudgetExceededError: For attempts, retries, sizes or active concurrency.
            ProviderTimeoutError: For action or workflow deadline exhaustion.
            Exception: Unexpected programming defects propagate unchanged.
        """
        if not self._slot.acquire(blocking=False):
            raise BudgetExceededError("Provider worker is active; do not start another attempt.")
        launched = False
        try:
            try:
                value = ModelRequest.model_validate(request)
            except ValidationError as exc:
                raise ContractValidationError("Provider input violates ModelRequest.") from exc
            if type(action_id) is not str or action_id not in self._actions:
                raise ContractValidationError("Provider action is not application-bound.")
            b = self._budget
            if _units(value.prompt) > b.max_context_tokens:
                raise BudgetExceededError("Provider prompt exceeds the conservative input budget.")
            context = ProviderCallContext(
                min(self._deadline, monotonic() + b.action_timeout_seconds), self._off_switch
            )
            context.checkpoint()
            if self._attempts >= b.max_provider_attempts:
                raise BudgetExceededError("Workflow provider-attempt budget exhausted.")
            if self._actions[action_id] >= b.max_retries_per_action + 1:
                raise BudgetExceededError("Application action retry budget exhausted.")
            self._attempts += 1
            self._actions[action_id] += 1
            self._audit.append(ProviderEvent.STARTED)
            result: Queue[ModelResult | BaseException] = Queue(maxsize=1)

            def invoke() -> None:
                try:
                    context.checkpoint()
                    raw = self._provider.generate(value, context)
                    context.checkpoint()
                    if type(raw) is not dict or set(raw) != {"text"}:
                        raise ProviderOutputRejected("Provider must return only plain text data.")
                    try:
                        response = _TextResponse.model_validate(raw)
                    except ValidationError as exc:
                        raise ProviderOutputRejected(
                            "Provider text response is malformed."
                        ) from exc
                    if _units(response.text) > b.max_output_tokens:
                        raise BudgetExceededError(
                            "Provider output exceeds its conservative budget."
                        )
                    if any(term in response.text.casefold() for term in self._terms):
                        raise ProviderOutputRejected(
                            "Provider output rejected by application filter."
                        )
                    context.checkpoint()
                    result.put(ModelResult(text=response.text))
                except BaseException as exc:
                    # Thread bridge preserves defects; it does not classify them as provider errors.
                    result.put(exc)
                finally:
                    self._slot.release()

            worker = Thread(target=invoke, name="module-06-5-provider", daemon=True)
            worker.start()
            launched = True
            try:
                outcome = result.get(timeout=max(0, context._deadline - monotonic()))
            except Empty as exc:
                context._cancelled.set()
                self._audit.append(ProviderEvent.TIMEOUT)
                raise ProviderTimeoutError("Provider timed out; discard late results.") from exc
            if isinstance(outcome, BaseException):
                if isinstance(outcome, TimeoutError):
                    self._audit.append(ProviderEvent.TIMEOUT)
                    raise ProviderTimeoutError(
                        "Provider timed out; discard the result."
                    ) from outcome
                self._audit.append(
                    ProviderEvent.CANCELLED
                    if isinstance(outcome, AuthorityViolationError)
                    else ProviderEvent.TIMEOUT
                    if isinstance(outcome, ProviderTimeoutError)
                    else ProviderEvent.REJECTED
                    if isinstance(outcome, (ContractValidationError, BudgetExceededError))
                    else ProviderEvent.DEFECT
                )
                raise outcome
            context.checkpoint()
            self._audit.append(ProviderEvent.VALIDATED)
            return outcome
        finally:
            if not launched:
                self._slot.release()


def _units(text: str) -> int:
    """Count UTF-8 bytes conservatively; this is not vendor tokenizer evidence."""
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ContractValidationError("Provider text must contain valid UTF-8.") from exc
