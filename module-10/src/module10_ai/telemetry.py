"""Provider-neutral, bounded, non-authoritative operational telemetry.

Only fixed operational values and digested correlation cross the sink boundary.
Sinks are trusted synchronous adapters and must return promptly without retries.
"""

import hashlib
import json
import logging
import math
import re
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from threading import Lock

from module10_ai.errors import ContractError, InferenceFailure

CORRELATION: ContextVar[str | None] = ContextVar("module10_correlation", default=None)
EVENTS = frozenset(
    {
        "http.completed",
        "application.failure",
        "queue.admitted",
        "queue.rejected",
        "job.completed",
        "inference.completed",
        "cache.hit",
        "cache.miss",
        "readiness.failed",
    }
)
STATUSES = frozenset({"success", "failure", "timeout", "cancelled", "rejected"})
CATEGORIES = frozenset({"none", "contract", "inference", "internal", "deadline"})
GAUGES = frozenset(
    {
        "queue.pending",
        "workers.active",
        "workers.configured",
        "cache.entries",
        "cache.expirations",
        "cache.evictions",
    }
)
LIMIT = 2**63 - 1

class SafeStreamHandler(logging.StreamHandler):
    """Return stream failures to the telemetry boundary without logging tracebacks."""

    def handleError(self, record: logging.LogRecord) -> None:
        """Re-raise the active emission error instead of stderr diagnostic fallback."""
        raise


LOGGER = logging.Logger("module10_ai.telemetry", level=logging.INFO)
LOGGER.addHandler(SafeStreamHandler())


def correlation_id(value: str) -> str:
    """Digest bounded caller metadata; syntax validation alone cannot detect secrets."""
    return hashlib.sha256(value[:128].encode("utf-8", errors="replace")).hexdigest()[:32]


def failure_category(exc: Exception) -> str:
    """Classify without reflecting exception names, text, causes, paths, or stacks."""
    if isinstance(exc, ContractError):
        return "contract"
    if isinstance(exc, InferenceFailure):
        return "inference"
    return "internal"


def logging_sink(record: str) -> None:
    """Emit one pre-serialized JSON record through standard-library logging."""
    LOGGER.log(logging.ERROR if '"severity":"ERROR"' in record else logging.INFO, record)


class Telemetry:
    """Fixed-cardinality counters, duration aggregates, gauges and safe event emission.

    Memory is independent of request volume: no samples, IDs or event history are
    retained. Counters saturate; invalid inputs are dropped and counted locally.
    """

    def __init__(self, sink: Callable[[str], None] | None = logging_sink) -> None:
        """Bind an optional trusted sink; None records metrics without emitting logs."""
        if sink is not None and not callable(sink):
            raise TypeError("Telemetry sink must be callable or None.")
        self._sink = sink
        self._lock = Lock()
        self._counts: dict[str, int] = {}
        self._durations: dict[str, dict[str, float | int]] = {}
        self._gauges: dict[str, int] = {}
        self._failures = 0

    def _failed(self) -> None:
        with self._lock:
            self._failures = min(LIMIT, self._failures + 1)

    def gauge(self, name: str, value: int) -> None:
        """Set one fixed gauge, rejecting invalid names, negative values and booleans."""
        if type(name) is not str or name not in GAUGES or type(value) is not int or value < 0:
            self._failed()
            return
        with self._lock:
            self._gauges[name] = min(LIMIT, value)

    def event(
        self,
        name: str,
        *,
        status: str = "success",
        duration: float | None = None,
        category: str = "none",
        job_id: str | None = None,
        quantity: int = 1,
    ) -> None:
        """Record allowlisted fields and emit JSON; sink/serialization errors stay local.

        Args:
            name: Fixed application event name.
            status: Fixed operational outcome.
            duration: Optional finite nonnegative monotonic elapsed seconds.
            category: Application-controlled failure classification.
            job_id: Optional internal UUID hex, never a metric dimension.
            quantity: Bounded counter increment, useful for expiration batches.
        """
        if (
            type(name) is not str
            or name not in EVENTS
            or type(status) is not str
            or status not in STATUSES
            or type(category) is not str
            or category not in CATEGORIES
            or type(quantity) is not int
            or not 1 <= quantity <= LIMIT
            or (
                duration is not None
                and (
                    type(duration) not in (int, float)
                    or not 0 <= duration <= 86400
                    or not math.isfinite(duration)
                )
            )
        ):
            self._failed()
            return
        key = f"{name}:{status}"
        with self._lock:
            self._counts[key] = min(LIMIT, self._counts.get(key, 0) + quantity)
            if duration is not None:
                aggregate = self._durations.setdefault(key, {"count": 0, "sum": 0.0, "max": 0.0})
                aggregate["count"] = min(LIMIT, aggregate["count"] + 1)
                aggregate["sum"] = min(float(LIMIT), aggregate["sum"] + duration)
                aggregate["max"] = max(aggregate["max"], duration)
        if self._sink is None:
            return
        # Genuine telemetry boundary: arbitrary adapter/handler/serializer failures
        # cannot change application decisions. No fallback logger or retry recursion.
        try:
            record = {
                "schema_version": 1,
                "event": name,
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": "INFO" if status == "success" else "ERROR",
                "status": status,
                "category": category,
            }
            correlation = CORRELATION.get()
            if type(correlation) is str and re.fullmatch(r"[a-f0-9]{32}", correlation):
                record["correlation_id"] = correlation
            if type(job_id) is str and re.fullmatch(r"[a-f0-9]{32}", job_id):
                record["job_id"] = job_id
            if duration is not None:
                record["duration_seconds"] = duration
            self._sink(json.dumps(record, separators=(",", ":"), allow_nan=False))
        except Exception:
            self._failed()

    def snapshot(self) -> dict[str, object]:
        """Return detached bounded process-local aggregates, with no IDs or payloads."""
        with self._lock:
            return {
                "evidence": "local-deterministic",
                "counters": dict(self._counts),
                "durations": {key: dict(value) for key, value in self._durations.items()},
                "gauges": dict(self._gauges),
                "telemetry_failures": self._failures,
            }
