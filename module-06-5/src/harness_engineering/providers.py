"""Story 9: bounded application-owned provider boundary and deterministic default.

Trusted bootstrap binds one runtime per workflow and its finite action IDs.
The fake remains default; optional vendor bindings require explicit bootstrap.
No automatic retry, tool routing, or authority deserialization occurs.
Python callbacks are trusted code; timeout rejects results, not external effects.
"""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from math import isfinite
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness_engineering.config import HarnessConfig
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    HarnessError,
)
from harness_engineering.lifecycle_controls import OffSwitch

if TYPE_CHECKING:
    from harness_engineering.guardrails_adapter import GuardrailsTextValidator


class ProviderTimeoutError(BudgetExceededError):
    """Provider action/workflow time expired; rejected results grant nothing."""


class ProviderOutputRejected(ContractValidationError):
    """Provider output violates the application text profile or content filter."""


class ProviderExecutionError(HarnessError):
    """Sanitized expected vendor failure; never an automatic retry instruction."""


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
    FAILED = "failed"


class ProviderCallContext:
    """Cooperative invocation checks supplied only by the application runtime."""

    def __init__(self, deadline: float, off_switch: OffSwitch) -> None:
        """Bind an absolute monotonic deadline and application cancellation."""
        self._deadline = deadline
        self._off_switch = off_switch
        self._cancelled = Event()
        self._max_output_tokens = 2_000
        self._max_context_tokens = 12_000
        self._live_allowed = False

    @property
    def remaining_seconds(self) -> float:
        """Return the remaining accepted invocation time, never a fresh timeout."""
        self.checkpoint()
        return max(0.0, self._deadline - monotonic())

    @property
    def max_output_tokens(self) -> int:
        """Return the application-owned per-call output limit."""
        return self._max_output_tokens

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
    accounting. Durable provider recovery integration remains a later concern.
    """

    def __init__(
        self,
        *,
        budget: RuntimeBudget | None = None,
        action_ids: tuple[str, ...] = ("model",),
        provider: ModelProvider | None = None,
        output_filter: OutputFilter | None = None,
        off_switch: OffSwitch | None = None,
        live_config: HarnessConfig | None = None,
        guardrails: GuardrailsTextValidator | None = None,
    ) -> None:
        """Snapshot trusted configuration, independently gating optional live bindings.

        Args:
            budget: Accepted workflow controls, which may only tighten frozen caps.
            action_ids: Finite application-owned work IDs; not model-selected routes.
            provider: Fake or an exact supported optional vendor adapter.
            output_filter: Optional trusted literal output rejection policy.
            off_switch: Shared one-way application cancellation source.
            live_config: Explicit non-deterministic live opt-in with a finite monetary
                budget matching this runtime. Never inferred from credentials.
            guardrails: Optional exact local Guardrails text validator from trusted bootstrap.

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
        self._live_allowed = False
        if provider is not None and type(provider) is not FakeProvider:
            from harness_engineering.vendor_providers import _validate_binding

            self._live_allowed = _validate_binding(provider, live_config, b)
        if off_switch is not None and type(off_switch) is not OffSwitch:
            raise ContractValidationError("Bind an application OffSwitch.")
        self._provider: ModelProvider = FakeProvider() if provider is None else provider
        self._off_switch = OffSwitch() if off_switch is None else off_switch
        self._terms = tuple(term.casefold() for term in policy.blocked_terms)
        if guardrails is not None:
            from harness_engineering.guardrails_adapter import GuardrailsTextValidator

            if type(guardrails) is not GuardrailsTextValidator:
                raise ContractValidationError("Bind the approved local Guardrails text validator.")
        self._guardrails = guardrails
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
            context._max_output_tokens = b.max_output_tokens
            context._max_context_tokens = b.max_context_tokens
            context._live_allowed = self._live_allowed
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
                    if self._guardrails is not None:
                        if self._guardrails.validate(response.text) is not None:
                            raise ProviderOutputRejected("Unsupported Guardrails adapter result.")
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
                    else ProviderEvent.FAILED
                    if isinstance(outcome, ProviderExecutionError)
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
