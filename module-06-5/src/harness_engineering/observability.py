"""Application-owned sanitized projections (REQ-OBS-001/002, ENG-002..007).

Trusted bootstrap owns sessions. No content, arbitrary metadata, external sinks,
credentials, exporter queues, authority decisions or spending are supported.
Correctness-critical observers are invoked unchanged by the accepted runtime.
"""

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from math import isfinite
from threading import Lock
from time import monotonic
from typing import Annotated, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    HarnessError,
)
from harness_engineering.latency import (
    Cohort,
    Duration,
    LatencyData,
    LatencyReport,
    LatencyWindow,
    Measurement,
    Outcome,
    TimingSource,
)


class TelemetryError(HarnessError):
    """Rejected observation or failed local telemetry; contains no source payload."""


class TraceContext(LatencyData):
    """Inert version-00 W3C traceparent hook, with neither baggage nor authority."""

    trace_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", max_length=32)]
    span_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$", max_length=16)]
    flags: Literal["00", "01"] = "01"

    @model_validator(mode="after")
    def nonzero(self) -> "TraceContext":
        """Reject the forbidden all-zero IDs."""
        if int(self.trace_id, 16) == 0 or int(self.span_id, 16) == 0:
            raise ValueError("Trace and span identifiers must be nonzero.")
        return self

    @classmethod
    def parse_traceparent(cls, value: str) -> "TraceContext":
        """Validate an external header as inert data; never install it in a session."""
        if type(value) is not str or len(value) != 55 or not value.startswith("00-"):
            raise TelemetryError("Expected a bounded version-00 traceparent.")
        parts = value.split("-")
        if len(parts) != 4:
            raise TelemetryError("Expected a bounded version-00 traceparent.")
        try:
            return cls(trace_id=parts[1], span_id=parts[2], flags=parts[3])
        except ValidationError:
            raise TelemetryError("Invalid traceparent identifiers or flags.") from None

    def traceparent(self) -> str:
        """Serialize a validated context without any business data."""
        checked = TraceContext.model_validate(self)
        return f"00-{checked.trace_id}-{checked.span_id}-{checked.flags}"


_trace: ContextVar[TraceContext | None] = ContextVar("harness_trace", default=None)


def current_trace() -> TraceContext | None:
    """Return only the current inert context, never workflow policy or authority."""
    return _trace.get()


@contextmanager
def bind_trace(context: TraceContext | None) -> Iterator[None]:
    """Explicitly bind/reset context across a trusted callback or worker boundary."""
    checked = None if context is None else TraceContext.model_validate(context)
    token = _trace.set(checked)
    try:
        yield
    finally:
        _trace.reset(token)


class EventKind(StrEnum):
    """Span vocabulary, separate from lifecycle and audit authority."""

    STARTED = "started"
    FINISHED = "finished"


class TelemetryEvent(LatencyData):
    """Closed operational schema; no free text or arbitrary metadata exists."""

    schema_version: Literal[1] = 1
    event_id: UUID
    workflow_id: UUID
    thread_id: UUID
    segment_id: UUID
    sequence: Annotated[int, Field(ge=1, le=1_000_000)]
    measurement: Measurement
    kind: EventKind
    outcome: Outcome | None = None
    step_index: Annotated[int, Field(ge=1, le=100)] | None = None
    trace: TraceContext
    parent_span_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")] | None = None
    elapsed_seconds: Duration | None = None
    evidence: EvidenceClass
    timing: TimingSource

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        """Do not coerce True or 1.0 into a schema-version assertion."""
        if type(value) is not int:
            raise ValueError("Schema version must be an integer.")
        return value

    @model_validator(mode="after")
    def coherent(self) -> "TelemetryEvent":
        """Reject contradictory or oversized records before local retention."""
        if self.kind is EventKind.STARTED:
            if self.outcome is not None or self.elapsed_seconds is not None:
                raise ValueError("Start events cannot claim completion.")
        elif self.outcome is None or self.elapsed_seconds is None:
            raise ValueError("Finish events require outcome and duration.")
        if self.parent_span_id == "0" * 16:
            raise ValueError("Parent span identifier must be nonzero.")
        if len(self.model_dump_json().encode("utf-8")) > 4096:
            raise ValueError("Telemetry event exceeds 4 KiB.")
        return self


class LocalTelemetrySink:
    """One identity-bound 512-event ring; no global workflow/cardinality registry."""

    def __init__(
        self, identity: WorkflowIdentity, segment_id: UUID, *, evidence: EvidenceClass,
        timing: TimingSource, trace_id: str,
    ) -> None:
        """Snapshot trusted identity; never accept workflow identities per event."""
        self._identity = WorkflowIdentity.model_validate(identity.model_dump())
        if type(segment_id) is not UUID:
            raise TelemetryError("Bind a generated segment UUID.")
        self._segment = segment_id
        if type(evidence) is not EvidenceClass or type(timing) is not TimingSource:
            raise TelemetryError("Bind application-owned evidence and timing classifications.")
        self._evidence = evidence
        self._timing = timing
        self._trace_id = TraceContext(trace_id=trace_id, span_id="0000000000000001").trace_id
        self._events: deque[TelemetryEvent] = deque(maxlen=512)
        self._dropped = 0
        self._sequence = 0
        self._lock = Lock()

    def emit(self, event: TelemetryEvent) -> None:
        """Revalidate and reject foreign/malformed/replayed events, without retaining them."""
        try:
            checked = TelemetryEvent.model_validate(event)
        except ValidationError:
            raise TelemetryError("Telemetry event violates the closed schema.") from None
        with self._lock:
            if (checked.workflow_id != self._identity.workflow_id
                    or checked.thread_id != self._identity.thread_id
                    or checked.segment_id != self._segment or checked.sequence <= self._sequence
                    or checked.evidence is not self._evidence or checked.timing is not self._timing
                    or checked.trace.trace_id != self._trace_id):
                raise TelemetryError("Telemetry identity or sequence conflicts with this sink.")
            self._sequence = checked.sequence
            self._dropped += int(len(self._events) == 512)
            self._events.append(checked)

    @property
    def dropped(self) -> int:
        """Count ring evictions without storing dropped content."""
        with self._lock:
            return self._dropped

    def snapshot(self) -> tuple[TelemetryEvent, ...]:
        """Return immutable sanitized events, never an authoritative runtime snapshot."""
        with self._lock:
            return tuple(self._events)


T = TypeVar("T")


class TelemetrySession:
    """Trusted per-workflow segment, with finite cohorts and fail-isolated local errors.

    Evidence class is a bootstrap assertion, never inferred from provider claims.
    Do not hand this mutable application object to untrusted plugins. Python
    in-process object access is not a security sandbox.
    """

    def __init__(
        self, identity: WorkflowIdentity, *, evidence: EvidenceClass,
        clock: Callable[[], float] = monotonic, slo_p95_seconds: float = 5.0,
    ) -> None:
        """Bind application identity/evidence, a monotonic clock, and a tightened SLO.

        Each session is a new execution segment. Resumed segments are not silently
        aggregated into end-to-end workflow latency. No external parent is accepted.
        """
        self._identity = WorkflowIdentity.model_validate(identity.model_dump())
        if type(evidence) is not EvidenceClass or not callable(clock):
            raise TelemetryError("Bind application EvidenceClass and callable clock.")
        self._evidence = evidence
        self._clock = clock
        self._timing = TimingSource.MONOTONIC if clock is monotonic else TimingSource.INJECTED
        self._segment = uuid4()
        self._root = uuid4().hex
        self._sink = LocalTelemetrySink(
            self._identity, self._segment, evidence=evidence, timing=self._timing,
            trace_id=self._root,
        )
        self._windows = {
            (measurement, outcome): LatencyWindow(
                Cohort(measurement=measurement, outcome=outcome, evidence=evidence,
                       timing=self._timing), slo_p95_seconds=slo_p95_seconds,
            ) for measurement in Measurement for outcome in Outcome
        }
        self._sequence = 0
        self._failures = 0
        self._lock = Lock()

    @property
    def sink(self) -> LocalTelemetrySink:
        """Expose local read/validation APIs, not a replaceable exporter callback."""
        return self._sink

    @property
    def failures(self) -> int:
        """Count rejected timing/event observations without source diagnostics."""
        with self._lock:
            return self._failures

    def reports(self) -> tuple[LatencyReport, ...]:
        """Return nonempty finite cohorts, keeping failures distinct from successes."""
        reports = tuple(window.report() for window in self._windows.values())
        return tuple(report for report in reports if report.sample_count)

    def _time(self) -> float:
        try:
            value = self._clock()
            if type(value) not in (float, int) or not isfinite(value) or value < 0:
                raise TelemetryError("Invalid telemetry clock reading.")
            return float(value)
        except Exception:
            # A trusted timing callback is an observability-only failure boundary.
            # Never expose its payload or replace the measured operation's outcome.
            raise TelemetryError("Telemetry clock unavailable.") from None

    def _failed(self) -> None:
        with self._lock:
            self._failures += 1

    def _emit(
        self, measurement: Measurement, kind: EventKind, trace: TraceContext,
        parent: str | None, step_index: int | None, outcome: Outcome | None = None,
        seconds: float | None = None,
    ) -> None:
        # Serialize assignment and sink admission together so concurrent completions
        # cannot reorder sequence IDs. Failures retain no exception or payload.
        try:
            with self._lock:
                self._sequence += 1
                event = TelemetryEvent(
                    event_id=uuid4(), workflow_id=self._identity.workflow_id,
                    thread_id=self._identity.thread_id, segment_id=self._segment,
                    sequence=self._sequence, measurement=measurement, kind=kind,
                    outcome=outcome, step_index=step_index, trace=trace,
                    parent_span_id=parent, elapsed_seconds=seconds, evidence=self._evidence,
                    timing=self._timing,
                )
                self._sink.emit(event)
        except Exception:
            # Local sink boundary only: report loss via a fixed counter, never
            # retry work or leak a storage/validation exception into business logic.
            self._failed()

    def call(
        self, measurement: Measurement, operation: Callable[[], T], *,
        step_index: int | None = None, classify: Callable[[T], Outcome] | None = None,
    ) -> T:
        """Observe a trusted callback once, preserving its result and exceptions.

        The optional classifier is application code, never an external response
        callback. Start/finish telemetry errors are counted; operation exceptions
        are only categorized and re-raised unchanged. No retries are performed.
        """
        if type(measurement) is not Measurement or (
            step_index is not None and (type(step_index) is not int or not 1 <= step_index <= 100)
        ):
            raise TelemetryError("Bind a finite measurement and bounded step ordinal.")
        parent = current_trace()
        # A different session's ambient trace can never replace this session's root.
        parent = parent if parent is not None and parent.trace_id == self._root else None
        trace = TraceContext(trace_id=self._root, span_id=uuid4().hex[:16])
        try:
            start = self._time()
        except TelemetryError:
            self._failed()
            start = None
        self._emit(measurement, EventKind.STARTED, trace,
                   parent.span_id if parent else None, step_index)
        outcome = Outcome.DEFECT
        try:
            with bind_trace(trace):
                result = operation()
            try:
                outcome = Outcome.RETURNED if classify is None else classify(result)
                if type(outcome) is not Outcome:
                    raise TelemetryError("Observation classifier must return a finite outcome.")
            except Exception:
                # Classification is telemetry-only, outside the operation callback.
                self._failed()
                outcome = Outcome.REJECTED
            return result
        except AuthorityViolationError:
            outcome = Outcome.DENIED
            raise
        except BudgetExceededError:
            outcome = Outcome.REJECTED
            raise
        except ContractValidationError:
            outcome = Outcome.REJECTED
            raise
        except HarnessError:
            outcome = Outcome.FAILED
            raise
        finally:
            try:
                end = self._time()
                if start is not None:
                    seconds = end - start
                    if not 0 <= seconds <= 86_400:
                        raise TelemetryError("Telemetry duration outside bounded monotonic range.")
                    self._windows[measurement, outcome].add(seconds)
                    self._emit(measurement, EventKind.FINISHED, trace,
                               parent.span_id if parent else None, step_index, outcome, seconds)
            except Exception:
                # Timing/retention only; the operation's exception still propagates.
                self._failed()
