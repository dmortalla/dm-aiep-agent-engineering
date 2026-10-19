"""Private offline SDK worker; no application runtime or authority is passed in.

The parent strips environment configuration and bounds this entire process,
including SDK teardown. Only finite phase names go to stdout; stderr is discarded.
Socket denial is defense in depth in addition to controlled HTTP/OTel transports.
"""

import json
import logging
import socket
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from harness_engineering.observability import TelemetryEvent


class ProjectionFailure(Exception):
    """Safe finite SDK phase, with no retained external diagnostic."""


def _phase(name: str, operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except Exception:
        # Deliberate external SDK failure boundary. Never chain SDK payloads.
        raise ProjectionFailure(name) from None


def deny_network() -> None:
    """Install a fail-closed socket boundary before optional SDK imports."""
    def denied(*args: object, **kwargs: object) -> Any:
        raise OSError("Offline observability worker denies network access.")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied


def langsmith_projection(events: tuple[TelemetryEvent, ...]) -> list[dict[str, Any]]:
    """Exercise genuine 0.14.7 Client create/update over a non-socket Session.

    Captured bodies are test evidence only; the parent receives a finite status.
    Empty inputs/outputs, omitted runtime environment and closed event metadata
    exclude content. Each event is an independent projection run, not a claim
    that a start/finish pair constitutes two authoritative workflow executions.
    """
    import requests
    from langsmith import Client
    from langsmith.schemas import LangSmithInfo

    records: list[dict[str, Any]] = []

    class OfflineSession(requests.Session):
        def send(self, request: Any, **kwargs: Any) -> Any:
            if len(records) >= 128 or request.method not in ("POST", "PATCH"):
                raise ValueError("Offline SDK request bound exceeded.")
            if not request.url.startswith("https://observability.invalid/runs"):
                raise ValueError("Unsupported offline SDK path.")
            body = json.loads(request.body)
            records.append({"method": request.method, "body": body})
            response = requests.Response()
            response.status_code = 200
            response._content = b"{}"
            response.request = request
            return response

    session = OfflineSession()
    session.trust_env = False
    client = _phase("construction", lambda: Client(
        api_url="https://observability.invalid", api_key="offline-dummy",
        session=session, auto_batch_tracing=False, timeout_ms=100,
        hide_inputs=True, hide_outputs=True, omit_traced_runtime_info=True,
        tracing_sampling_rate=1.0, tracing_mode="langsmith",
        info=LangSmithInfo(), disable_prompt_cache=True,
    ))
    try:
        for event in events:
            metadata = event.model_dump(mode="json", exclude_none=True)
            _phase("create", lambda event=event, metadata=metadata: client.create_run(
                name="harness." + event.kind.value, inputs={}, run_type="chain",
                project_name="module-06-5-offline", id=event.event_id,
                trace_id=UUID(hex=event.trace.trace_id),
                start_time=datetime(2000, 1, 1, tzinfo=UTC),
                extra={"metadata": metadata},
            ))
            _phase("update", lambda event=event: client.update_run(
                event.event_id, outputs={}, end_time=datetime(2000, 1, 1, tzinfo=UTC),
                trace_id=UUID(hex=event.trace.trace_id),
            ))
        _phase("flush", lambda: client.flush(timeout=0.1))
    finally:
        _phase("close", lambda: client.close(timeout=0.1))
        session.close()
    if len(records) != 2 * len(events):
        raise ProjectionFailure("create")
    return records


def langfuse_projection(events: tuple[TelemetryEvent, ...]) -> list[dict[str, Any]]:
    """Exercise genuine 4.17.0 observations and OTel exporter without HTTP export."""
    import httpx
    from langfuse import Langfuse
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    records: list[dict[str, Any]] = []

    class OfflineExporter(SpanExporter):
        def export(self, spans: Any) -> SpanExportResult:
            for span in spans:
                if len(records) >= 64:
                    return SpanExportResult.FAILURE
                records.append({
                    "trace_id": format(span.context.trace_id, "032x"),
                    "parent_span_id": format(span.parent.span_id, "016x"),
                    "attributes": dict(span.attributes),
                })
            return SpanExportResult.SUCCESS

    def reject_http(request: httpx.Request) -> httpx.Response:
        raise OSError("No Langfuse HTTP request is supported offline.")

    http = httpx.Client(transport=httpx.MockTransport(reject_http), trust_env=False)
    provider = TracerProvider(resource=Resource({}), shutdown_on_exit=False)
    client = _phase("construction", lambda: Langfuse(
        public_key="offline-public", secret_key="offline-dummy",
        base_url="https://observability.invalid", httpx_client=http,
        environment="offline", release="module-06-5", timeout=1,
        sample_rate=1.0, flush_at=64, flush_interval=60,
        tracer_provider=provider, span_exporter=OfflineExporter(),
    ))
    try:
        for event in events:
            observation = _phase("create", lambda event=event: client.start_observation(
                name="harness." + event.kind.value,
                trace_context={"trace_id": event.trace.trace_id,
                               "parent_span_id": event.trace.span_id},
                metadata=event.model_dump(mode="json", exclude_none=True),
            ))
            _phase("update", observation.end)
        _phase("flush", client.flush)
        if len(records) != len(events):
            raise ProjectionFailure("flush")
    finally:
        _phase("close", client.shutdown)
        _phase("close", provider.shutdown)
        http.close()
    return records


def main() -> None:
    """Read <=64 strict events; emit only a finite result, never SDK diagnostics."""
    logging.disable(logging.CRITICAL)
    deny_network()
    try:
        raw = sys.stdin.read(262145)
        if len(raw) > 262144:
            raise ProjectionFailure("create")
        payload = json.loads(raw)
        if type(payload) is not list or not 1 <= len(payload) <= 64:
            raise ProjectionFailure("create")
        events = tuple(TelemetryEvent.model_validate_json(json.dumps(item)) for item in payload)
        if sys.argv[1] == "langsmith":
            langsmith_projection(events)
        elif sys.argv[1] == "langfuse":
            langfuse_projection(events)
        else:
            raise ProjectionFailure("construction")
    except ImportError:
        sys.stdout.write("unavailable")
    except ProjectionFailure as error:
        sys.stdout.write(str(error))
    except Exception:
        # Process entry boundary: malformed input/internal failure has no payload output.
        sys.stdout.write("construction")
    else:
        sys.stdout.write("ok")


if __name__ == "__main__":
    main()
