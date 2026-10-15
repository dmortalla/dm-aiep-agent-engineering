"""Story 10.6 deterministic observability, adversarial input and failure isolation."""

import asyncio
import json
import math
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from module10_ai import DeterministicRuntime, InferenceRequest, InferenceResult, InferenceService
from module10_ai.api import create_app
from module10_ai.cache import LocalInferenceCache
from module10_ai.errors import ConfigurationError, RuntimeFailure
from module10_ai.execution import JobTimeout, LocalExecution, QueueUnavailable
from module10_ai.execution_config import ExecutionConfig
from module10_ai.telemetry import (
    CATEGORIES,
    CORRELATION,
    EVENTS,
    GAUGES,
    LIMIT,
    LOGGER,
    STATUSES,
    Telemetry,
    correlation_id,
)


class GatedRuntime:
    """Hold a worker without relying on timing to produce queue saturation."""

    def __init__(self, failure: Exception | None = None) -> None:
        """Bind an optional failure and explicit worker gate."""
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.failure = failure

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Signal entry, wait cooperatively, then fail or return deterministic data."""
        self.entered.set()
        await self.release.wait()
        if self.failure is not None:
            raise self.failure
        return await DeterministicRuntime().infer(request)


def broken_sink(record: str) -> None:
    """Inject a handler failure containing sensitive text that must stay internal."""
    raise RuntimeError("secret-handler-value /private/file.py")


def test_http_correlation_and_minimization() -> None:
    """HTTP identity stays compatible while every related event uses its safe digest."""
    lines: list[str] = []
    telemetry = Telemetry(lines.append)
    app = create_app(telemetry=telemetry)
    caller_id = "sk-proj-SyntheticSecretCallerValue"
    text = "password Bearer SyntheticSecretPrompt api_key"
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/api/v1/inference",
                json={"text": text},
                headers={
                    "X-Request-ID": caller_id,
                    "Authorization": "Bearer secret-auth",
                    "Cookie": "password=secret-cookie",
                },
            )
            assert response.status_code == 200
            assert response.headers["X-Request-ID"] == caller_id
        assert client.post("/api/v1/inference", json={"text": ""}).status_code == 422
        assert client.post(
            "/api/v1/inference", content=b"{", headers={"content-type": "application/json"}
        ).status_code in (400, 422)
        before = len(lines)
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert len(lines) == before
        assert client.get("/metrics").status_code == 404
    records = [json.loads(line) for line in lines]
    related = [
        record for record in records if record.get("correlation_id") == correlation_id(caller_id)
    ]
    assert {record["event"] for record in related} >= {
        "http.completed",
        "queue.admitted",
        "job.completed",
        "inference.completed",
        "cache.miss",
        "cache.hit",
    }
    for record in records:
        assert record["event"] in EVENTS
        assert record["status"] in STATUSES
        assert record["category"] in CATEGORIES
        assert record["severity"] in ("INFO", "ERROR")
        assert datetime.fromisoformat(record["timestamp"]).utcoffset().total_seconds() == 0
        assert len(json.dumps(record)) < 600
        assert set(record) <= {
            "schema_version",
            "event",
            "timestamp",
            "severity",
            "status",
            "category",
            "correlation_id",
            "job_id",
            "duration_seconds",
        }
    emitted = "\n".join(lines)
    for secret in (caller_id, text, "secret-auth", "secret-cookie", "password", "api_key"):
        assert secret not in emitted
    snapshot = telemetry.snapshot()
    assert snapshot["counters"]["http.completed:success"] == 2
    assert snapshot["counters"]["http.completed:failure"] == 3
    assert snapshot["counters"]["cache.hit:success"] == 1
    assert snapshot["counters"]["cache.miss:success"] == 1
    assert snapshot["counters"]["inference.completed:success"] == 1
    assert snapshot["durations"]["http.completed:success"]["count"] == 2
    assert snapshot["gauges"]["workers.active"] == 0
    assert CORRELATION.get() is None


@pytest.mark.parametrize("sink", [None, broken_sink])
@pytest.mark.parametrize(
    "failure",
    [
        None,
        RuntimeFailure("secret-provider-value"),
        ValueError("secret-defect-value /private/file.py"),
    ],
)
def test_sink_failure_preserves_business_outcome(sink: object, failure: Exception | None) -> None:
    """Unavailable/failing telemetry neither fails success nor converts failures to success."""
    runtime = GatedRuntime(failure)
    runtime.release.set()
    telemetry = Telemetry(sink)
    with TestClient(
        create_app(service=InferenceService(runtime=runtime), telemetry=telemetry)
    ) as c:
        response = c.post("/api/v1/inference", json={"text": "alpha beta"})
    assert response.status_code == (
        200 if failure is None else 503 if isinstance(failure, RuntimeFailure) else 500
    )
    assert "secret" not in response.text
    if sink is broken_sink:
        assert 1 <= telemetry.snapshot()["telemetry_failures"] <= 10


@pytest.mark.parametrize(
    "failure,category",
    [
        (RuntimeFailure("Bearer secret-exception"), "inference"),
        (ValueError("sk-proj-secret /private/file.py"), "internal"),
    ],
)
def test_safe_failure_classification(failure: Exception, category: str) -> None:
    """Operational failures reveal only application-controlled categories."""
    lines: list[str] = []
    runtime = GatedRuntime(failure)
    runtime.release.set()
    with TestClient(
        create_app(service=InferenceService(runtime=runtime), telemetry=Telemetry(lines.append))
    ) as c:
        assert c.post("/api/v1/inference", json={"text": "secret-prompt"}).status_code >= 500
    failures = [json.loads(line) for line in lines if '"event":"application.failure"' in line]
    assert len(failures) == 1
    assert failures[0]["category"] == category
    for value in ("Bearer", "sk-proj", "secret", "file.py", "Traceback", type(failure).__name__):
        assert value not in "\n".join(lines)


@pytest.mark.parametrize(
    "duration", [-1, float("nan"), float("inf"), float("-inf"), True, "secret", 10**1000, 86401]
)
def test_invalid_duration_is_isolated(duration: object) -> None:
    """Invalid/non-finite timing never emits or creates metric state."""
    lines: list[str] = []
    telemetry = Telemetry(lines.append)
    telemetry.event("http.completed", duration=duration)
    assert telemetry.snapshot()["telemetry_failures"] == 1
    assert telemetry.snapshot()["counters"] == {}
    assert lines == []


def test_serialization_and_handler_failure() -> None:
    """Both serialization and logger/handler exceptions are bounded failure boundaries."""
    telemetry = Telemetry()
    with patch("module10_ai.telemetry.json.dumps", side_effect=ValueError("secret-serializer")):
        telemetry.event("http.completed")
    with patch.object(LOGGER, "log", side_effect=RuntimeError("secret-handler")):
        telemetry.event("http.completed")
    assert telemetry.snapshot()["telemetry_failures"] == 2
    assert telemetry.snapshot()["counters"]["http.completed:success"] == 2


def test_logging_sink_emits_json() -> None:
    """The default sink forwards machine-readable JSON, without exception metadata."""
    with patch.object(LOGGER, "log") as emit:
        Telemetry().event("http.completed")
    severity, record = emit.call_args.args
    assert severity == 20
    assert json.loads(record)["event"] == "http.completed"
    assert emit.call_args.kwargs == {}


def test_fixed_cardinality_and_detached_snapshot() -> None:
    """Arbitrary labels/metadata cannot grow retention; aggregate arithmetic saturates."""
    telemetry = Telemetry(None)
    for i in range(1000):
        telemetry.event(f"secret-{i}")
        telemetry.gauge(f"secret-{i}", i)
        telemetry.event("http.completed", status=f"secret-{i}")
        telemetry.event("http.completed", category=f"secret-{i}")
    for name in EVENTS:
        for status in STATUSES:
            telemetry.event(name, status=status, duration=0.0, quantity=LIMIT)
            telemetry.event(name, status=status, duration=1.0)
    for name in GAUGES:
        telemetry.gauge(name, LIMIT + 1)
    telemetry.gauge("workers.active", True)
    snap = telemetry.snapshot()
    assert len(snap["counters"]) == len(EVENTS) * len(STATUSES)
    assert len(snap["durations"]) == len(EVENTS) * len(STATUSES)
    assert len(snap["gauges"]) == len(GAUGES)
    assert set(snap["counters"].values()) == {LIMIT}
    assert all(math.isfinite(v["sum"]) for v in snap["durations"].values())
    assert "secret" not in json.dumps(snap)
    snap["counters"].clear()
    assert telemetry.snapshot()["counters"]


@pytest.mark.parametrize(
    "value", ["Bearer token\r\ninjected=true", "sk-proj-secret", "x" * 100000],
    ids=["control-characters", "secret-like", "oversized"],
)
def test_adversarial_correlation(value: str) -> None:
    """Untrusted values are digested with bounded input and never reflected verbatim."""
    digest = correlation_id(value)
    assert len(digest) == 32 and digest == correlation_id(value)
    lines: list[str] = []
    telemetry = Telemetry(lines.append)
    token = CORRELATION.set(value)
    try:
        telemetry.event("http.completed", job_id=value)
    finally:
        CORRELATION.reset(token)
    assert value not in lines[0]
    assert "correlation_id" not in json.loads(lines[0])
    assert "job_id" not in json.loads(lines[0])


def test_worker_correlation_backpressure_and_cancellation() -> None:
    """Explicit job context survives fixed workers and isolation between submissions."""

    async def scenario() -> None:
        lines: list[str] = []
        telemetry = Telemetry(lines.append)
        runtime = GatedRuntime()
        execution = LocalExecution(
            InferenceService(runtime=runtime),
            ExecutionConfig(max_workers=1, queue_capacity=1),
            telemetry=telemetry,
        )
        await execution.start()
        token = CORRELATION.set(correlation_id("request-one"))
        first = execution.submit(InferenceRequest("alpha"))
        CORRELATION.reset(token)
        await runtime.entered.wait()
        token = CORRELATION.set(correlation_id("request-two"))
        second = execution.submit(InferenceRequest("beta"))
        CORRELATION.reset(token)
        with pytest.raises(QueueUnavailable):
            execution.submit(InferenceRequest("gamma"))
        assert telemetry.snapshot()["gauges"]["queue.pending"] == 1
        assert telemetry.snapshot()["gauges"]["workers.active"] == 1
        await execution.cancel(first)
        await execution.close()
        completed = [json.loads(s) for s in lines if '"event":"job.completed"' in s]
        assert {r["job_id"] for r in completed} == {first.id, second.id}
        assert {r["correlation_id"] for r in completed} == {
            correlation_id("request-one"),
            correlation_id("request-two"),
        }
        assert all(r["status"] == "cancelled" for r in completed)
        snapshot = telemetry.snapshot()
        assert snapshot["counters"]["queue.rejected:rejected"] == 1
        assert snapshot["counters"]["job.completed:cancelled"] == 2
        assert snapshot["gauges"]["workers.active"] == 0
        assert snapshot["gauges"]["queue.pending"] == 0
        assert CORRELATION.get() is None

    asyncio.run(scenario())


def test_job_timeout_metrics() -> None:
    """Cooperative timeout is counted independently from provider programming errors."""

    async def scenario() -> None:
        telemetry = Telemetry(None)
        execution = LocalExecution(
            InferenceService(runtime=GatedRuntime()),
            ExecutionConfig(job_timeout_seconds=0.01),
            telemetry=telemetry,
        )
        await execution.start()
        try:
            with pytest.raises(JobTimeout):
                await execution.infer(InferenceRequest("alpha"))
            assert telemetry.snapshot()["counters"]["job.completed:timeout"] == 1
        finally:
            await execution.close()

    asyncio.run(scenario())


def test_cache_maintenance_metrics_and_sink_isolation() -> None:
    """TTL/LRU semantics survive sink failure; maintenance/occupancy remain observable."""
    now = [0.0]
    telemetry = Telemetry(broken_sink)
    cache = LocalInferenceCache(
        ExecutionConfig(cache_capacity=1, cache_ttl_seconds=1),
        clock=lambda: now[0],
        telemetry=telemetry,
    )
    result = asyncio.run(DeterministicRuntime().infer(InferenceRequest("alpha")))
    assert cache.get("first") is None
    cache.put("first", result)
    assert cache.get("first") == result
    cache.put("second", result)
    now[0] = 2
    assert cache.get("second") is None
    snapshot = telemetry.snapshot()
    assert snapshot["gauges"]["cache.evictions"] == 1
    assert snapshot["gauges"]["cache.expirations"] == 1
    assert snapshot["gauges"]["cache.entries"] == 0
    cache.put("third", result)
    cache.invalidate("third")
    assert telemetry.snapshot()["gauges"]["cache.entries"] == 0


def test_invalid_configuration_and_readiness() -> None:
    """No arbitrary recorder implementation or invalid sink bypasses validated boundaries."""
    with pytest.raises(TypeError):
        Telemetry("secret")
    with pytest.raises(ConfigurationError):
        create_app(telemetry=object())
    telemetry = Telemetry(None)
    app = create_app(telemetry=telemetry)
    with TestClient(app) as client:
        app.state.ready = False
        assert client.get("/health/ready").status_code == 503
    assert telemetry.snapshot()["counters"]["readiness.failed:failure"] == 1


def test_actual_stream_failure_never_prints_diagnostics(capsys: pytest.CaptureFixture) -> None:
    """Standard logging's default traceback fallback must not expose stream failures."""
    telemetry = Telemetry()
    handler = LOGGER.handlers[0]
    with patch.object(handler, "stream") as stream:
        stream.write.side_effect = OSError("secret-stream-value /private/file.py")
        telemetry.event("http.completed")
    assert telemetry.snapshot()["telemetry_failures"] == 1
    assert telemetry.snapshot()["counters"]["http.completed:success"] == 1
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
