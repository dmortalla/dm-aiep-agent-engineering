"""Story 9: bounded application-owned provider boundary and deterministic default.

Trusted bootstrap binds one runtime per workflow and its finite action IDs.
The fake remains default; optional vendor bindings require explicit bootstrap.
No automatic retry, tool routing, or authority deserialization occurs.
Python callbacks are trusted code; timeout rejects results, not external effects.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from math import isfinite
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness_engineering.anomaly_signals import AnomalyDetector
from harness_engineering.config import HarnessConfig
from harness_engineering.cost_governance import FixtureLedger, ProviderAlias
from harness_engineering.domain import EvidenceClass, RuntimeBudget, WorkflowIdentity
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    HarnessError,
)
from harness_engineering.governance_facts import GovernanceKind
from harness_engineering.latency import Measurement, Outcome
from harness_engineering.lifecycle_controls import OffSwitch
from harness_engineering.live_authorization import (
    LIVE_INPUT_OVERHEAD_TOKENS,
    MAX_AUTHORIZATION_WINDOW,
    LiveExecutionAuthorization,
    require_tariff_floor,
)
from harness_engineering.live_credentials import CREDENTIAL_SOURCE_TYPES, CredentialSource
from harness_engineering.observability import (
    TelemetrySession,
    TraceContext,
    bind_trace,
    current_trace,
)
from harness_engineering.usage import UsageCapture, UsageReceipt, UsageState

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
        self._max_output_bytes = 2_000
        self._max_context_tokens = 12_000
        self._live_allowed = False
        self._authorization: LiveExecutionAuthorization | None = None
        self._credentials: CredentialSource | None = None
        self._dispatched = Event()
        self._trace_context: TraceContext | None = None
        self._usage = UsageCapture()

    @property
    def trace_context(self) -> TraceContext | None:
        """Return inert application trace linkage, never execution authority."""
        return self._trace_context

    @property
    def remaining_seconds(self) -> float:
        """Return the remaining accepted invocation time, never a fresh timeout."""
        self.checkpoint()
        return max(0.0, self._deadline - monotonic())

    @property
    def max_output_tokens(self) -> int:
        """Return the application-owned per-call provider output-token limit."""
        return self._max_output_tokens

    @property
    def max_output_bytes(self) -> int:
        """Return the local per-call UTF-8 byte ceiling for returned text."""
        return self._max_output_bytes

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
        live_authorization: LiveExecutionAuthorization | None = None,
        credentials: CredentialSource | None = None,
        guardrails: GuardrailsTextValidator | None = None,
        telemetry: TelemetrySession | None = None,
        ledger: FixtureLedger | None = None,
        identity: WorkflowIdentity | None = None,
        anomalies: AnomalyDetector | None = None,
    ) -> None:
        """Snapshot trusted configuration, independently gating optional live bindings.

        Args:
            budget: Accepted workflow controls, which may only tighten frozen caps.
            action_ids: Finite application-owned work IDs; not model-selected routes.
            provider: Fake or an exact supported optional vendor adapter.
            output_filter: Optional trusted literal output rejection policy.
            off_switch: Shared one-way application cancellation source.
            live_config: Explicit non-deterministic live opt-in with a finite monetary
                budget matching this runtime and a live provider/model allowlist
                policy. Never inferred from credentials.
            live_authorization: Optional current human live-execution
                authorization for exactly the bound provider/model. Without it
                a live-configured runtime binds but can never dispatch.
            credentials: Trusted server-side credential source whose kind matches
                the live policy; required for, and only accepted by, live runtimes.
            guardrails: Optional exact local Guardrails text validator from trusted bootstrap.
            telemetry: Optional exact application-owned local telemetry session.
            ledger: Optional dedicated fixture-only exposure/token authority.
            identity: Optional trusted workflow attribution, reconciled with ledger.
            anomalies: Optional advisory-only provider event observer.

        Raises:
            ContractValidationError: For invalid bootstrap or unsupported adapters,
                or live authorization/credential bindings that do not match.
            AuthorityViolationError: For a vendor adapter without explicit live
                opt-in, budget and allowlist policy.
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
        live: HarnessConfig | None = None
        if provider is not None and type(provider) is not FakeProvider:
            from harness_engineering.vendor_providers import _validate_binding

            live = _validate_binding(provider, live_config, b)
        self._live_allowed = live is not None
        self._bind_live(provider, live, live_authorization, credentials)
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
        if telemetry is not None and type(telemetry) is not TelemetrySession:
            raise ContractValidationError("Bind an application-owned telemetry session.")
        self._telemetry = telemetry
        self._identity = WorkflowIdentity.model_validate(
            (WorkflowIdentity() if identity is None else identity).model_dump()
        )
        self._provider_alias = (
            "fake" if type(self._provider) is FakeProvider else self._provider._sdk
        )
        if ledger is not None:
            if type(ledger) is not FixtureLedger or self._live_allowed:
                raise ContractValidationError("Bind a fixture ledger only to offline execution.")
            p = ledger.policy
            if b.max_cost_usd is not None:
                if not isfinite(b.max_cost_usd):
                    raise ContractValidationError("Fixture cost configuration must be finite.")
                legacy_cap = int((Decimal(str(b.max_cost_usd)) * 1_000_000).to_integral_value(
                    rounding=ROUND_FLOOR,
                ))
                if p.cap_units > legacy_cap:
                    raise ContractValidationError("Fixture ledger exceeds the configured cost cap.")
            if identity is None:
                self._identity = WorkflowIdentity(workflow_id=p.workflow_id, thread_id=p.thread_id)
            if (p.workflow_id != self._identity.workflow_id
                    or p.thread_id != self._identity.thread_id
                    or p.tokens.step_count != len(action_ids)
                    or p.action_ids != action_ids
                    or p.tokens.input_per_call != b.max_context_tokens
                    or p.tokens.output_per_call != b.max_output_tokens
                    or p.tokens.workflow_attempts > b.max_provider_attempts
                    or p.tokens.attempts_per_step > b.max_retries_per_action + 1
                    or p.tariff.provider is not ProviderAlias(self._provider_alias)
                    or (self._provider_alias != "fake"
                        and self._provider._model != p.tariff.model)):
                raise ContractValidationError("Fixture ledger conflicts with provider bounds.")
            ledger.snapshot()
        self._ledger = ledger
        if telemetry is not None:
            if identity is None and ledger is None:
                self._identity = telemetry.identity
            elif self._identity != telemetry.identity:
                raise ContractValidationError("Usage, ledger and telemetry identity must agree.")
        if anomalies is not None and type(anomalies) is not AnomalyDetector:
            raise ContractValidationError("Bind an exact advisory anomaly detector.")
        if anomalies is not None:
            try:
                anomalies.bind_fixture(self._identity)
            except ValueError:
                raise ContractValidationError(
                    "Anomaly projection identity/evidence conflicts with provider accounting."
                ) from None
        self._anomalies = anomalies
        self._advisory_failures = 0
        self._usage_receipts: deque[UsageReceipt] = deque(maxlen=8)
        self._usage_channels: deque[tuple[UUID, UsageCapture]] = deque(maxlen=8)
        self._deadline = monotonic() + b.workflow_deadline_seconds
        self._attempts = 0
        self._actions = dict.fromkeys(action_ids, 0)
        self._slot = Lock()
        self._audit: deque[ProviderEvent] = deque(maxlen=128)

    def _bind_live(
        self,
        provider: object,
        live: HarnessConfig | None,
        authorization: object,
        credentials: object,
    ) -> None:
        """Bind live-only authorization, credential source and exposure accounting.

        Raises:
            ContractValidationError: If a live-only binding is supplied to an
                offline runtime, a live runtime lacks its policy's credential
                source, or the authorization mismatches, is outside its window,
                or cannot afford one fully bounded call.
        """
        self._authorization: LiveExecutionAuthorization | None = None
        self._credentials: CredentialSource | None = None
        self._live_cap = Decimal(0)
        self._live_exposure = Decimal(0)
        self._live_call_bound = Decimal(0)
        if live is None:
            if authorization is not None or credentials is not None:
                raise ContractValidationError(
                    "Live authorization and credentials bind only to a live runtime."
                )
            return
        if live.live is None or live.budget.max_cost_usd is None:
            raise ContractValidationError("Live runtime requires its validated live policy.")
        if (
            type(credentials) not in CREDENTIAL_SOURCE_TYPES
            or credentials.kind != live.live.credential_source  # type: ignore[union-attr]
        ):
            raise ContractValidationError(
                "Bind the trusted credential source named by the live policy."
            )
        self._credentials = credentials  # type: ignore[assignment]
        self._live_cap = Decimal(str(live.budget.max_cost_usd))
        if authorization is None:
            return  # Adapter readiness only: dispatch stays denied without authorization.
        if type(authorization) is not LiveExecutionAuthorization:
            raise ContractValidationError("Bind an exact human live-execution authorization.")
        now = datetime.now(UTC)
        if (
            authorization.provider != provider._sdk  # type: ignore[attr-defined]
            or authorization.model != provider._model  # type: ignore[attr-defined]
            or not now < authorization.expires_at <= now + MAX_AUTHORIZATION_WINDOW
        ):
            raise ContractValidationError(
                "Live authorization must cover this provider/model inside its window."
            )
        b = self._budget
        prompt_bound = b.max_context_tokens + LIVE_INPUT_OVERHEAD_TOKENS
        # Price the full prompt exposure at its published tier; never underprice.
        require_tariff_floor(authorization, prompt_bound)
        self._live_call_bound = authorization.worst_case_usd(prompt_bound, b.max_output_tokens)
        if self._live_call_bound > self._live_cap:
            raise ContractValidationError("Live budget cannot afford one fully bounded call.")
        self._authorization = authorization

    @property
    def evidence_class(self) -> EvidenceClass:
        """Return the strongest evidence this runtime can self-report.

        In-process execution never self-certifies live-provider evidence: that
        class is established only by a separately authorized, independently
        evidenced live exercise. Vendor adapters report adapter evidence.
        """
        if type(self._provider) is FakeProvider:
            return EvidenceClass.DETERMINISTIC
        return EvidenceClass.ADAPTER

    @property
    def live_exposure_usd(self) -> Decimal:
        """Return conservative live cost exposure, never verified billing."""
        return self._live_exposure

    @property
    def attempts(self) -> int:
        """Return measured consumed attempts, never a writable budget token."""
        return self._attempts

    @property
    def audit(self) -> tuple[ProviderEvent, ...]:
        """Return bounded sanitized observations without executable authority."""
        return tuple(self._audit)

    def generate(self, request: object, *, action_id: str = "model") -> ModelResult:
        """Observe caller-boundary latency without changing provider execution semantics.

        Telemetry captures no request, output, action string or exception payload.
        Worker completion after timeout never creates a second completion sample.
        """
        if self._telemetry is None:
            return self._generate_observed(request, action_id=action_id)
        return self._telemetry.call(
            Measurement.PROVIDER, lambda: self._generate_observed(request, action_id=action_id),
            classify=lambda _: Outcome.SUCCEEDED,
        )

    def _advisory(self, kind: GovernanceKind) -> None:
        if self._anomalies is not None:
            try:
                self._anomalies.observe(kind)
            except Exception:
                # Advisory event observation cannot change execution/authority.
                self._advisory_failures += 1

    @property
    def advisory_failures(self) -> int:
        """Count rule-observation failures without diagnostics or hidden retries."""
        return self._advisory_failures

    def _generate_observed(self, request: object, *, action_id: str) -> ModelResult:
        try:
            return self._generate(request, action_id=action_id)
        except AuthorityViolationError:
            self._advisory(GovernanceKind.DENIAL_BURST)
            raise

    @property
    def usage_receipts(self) -> tuple[UsageReceipt, ...]:
        """Return immutable bounded numeric claims, distinct from verified billing."""
        return tuple(self._usage_receipts)

    @property
    def late_usage_attempts(self) -> tuple[UUID, ...]:
        """Identify late receipt arrivals; they never rewrite caller evidence or exposure."""
        return tuple(attempt for attempt, channel in self._usage_channels if channel.late)

    def _generate(self, request: object, *, action_id: str = "model") -> ModelResult:
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
        charged = False
        completed = False
        finished = False
        reservation = None
        live_reserved = Decimal(0)
        context = None
        attempt_id = uuid4()
        failure_state = None
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
            context._max_output_bytes = b.output_byte_limit
            context._max_context_tokens = b.max_context_tokens
            context._live_allowed = self._live_allowed
            context._authorization = self._authorization
            context._credentials = self._credentials
            context._trace_context = current_trace()
            context.checkpoint()
            if self._attempts >= b.max_provider_attempts:
                raise BudgetExceededError("Workflow provider-attempt budget exhausted.")
            if self._actions[action_id] >= b.max_retries_per_action + 1:
                raise BudgetExceededError("Application action retry budget exhausted.")
            if (
                self._authorization is not None
                and self._live_exposure + self._live_call_bound > self._live_cap
            ):
                # Pre-dispatch cost gate: reserve the fully bounded worst case.
                raise BudgetExceededError("Live cost exposure would exceed the approved budget.")
            step_index = tuple(self._actions).index(action_id) + 1
            if self._ledger is not None:
                reservation = self._ledger.reserve(step_index)
                attempt_id = reservation.attempt_id
            self._attempts += 1
            self._actions[action_id] += 1
            charged = True
            if self._authorization is not None:
                live_reserved = self._live_call_bound
                self._live_exposure += live_reserved
            if self._actions[action_id] > 1:
                self._advisory(GovernanceKind.RETRY_BURST)
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
                    if _units(response.text) > b.output_byte_limit:
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

            def traced_invoke() -> None:
                with bind_trace(context.trace_context):
                    invoke()

            worker = Thread(target=traced_invoke, name="module-06-5-provider", daemon=True)
            worker.start()
            launched = True
            try:
                outcome = result.get(timeout=max(0, context._deadline - monotonic()))
                finished = True
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
            completed = True
            return outcome
        except ProviderTimeoutError:
            failure_state = UsageState.TIMEOUT
            raise
        except AuthorityViolationError:
            failure_state = (
                UsageState.CANCELLED if self._off_switch.is_active() else UsageState.UNAVAILABLE
            )
            raise
        finally:
            if not launched:
                self._slot.release()
            if charged and context is not None:
                fallback = failure_state or (
                    UsageState.TIMEOUT if context._cancelled.is_set()
                    else UsageState.CANCELLED if self._off_switch.is_active()
                    else UsageState.LOCAL if completed and self._provider_alias == "fake"
                    else UsageState.UNAVAILABLE
                )
                facts = context._usage.close(fallback)
                if live_reserved and self._authorization is not None:
                    if (finished or not launched) and not context._dispatched.is_set():
                        self._live_exposure -= live_reserved  # Provably never dispatched.
                    elif facts.state is UsageState.REPORTED:
                        self._live_exposure += self._authorization.worst_case_usd(
                            facts.input_tokens or 0, facts.output_tokens or 0,
                        ) - live_reserved
                    # Otherwise the worst-case reservation stays consumed.
                receipt = UsageReceipt(
                    workflow_id=self._identity.workflow_id, thread_id=self._identity.thread_id,
                    attempt_id=attempt_id, step_index=step_index, provider=self._provider_alias,
                    local_input_bytes=_units(value.prompt), usage=facts,
                )
                self._usage_receipts.append(receipt)
                self._usage_channels.append((attempt_id, context._usage))
                if self._ledger is not None and reservation is not None:
                    self._ledger.settle(reservation, facts)
                if not completed:
                    self._advisory(GovernanceKind.PROVIDER_FAILURE_BURST)


def _units(text: str) -> int:
    """Count UTF-8 bytes conservatively; this is not vendor tokenizer evidence."""
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ContractValidationError("Provider text must contain valid UTF-8.") from exc
