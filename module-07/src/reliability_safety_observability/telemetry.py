"""Bounded, non-authoritative local telemetry and a cooperative neutral sink seam.

Only application facts cross this boundary. Free text is omitted, not guessed
safe. Sinks receive immutable minimized JSON, never workflow objects or policy.
"""

import asyncio
import json
import math
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .domain import MAX_COUNTER, BudgetState, EvidenceClass, TelemetryRecord, UsageRecord
from .logging import _is_sensitive_key, _redact
from .reliability import RecoveryResult

Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Counter = Annotated[int, Field(ge=0, le=MAX_COUNTER)]


class Event(StrEnum):
    """Application event labels; untrusted text cannot supply a new label."""

    WORKFLOW = "workflow"
    ATTEMPT = "attempt"
    RECOVERY = "recovery"
    DECISION = "decision"
    EVALUATION = "evaluation"


class Component(StrEnum):
    """Safe operation/component labels, separate from raw operation names."""

    WORKFLOW = "workflow"
    RELIABILITY = "reliability"
    SAFETY = "safety"
    AUTHORIZATION = "authorization"
    TOOL = "tool"
    MODEL = "model"
    EVALUATION = "evaluation"


class Code(StrEnum):
    """Safe debugging codes aligned with application recovery outcomes."""

    SUCCESS = "success"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TRANSIENT = "transient"
    TERMINAL = "terminal"
    TIMEOUT = "timeout"
    TIMEOUT_UNRESOLVED = "timeout_unresolved"
    UNKNOWN = "unknown"
    TRANSIENT_EXHAUSTED = "transient_exhausted"
    TERMINAL_EXHAUSTED = "terminal_exhausted"
    TIMEOUT_EXHAUSTED = "timeout_exhausted"
    UNKNOWN_EXHAUSTED = "unknown_exhausted"
    AUTHORIZATION_DENIED = "authorization_denied"
    SAFETY_DENIED = "safety_denied"
    IDENTITY_DENIED = "identity_denied"
    PENDING = "pending"
    CONCURRENCY_EXHAUSTED = "concurrency_exhausted"
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    ATTEMPT_EXHAUSTED = "attempt_exhausted"
    TIME_EXHAUSTED = "time_exhausted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ACCOUNTING_EXHAUSTED = "accounting_exhausted"
    MALFORMED_RESULT = "malformed_result"
    EFFECT_UNCERTAIN = "effect_uncertain"
    INTERRUPTED = "interrupted"


def _code(value: object) -> Code:
    """Project only known application codes, without rendering arbitrary values."""
    if type(value) is str and len(value) <= 64:
        try:
            return Code(value)
        except ValueError:
            pass
    return Code.UNKNOWN


class CostBasis(StrEnum):
    """Provenance supplied by a trusted adapter, never inferred from zero defaults."""

    UNKNOWN = "unknown"
    FIXTURE = "fixture"
    SUPPORTED_USAGE = "supported_usage"


class Observation(BaseModel):
    """Immutable neutral envelope; this is evidence and confers no authority.

    Attributes:
        telemetry: Existing foundation schema, unchanged and never exported raw.
        action_id: Original application idempotency identity.
        event: Application event type.
        component: Safe application operation/stage label replacing raw text.
        cost_basis: Explicit availability of supported usage, unknown by default.
        source_evidence: Upstream evidence, distinct from boundary-test evidence.
        evaluation_id: Optional future evaluation join UUID, with no implied score.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    telemetry: TelemetryRecord = Field(repr=False)
    action_id: UUID
    event: Event = Event.WORKFLOW
    component: Component = Component.WORKFLOW
    cost_basis: CostBasis = CostBasis.UNKNOWN
    usage_available: bool = False
    source_evidence: EvidenceClass | None = None
    evaluation_id: UUID | None = None
    attempts: Counter = 0
    fallbacks: Counter = 0
    recovered: bool = False
    replayed: bool = False
    budget: BudgetState | None = None
    actual_cost_usd: Nonnegative | None = None
    overage_usd: Nonnegative = 0
    remaining_attempts: Counter | None = None
    remaining_seconds: Nonnegative | None = None
    history: tuple[Code, ...] = Field(default=(), max_length=1000)


def from_recovery(
    result: RecoveryResult,
    *,
    span_id: UUID | None = None,
    cost_basis: CostBasis = CostBasis.UNKNOWN,
    usage_available: bool = False,
) -> Observation:
    """Project Story 3 without mutating state, copying output or executing work.

    Args:
        result: Application-owned local recovery result, not a provider payload.
        span_id: Optional deterministic observation identity.
        cost_basis: Trusted knowledge of usage availability; defaults to unknown.
        usage_available: Whether token counts are known even if monetary cost is not.

    Returns:
        Correlated whole-execution evidence; original source labels are preserved.
    """
    state = result.state
    return Observation(
        telemetry=TelemetryRecord(
            workflow_id=state.identity.workflow_id,
            trace_id=state.identity.trace_id,
            span_id=span_id or uuid4(),
            operation=Component.RELIABILITY.value,
            status=_code(result.classification).value,
            duration_ms=result.elapsed_seconds * 1000,
            retry_attempt=state.retry_attempt,
            fallback_used=state.fallback_used,
            safety_decision=state.safety.decision if state.safety else None,
            authorization_decision=state.authorization.decision if state.authorization else None,
            usage=state.usage,
            error_classification=(
                None if result.classification == "success" else _code(result.classification).value
            ),
            evidence_class=EvidenceClass.DETERMINISTIC_FIXTURE,
        ),
        action_id=state.idempotency_key,
        event=Event.RECOVERY,
        component=Component.RELIABILITY,
        cost_basis=cost_basis,
        usage_available=usage_available,
        source_evidence=state.evidence_class,
        attempts=result.attempts,
        fallbacks=result.fallbacks,
        recovered=bool(result.reliability and result.reliability.recovered),
        replayed=result.replayed,
        budget=state.budget,
        actual_cost_usd=result.actual_cost_usd,
        overage_usd=result.overage_usd,
        remaining_attempts=result.remaining_attempts,
        remaining_seconds=result.remaining_seconds,
        history=tuple(_code(item) for item in result.history[:1000]),
    )


def elapsed_ms(start_seconds: float, *, clock: Callable[[], float]) -> float:
    """Measure a finite nonnegative elapsed interval using an injected clock.

    Args:
        start_seconds: Start from the same monotonic clock, in seconds.
        clock: Trusted monotonic clock, controllable in deterministic tests.

    Returns:
        Elapsed milliseconds.

    Raises:
        ValueError: If the clock interval is negative or non-finite.
    """
    end = clock()
    duration = (end - start_seconds) * 1000
    if not all(math.isfinite(x) for x in (start_seconds, end, duration)) or duration < 0:
        raise ValueError("Telemetry timing requires a finite nonnegative clock interval.")
    return duration


class TelemetryLimits(BaseModel):
    """Finite application configuration; full pipelines refuse more observations."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_events: int = Field(default=256, ge=1, le=4096)
    max_bytes: int = Field(default=16_384, ge=512, le=65_536)
    max_nodes: int = Field(default=128, ge=1, le=1024)
    max_depth: int = Field(default=6, ge=1, le=16)
    sink_timeout_seconds: float = Field(default=0.1, gt=0, le=5, allow_inf_nan=False)


def minimize(value: object, limits: TelemetryLimits | None = None) -> object:
    """Bound traversal and minimize optional untrusted diagnostic metadata.

    Args:
        value: Untrusted diagnostic object. No arbitrary str/repr or iteration.
        limits: Trusted finite traversal limits.

    Returns:
        JSON-safe data: raw strings/unknown keys omitted, secrets redacted.
        Useful booleans, finite numbers and UUIDs survive under fixed safe keys.
    """
    policy = limits or TelemetryLimits()
    remaining = policy.max_nodes
    safe_keys = {"details", "nested", "items", "count", "safe", "value"}

    def visit(item: object, depth: int) -> object:
        nonlocal remaining
        if remaining <= 0 or depth > policy.max_depth:
            return "[TRUNCATED]"
        remaining -= 1
        if isinstance(item, SecretStr):
            return "[REDACTED]"
        if type(item) is dict:
            output: dict[str, object] = {}
            for key, child in item.items():
                if remaining <= 0:
                    output["[TRUNCATED]"] = True
                    break
                remaining -= 1
                if type(key) is not str:
                    output["[UNSUPPORTED_TYPE]"] = "[UNSUPPORTED_TYPE]"
                elif len(key) > 128:
                    output["[OMITTED_FIELD]"] = "[OMITTED]"
                elif _is_sensitive_key(key):
                    output["[REDACTED_FIELD]"] = "[REDACTED]"
                elif key in safe_keys:
                    output[key] = visit(child, depth + 1)
                else:
                    output["[OMITTED_FIELD]"] = "[OMITTED]"
            return output
        if type(item) in (list, tuple, set, frozenset):
            output_list: list[object] = []
            for child in item:
                if remaining <= 0:
                    output_list.append("[TRUNCATED]")
                    break
                output_list.append(visit(child, depth + 1))
            return output_list
        if type(item) is UUID:
            return str(item)
        if type(item) is str:
            return "[OMITTED]"
        if item is None or type(item) is bool:
            return item
        if type(item) is int:
            return item if abs(item) <= MAX_COUNTER else "[TRUNCATED]"
        if type(item) is float:
            return item if math.isfinite(item) else "[UNSUPPORTED_TYPE]"
        return "[UNSUPPORTED_TYPE]"

    return visit(value, 0)


def _project(observation: Observation) -> dict[str, object]:
    """Project schema fields only, using names compatible with the unchanged redactor."""
    t = observation.telemetry
    if t.evidence_class not in {
        EvidenceClass.DETERMINISTIC_FIXTURE, EvidenceClass.MOCKED_PROVIDER_CONTRACT
    }:
        raise ValueError("Story 4 boundary requires deterministic or mocked evidence.")
    if observation.source_evidence in {EvidenceClass.LIVE_VENDOR, EvidenceClass.LIVE_MODEL}:
        raise ValueError("Story 4 cannot claim live upstream evidence.")
    known = observation.cost_basis is not CostBasis.UNKNOWN
    units_known = known or observation.usage_available
    return {
        "span_id": str(t.span_id),
        "action_id": str(observation.action_id),
        "operation": observation.component.value,
        "status": _code(t.status).value,
        "duration_ms": t.duration_ms,
        "retry_attempt": t.retry_attempt,
        "fallback_used": t.fallback_used,
        "safety_outcome": t.safety_decision.value if t.safety_decision else None,
        "permission_outcome": t.authorization_decision.value if t.authorization_decision else None,
        "usage": {
            "input_units": t.usage.input_tokens if units_known else None,
            "output_units": t.usage.output_tokens if units_known else None,
            "cost_usd": t.usage.cost_usd if known else None,
            "basis": observation.cost_basis.value,
            "unit": "model_tokens",
        },
        "error_classification": _code(t.error_classification).value
        if t.error_classification else None,
        "evidence_class": t.evidence_class.value,
        "source_evidence": (
            observation.source_evidence.value if observation.source_evidence else None
        ),
        "evaluation_id": str(observation.evaluation_id) if observation.evaluation_id else None,
        "attempts": observation.attempts,
        "fallbacks": observation.fallbacks,
        "recovered": observation.recovered,
        "replayed": observation.replayed,
        "budget": observation.budget.model_dump() if observation.budget else None,
        "actual_cost_usd": observation.actual_cost_usd if known else None,
        "overage_usd": observation.overage_usd,
        "remaining_attempts": observation.remaining_attempts,
        "remaining_seconds": observation.remaining_seconds,
        "history": [code.value for code in observation.history],
        # Historical usage is displayed on replay, but never a new consumption delta.
        "new_cost_usd": 0.0 if observation.replayed else (
            (observation.actual_cost_usd if observation.actual_cost_usd is not None
             else t.usage.cost_usd) if known else None
        ),
    }


def _validate(observation: Observation) -> Observation:
    """Revalidate schema facts without serialization warnings rendering unsafe objects."""
    if type(observation) is not Observation or type(observation.telemetry) is not TelemetryRecord:
        raise ValueError("Provide a neutral Observation and TelemetryRecord.")
    t = observation.telemetry
    if type(t.usage) is not UsageRecord:
        raise ValueError("Provide typed usage facts.")
    if type(observation.history) is not tuple or len(observation.history) > 1000:
        raise ValueError("Provide bounded application history.")
    values = {name: getattr(observation, name) for name in Observation.model_fields}
    telemetry = {name: getattr(t, name) for name in TelemetryRecord.model_fields}
    telemetry["usage"] = {name: getattr(t.usage, name) for name in UsageRecord.model_fields}
    values["telemetry"] = telemetry
    if observation.budget is not None:
        if type(observation.budget) is not BudgetState:
            raise ValueError("Provide typed budget facts.")
        values["budget"] = {
            name: getattr(observation.budget, name) for name in BudgetState.model_fields
        }
    return Observation.model_validate(values)


class NeutralSink(Protocol):
    """Trusted cooperative async adapter; replies are ignored and grant no authority.

    Adapters must yield, bound their I/O and honor cancellation. Blocking callbacks
    and forcibly stopping remote effects are unsupported, as in Story 3.
    """

    async def send(self, record: str) -> object:
        """Accept one immutable minimized JSON record; never receive domain state."""
        ...


class Delivery(StrEnum):
    """Observation outcomes, never authoritative workflow outcomes."""

    LOCAL = "local"
    EXPORTED = "exported"
    EXPORT_FAILED = "export_failed"
    INVALID = "invalid_observation"
    FULL = "observation_capacity_exhausted"
    BUSY = "observation_busy"


def _consume(task: asyncio.Task[object]) -> None:
    """Retrieve late sink exceptions without recording their unsafe content."""
    if not task.cancelled():
        task.exception()


class TelemetryPipeline:
    """Bounded local records plus optional neutral sinks; no workflow references.

    Args:
        limits: Finite event, payload and cooperative sink bounds.
        exporter: Optional trusted fake/neutral adapter; no vendor is configured.
        local_sink: Optional independent local record adapter.
    """

    def __init__(
        self, *, limits: TelemetryLimits | None = None,
        exporter: NeutralSink | None = None, local_sink: NeutralSink | None = None,
    ) -> None:
        self.limits = limits or TelemetryLimits()
        self._exporter = exporter
        self._local_sink = local_sink
        self._records: list[str] = []
        self._count = 0
        self._busy = False
        self._pending: set[asyncio.Task[object]] = set()

    @property
    def records(self) -> tuple[str, ...]:
        """Return immutable bounded local evidence, including export failures."""
        return tuple(self._records)

    async def _send(self, sink: NeutralSink, record: str) -> bool:
        """Bound a cooperative send, discard replies/errors, retain unresolved protection."""
        task: asyncio.Task[object] | None = None
        try:
            task = asyncio.create_task(sink.send(record))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
            task.add_done_callback(_consume)
            done, _ = await asyncio.wait({task}, timeout=self.limits.sink_timeout_seconds)
            if not done:
                task.cancel()
                return False
            if task.cancelled():
                return False
            task.result()
            return True
        except Exception:
            # Explicit non-authoritative sink boundary; never expose exception text.
            return False
        finally:
            if task is not None and not task.done():
                task.cancel()

    async def emit(self, observation: Observation, *, metadata: object = None) -> Delivery:
        """Emit once without changing workflow results or interpreting sink responses.

        Args:
            observation: Typed application observation; not an authorization grant.
            metadata: Optional untrusted debugging content, aggressively minimized.

        Returns:
            Bounded observation status. Invalid input never falls back to raw export.
            Cancellation propagates to the caller without altering workflow state.
        """
        if self._busy or any(not task.done() for task in self._pending):
            return Delivery.BUSY
        if self._count >= self.limits.max_events:
            return Delivery.FULL
        self._count += 1
        self._busy = True
        try:
            try:
                # Revalidate even model_construct/model_copy inputs before exporting facts.
                observation = _validate(observation)
                fields = _project(observation)
                fields["details"] = minimize(metadata, self.limits)
                payload = {
                    "event": observation.event.value,
                    "workflow_id": str(observation.telemetry.workflow_id),
                    "trace_id": str(observation.telemetry.trace_id),
                    "fields": _redact(fields),
                }
                record = json.dumps(payload, sort_keys=True, allow_nan=False)
                # Reserve space for the independent local delivery-status field.
                if len(record.encode("utf-8")) + 64 > self.limits.max_bytes:
                    return Delivery.INVALID
            except Exception:
                # Serialization/redaction boundary: no raw-input fallback or exception chain.
                return Delivery.INVALID
            status = Delivery.LOCAL
            if self._exporter:
                status = Delivery.EXPORTED if await self._send(self._exporter, record) else (
                    Delivery.EXPORT_FAILED
                )
            # Independent local evidence survives primary and secondary sink failure.
            payload["delivery"] = status.value
            local = json.dumps(payload, sort_keys=True, allow_nan=False)
            self._records.append(local)
            if self._local_sink:
                await self._send(self._local_sink, local)
            return status
        finally:
            self._busy = False
