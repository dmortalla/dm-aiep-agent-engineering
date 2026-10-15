"""Bounded cooperative workers and ephemeral job handles for deterministic inference."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from module10_ai.cache import InferenceCache, LocalInferenceCache, cache_key
from module10_ai.contracts import EvidenceClass, InferenceRequest, InferenceResult
from module10_ai.errors import ConfigurationError, ContractError, InferenceFailure
from module10_ai.execution_config import ExecutionConfig
from module10_ai.service import InferenceService
from module10_ai.telemetry import CORRELATION, Telemetry, failure_category


class QueueUnavailable(RuntimeError):
    """Queue is saturated or not accepting work; retry policy belongs to the caller."""


class UnknownJob(ValueError):
    """Handle does not belong to this queue's active work."""


class JobTimeout(TimeoutError):
    """Worker execution exceeded its configured cooperative deadline."""


class JobState(StrEnum):
    """Ephemeral lifecycle; terminal handles are retained only by their callers."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"


@dataclass(slots=True, eq=False)
class Job:
    """Opaque process-local handle, never authorization or a durable job record."""

    id: str = field(default_factory=lambda: uuid4().hex)
    _correlation: str | None = field(default=None, repr=False)
    _owner: object | None = field(default=None, repr=False)
    _state: JobState = field(default=JobState.QUEUED, repr=False)
    _done: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _result: InferenceResult | None = field(default=None, repr=False)
    _failure: Exception | None = field(default=None, repr=False)
    _task: asyncio.Task[InferenceResult] | None = field(default=None, repr=False)

    @property
    def state(self) -> JobState:
        """Return current lifecycle state without exposing payload or exception details."""
        return self._state

    async def result(self) -> InferenceResult:
        """Await completion; cancellation and original internal failures propagate."""
        await self._done.wait()
        if self._state is JobState.CANCELLED:
            raise asyncio.CancelledError
        if self._failure is not None:
            raise self._failure
        assert self._result is not None
        return self._result


class JobQueue(Protocol):
    """Minimal application contract for accepted work and controlled lifecycle."""

    async def start(self) -> None:
        """Start a fixed number of workers."""
        ...

    def submit(self, request: InferenceRequest) -> Job:
        """Accept immediately or raise QueueUnavailable without creating a task."""
        ...

    async def cancel(self, job: Job) -> None:
        """Cancel owned work and await cooperative cleanup."""
        ...

    async def close(self) -> None:
        """Reject submissions and cancel all outstanding work."""
        ...


@dataclass(frozen=True, slots=True)
class QueueStats:
    """Bounded aggregate queue telemetry, without request/job identifiers."""

    submitted: int
    rejected: int
    pending_slots: int
    running: int
    workers: int


class LocalExecution:
    """Single-event-loop queue with fixed workers and bounded cache composition."""

    def __init__(
        self,
        service: InferenceService,
        config: ExecutionConfig | None = None,
        cache: InferenceCache | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        """Bind trusted service/configuration; instances cannot restart after shutdown."""
        self.config = ExecutionConfig() if config is None else config
        if type(self.config) is not ExecutionConfig:
            raise ConfigurationError("Execution requires ExecutionConfig.")
        self.config.__post_init__()
        self._service = service
        self.telemetry = Telemetry() if telemetry is None else telemetry
        if type(self.telemetry) is not Telemetry:
            raise ConfigurationError("Execution requires Telemetry.")
        self.cache = (
            LocalInferenceCache(self.config, telemetry=self.telemetry) if cache is None else cache
        )
        self._queue: asyncio.Queue[tuple[Job, InferenceRequest]] = asyncio.Queue(
            self.config.queue_capacity
        )
        self._active: dict[str, Job] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._started = self._closed = False
        self._submitted = self._rejected = 0

    def _occupancy(self) -> None:
        stats = self.stats()
        self.telemetry.gauge("queue.pending", stats.pending_slots)
        self.telemetry.gauge("workers.active", stats.running)
        self.telemetry.gauge("workers.configured", stats.workers)

    @property
    def accepting(self) -> bool:
        """Report worker lifecycle health, independently of transient saturation."""
        return (
            self._started
            and not self._closed
            and all(not worker.done() for worker in self._workers)
        )

    def stats(self) -> QueueStats:
        """Snapshot process-local activity; cancelled pending slots remain occupied."""
        return QueueStats(
            self._submitted,
            self._rejected,
            self._queue.qsize(),
            sum(job.state is JobState.RUNNING for job in self._active.values()),
            len(self._workers),
        )

    async def start(self) -> None:
        """Start fixed workers idempotently; reject reopening a closed instance."""
        if self._closed:
            raise QueueUnavailable("Execution has been closed.")
        if not self._started:
            self._workers = [
                asyncio.create_task(self._worker()) for _ in range(self.config.max_workers)
            ]
            self._started = True
            self._occupancy()

    def submit(self, request: InferenceRequest) -> Job:
        """Validate input and enqueue without waiting or spawning per-submission tasks.

        Raises:
            QueueUnavailable: Workers are unavailable or pending capacity is exhausted.
            ContractError: Input is not the validated domain contract.
        """
        if type(request) is not InferenceRequest:
            raise ContractError("Queue requires InferenceRequest.")
        self._service.validate_request(request)
        if not self.accepting or self._queue.full():
            self._rejected += 1
            self.telemetry.event("queue.rejected", status="rejected")
            raise QueueUnavailable("Execution capacity is unavailable.")
        job = Job(_owner=self, _correlation=CORRELATION.get())
        self._queue.put_nowait((job, request))
        self._active[job.id] = job
        self._submitted += 1
        self.telemetry.event("queue.admitted", job_id=job.id)
        self._occupancy()
        return job

    async def cancel(self, job: Job) -> None:
        """Cancel owned active work; a completed owned handle is an idempotent no-op."""
        if type(job) is not Job:
            raise UnknownJob("Cancellation requires an owned job handle.")
        if self._active.get(job.id) is not job:
            if job._owner is self:
                return
            raise UnknownJob("Job is not active in this execution queue.")
        job._state = JobState.CANCELLED
        if job._task is not None:
            job._task.cancel()
            await asyncio.gather(job._task, return_exceptions=True)
        job._done.set()
        # Queued tombstones remain bounded until consumed, preventing cancellation churn.

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Await queued work and propagate caller cancellation after runtime cleanup."""
        job = self.submit(request)
        try:
            return await job.result()
        except asyncio.CancelledError:
            if self._active.get(job.id) is job:
                await self.cancel(job)
            raise

    async def _execute(self, request: InferenceRequest) -> InferenceResult:
        key = cache_key(request)
        result = self.cache.get(key)
        if result is not None:
            try:
                if type(result) is not InferenceResult:
                    raise ContractError("Cache must return InferenceResult.")
                result.__post_init__()
                if (
                    result.evidence is not EvidenceClass.DETERMINISTIC
                    or len(result.keywords) > request.keyword_limit
                ):
                    raise ContractError("Cache violates deterministic inference semantics.")
            except ContractError as exc:
                raise InferenceFailure("Cache returned an invalid inference result.") from exc
            return result
        begin = time.monotonic()
        status, category = "success", "none"
        try:
            result = await self._service.infer(request)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as exc:
            status, category = "failure", failure_category(exc)
            raise
        finally:
            self.telemetry.event(
                "inference.completed", status=status, category=category,
                duration=time.monotonic() - begin,
            )
        self.cache.put(key, result)
        return result

    async def _worker(self) -> None:
        while True:
            job, request = await self._queue.get()
            token = CORRELATION.set(job._correlation)
            begin = time.monotonic()
            try:
                if job.state is JobState.CANCELLED:
                    continue
                job._state = JobState.RUNNING
                self._occupancy()
                job._task = asyncio.create_task(self._execute(request))
                deadline = asyncio.timeout(self.config.job_timeout_seconds)
                try:
                    async with deadline:
                        job._result = await job._task
                    if job.state is not JobState.CANCELLED:
                        job._state = JobState.SUCCEEDED
                except asyncio.CancelledError:
                    job._state = JobState.CANCELLED
                    if asyncio.current_task().cancelling():
                        raise
                except TimeoutError as exc:
                    if deadline.expired():
                        job._state = JobState.TIMED_OUT
                        job._failure = JobTimeout("Job execution deadline exceeded.")
                    else:
                        job._state = JobState.FAILED
                        job._failure = exc
                except Exception as exc:
                    # Genuine worker boundary: preserve defects for caller/API diagnostics.
                    job._state = JobState.FAILED
                    job._failure = exc
            finally:
                job._task = None
                job._done.set()
                self._active.pop(job.id, None)
                self._queue.task_done()
                status = {
                    JobState.SUCCEEDED: "success", JobState.FAILED: "failure",
                    JobState.TIMED_OUT: "timeout", JobState.CANCELLED: "cancelled",
                }[job.state]
                self.telemetry.event(
                    "job.completed", status=status, job_id=job.id,
                    category=("deadline" if job.state is JobState.TIMED_OUT else
                              failure_category(job._failure) if job._failure else "none"),
                    duration=time.monotonic() - begin,
                )
                self._occupancy()
                CORRELATION.reset(token)

    async def close(self) -> None:
        """Cancel workers/running work, drain queued work, and leave no owned tasks."""
        self._closed = True
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        while not self._queue.empty():
            job, _ = self._queue.get_nowait()
            job._state = JobState.CANCELLED
            job._done.set()
            self._active.pop(job.id, None)
            self._queue.task_done()
            token = CORRELATION.set(job._correlation)
            self.telemetry.event("job.completed", status="cancelled", job_id=job.id)
            CORRELATION.reset(token)
        self._occupancy()
