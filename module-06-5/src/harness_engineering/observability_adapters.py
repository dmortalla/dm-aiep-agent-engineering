"""Explicit offline SDK projections; application telemetry remains authoritative.

Enqueue is nonblocking with respect to exporters. Flush is an explicit reviewer
operation, never installed as a workflow callback. One process-wide drain slot,
64 pending records per adapter, no retries and a ten-second child lifetime bound
isolate optional SDK threads, configuration, errors and shutdown from runtime.
"""

import json
import os
import subprocess
import sys
from collections import deque
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from harness_engineering.anomaly_signals import validate_fixture_projection
from harness_engineering.latency import LatencyData
from harness_engineering.observability import TelemetryEvent, TelemetrySession

_DRAIN = Lock()
_LIMIT = 1_000_000
FailureCategory = Literal[
    "unavailable", "construction", "create", "update", "flush", "close",
    "worker", "timeout", "disabled", "closed", "projection", "capacity",
]


class Vendor(StrEnum):
    """The only optional SDK projections supported by this offline boundary."""

    LANGSMITH = "langsmith"
    LANGFUSE = "langfuse"


class ExportHealth(LatencyData):
    """Advisory bounded counters, never diagnostics or authority input."""

    pending: Annotated[int, Field(ge=0, le=64)]
    exported: Annotated[int, Field(ge=0, le=_LIMIT)]
    dropped: Annotated[int, Field(ge=0, le=_LIMIT)]
    failure: FailureCategory | None
    closed: bool


class OfflineObservabilityAdapter:
    """Bind one trusted session to a disabled-by-default offline vendor adapter.

    No client, credentials, endpoint, metadata or callback can be supplied. The
    only executable integration is the bundled socket-denied offline worker.
    Future hosted export requires a separately reviewed integration boundary.
    """

    def __init__(
        self, source: TelemetrySession, vendor: Vendor, *, enabled: bool = False
    ) -> None:
        """Snapshot application provenance; reject live/deployment classifications."""
        if type(source) is not TelemetrySession or type(vendor) is not Vendor:
            raise ValueError("Bind an application telemetry session and supported vendor.")
        if type(enabled) is not bool:
            raise ValueError("Offline activation must be an explicit boolean.")
        validate_fixture_projection(source.identity, source.evidence, source)
        self._source = source
        self._identity = source.identity.model_copy(deep=True)
        self._evidence = source.evidence
        self._vendor = vendor
        self._enabled = enabled
        self._queue: deque[TelemetryEvent] = deque()
        self._lock = Lock()
        self._sequence = 0
        self._exported = 0
        self._dropped = 0
        self._failure: FailureCategory | None = None
        self._closed = False

    def _drop(self, count: int, category: FailureCategory) -> None:
        self._dropped = min(_LIMIT, self._dropped + count)
        self._failure = category

    def enqueue(self, event: TelemetryEvent) -> bool:
        """Copy only a validated event actually retained by the bound local sink.

        Drop newest on capacity; reject replay, forged provenance and malformed
        records. No SDK or process is invoked here and no source state is changed.
        """
        with self._lock:
            if self._closed or not self._enabled:
                self._drop(1, "disabled" if not self._enabled else "closed")
                return False
            try:
                if type(event) is not TelemetryEvent:
                    raise ValueError("Invalid projection type.")
                checked = TelemetryEvent.model_validate(event)
                if (
                    checked.workflow_id != self._identity.workflow_id
                    or checked.thread_id != self._identity.thread_id
                    or checked.evidence is not self._evidence
                    or checked.sequence <= self._sequence
                    or checked not in self._source.sink.snapshot()
                ):
                    raise ValueError("Projection provenance/replay rejected.")
            except (ValidationError, ValueError):
                self._drop(1, "projection")
                return False
            self._sequence = checked.sequence
            if len(self._queue) == 64:
                self._drop(1, "capacity")
                return False
            self._queue.append(checked.model_copy(deep=True))
            return True

    def health(self) -> ExportHealth:
        """Return an immutable advisory snapshot without SDK exception payloads."""
        with self._lock:
            return ExportHealth(
                pending=len(self._queue), exported=self._exported,
                dropped=self._dropped, failure=self._failure, closed=self._closed,
            )

    def flush(self) -> None:
        """Attempt one offline batch, bounded to ten seconds; never retry it.

        Busy drains return immediately. SDK imports, serialization, export, flush
        and close all share the same hard process lifetime budget. No vendor
        response or generated context is returned to authoritative application state.
        """
        if not _DRAIN.acquire(blocking=False):
            return
        try:
            with self._lock:
                if self._closed or not self._enabled or not self._queue:
                    return
                batch = tuple(self._queue)
                self._queue.clear()
            environment = {
                "LANGSMITH_CONFIG_FILE": os.devnull,
                "LANGFUSE_MEDIA_UPLOAD_ENABLED": "false",
            }
            if "SYSTEMROOT" in os.environ:
                environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", "-B", str(Path(__file__).with_name(
                        "_offline_observability_worker.py")), self._vendor.value],
                    input=json.dumps([item.model_dump(mode="json") for item in batch]),
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=10, check=False, env=environment,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                result = completed.stdout
                category = result if result in (
                    "unavailable", "construction", "create", "update", "flush", "close"
                ) else "worker"
                success = completed.returncode == 0 and result == "ok"
            except subprocess.TimeoutExpired:
                success, category = False, "timeout"
            except OSError:
                success, category = False, "unavailable"
            with self._lock:
                if success:
                    self._exported = min(_LIMIT, self._exported + len(batch))
                else:
                    self._drop(len(batch), category)
        finally:
            _DRAIN.release()

    def close(self) -> None:
        """Stop admission and discard pending work immediately; idempotent.

        Explicit flush before close is optional. An already running isolated
        drain retains its ten-second lifetime bound; close never waits for it.
        """
        with self._lock:
            if not self._closed:
                self._drop(len(self._queue), "closed")
                self._queue.clear()
                self._closed = True
