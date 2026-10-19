"""Story 5 Langfuse adapter: minimized neutral records to Langfuse, never authority.

Data path: ``TelemetryPipeline`` (Story 4 validation, minimization, redaction and
size bounds) -> one minimized JSON record -> ``LangfuseSink.send`` -> strict
parsing into an SDK-free ``LangfuseExportSpec`` -> ``LangfuseTransport``.

This is the only Module 7 file that imports the Langfuse SDK, and it does so
lazily inside ``LangfuseSdkTransport``. The public LangfuseAPI uses an
application-owned HTTP client: no OpenTelemetry provider is created or
registered, and foreign spans never reach Langfuse. Everything the
SDK or Langfuse returns is untrusted and discarded except the bounded
identifier comparison in opt-in live verification.
"""

import asyncio
import contextlib
import json
import logging
import math
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from .config import RuntimeSettings
from .domain import (
    MAX_COUNTER,
    BudgetState,
    Decision,
    EvidenceClass,
    TelemetryRecord,
    UsageRecord,
    WorkflowIdentity,
)
from .errors import ConfigurationError, ModuleSevenError
from .langfuse_config import LangfuseSettings, require_live_langfuse
from .telemetry import (
    Code,
    Component,
    CostBasis,
    Delivery,
    Event,
    Observation,
    TelemetryLimits,
    TelemetryPipeline,
)

# Presentation-only vendor severity. The application code in metadata remains the
# classification of record. Every Code member is listed explicitly; a new member
# without an entry is refused rather than silently mapped.
SEVERITY: dict[Code, str] = {
    Code.SUCCESS: "DEFAULT",
    Code.SUCCEEDED: "DEFAULT",
    Code.DENIED: "WARNING",
    Code.AUTHORIZATION_DENIED: "WARNING",
    Code.SAFETY_DENIED: "WARNING",
    Code.IDENTITY_DENIED: "WARNING",
    Code.PENDING: "WARNING",
    Code.CANCELLED: "WARNING",
    Code.FAILED: "ERROR",
    Code.TRANSIENT: "ERROR",
    Code.TERMINAL: "ERROR",
    Code.TIMEOUT: "ERROR",
    Code.TIMEOUT_UNRESOLVED: "ERROR",
    Code.UNKNOWN: "ERROR",
    Code.TRANSIENT_EXHAUSTED: "ERROR",
    Code.TERMINAL_EXHAUSTED: "ERROR",
    Code.TIMEOUT_EXHAUSTED: "ERROR",
    Code.UNKNOWN_EXHAUSTED: "ERROR",
    Code.CONCURRENCY_EXHAUSTED: "ERROR",
    Code.CAPACITY_EXHAUSTED: "ERROR",
    Code.ATTEMPT_EXHAUSTED: "ERROR",
    Code.TIME_EXHAUSTED: "ERROR",
    Code.BUDGET_EXHAUSTED: "ERROR",
    Code.ACCOUNTING_EXHAUSTED: "ERROR",
    Code.MALFORMED_RESULT: "ERROR",
    Code.EFFECT_UNCERTAIN: "ERROR",
    Code.INTERRUPTED: "ERROR",
}

TIMING_ANCHOR = "export_time"
_RECORD_EVIDENCE = frozenset(
    {EvidenceClass.DETERMINISTIC_FIXTURE.value, EvidenceClass.MOCKED_PROVIDER_CONTRACT.value}
)
_SOURCE_EVIDENCE = frozenset(
    {
        EvidenceClass.DETERMINISTIC_FIXTURE.value,
        EvidenceClass.SIMULATED_FAILURE.value,
        EvidenceClass.MOCKED_PROVIDER_CONTRACT.value,
    }
)
_KNOWN_BASES = frozenset({CostBasis.FIXTURE.value, CostBasis.SUPPORTED_USAGE.value})
_DETAIL_KEYS = frozenset({"details", "nested", "items", "count", "safe", "value"})
_MARKER_KEYS = frozenset(
    {"[TRUNCATED]", "[UNSUPPORTED_TYPE]", "[OMITTED_FIELD]", "[REDACTED_FIELD]"}
)
_MARKERS = frozenset({"[REDACTED]", "[OMITTED]", "[TRUNCATED]", "[UNSUPPORTED_TYPE]"})
_MAX_DETAIL_DEPTH = 17
_MAX_DETAIL_NODES = 2048


class RefusalReason(StrEnum):
    """Fixed, secret-free reasons a record or call was not exported."""

    MALFORMED = "malformed_record"
    OVERSIZED = "oversized_record"
    CAPACITY = "observation_capacity_exhausted"
    CLOSED = "adapter_closed"
    TRANSPORT = "transport_rejected"


class LangfuseExportError(ModuleSevenError):
    """Fixed-message export refusal; never carries vendor or record content."""

    def __init__(self, reason: RefusalReason) -> None:
        """Create a refusal.

        Args:
            reason: Fixed refusal reason.
        """
        super().__init__(f"Langfuse export refused: {reason.value}")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class LangfuseExportSpec:
    """Immutable SDK-free export specification built only from primitives.

    Attributes:
        trace_id: 32 lowercase hex characters derived from the application trace UUID.
        name: Fixed ``component.event`` observation name.
        observation_type: ``generation`` when native usage/cost is sent, else ``span``.
        level: Presentation severity from ``SEVERITY``.
        status_message: Verbatim application status code.
        start_time_ns: Export-time anchor minus the unchanged duration.
        end_time_ns: Export-time anchor.
        metadata: Flattened metadata; values are str/int or canonical JSON text.
        trace_metadata: Workflow and trace correlation for the Langfuse trace.
        usage_details: Native token usage, when known and not replayed.
        cost_details: Native cost from ``new_cost_usd`` when the basis is known.
    """

    trace_id: str
    name: str
    observation_type: str
    level: str
    status_message: str
    start_time_ns: int
    end_time_ns: int
    metadata: tuple[tuple[str, str | int], ...]
    trace_metadata: tuple[tuple[str, str], ...]
    usage_details: tuple[tuple[str, int], ...] | None
    cost_details: tuple[tuple[str, float], ...] | None


def _malformed() -> LangfuseExportError:
    return LangfuseExportError(RefusalReason.MALFORMED)


def _reject_constant(_: str) -> object:
    raise ValueError("non-finite JSON constant")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _uuid(value: object) -> str:
    if type(value) is not str or len(value) != 36:
        raise _malformed()
    try:
        parsed = UUID(value)
    except ValueError:
        raise _malformed() from None
    if str(parsed) != value:
        raise _malformed()
    return value


def _optional_uuid(value: object) -> str | None:
    return None if value is None else _uuid(value)


def _counter(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        raise _malformed()
    return value


def _optional_counter(value: object) -> int | None:
    return None if value is None else _counter(value)


def _amount(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise _malformed()
    return float(value)


def _optional_amount(value: object) -> float | None:
    return None if value is None else _amount(value)


def _flag(value: object) -> bool:
    if type(value) is not bool:
        raise _malformed()
    return value


def _member(value: object, allowed: Iterable[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise _malformed()
    return value


def _optional_member(value: object, allowed: Iterable[str]) -> str | None:
    return None if value is None else _member(value, allowed)


_CODES = frozenset(code.value for code in Code)
_DECISIONS = frozenset(decision.value for decision in Decision)


def _details(value: object) -> object:
    """Accept only the shape Story 4 ``minimize`` produces; anything else is refused."""
    remaining = _MAX_DETAIL_NODES

    def visit(item: object, depth: int) -> object:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > _MAX_DETAIL_DEPTH:
            raise _malformed()
        if item is None or type(item) is bool:
            return item
        if type(item) is int:
            if abs(item) > MAX_COUNTER:
                raise _malformed()
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise _malformed()
            return item
        if type(item) is str:
            return item if item in _MARKERS else _uuid(item)
        if type(item) is list:
            return [visit(child, depth + 1) for child in item]
        if type(item) is dict:
            output: dict[str, object] = {}
            for key, child in item.items():
                if key not in _DETAIL_KEYS and key not in _MARKER_KEYS:
                    raise _malformed()
                output[key] = visit(child, depth + 1)
            return output
        raise _malformed()

    return visit(value, 0)


def _usage(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "input_units", "output_units", "cost_usd", "basis", "unit",
    }:
        raise _malformed()
    basis = _member(value["basis"], {basis.value for basis in CostBasis})
    usage = {
        "input_units": _optional_counter(value["input_units"]),
        "output_units": _optional_counter(value["output_units"]),
        "cost_usd": _optional_amount(value["cost_usd"]),
        "basis": basis,
        "unit": _member(value["unit"], {"model_tokens"}),
    }
    if basis not in _KNOWN_BASES and usage["cost_usd"] is not None:
        raise _malformed()
    return usage


def _budget(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"cost_limit_usd", "cost_used_usd"}:
        raise _malformed()
    return {key: _amount(value[key]) for key in ("cost_limit_usd", "cost_used_usd")}


def _canonical(value: object) -> str | int:
    if type(value) is str or type(value) is int:
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


_REQUIRED_FIELDS = frozenset(
    {
        "span_id", "action_id", "operation", "status", "duration_ms", "retry_attempt",
        "fallback_used", "safety_outcome", "permission_outcome", "usage",
        "error_classification", "evidence_class", "source_evidence", "evaluation_id",
        "attempts", "fallbacks", "recovered", "replayed", "budget", "actual_cost_usd",
        "overage_usd", "remaining_attempts", "remaining_seconds", "history", "new_cost_usd",
        "details",
    }
)


def to_export_spec(
    record: str, *, max_record_bytes: int, clock_ns: Callable[[], int]
) -> LangfuseExportSpec:
    """Strictly parse one minimized neutral record into an export specification.

    Unknown fields are dropped. Missing, mistyped, non-finite, forged-vocabulary or
    oversized content refuses the whole record; nothing is partially sent.

    Args:
        record: Minimized JSON produced by ``TelemetryPipeline``.
        max_record_bytes: Admission bound for the record.
        clock_ns: Trusted clock in nanoseconds used only to anchor placement.

    Returns:
        The immutable export specification.

    Raises:
        LangfuseExportError: With a fixed reason for any refused record.
    """
    if type(record) is not str:
        raise _malformed()
    if len(record.encode("utf-8")) > max_record_bytes:
        raise LangfuseExportError(RefusalReason.OVERSIZED)
    try:
        payload = json.loads(
            record, parse_constant=_reject_constant, object_pairs_hook=_unique_object
        )
    except (ValueError, RecursionError):
        payload = None
    if type(payload) is not dict or type(payload.get("fields")) is not dict:
        raise _malformed()
    fields: dict[str, Any] = payload["fields"]
    if not set(fields) >= _REQUIRED_FIELDS:
        raise _malformed()

    workflow_id = _uuid(payload.get("workflow_id"))
    trace_uuid = _uuid(payload.get("trace_id"))
    if UUID(trace_uuid).int == 0:
        raise _malformed()  # An all-zero OpenTelemetry trace ID is invalid.
    event = _member(payload.get("event"), {item.value for item in Event})
    component = _member(fields["operation"], {item.value for item in Component})
    status = Code(_member(fields["status"], _CODES))
    if status not in SEVERITY:
        raise _malformed()
    error = _optional_member(fields["error_classification"], _CODES)
    history = fields["history"]
    if type(history) is not list or len(history) > 1000:
        raise _malformed()
    history = [_member(item, _CODES) for item in history]
    duration_ms = _amount(fields["duration_ms"])
    usage = _usage(fields["usage"])
    replayed = _flag(fields["replayed"])
    new_cost = _optional_amount(fields["new_cost_usd"])

    metadata: dict[str, object] = {
        "workflow_id": workflow_id,
        "trace_id": trace_uuid,
        "span_id": _uuid(fields["span_id"]),
        "action_id": _uuid(fields["action_id"]),
        "event": event,
        "component": component,
        "status": status.value,
        "error_classification": error,
        "history": history,
        "retry_attempt": _counter(fields["retry_attempt"]),
        "attempts": _counter(fields["attempts"]),
        "fallback_used": _flag(fields["fallback_used"]),
        "fallbacks": _counter(fields["fallbacks"]),
        "recovered": _flag(fields["recovered"]),
        "replayed": replayed,
        "remaining_attempts": _optional_counter(fields["remaining_attempts"]),
        "remaining_seconds": _optional_amount(fields["remaining_seconds"]),
        "permission_outcome": _optional_member(fields["permission_outcome"], _DECISIONS),
        "safety_outcome": _optional_member(fields["safety_outcome"], _DECISIONS),
        "evidence_class": _member(fields["evidence_class"], _RECORD_EVIDENCE),
        "source_evidence": _optional_member(fields["source_evidence"], _SOURCE_EVIDENCE),
        "evaluation_id": _optional_uuid(fields["evaluation_id"]),
        "duration_ms": duration_ms,
        "timing_anchor": TIMING_ANCHOR,
        "cost_basis": usage["basis"],
        "usage": usage,
        "usage_scope": "historical" if replayed else "current",
        "budget": _budget(fields["budget"]),
        "actual_cost_usd": _optional_amount(fields["actual_cost_usd"]),
        "overage_usd": _amount(fields["overage_usd"]),
        "new_cost_usd": new_cost,
        "details": _details(fields["details"]),
    }

    anchor = clock_ns()
    duration_ns = round(duration_ms * 1_000_000)
    if type(anchor) is not int or anchor < duration_ns:
        raise _malformed()

    usage_details: tuple[tuple[str, int], ...] | None = None
    if not replayed:
        known_units = tuple(
            (name, value)
            for name, value in (("input", usage["input_units"]), ("output", usage["output_units"]))
            if type(value) is int
        )
        usage_details = known_units or None
    cost_details: tuple[tuple[str, float], ...] | None = None
    if usage["basis"] in _KNOWN_BASES and new_cost is not None:
        cost_details = (("total", new_cost),)
    native = usage_details is not None or cost_details is not None

    return LangfuseExportSpec(
        trace_id=UUID(trace_uuid).hex,
        name=f"{component}.{event}",
        observation_type="generation" if native else "span",
        level=SEVERITY[status],
        status_message=status.value,
        start_time_ns=anchor - duration_ns,
        end_time_ns=anchor,
        metadata=tuple(
            (key, _canonical(value)) for key, value in metadata.items() if value is not None
        ),
        trace_metadata=(("workflow_id", workflow_id), ("trace_id", trace_uuid)),
        usage_details=usage_details,
        cost_details=cost_details,
    )


class LangfuseTransport(Protocol):
    """Trusted application seam between export specifications and the SDK.

    ``submit`` must not block or perform network I/O. ``flush`` and ``close`` may
    block; the sink runs them off the event loop under a bounded wait.
    """

    evidence_class: EvidenceClass | None

    def submit(self, spec: LangfuseExportSpec) -> None:
        """Hand one specification to the export queue without network I/O."""
        ...

    def flush(self) -> bool:
        """Export queued observations; return whether every batch succeeded."""
        ...

    def close(self) -> bool:
        """Flush, then stop transport-owned background work; return success."""
        ...


class LifecycleState(StrEnum):
    """Secret-free adapter states; observation outcomes, never workflow outcomes."""

    ACTIVE = "active"
    FLUSHED = "flushed"
    FLUSH_FAILED = "flush_failed"
    FLUSH_TIMEOUT = "flush_timeout"
    BUSY = "lifecycle_busy"
    CLOSED = "closed"
    CLOSE_FAILED = "close_failed"
    CLOSE_TIMEOUT = "close_timeout"


@dataclass(frozen=True, slots=True)
class LangfuseExportStatus:
    """Bounded local export evidence with counters but no content.

    Attributes:
        state: Last lifecycle state.
        accepted: Specifications handed to the transport (not confirmed ingestion).
        refused: Records refused before the transport.
        failed: Specifications the transport rejected at submission.
        evidence_class: mocked_provider_contract for in-process transports; None
            for a network transport whose ingestion is unconfirmed.
    """

    state: LifecycleState
    accepted: int
    refused: int
    failed: int
    evidence_class: EvidenceClass | None


_OPERATIONS: dict[int, threading.Thread] = {}
_OPERATIONS_LOCK = threading.Lock()


def _operation_busy(owner: object) -> bool:
    with _OPERATIONS_LOCK:
        return id(owner) in _OPERATIONS


async def _run_bounded[T](
    call: Callable[[], T], timeout: float, *, owner: object
) -> tuple[str, T | None, threading.Thread]:
    """Run a blocking call on a daemon thread and wait for at most ``timeout``.

    Returns:
        ("ok", value, thread), ("failed", None, thread), ("busy", None, thread)
        or ("timeout", None, thread). Ownership is registered before awaiting;
        timeout and cancellation never kill or unregister the underlying call.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[tuple[str, T | None]] = loop.create_future()

    def deliver(result: tuple[str, T | None]) -> None:
        if not future.done():
            future.set_result(result)

    def worker() -> None:
        result: tuple[str, T | None]
        try:
            result = ("ok", call())
        except Exception:
            # Vendor lifecycle boundary: failure is recorded without its text.
            result = ("failed", None)
        # The closure retains owner until completion, preventing identity reuse.
        with _OPERATIONS_LOCK:
            _OPERATIONS.pop(id(owner), None)
        # A closed loop means the caller already stopped waiting.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(deliver, result)

    thread = threading.Thread(target=worker, name="module7-langfuse-lifecycle", daemon=True)
    with _OPERATIONS_LOCK:
        if id(owner) in _OPERATIONS:
            return "busy", None, _OPERATIONS[id(owner)]
        _OPERATIONS[id(owner)] = thread
        try:
            thread.start()
        except RuntimeError:
            _OPERATIONS.pop(id(owner), None)
            return "failed", None, thread
    try:
        outcome, value = await asyncio.wait_for(asyncio.shield(future), timeout)
    except TimeoutError:
        return "timeout", None, thread
    return outcome, value, thread


class LangfuseSink:
    """``NeutralSink`` that maps minimized records into Langfuse specifications.

    Its only data ingress is ``send(record: str)`` from ``TelemetryPipeline``.
    Replies, SDK return values and vendor content are never interpreted. The sink
    never emits into the telemetry pipeline or logger about its own failures.

    Args:
        transport: Trusted transport (SDK-backed or deterministic fake).
        settings: Validated bounds; credentials are not read here.
        clock_ns: Trusted nanosecond clock used only to anchor placement.
    """

    def __init__(
        self,
        transport: LangfuseTransport,
        *,
        settings: LangfuseSettings | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        bounds = settings or LangfuseSettings()
        self._transport = transport
        self._max_record_bytes = bounds.max_record_bytes
        self._max_observations = bounds.max_observations
        self._lifecycle_timeout = bounds.lifecycle_timeout_seconds
        self._clock_ns = clock_ns
        self._state = LifecycleState.ACTIVE
        self._accepted = 0
        self._refused = 0
        self._failed = 0
        self._closed = False
        self._close_started = False
        self._running = False

    @property
    def status(self) -> LangfuseExportStatus:
        """Return a secret-free snapshot of local export evidence."""
        return LangfuseExportStatus(
            state=self._state,
            accepted=self._accepted,
            refused=self._refused,
            failed=self._failed,
            evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
        )

    async def send(self, record: str) -> None:
        """Map and submit one record; refusals raise and become ``export_failed``.

        Args:
            record: Minimized JSON from ``TelemetryPipeline``.

        Raises:
            LangfuseExportError: Fixed-reason refusal without a chained cause.
        """
        refusal: RefusalReason | None = None
        spec: LangfuseExportSpec | None = None
        if self._closed:
            refusal = RefusalReason.CLOSED
        elif _operation_busy(self._transport):
            refusal = RefusalReason.TRANSPORT
        elif self._accepted >= self._max_observations:
            refusal = RefusalReason.CAPACITY
        else:
            try:
                spec = to_export_spec(
                    record, max_record_bytes=self._max_record_bytes, clock_ns=self._clock_ns
                )
            except LangfuseExportError as exc:
                refusal = exc.reason
        if refusal is not None or spec is None:
            self._refused += 1
            raise LangfuseExportError(refusal or RefusalReason.MALFORMED)

        submitted = True
        try:
            self._transport.submit(spec)
        except Exception:
            # Transport boundary: vendor errors are counted, never rendered.
            submitted = False
        if not submitted:
            self._failed += 1
            raise LangfuseExportError(RefusalReason.TRANSPORT)
        self._accepted += 1

    def _busy(self) -> bool:
        return self._running or _operation_busy(self._transport)

    async def _run(
        self, call: Callable[[], bool], ok: LifecycleState, failed: LifecycleState,
        timed_out: LifecycleState,
    ) -> LangfuseExportStatus:
        self._running = True
        try:
            outcome, value, _ = await _run_bounded(
                call, self._lifecycle_timeout, owner=self._transport)
        except asyncio.CancelledError:
            self._state = timed_out
            raise
        finally:
            self._running = False
        if outcome == "timeout":
            self._state = timed_out
        elif outcome == "busy":
            self._state = LifecycleState.BUSY
        elif outcome == "ok" and value is True:
            self._state = ok
        else:
            self._state = failed
        return self.status

    async def flush(self) -> LangfuseExportStatus:
        """Flush within the configured bound; no retry is attempted.

        Returns:
            Status: flushed, flush_failed, flush_timeout or lifecycle_busy.
        """
        if self._closed:
            return self.status
        if self._busy():
            self._state = LifecycleState.BUSY
            return self.status
        return await self._run(
            self._transport.flush, LifecycleState.FLUSHED, LifecycleState.FLUSH_FAILED,
            LifecycleState.FLUSH_TIMEOUT,
        )

    async def close(self) -> LangfuseExportStatus:
        """Refuse further sends and close the transport at most once, bounded.

        Returns:
            Status: closed, close_failed, close_timeout or lifecycle_busy.
        """
        self._closed = True
        if self._busy():
            self._state = LifecycleState.BUSY
            return self.status
        if self._close_started:
            if self._state is LifecycleState.BUSY:
                self._state = LifecycleState.CLOSE_TIMEOUT
            return self.status
        self._close_started = True
        return await self._run(
            self._transport.close, LifecycleState.CLOSED, LifecycleState.CLOSE_FAILED,
            LifecycleState.CLOSE_TIMEOUT,
        )


class _SecretLogFilter(logging.Filter):
    """Replace configured credential values in SDK log records; drop tracebacks."""

    def __init__(self, values: Iterable[str]) -> None:
        super().__init__()
        self._values = tuple(value for value in values if value)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # Unformattable third-party log record: keep only a fixed message.
            message = "Langfuse SDK log record could not be formatted safely."
        for value in self._values:
            message = message.replace(value, "[REDACTED]")
        record.msg, record.args = message, None
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True


class LangfuseSdkTransport:
    """Public LangfuseAPI OTLP integration with an explicitly owned HTTP client.

    submit only queues bounded specifications. Public API calls run in the sink's
    tracked blocking-operation lane; construction starts no SDK/provider worker.
    Injected HTTP transports are deterministic testing seams, never live evidence.
    """

    evidence_class = EvidenceClass.MOCKED_PROVIDER_CONTRACT

    def __init__(
        self, settings: LangfuseSettings, *, runtime: RuntimeSettings | None = None,
        http_transport: Any = None,
    ) -> None:
        if http_transport is None and (
            runtime is None or not require_live_langfuse(runtime, settings)
        ):
            raise ConfigurationError("Network Langfuse export requires explicit live settings.")
        self._initialize(settings, http_transport)

    def _initialize(self, settings: LangfuseSettings, http_transport: Any) -> None:
        import httpx
        from langfuse.api import LangfuseAPI

        if (not settings.enabled or settings.public_key is None
                or settings.secret_key is None or settings.host is None):
            raise ConfigurationError("Langfuse transport requires enabled, complete settings.")
        self._settings = settings
        self._queue: list[LangfuseExportSpec] = []
        self._closed = False
        self._close_attempted = False
        self._close_result = False
        self._http = httpx.Client(
            transport=http_transport, timeout=settings.request_timeout_seconds,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            follow_redirects=False, trust_env=False,
        )
        public = settings.public_key.get_secret_value()
        secret = settings.secret_key.get_secret_value()
        self._log_filter = _SecretLogFilter((public, secret))
        self._loggers = [logging.getLogger(name) for name in ("langfuse", "httpx", "httpcore")]
        for logger in self._loggers:
            logger.addFilter(self._log_filter)
        try:
            self._client = LangfuseAPI(
                base_url=settings.host, username=public, password=secret,
                x_langfuse_public_key=public, x_langfuse_sdk_name="python",
                headers={"x-langfuse-ingestion-version": "4"},
                timeout=settings.request_timeout_seconds, httpx_client=self._http,
            )
        except Exception:
            self._http.close()
            for logger in self._loggers:
                logger.removeFilter(self._log_filter)
            raise ConfigurationError("Langfuse API construction failed.") from None

    def submit(self, spec: LangfuseExportSpec) -> None:
        """Admit one bounded application specification, without network I/O."""
        if self._closed or len(self._queue) >= self._settings.max_observations:
            raise LangfuseExportError(RefusalReason.CAPACITY)
        self._queue.append(spec)

    @staticmethod
    def _resource_spans(specs: list[LangfuseExportSpec]) -> list[Any]:
        from langfuse import LangfuseOtelSpanAttributes as attrs
        from langfuse.api import (
            OtelAttribute,
            OtelAttributeValue,
            OtelResource,
            OtelResourceSpan,
            OtelScope,
            OtelScopeSpan,
            OtelSpan,
        )

        spans = []
        for spec in specs:
            values: dict[str, Any] = {
                attrs.AS_ROOT: True, attrs.OBSERVATION_TYPE: spec.observation_type,
                attrs.OBSERVATION_LEVEL: spec.level,
                attrs.OBSERVATION_STATUS_MESSAGE: spec.status_message,
            }
            values.update({f"{attrs.OBSERVATION_METADATA}.{k}": v for k, v in spec.metadata})
            values.update({f"{attrs.TRACE_METADATA}.{k}": v for k, v in spec.trace_metadata})
            if spec.usage_details is not None:
                values[attrs.OBSERVATION_USAGE_DETAILS] = json.dumps(dict(spec.usage_details))
            if spec.cost_details is not None:
                values[attrs.OBSERVATION_COST_DETAILS] = json.dumps(dict(spec.cost_details))
            attributes = [OtelAttribute(key=k, value=OtelAttributeValue(
                **({"bool_value": v} if type(v) is bool else
                   {"int_value": v} if type(v) is int else {"string_value": v})))
                for k, v in values.items()]
            canonical_span = dict(spec.metadata)["span_id"]
            # OTLP uses 64-bit span IDs; retain the full canonical UUID in metadata.
            import hashlib
            native_id = format(
                int(hashlib.sha256(str(canonical_span).encode()).hexdigest()[:16], 16) or 1,
                "016x",
            )
            spans.append(OtelSpan(
                trace_id=spec.trace_id, span_id=native_id, name=spec.name, kind=1,
                start_time_unix_nano=str(spec.start_time_ns),
                end_time_unix_nano=str(spec.end_time_ns), attributes=attributes,
            ))
        return [OtelResourceSpan(resource=OtelResource(attributes=[]), scope_spans=[
            OtelScopeSpan(scope=OtelScope(name="module7.langfuse"), spans=spans)])]

    def flush(self) -> bool:
        """Send finite queued batches exactly once; reject partial/malformed results."""
        if self._closed:
            return False
        while self._queue:
            batch = self._queue[:self._settings.flush_at]
            del self._queue[:len(batch)]  # Never retry an attempted batch implicitly.
            response = self._client.opentelemetry.export_traces(
                resource_spans=self._resource_spans(batch),
                request_options={"max_retries": 0,
                                 "timeout_in_seconds": self._settings.request_timeout_seconds},
            )
            if response.model_dump(exclude_none=True) != {}:
                return False  # Includes partialSuccess/rejectedSpans/unknown content.
        return True

    def close(self) -> bool:
        """Flush then publicly close the owned HTTP resource; safe to repeat."""
        if self._close_attempted:
            return self._close_result
        self._close_attempted = True
        flushed = False
        try:
            flushed = self.flush()
        finally:
            self._http.close()
            self._closed = self._http.is_closed
            if self._closed:
                for logger in self._loggers:
                    logger.removeFilter(self._log_filter)
        self._close_result = flushed and self._closed
        return self._close_result

    def read_back(self, trace_id: str, span_ids: frozenset[str]) -> int:
        """Compare identifiers from one bounded public observations API page."""
        response = self._client.observations.get_many(
            trace_id=trace_id, fields="core,basic,metadata", limit=100,
            request_options={"max_retries": 0,
                             "timeout_in_seconds": self._settings.request_timeout_seconds},
        )
        found = set()
        for row in response.data:
            value = row.metadata.get("span_id") if isinstance(row.metadata, dict) else None
            if row.trace_id == trace_id and type(value) is str and value in span_ids:
                found.add(value)
        return len(found)



def create_langfuse_sink(
    runtime: RuntimeSettings,
    settings: LangfuseSettings,
    *,
    clock_ns: Callable[[], int] = time.time_ns,
) -> LangfuseSink | None:
    """Build the real Langfuse sink only for explicit, complete live configuration.

    Args:
        runtime: Accepted runtime settings.
        settings: Langfuse settings.
        clock_ns: Trusted clock for placement anchoring.

    Returns:
        None when Langfuse is disabled (deterministic default), else a sink.

    Raises:
        ConfigurationError: If enabled outside live mode or the SDK cannot be bound.
    """
    if not require_live_langfuse(runtime, settings):
        return None
    transport = LangfuseSdkTransport(settings, runtime=runtime)
    return LangfuseSink(transport, settings=settings, clock_ns=clock_ns)


class LiveOutcome(StrEnum):
    """Outcome of opt-in live verification."""

    CONFIRMED = "confirmed"
    EXPORT_FAILED = "export_failed"
    NOT_CONFIRMED = "readback_not_confirmed"


@dataclass(frozen=True, slots=True)
class LiveVerificationResult:
    """Live verification evidence; live_vendor only after confirmed read-back.

    Attributes:
        outcome: Confirmed, export failure or unconfirmed read-back.
        evidence_class: live_vendor only when confirmed, otherwise None.
        trace_id: Synthetic Langfuse trace identifier used.
        expected_observations: Observations exported.
        confirmed_observations: Expected span identifiers found by read-back.
        close_state: Final bounded adapter lifecycle state.
    """

    outcome: LiveOutcome
    evidence_class: EvidenceClass | None
    trace_id: str
    expected_observations: int
    confirmed_observations: int
    close_state: LifecycleState


class ReadbackTransport(LangfuseTransport, Protocol):
    """Transport that can also read back exported observation identifiers."""

    def read_back(self, trace_id: str, span_ids: frozenset[str]) -> int:
        """Return how many expected span identifiers are visible."""
        ...


def _live_fixture(identity: WorkflowIdentity) -> tuple[Observation, ...]:
    """Two synthetic fixture observations; no user, model or provider content."""
    success = Observation(
        telemetry=TelemetryRecord(
            **identity.model_dump(), span_id=uuid4(), operation="workflow",
            status=Code.SUCCESS.value, duration_ms=125.0,
            usage=UsageRecord(input_tokens=12, output_tokens=3, cost_usd=0.0),
        ),
        action_id=uuid4(), cost_basis=CostBasis.FIXTURE,
        budget=BudgetState(cost_limit_usd=1.0, cost_used_usd=0.0),
    )
    retry = Observation(
        telemetry=TelemetryRecord(
            **identity.model_dump(), span_id=uuid4(), operation="reliability",
            status=Code.TRANSIENT_EXHAUSTED.value, duration_ms=40.0, retry_attempt=1,
            error_classification=Code.TRANSIENT_EXHAUSTED.value,
        ),
        action_id=success.action_id, event=Event.RECOVERY, component=Component.RELIABILITY,
        attempts=2, history=(Code.TRANSIENT, Code.TRANSIENT),
    )
    return success, retry


async def run_live_verification(
    runtime: RuntimeSettings,
    settings: LangfuseSettings,
    *,
    opt_in: bool,
    transport: ReadbackTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LiveVerificationResult:
    """Export one synthetic fixture workflow and confirm it by bounded read-back.

    Writes data to the configured external Langfuse project; run only with the
    human's authorization and externally supplied credentials. No model is called.

    Args:
        runtime: Live runtime settings (Story 1 still requires provider_api_key).
        settings: Enabled Langfuse settings.
        opt_in: Explicit verification opt-in, separate from configuration.
        transport: Optional read-back transport (tests); defaults to the SDK.
        sleep: Awaitable delay between bounded read-back attempts.

    Returns:
        Verification evidence; live_vendor only for confirmed read-back.

    Raises:
        ConfigurationError: Without opt-in or complete live Langfuse configuration.
    """
    if not opt_in:
        raise ConfigurationError("Live Langfuse verification requires explicit opt-in.")
    if not require_live_langfuse(runtime, settings):
        raise ConfigurationError("Live Langfuse verification requires enabled settings.")
    if transport is None:
        return await _verify_owned_network(runtime, settings, sleep=sleep)
    chosen = transport
    sink = LangfuseSink(chosen, settings=settings)
    identity = WorkflowIdentity()
    observations = _live_fixture(identity)
    span_ids = frozenset(str(item.telemetry.span_id) for item in observations)
    trace_hex = identity.trace_id.hex
    pipeline = TelemetryPipeline(exporter=sink, limits=TelemetryLimits(max_events=2))
    confirmed = 0
    outcome = LiveOutcome.EXPORT_FAILED
    try:
        exported = [await pipeline.emit(item) for item in observations]
        if all(status is Delivery.EXPORTED for status in exported) and (
            (await sink.flush()).state is LifecycleState.FLUSHED
        ):
            outcome = LiveOutcome.NOT_CONFIRMED
            for attempt in range(settings.readback_attempts):
                result, count, _ = await _run_bounded(
                    lambda: chosen.read_back(trace_hex, span_ids),
                    settings.lifecycle_timeout_seconds,
                    owner=chosen,
                )
                if result in {"timeout", "busy"}:
                    break
                if result == "ok" and type(count) is int:
                    confirmed = max(confirmed, min(count, len(span_ids)))
                if confirmed == len(span_ids):
                    outcome = LiveOutcome.CONFIRMED
                    break
                if attempt + 1 < settings.readback_attempts:
                    await sleep(settings.readback_interval_seconds)
    finally:
        closed = await sink.close()
    return LiveVerificationResult(
        outcome=outcome,
        evidence_class=(EvidenceClass.MOCKED_PROVIDER_CONTRACT
                        if outcome is LiveOutcome.CONFIRMED else None),
        trace_id=trace_hex,
        expected_observations=len(span_ids),
        confirmed_observations=confirmed,
        close_state=closed.state,
    )


# Implementation reuse only: object identity is never used as evidence authority.
_API_IMPLEMENTATION = LangfuseSdkTransport


async def _verify_owned_network(
    runtime: RuntimeSettings, settings: LangfuseSettings, *,
    sleep: Callable[[float], Awaitable[None]],
) -> LiveVerificationResult:
    """Own construction, network execution and evidence validation end to end.

    No transport/factory is accepted. A mocked SDK/client/HTTP response cannot
    manufacture receipts from the endpoint operations executed inside this boundary.
    Trusted application code and its Python runtime are the authority boundary;
    this is not a sandbox against arbitrary replacement of this verifier itself.
    """
    import http.client
    import ipaddress
    import socket

    import httpx

    endpoint = httpx.URL(str(settings.host))
    port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
    prefix = endpoint.path.rstrip("/") + "/api/public/"
    tls = httpx.create_ssl_context(trust_env=False)
    receipts: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

    class OwnedNetwork(httpx.BaseTransport):
        """Execute the exact endpoint operation; never consume HTTPX socket claims."""

        def handle_request(self, request: Any) -> Any:
            if (request.url.scheme != endpoint.scheme or request.url.host != endpoint.host
                    or (request.url.port or (443 if request.url.scheme == "https" else 80))
                    != port or request.url.userinfo
                    or (request.method, request.url.path) not in {
                        ("POST", prefix + "otel/v1/traces"),
                        ("GET", prefix + "v2/observations"),
                    }):
                raise LangfuseExportError(RefusalReason.TRANSPORT)
            body = request.content
            headers = httpx.Headers({
                k: v for k, v in request.headers.items()
                if k.lower() not in {"host", "connection", "content-length",
                                     "transfer-encoding", "accept-encoding"}
            })
            headers["Host"] = endpoint.netloc.decode("ascii")
            headers["Connection"] = "close"
            headers["Accept-Encoding"] = "identity"
            headers["Content-Length"] = str(len(body))
            wire = (request.method.encode("ascii") + b" " + request.url.raw_path
                    + b" HTTP/1.1\r\n" + b"".join(
                        k + b": " + v + b"\r\n" for k, v in headers.raw)
                    + b"\r\n" + body)

            # These bytes are written/read here over the connection created for
            # the accepted endpoint. No injected HTTP response, peer-looking
            # metadata, or dependency evidence marker can create a receipt.
            connection = socket.create_connection(
                (endpoint.host, port), timeout=settings.request_timeout_seconds)
            try:
                peer = socket.socket.getpeername(connection)
                if peer[1] != port:
                    raise LangfuseExportError(RefusalReason.TRANSPORT)
                if endpoint.scheme == "http":
                    expected = (ipaddress.ip_address(endpoint.host)
                                if endpoint.host != "localhost" else None)
                    actual = ipaddress.ip_address(peer[0])
                    if ((expected is not None and actual != expected)
                            or (expected is None and not actual.is_loopback)):
                        raise LangfuseExportError(RefusalReason.TRANSPORT)
                else:
                    connection = tls.wrap_socket(connection, server_hostname=endpoint.host)
                connection.sendall(wire)
                response = http.client.HTTPResponse(connection, method=request.method)
                try:
                    response.begin()
                    if response.getheader("Content-Encoding", "identity") != "identity":
                        raise LangfuseExportError(RefusalReason.TRANSPORT)
                    incoming_body = response.read(1_048_577)
                    if len(incoming_body) > 1_048_576:
                        raise LangfuseExportError(RefusalReason.TRANSPORT)
                    status, response_headers = response.status, response.getheaders()
                finally:
                    response.close()
            finally:
                connection.close()

            if 200 <= status < 300:
                try:
                    incoming = json.loads(incoming_body)
                    outgoing = json.loads(body) if request.method == "POST" else {}
                except (ValueError, UnicodeError):
                    incoming, outgoing = None, None
                if type(incoming) is dict and type(outgoing) is dict:
                    receipts.append((request.method, str(request.url), outgoing, incoming))
            return httpx.Response(status, headers=response_headers,
                                  content=incoming_body, request=request)

        def close(self) -> None:
            # Each operation closes its own socket in finally. The sink's shared
            # operation lane refuses client close while any operation is unresolved.
            return None

    network = OwnedNetwork()
    try:
        # Injection is deliberately unavailable to callers of this branch. The
        # application supplies its own resource to the official public API.
        owned = _API_IMPLEMENTATION(settings, runtime=runtime, http_transport=network)
    except Exception:
        network.close()
        raise ConfigurationError("Owned Langfuse verification construction failed.") from None
    result = await run_live_verification(
        runtime, settings, opt_in=True, transport=owned, sleep=sleep)
    if (result.outcome is not LiveOutcome.CONFIRMED
            or result.close_state is not LifecycleState.CLOSED):
        return result

    sent, seen = set(), set()
    expected_path = str(settings.host) + "/api/public/"
    for method, url, outgoing, incoming in receipts:
        if method == "POST" and url == expected_path + "otel/v1/traces" and incoming == {}:
            for resource in outgoing.get("resourceSpans", []):
                for scope in resource.get("scopeSpans", []):
                    for span in scope.get("spans", []):
                        if span.get("traceId") == result.trace_id:
                            attributes = {a.get("key"): a.get("value", {}).get("stringValue")
                                          for a in span.get("attributes", [])}
                            value = attributes.get("langfuse.observation.metadata.span_id")
                            if type(value) is str:
                                sent.add(value)
        elif method == "GET" and url.startswith(expected_path + "v2/observations?"):
            for row in incoming.get("data", []):
                if type(row) is dict and row.get("traceId") == result.trace_id:
                    metadata = row.get("metadata")
                    value = metadata.get("span_id") if type(metadata) is dict else None
                    if type(value) is str and value in sent:
                        seen.add(value)
    if len(sent) != result.expected_observations or seen != sent:
        return result
    return LiveVerificationResult(
        outcome=result.outcome, evidence_class=EvidenceClass.LIVE_VENDOR,
        trace_id=result.trace_id, expected_observations=result.expected_observations,
        confirmed_observations=result.confirmed_observations, close_state=result.close_state,
    )


__all__ = [
    "SEVERITY",
    "TIMING_ANCHOR",
    "LangfuseExportError",
    "LangfuseExportSpec",
    "LangfuseExportStatus",
    "LangfuseSdkTransport",
    "LangfuseSink",
    "LangfuseTransport",
    "LifecycleState",
    "LiveOutcome",
    "LiveVerificationResult",
    "ReadbackTransport",
    "RefusalReason",
    "create_langfuse_sink",
    "run_live_verification",
    "to_export_spec",
]
