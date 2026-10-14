"""Story 10.4 deterministic queue/cache acceptance and measured local workload."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from module10_ai import (
    DeterministicRuntime,
    EvidenceClass,
    InferenceRequest,
    InferenceResult,
    InferenceService,
    RuntimeConfig,
)
from module10_ai.api import create_app
from module10_ai.cache import LocalInferenceCache, cache_key
from module10_ai.errors import ConfigurationError, ContractError, InferenceFailure, RuntimeFailure
from module10_ai.execution import (
    Job,
    JobState,
    JobTimeout,
    LocalExecution,
    QueueUnavailable,
    UnknownJob,
)
from module10_ai.execution_config import ExecutionConfig


class ControlledRuntime:
    """Event-controlled runtime measuring actual concurrency and cleanup."""

    def __init__(self, failure: BaseException | None = None) -> None:
        """Initialize gates and bounded counters."""
        self.entered = asyncio.Event()
        self.two_running = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = self.active = self.peak = self.cleaned = 0
        self.failure = failure

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Execute deterministic work after the explicit test gate opens."""
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.entered.set()
        if self.active == 2:
            self.two_running.set()
        try:
            await self.release.wait()
            if self.failure is not None:
                raise self.failure
            return await DeterministicRuntime().infer(request)
        finally:
            self.active -= 1
            self.cleaned += 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_workers", 0),
        ("max_workers", 33),
        ("max_workers", True),
        ("queue_capacity", 0),
        ("queue_capacity", 1025),
        ("queue_capacity", "5"),
        ("cache_capacity", 0),
        ("cache_capacity", 4097),
        ("job_timeout_seconds", 0),
        ("job_timeout_seconds", 31),
        ("job_timeout_seconds", float("nan")),
        ("job_timeout_seconds", True),
        ("cache_ttl_seconds", 0),
        ("cache_ttl_seconds", 3601),
        ("cache_ttl_seconds", float("inf")),
    ],
)
def test_resource_rejection(field: str, value: Any) -> None:
    """No coercion or unbounded resource settings are permitted."""
    with pytest.raises(ConfigurationError):
        ExecutionConfig(**{field: value})


def test_cache_semantics() -> None:
    """Exact keys, TTL boundaries, LRU eviction, invalidation, and counters work."""
    now = [0.0]
    cache = LocalInferenceCache(
        ExecutionConfig(cache_capacity=2, cache_ttl_seconds=1), clock=lambda: now[0]
    )
    request = InferenceRequest("synthetic private secret")
    key = cache_key(request)
    assert len(key) == 64 and "secret" not in key
    assert key == cache_key(request)
    assert key != cache_key(InferenceRequest(request.text, 1))
    assert key != cache_key(InferenceRequest(request.text.upper()))
    result = asyncio.run(InferenceService().infer(request))
    assert cache.get(key) is None
    cache.put(key, result)
    assert cache.get(key) is result
    cache.put("second", result)
    cache.get(key)
    cache.put("third", result)
    assert cache.get("second") is None
    now[0] = 1
    assert cache.get(key) is None
    stats = cache.stats()
    assert (stats.hits, stats.misses, stats.evictions, stats.expirations, stats.entries) == (
        2,
        3,
        1,
        2,
        0,
    )
    cache.put(key, result)
    cache.invalidate(key)
    cache.invalidate(key)
    assert cache.get(key) is None


def test_cache_thread_safety() -> None:
    """Concurrent cache calls preserve capacity and deterministic evidence."""
    cache = LocalInferenceCache(ExecutionConfig(cache_capacity=2))
    result = asyncio.run(InferenceService().infer(InferenceRequest("data")))

    def use(index: int) -> None:
        """Exercise concurrent mutation without requiring a hit across eviction."""
        cache.put(str(index % 3), result)
        found = cache.get(str(index % 3))
        assert found is None or found.evidence is EvidenceClass.DETERMINISTIC

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(use, range(100)))
    assert cache.stats().entries <= 2


def test_queue_bounds_and_success() -> None:
    """Fixed workers, queue saturation, job states and no per-submission tasks."""

    async def exercise() -> None:
        runtime = ControlledRuntime()
        queue = LocalExecution(
            InferenceService(runtime=runtime), ExecutionConfig(max_workers=1, queue_capacity=2)
        )
        with pytest.raises(QueueUnavailable):
            queue.submit(InferenceRequest("data"))
        await queue.start()
        await queue.start()
        first = queue.submit(InferenceRequest("first"))
        await runtime.entered.wait()
        assert first.state is JobState.RUNNING
        baseline_tasks = len(asyncio.all_tasks())
        second = queue.submit(InferenceRequest("second"))
        third = queue.submit(InferenceRequest("third"))
        assert second.state is JobState.QUEUED
        assert len(asyncio.all_tasks()) == baseline_tasks
        with pytest.raises(QueueUnavailable):
            queue.submit(InferenceRequest("overflow"))
        assert len({first.id, second.id, third.id}) == 3
        runtime.release.set()
        for job in (first, second, third):
            assert (await job.result()).evidence is EvidenceClass.DETERMINISTIC
            assert job.state is JobState.SUCCEEDED
            await queue.cancel(job)
        assert runtime.peak == 1
        assert not queue._active
        await queue.close()
        await queue.close()
        assert not queue.accepting
        with pytest.raises(QueueUnavailable):
            queue.submit(InferenceRequest("closed"))
        with pytest.raises(QueueUnavailable):
            await queue.start()
        with pytest.raises(UnknownJob):
            await queue.cancel(Job())

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeFailure("private"),
        TypeError("private"),
        TimeoutError("private"),
        asyncio.CancelledError(),
    ],
)
def test_failure_and_worker_survival(failure: BaseException) -> None:
    """Expected failures, defects, provider timeout and cancellation stay distinct."""

    async def exercise() -> None:
        runtime = ControlledRuntime(failure)
        runtime.release.set()
        queue = LocalExecution(InferenceService(runtime=runtime))
        await queue.start()
        job = queue.submit(InferenceRequest("data"))
        with pytest.raises(
            type(failure) if not isinstance(failure, RuntimeFailure) else InferenceFailure
        ):
            await job.result()
        assert job.state is (
            JobState.CANCELLED if isinstance(failure, asyncio.CancelledError) else JobState.FAILED
        )
        runtime.failure = None
        assert (await queue.infer(InferenceRequest("next"))).word_count == 1
        assert queue.accepting
        await queue.close()

    asyncio.run(exercise())


def test_execution_timeout() -> None:
    """Worker deadline cancels execution and the worker continues accepting work."""

    async def exercise() -> None:
        runtime = ControlledRuntime()
        queue = LocalExecution(
            InferenceService(runtime=runtime), ExecutionConfig(job_timeout_seconds=0.1)
        )
        await queue.start()
        job = queue.submit(InferenceRequest("data"))
        with pytest.raises(JobTimeout):
            await job.result()
        assert job.state is JobState.TIMED_OUT and runtime.cleaned == 1
        runtime.release.set()
        await queue.infer(InferenceRequest("next"))
        await queue.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("shutdown", [False, True])
def test_cancellation_and_shutdown(shutdown: bool) -> None:
    """Queued/running work cancels, cooperative cleanup finishes and no tasks remain."""

    async def exercise() -> None:
        baseline = set(asyncio.all_tasks())
        runtime = ControlledRuntime()
        queue = LocalExecution(InferenceService(runtime=runtime), ExecutionConfig(max_workers=1))
        await queue.start()
        running = queue.submit(InferenceRequest("running"))
        await runtime.entered.wait()
        pending = queue.submit(InferenceRequest("pending"))
        if shutdown:
            await queue.close()
        else:
            await queue.cancel(pending)
            await queue.cancel(running)
        for job in (running, pending):
            with pytest.raises(asyncio.CancelledError):
                await job.result()
            assert job.state is JobState.CANCELLED
        await queue.close()
        assert runtime.cleaned == 1 and runtime.calls == 1
        assert set(asyncio.all_tasks()) == baseline
        assert not queue._active

    asyncio.run(exercise())


def test_caller_cancellation() -> None:
    """Cancellation of synchronous-result inference waits for runtime cleanup."""

    async def exercise() -> None:
        runtime = ControlledRuntime()
        queue = LocalExecution(InferenceService(runtime=runtime))
        await queue.start()
        task = asyncio.create_task(queue.infer(InferenceRequest("data")))
        await runtime.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.cleaned == 1
        await queue.close()

    asyncio.run(exercise())


def test_local_performance(capsys: pytest.CaptureFixture[str]) -> None:
    """LOCAL/DETERMINISTIC/NON-PRODUCTION measured workload; no timing pass threshold."""

    async def exercise() -> None:
        runtime = ControlledRuntime()
        queue = LocalExecution(
            InferenceService(runtime=runtime), ExecutionConfig(max_workers=2, queue_capacity=8)
        )
        await queue.start()
        started = time.perf_counter()
        jobs = [queue.submit(InferenceRequest(f"word {i}")) for i in range(8)]
        with pytest.raises(QueueUnavailable):
            queue.submit(InferenceRequest("overflow"))
        await runtime.two_running.wait()
        runtime.release.set()
        for job in jobs:
            await job.result()
        cold_seconds = time.perf_counter() - started
        calls = runtime.calls
        started = time.perf_counter()
        for i in range(8):
            result = await queue.infer(InferenceRequest(f"word {i}"))
            assert result.evidence is EvidenceClass.DETERMINISTIC
        warm_seconds = time.perf_counter() - started
        assert runtime.calls == calls == 8
        assert runtime.peak == 2
        assert queue.cache.stats().hits == 8
        await queue.close()
        print(
            f"LOCAL DETERMINISTIC NON-PRODUCTION cold={cold_seconds:.6f}s "
            f"warm={warm_seconds:.6f}s calls={calls} hits=8 peak={runtime.peak}"
        )

    asyncio.run(exercise())
    output = capsys.readouterr().out
    assert "LOCAL DETERMINISTIC NON-PRODUCTION" in output
    # Run pytest with --capture=tee-sys to retain the actual measurement.
    print(output.strip())


def test_http_cache_integration() -> None:
    """Existing endpoint preserves its response and reuses actual cached work."""
    app = create_app(execution_config=ExecutionConfig(max_workers=1, cache_capacity=2))
    with TestClient(app) as client:
        first = client.post("/api/v1/inference", json={"text": "data"})
        second = client.post("/api/v1/inference", json={"text": "data"})
        assert first.status_code == second.status_code == 200
        assert first.json()["evidence"] == second.json()["evidence"] == "deterministic"
        assert app.state.execution.cache.stats().hits == 1
    assert not app.state.execution.accepting


def test_http_saturation_and_readiness() -> None:
    """Actual HTTP admission rejects saturation while healthy workers stay ready."""

    async def exercise() -> None:
        runtime = ControlledRuntime()
        app = create_app(
            service=InferenceService(runtime=runtime),
            execution_config=ExecutionConfig(max_workers=1, queue_capacity=1),
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                first = asyncio.create_task(client.post("/api/v1/inference", json={"text": "one"}))
                await runtime.entered.wait()
                pending = app.state.execution.submit(InferenceRequest("two"))
                response = await client.post("/api/v1/inference", json={"text": "private"})
                assert response.status_code == 503
                assert response.json()["code"] == "queue_unavailable"
                assert "private" not in response.text
                assert response.headers["x-request-id"] == response.json()["request_id"]
                assert (await client.get("/health/ready")).status_code == 200
                stats = app.state.execution.stats()
                assert (stats.running, stats.pending_slots, stats.rejected) == (1, 1, 1)
                runtime.release.set()
                assert (await first).status_code == 200
                await pending.result()

    asyncio.run(exercise())


def test_http_worker_timeout() -> None:
    """Separate worker deadline returns the established safe 504 contract."""
    runtime = ControlledRuntime()
    app = create_app(
        service=InferenceService(runtime=runtime),
        execution_config=ExecutionConfig(job_timeout_seconds=0.1),
    )
    with TestClient(app) as client:
        response = client.post("/api/v1/inference", json={"text": "data"})
        assert response.status_code == 504
        assert response.json()["code"] == "inference_timeout"
        assert runtime.cleaned == 1
        assert client.get("/health/ready").status_code == 200


def test_invalid_handles_and_config() -> None:
    """Foreign or invalid handles cannot control another queue's work."""

    async def exercise() -> None:
        queue = LocalExecution(InferenceService())
        other = LocalExecution(InferenceService())
        await other.start()
        job = other.submit(InferenceRequest("data"))
        for handle in (job, "unsafe/id", None):
            with pytest.raises(UnknownJob):
                await queue.cancel(handle)
        assert (await job.result()).word_count == 1
        await other.close()
        with pytest.raises(ConfigurationError):
            LocalExecution(InferenceService(), config={})
        with pytest.raises(ConfigurationError):
            create_app(execution_config={})

    asyncio.run(exercise())


def test_cache_failures_and_untrusted_output() -> None:
    """Cache defects and corrupted evidence never become successful HTTP results."""
    app = create_app()
    cache = app.state.execution.cache
    result = asyncio.run(InferenceService().infer(InferenceRequest("data")))
    cache.put(cache_key(InferenceRequest("data")), result)
    object.__setattr__(result, "evidence", EvidenceClass.LIVE_CLOUD)
    with TestClient(app) as client:
        response = client.post("/api/v1/inference", json={"text": "data"})
        assert response.status_code == 503
        assert "live-cloud" not in response.text

    class BrokenCache:
        """Trusted adapter failing at its genuine lookup boundary."""

        def get(self, key: str) -> InferenceResult | None:
            """Raise a sensitive defect that must remain internal."""
            raise OSError("private/path/secret")

    app = create_app()
    app.state.execution.cache = BrokenCache()
    with TestClient(app) as client:
        response = client.post("/api/v1/inference", json={"text": "data"})
        assert response.status_code == 500
        assert "private" not in response.text
        assert client.get("/health/ready").status_code == 200


def test_cache_cannot_bypass_service_admission() -> None:
    """Prepopulated adapter output cannot bypass accepted request ceiling validation."""

    async def exercise() -> None:
        request = InferenceRequest("oversized")
        cache = LocalInferenceCache(ExecutionConfig())
        cache.put(cache_key(request), await InferenceService().infer(request))
        service = InferenceService(RuntimeConfig(max_text_characters=1))
        queue = LocalExecution(service, cache=cache)
        await queue.start()
        with pytest.raises(ContractError):
            queue.submit(request)
        assert cache.stats().hits == 0
        assert queue.stats().submitted == 0
        await queue.close()

    asyncio.run(exercise())
