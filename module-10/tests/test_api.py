"""HTTP contracts, failure paths, resource bounds, and lifecycle evidence."""

import asyncio
import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message

from module10_ai import InferenceRequest, InferenceResult, InferenceService, RuntimeConfig
from module10_ai.api import create_app
from module10_ai.errors import ConfigurationError, ContractError, RuntimeFailure
from module10_ai.http_config import HttpConfig


class FailureRuntime:
    """Inject a trusted failure, counting any execution attempt."""

    def __init__(self, failure: BaseException) -> None:
        """Store the exact failure for expected and unexpected paths."""
        self.failure = failure
        self.calls = 0

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Raise a controlled failure at the provider boundary."""
        self.calls += 1
        raise self.failure


class SlowRuntime:
    """Exercise a cooperative deadline with observable cancellation cleanup."""

    cancelled = False
    started = False

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Wait until cancelled and retain cancellation semantics."""
        self.started = True
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("Unexpected completion")


def test_construction_health_and_lifecycle() -> None:
    """Readiness reflects lifespan while liveness remains lightweight."""
    app = create_app()
    assert not app.state.ready
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "alive", "mode": "deterministic"}
        assert client.get("/health/ready").json()["status"] == "ready"
        app.state.ready = False
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200
        assert client.post("/api/v1/inference", json={"text": "data"}).status_code == 503
    assert not app.state.ready


def test_http_inference_contract() -> None:
    """The accepted deterministic behavior passes through typed HTTP conversion."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/inference",
            json={
                "text": "Beta alpha beta gamma",
                "keyword_limit": 3,
            },
            headers={"X-Request-ID": "review_123-ABC"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "word_count": 4,
            "keywords": ["beta", "alpha", "gamma"],
            "evidence": "deterministic",
            "request_id": "review_123-ABC",
        }
        assert response.headers["x-request-id"] == "review_123-ABC"
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("identifier", [None, "", "bad id", "bad.id", "x" * 65, "bad\tvalue"])
def test_identifier_replacement(identifier: str | None) -> None:
    """Missing, malformed, and unbounded IDs become fresh safe identifiers."""
    headers = {} if identifier is None else {"x-request-id": identifier}
    with TestClient(create_app()) as client:
        responses = [
            client.post("/api/v1/inference", json={"text": "data"}, headers=headers)
            for _ in range(2)
        ]
    ids = [r.headers["x-request-id"] for r in responses]
    assert all(re.fullmatch(r"[0-9a-f]{32}", value) for value in ids)
    assert ids[0] != ids[1]
    assert all(r.json()["request_id"] == r.headers["x-request-id"] for r in responses)


def test_duplicate_identifier_replaced() -> None:
    """Ambiguous repeated headers are never trusted for correlation."""
    with TestClient(create_app()) as client:
        response = client.get(
            "/health/live", headers=[("x-request-id", "first"), ("x-request-id", "second")]
        )
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": ""},
        {"text": " \n"},
        {"text": "x" * 4097},
        {"text": 123},
        {"text": "data", "keyword_limit": True},
        {"text": "data", "keyword_limit": "3"},
        {"text": "data", "keyword_limit": 0},
        {"text": "data", "keyword_limit": 11},
        {"text": "data", "secret-field": "synthetic-secret"},
        ["synthetic-secret"],
    ],
)
def test_schema_rejection(payload: Any) -> None:
    """Invalid input receives fixed-size public errors without raw values or locations."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/inference", json=payload)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "request_id"}
    assert response.json()["code"] == "invalid_request"
    assert "synthetic-secret" not in response.text
    assert len(response.content) < 256


@pytest.mark.parametrize("body", [b'{"text":', b"\xff", b"[" * 1500])
def test_malformed_json(body: bytes) -> None:
    """Malformed encoding, JSON, and excessive nesting cannot leak parser details."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/inference", content=body, headers={"content-type": "application/json"}
        )
    assert response.status_code in (400, 422)
    assert set(response.json()) == {"code", "message", "request_id"}


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/octet-stream"])
def test_content_type(content_type: str | None) -> None:
    """Only declared JSON reaches inference body parsing."""
    headers = {} if content_type is None else {"content-type": content_type}
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/inference", content=b"{}", headers=headers)
    assert response.status_code == 415


def test_configured_text_and_body_bounds() -> None:
    """HTTP text ceilings and raw bytes constrain processing independently."""
    runtime = FailureRuntime(AssertionError("Must not execute"))
    with TestClient(
        create_app(
            HttpConfig(max_text_characters=3, max_body_bytes=128), InferenceService(runtime=runtime)
        )
    ) as client:
        assert client.post("/api/v1/inference", json={"text": "four"}).status_code == 422
        assert client.post("/api/v1/inference", json={"text": "x" * 200}).status_code == 413
    assert runtime.calls == 0


def test_timeout_cancels_runtime() -> None:
    """The configured deadline produces a safe 504 and cancels awaited work."""
    runtime = SlowRuntime()
    with TestClient(
        create_app(HttpConfig(inference_timeout_seconds=0.01), InferenceService(runtime=runtime))
    ) as client:
        response = client.post("/api/v1/inference", json={"text": "data"})
    assert response.status_code == 504
    assert response.json()["code"] == "inference_timeout"
    assert runtime.cancelled


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (RuntimeFailure("secret C:/private/key.txt"), 503, "inference_unavailable"),
        (ContractError("secret C:/private/key.txt"), 503, "inference_unavailable"),
        (TypeError("secret C:/private/key.txt"), 500, "internal_error"),
    ],
)
def test_failure_sanitization(
    failure: Exception, status: int, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Expected failures and defects expose stable contracts without sensitive internals."""
    with TestClient(
        create_app(service=InferenceService(runtime=FailureRuntime(failure)))
    ) as client:
        response = client.post(
            "/api/v1/inference", json={"text": "private input"}, headers={"x-request-id": "safe-id"}
        )
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"] == "safe-id"
    for value in ("secret", "C:/private", "key.txt", "private input", "Traceback"):
        assert value not in response.text
        assert value not in caplog.text


def test_domain_failure_mapping() -> None:
    """A stricter injected application contract maps caller rejection to 422."""
    with TestClient(
        create_app(service=InferenceService(RuntimeConfig(max_text_characters=1)))
    ) as c:
        response = c.post("/api/v1/inference", json={"text": "data"})
    assert response.status_code == 422


async def raw_request(
    app: Any, chunks: list[Message], headers: list[tuple[bytes, bytes]], delay: float = 0
) -> list[Message]:
    """Send raw ASGI messages to verify bounds without client-side framing assistance."""
    messages: list[Message] = []
    position = 0

    async def receive() -> Message:
        """Deliver chunks and simulate slow clients when requested."""
        nonlocal position
        await asyncio.sleep(delay)
        if position >= len(chunks):
            return {"type": "http.disconnect"}
        message = chunks[position]
        position += 1
        return message

    async def send(message: Message) -> None:
        """Capture actual emitted ASGI response messages."""
        messages.append(message)

    async with app.router.lifespan_context(app):
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/inference",
                "raw_path": b"/api/v1/inference",
                "query_string": b"",
                "headers": headers,
                "client": ("127.0.0.1", 1),
                "server": ("test", 80),
            },
            receive,
            send,
        )
    return messages


@pytest.mark.parametrize(
    "headers,body,status",
    [
        ([], b"x" * 129, 413),
        ([(b"content-length", b"2")], b"x" * 129, 413),
        ([(b"content-length", b"129")], b"", 413),
        ([(b"content-length", b"bad")], b"{}", 400),
        ([(b"content-length", b"1"), (b"content-length", b"1")], b"{}", 400),
        ([(b"content-length", b"1")], b"{}", 400),
        ([(b"content-encoding", b"gzip")], b"{}", 415),
        ([(b"content-type", b"application/json")], b"{}", 415),
        ([(b"x-request-id", b"x" * 2049)], b"{}", 431),
        ([(b"x-extra", b"x" * 2000)] * 5, b"{}", 431),
        ([(b"x-extra", b"x")] * 65, b"{}", 431),
    ],
)
def test_raw_body_and_header_bounds(
    headers: list[tuple[bytes, bytes]], body: bytes, status: int
) -> None:
    """Actual streamed bytes, declared framing, and relevant headers are bounded."""
    runtime = FailureRuntime(AssertionError("Must not execute"))
    chunks = [
        {"type": "http.request", "body": body[:64], "more_body": True},
        {"type": "http.request", "body": body[64:], "more_body": False},
    ]
    messages = asyncio.run(
        raw_request(
            create_app(HttpConfig(max_body_bytes=128), InferenceService(runtime=runtime)),
            chunks,
            [(b"content-type", b"application/json"), *headers],
        )
    )
    assert messages[0]["status"] == status
    assert runtime.calls == 0
    assert "request_id" in json.loads(messages[1]["body"])


def test_body_read_timeout() -> None:
    """Slow request bodies expire independently of inference execution."""
    messages = asyncio.run(
        raw_request(
            create_app(HttpConfig(body_timeout_seconds=0.01)),
            [],
            [(b"content-type", b"application/json")],
            delay=0.1,
        )
    )
    assert messages[0]["status"] == 408


def test_disconnect_does_not_execute() -> None:
    """Disconnect before complete body returns without invoking the service."""
    runtime = FailureRuntime(AssertionError("Must not execute"))
    messages = asyncio.run(
        raw_request(
            create_app(service=InferenceService(runtime=runtime)),
            [],
            [(b"content-type", b"application/json")],
        )
    )
    assert messages == []
    assert runtime.calls == 0


def test_cancellation_propagates_through_http() -> None:
    """External task cancellation is never converted into an HTTP failure."""
    runtime = FailureRuntime(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            raw_request(
                create_app(service=InferenceService(runtime=runtime)),
                [{"type": "http.request", "body": b'{"text":"data"}', "more_body": False}],
                [(b"content-type", b"application/json")],
            )
        )
    assert runtime.calls == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("inference_timeout_seconds", 0),
        ("inference_timeout_seconds", 31),
        ("inference_timeout_seconds", float("nan")),
        ("inference_timeout_seconds", float("inf")),
        ("inference_timeout_seconds", True),
        ("body_timeout_seconds", "5"),
        ("max_body_bytes", 127),
        ("max_body_bytes", 65537),
        ("max_body_bytes", True),
        ("max_text_characters", 0),
        ("max_text_characters", 4097),
        ("max_request_id_characters", 31),
        ("max_request_id_characters", 129),
        ("docs_enabled", 1),
    ],
)
def test_configuration_rejection(field: str, value: Any) -> None:
    """HTTP settings reject unsafe values without coercion."""
    with pytest.raises(ConfigurationError):
        HttpConfig(**{field: value})


def test_configuration_inclusive_bounds() -> None:
    """Both ends of each supported HTTP configuration interval are valid."""
    HttpConfig(
        inference_timeout_seconds=0.01,
        body_timeout_seconds=30,
        max_body_bytes=128,
        max_text_characters=1,
        max_request_id_characters=32,
    )
    HttpConfig(
        inference_timeout_seconds=30,
        body_timeout_seconds=0.01,
        max_body_bytes=65536,
        max_text_characters=4096,
        max_request_id_characters=128,
        docs_enabled=True,
    )
    with pytest.raises(ConfigurationError):
        create_app(config={})
    with pytest.raises(ConfigurationError):
        create_app(service={})


def test_openapi_contract_and_docs_defaults() -> None:
    """OpenAPI describes strict inputs, deterministic outputs, health, and safe failures."""
    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {"/api/v1/inference", "/health/live", "/health/ready"}
    operation = schema["paths"]["/api/v1/inference"]["post"]
    assert operation["requestBody"]["required"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/InferenceOutput"
    }
    for status in ("400", "408", "413", "415", "422", "431", "500", "503", "504"):
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorOutput"
        }
    models = schema["components"]["schemas"]
    assert models["InferenceInput"]["additionalProperties"] is False
    assert models["InferenceInput"]["properties"]["text"]["maxLength"] == 4096
    assert models["InferenceInput"]["properties"]["keyword_limit"]["maximum"] == 10
    assert models["InferenceOutput"]["properties"]["evidence"]["const"] == "deterministic"
    parameter = operation["parameters"][0]
    assert parameter["name"] == "X-Request-ID"
    assert parameter["schema"]["maxLength"] == 64
    assert "X-Request-ID" in operation["responses"]["200"]["headers"]
    assert "503" in schema["paths"]["/health/ready"]["get"]["responses"]
    with TestClient(create_app(HttpConfig(docs_enabled=True))) as client:
        assert client.get("/docs").status_code == 200


def test_external_task_cancellation() -> None:
    """Cancelling an in-flight HTTP task interrupts inference and runs cleanup."""

    async def exercise() -> None:
        """Cancel only after the runtime has entered its await boundary."""
        runtime = SlowRuntime()
        task = asyncio.create_task(
            raw_request(
                create_app(service=InferenceService(runtime=runtime)),
                [{"type": "http.request", "body": b'{"text":"data"}', "more_body": False}],
                [(b"content-type", b"application/json")],
            )
        )
        async with asyncio.timeout(1):
            while not runtime.started:
                await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.cancelled

    asyncio.run(exercise())


def test_provider_timeout_is_not_api_deadline() -> None:
    """Unclassified provider TimeoutError remains a sanitized defect, not a fake deadline."""
    with TestClient(
        create_app(
            service=InferenceService(
                runtime=FailureRuntime(TimeoutError("sensitive provider detail")),
            )
        )
    ) as client:
        response = client.post("/api/v1/inference", json={"text": "data"})
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "sensitive" not in response.text


def test_inclusive_http_input_and_identifier_bounds() -> None:
    """Maximum Unicode input, keyword limit, and valid identifier remain usable."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/inference",
            json={"text": "é" * 4096, "keyword_limit": 10},
            headers={"x-request-id": "x" * 64},
        )
    assert response.status_code == 200
    assert response.json()["keywords"] == ["é" * 4096]
    assert response.headers["x-request-id"] == "x" * 64
