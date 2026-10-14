"""Bounded process-local TTL/LRU cache behind an application contract."""

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from module10_ai.contracts import InferenceRequest, InferenceResult
from module10_ai.execution_config import ExecutionConfig


def cache_key(request: InferenceRequest) -> str:
    """Hash exact input and versioned deterministic semantics without exposing raw text."""
    request.__post_init__()
    payload = json.dumps(
        ["module10-lexical-v1", request.text, request.keyword_limit],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Aggregate counters without per-key or payload telemetry."""

    hits: int
    misses: int
    expirations: int
    evictions: int
    entries: int


class InferenceCache(Protocol):
    """Application cache operations; results remain untrusted data."""

    def get(self, key: str) -> InferenceResult | None:
        """Return an unexpired result or a miss."""
        ...

    def put(self, key: str, result: InferenceResult) -> None:
        """Store a validated result subject to bounded retention."""
        ...

    def invalidate(self, key: str) -> None:
        """Remove a key idempotently."""
        ...

    def stats(self) -> CacheStats:
        """Return aggregate statistics."""
        ...


class LocalInferenceCache:
    """Thread-safe TTL cache with LRU eviction, never durable or distributed."""

    def __init__(
        self, config: ExecutionConfig, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Bind validated capacity/TTL and a monotonic clock for deterministic tests."""
        config.__post_init__()
        self._capacity = config.cache_capacity
        self._ttl = config.cache_ttl_seconds
        self._clock = clock
        self._lock = Lock()
        self._entries: OrderedDict[str, tuple[float, InferenceResult]] = OrderedDict()
        self._hits = self._misses = self._expirations = self._evictions = 0

    def _expire(self) -> None:
        now = self._clock()
        for key in [key for key, (deadline, _) in self._entries.items() if deadline <= now]:
            del self._entries[key]
            self._expirations += 1

    def get(self, key: str) -> InferenceResult | None:
        """Read and promote an unexpired entry under one lock."""
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            self._hits += 1
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, key: str, result: InferenceResult) -> None:
        """Validate and insert, refreshing TTL and evicting least recently used entries."""
        result.__post_init__()
        with self._lock:
            self._expire()
            self._entries[key] = (self._clock() + self._ttl, result)
            self._entries.move_to_end(key)
            if len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
                self._evictions += 1

    def invalidate(self, key: str) -> None:
        """Remove an entry without exposing whether it contained sensitive data."""
        with self._lock:
            self._entries.pop(key, None)

    def stats(self) -> CacheStats:
        """Expire stale entries and snapshot bounded aggregate counters."""
        with self._lock:
            self._expire()
            return CacheStats(
                self._hits, self._misses, self._expirations, self._evictions, len(self._entries)
            )
