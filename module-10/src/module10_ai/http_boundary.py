"""Pure ASGI request bounds, correlation, and final sanitized failure boundary."""

import asyncio
import re
import time
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from module10_ai.http_config import HttpConfig
from module10_ai.telemetry import CORRELATION, Telemetry, correlation_id, failure_category


def error_response(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    """Construct a stable public failure without serializing internal diagnostics."""
    return JSONResponse(
        {"code": code, "message": message, "request_id": request_id}, status_code=status
    )


def record_failure(exc: Exception, telemetry: Telemetry) -> None:
    """Emit a fixed classification; raw IDs and exception internals are excluded."""
    telemetry.event("application.failure", status="failure", category=failure_category(exc))


class HttpBoundary:
    """Bound raw input before FastAPI buffers or validates it."""

    def __init__(self, app: ASGIApp, config: HttpConfig, telemetry: Telemetry) -> None:
        """Bind the downstream application and validated HTTP settings."""
        self.app = app
        self.config = config
        self.telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Measure the complete HTTP boundary including framing/validation rejection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = CORRELATION.set(None)
        begin = time.monotonic()
        status = "cancelled"

        async def observed_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = "success" if message["status"] < 400 else "failure"
                if message["status"] in (408, 504):
                    status = "timeout"
            await send(message)

        try:
            await self._serve(scope, receive, observed_send)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            status = "failure"
            raise
        finally:
            # Successful health probes remain quiet; failed readiness is actionable.
            if scope["path"] not in ("/health/live", "/health/ready") or status != "success":
                self.telemetry.event(
                    "http.completed", status=status, duration=time.monotonic() - begin
                )
            CORRELATION.reset(token)

    async def _serve(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Validate framing, bound body reads, and preserve caller cancellation."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        ids = [value for name, value in headers if name.lower() == b"x-request-id"]
        request_id = uuid4().hex
        if (
            len(ids) == 1
            and 1 <= len(ids[0]) <= self.config.max_request_id_characters
            and re.fullmatch(rb"[A-Za-z0-9_-]+", ids[0])
        ):
            request_id = ids[0].decode("ascii")
        scope.setdefault("state", {})["request_id"] = request_id
        CORRELATION.set(correlation_id(request_id))
        started = False

        async def safe_send(message: Message) -> None:
            """Attach safe correlation metadata to every HTTP response."""
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in (b"x-request-id", b"x-content-type-options")
                ] + [
                    (b"x-request-id", request_id.encode("ascii")),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        async def reject(status: int, code: str, message: str) -> None:
            """Send a bounded failure without draining an attacker-controlled body."""
            await error_response(status, code, message, request_id)(scope, receive, safe_send)

        if (
            len(headers) > 64
            or sum(len(k) + len(v) for k, v in headers) > 8192
            or any(len(k) > 128 or len(v) > 2048 for k, v in headers)
        ):
            await reject(431, "headers_too_large", "Request headers exceed supported bounds.")
            return
        lengths = [v for k, v in headers if k.lower() == b"content-length"]
        encodings = [v for k, v in headers if k.lower() == b"content-encoding"]
        if encodings and encodings != [b"identity"]:
            await reject(415, "unsupported_encoding", "Compressed request bodies are unsupported.")
            return
        if len(lengths) > 1 or (lengths and not re.fullmatch(rb"[0-9]{1,10}", lengths[0])):
            await reject(400, "invalid_framing", "Invalid request body framing.")
            return
        declared = int(lengths[0]) if lengths else None
        if declared is not None and declared > self.config.max_body_bytes:
            await reject(413, "body_too_large", "Request body exceeds supported bounds.")
            return
        if scope["path"] == "/api/v1/inference" and scope["method"] == "POST":
            types = [v for k, v in headers if k.lower() == b"content-type"]
            if len(types) != 1 or types[0].split(b";", 1)[0].strip().lower() != b"application/json":
                await reject(415, "unsupported_media_type", "Use application/json.")
                return
        body = bytearray()
        try:
            async with asyncio.timeout(self.config.body_timeout_seconds):
                while True:
                    chunk = await receive()
                    if chunk["type"] == "http.disconnect":
                        return
                    data = chunk.get("body", b"")
                    if len(body) + len(data) > self.config.max_body_bytes:
                        await reject(
                            413, "body_too_large", "Request body exceeds supported bounds."
                        )
                        return
                    body.extend(data)
                    if not chunk.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "body_timeout", "Request body deadline exceeded.")
            return
        if declared is not None and declared != len(body):
            await reject(400, "invalid_framing", "Invalid request body framing.")
            return
        delivered = False

        async def bounded_receive() -> Message:
            """Replay the bounded body once, then retain ASGI disconnect semantics."""
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        try:
            await self.app(scope, bounded_receive, safe_send)
        except Exception as exc:
            # Deliberately exclude BaseException/CancelledError. Never log payloads,
            # exception messages, filenames, or traceback locals containing secrets.
            record_failure(exc, self.telemetry)
            if started:
                raise
            await reject(500, "internal_error", "An internal service error occurred.")
