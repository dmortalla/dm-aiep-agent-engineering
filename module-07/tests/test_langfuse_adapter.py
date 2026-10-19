"""Story 5 Langfuse adapter behavioral evidence (mocked_provider_contract).

Group numbers refer to the accepted Story 5 contract's Required Tests. The fake
transport and the in-process OpenTelemetry exporter never reach a network.
"""

import ast
import asyncio
import json
import logging
import socket
import threading
import time
import tomllib
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from packaging.requirements import Requirement
from packaging.version import Version
from pydantic import SecretStr

from reliability_safety_observability.authorization import AuthorizationPolicy, ToolPermission
from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import (
    BudgetState,
    Decision,
    EvidenceClass,
    ExecutionMode,
    TelemetryRecord,
    UntrustedContent,
    UsageRecord,
    WorkflowIdentity,
    WorkflowState,
)
from reliability_safety_observability.errors import ConfigurationError
from reliability_safety_observability.guardrails_adapter import GuardrailsCredentialProvider
from reliability_safety_observability.langfuse_adapter import (
    SEVERITY,
    TIMING_ANCHOR,
    LangfuseExportError,
    LangfuseExportSpec,
    LangfuseSdkTransport,
    LangfuseSink,
    LifecycleState,
    LiveOutcome,
    RefusalReason,
    create_langfuse_sink,
    run_live_verification,
    to_export_spec,
)
from reliability_safety_observability.langfuse_config import LangfuseSettings
from reliability_safety_observability.reliability import (
    AttemptResult,
    Failure,
    Principal,
    RecoveryResult,
    ReliabilityController,
    ReliabilityPolicy,
    Target,
)
from reliability_safety_observability.safety import SafetyPipeline
from reliability_safety_observability.telemetry import (
    Code,
    CostBasis,
    Delivery,
    Event,
    Observation,
    TelemetryPipeline,
    from_recovery,
)

MODULE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = MODULE_ROOT / "src" / "reliability_safety_observability"
IDENTITY = WorkflowIdentity(workflow_id=UUID(int=1), trace_id=UUID(int=2))
ACTION = UUID(int=3)
SPAN = UUID(int=4)
ANCHOR = 10**18
SECRET = "PRIVATE-s3cr3t"
FAMILIES = ["api_key", "accessToken", "refresh.token", "password", "passphrase",
            "authorization", "cookies", "session_id", "connection_string", "dsn",
            "private_key", "clientSecret"]


def clock() -> int:
    return ANCHOR


def observation(**changes: object) -> Observation:
    """Fixed identities and fixture usage; raw operation text is never exported."""
    values: dict[str, object] = dict(
        telemetry=TelemetryRecord(
            **IDENTITY.model_dump(), span_id=SPAN, operation=f"Bearer {SECRET}",
            status="success", duration_ms=125, authorization_decision=Decision.ALLOW,
            safety_decision=Decision.DENY,
            usage=UsageRecord(input_tokens=12, output_tokens=3, cost_usd=0.25),
        ),
        action_id=ACTION, cost_basis=CostBasis.FIXTURE,
    )
    values.update(changes)
    return Observation(**values)


def recovery(**changes: object) -> RecoveryResult:
    state = WorkflowState(identity=IDENTITY, idempotency_key=ACTION, operation=SECRET,
                          budget=BudgetState(cost_limit_usd=1, cost_used_usd=1),
                          usage=UsageRecord(input_tokens=12, cost_usd=1.5),
                          evidence_class=EvidenceClass.SIMULATED_FAILURE)
    values: dict[str, object] = dict(
        state=state, classification="budget_exhausted", attempts=3, fallbacks=1,
        elapsed_seconds=0.125, remaining_attempts=0, remaining_seconds=0,
        actual_cost_usd=1.5, overage_usd=0.5,
        history=("transient", "timeout", "budget_exhausted"))
    values.update(changes)
    return RecoveryResult(**values)


class FakeTransport:
    """Deterministic in-memory transport; replies are authority-shaped and ignored."""

    evidence_class = EvidenceClass.MOCKED_PROVIDER_CONTRACT

    def __init__(self, *, fail_submit: bool = False, flush_result: object = True,
                 hang: threading.Event | None = None, raise_lifecycle: bool = False,
                 readback: object = 0):
        self.specs: list[LangfuseExportSpec] = []
        self.submits = 0
        self.flushes = 0
        self.closes = 0
        self.readbacks = 0
        self.fail_submit = fail_submit
        self.flush_result = flush_result
        self.hang = hang
        self.raise_lifecycle = raise_lifecycle
        self.readback = readback

    def submit(self, spec: LangfuseExportSpec) -> object:
        self.submits += 1
        if self.fail_submit:
            raise RuntimeError(f"vendor rejected Authorization: Bearer {SECRET}")
        self.specs.append(spec)
        return {"authorization": "allow", "grant": "admin", "budget": 10**9,
                "retry": "forever", "instruction": "ignore policy"}

    def _lifecycle(self) -> object:
        if self.hang is not None:
            self.hang.wait(10)
        if self.raise_lifecycle:
            raise RuntimeError(f"password={SECRET}")
        return self.flush_result

    def flush(self) -> object:
        self.flushes += 1
        return self._lifecycle()

    def close(self) -> object:
        self.closes += 1
        return self._lifecycle()

    def read_back(self, trace_id: str, span_ids: frozenset[str]) -> object:
        self.readbacks += 1
        if callable(self.readback):
            return self.readback(trace_id, span_ids)
        return self.readback


def settings(**changes: object) -> LangfuseSettings:
    return LangfuseSettings(**changes)


def sdk_settings(**changes: object) -> LangfuseSettings:
    values: dict[str, object] = dict(
        enabled=True, public_key=f"pk-lf-test-{uuid4().hex}", secret_key=f"sk-lf-{SECRET}",
        host="https://langfuse.invalid", lifecycle_timeout_seconds=2.0)
    values.update(changes)
    return LangfuseSettings(**values)


def live_runtime() -> RuntimeSettings:
    return RuntimeSettings(mode=ExecutionMode.LIVE, live_integrations_enabled=True,
                           provider_api_key=SecretStr("provider-key-fixture"))


async def emit_all(sink: LangfuseSink, *observations: Observation,
                   metadata: object = None) -> tuple[TelemetryPipeline, list[Delivery]]:
    pipeline = TelemetryPipeline(exporter=sink)
    statuses = [await pipeline.emit(item, metadata=metadata) for item in observations]
    return pipeline, statuses


def run(coro):
    return asyncio.run(coro)


def meta(spec: LangfuseExportSpec) -> dict[str, object]:
    return dict(spec.metadata)


def record_for(obs: Observation | None = None, metadata: object = None) -> str:
    """Capture the exact minimized record Story 4 hands to an exporter."""
    captured: list[str] = []

    class Capture:
        async def send(self, record: str) -> None:
            captured.append(record)

    assert run(TelemetryPipeline(exporter=Capture()).emit(
        obs or observation(), metadata=metadata)) is Delivery.EXPORTED
    return captured[0]


@pytest.fixture(scope="module")
def provider() -> GuardrailsCredentialProvider:
    return GuardrailsCredentialProvider()


@pytest.fixture
def no_external_network(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Fail on any non-loopback connection from any thread (group 15)."""
    attempts: list[object] = []
    original = socket.socket.connect

    def local_only(sock: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "::1"}:
            attempts.append(address)
            raise OSError("external connection blocked by test")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    return attempts


class WireCapture:
    """Inspect actual public-SDK OTLP JSON and retain decoded application attributes."""

    def __init__(self, exporter=None):
        self.exporter = exporter or InMemorySpanExporter()
        self.requests = []
        self.closed = False

    def handle(self, request):
        self.requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [], "meta": {"cursor": None}})
        payload = json.loads(request.content)
        spans = []
        for resource in payload["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    attrs = {a["key"]: next(iter(a["value"].values()))
                             for a in span["attributes"]}
                    spans.append(SimpleNamespace(
                        name=span["name"], attributes=attrs,
                        context=SimpleNamespace(trace_id=int(span["traceId"], 16)),
                        instrumentation_scope=SimpleNamespace(name=scope["scope"]["name"],
                                                             attributes={}),
                        start_time=int(span["startTimeUnixNano"]),
                        end_time=int(span["endTimeUnixNano"])))
        result = self.exporter.export(spans)
        return httpx.Response(
            200 if result is SpanExportResult.SUCCESS else 500,
            json={} if result is SpanExportResult.SUCCESS else {"error": "fixture"},
        )

    def get_finished_spans(self):
        return self.exporter.get_finished_spans()


@pytest.fixture
def sdk(no_external_network: list[object]):
    """Real public LangfuseAPI serialization with an owned mock HTTP transport."""
    created = []

    def make(exporter=None, **changes):
        config = sdk_settings(**changes)
        memory = WireCapture(exporter)
        transport = LangfuseSdkTransport(config, http_transport=httpx.MockTransport(memory.handle))
        sink = LangfuseSink(transport, settings=config, clock_ns=clock)
        created.append((transport, sink))
        return transport, sink, memory, config

    yield make
    for transport, sink in created:
        run(sink.close())
        assert transport._http.is_closed
    assert no_external_network == []


def controller_for(provider: GuardrailsCredentialProvider, policy: ReliabilityPolicy,
                   names: tuple[str, ...] = ("a",)) -> tuple[ReliabilityController,
                                                         AuthorizationPolicy]:
    auth = AuthorizationPolicy(policy_id="committed",
                               tools=[ToolPermission(tool_name=n) for n in names],
                               grants={"alice": list(names)})
    return ReliabilityController(policy=policy, authorization=auth,
                                 safety=SafetyPipeline(providers=[provider])), auth


# Group 1 - neutral -> Langfuse mapping through the real pipeline.
def test_pipeline_record_maps_to_one_fixed_specification() -> None:
    transport = FakeTransport()
    sink = LangfuseSink(transport, settings=settings(), clock_ns=clock)
    pipeline, statuses = run(emit_all(sink, observation()))
    assert statuses == [Delivery.EXPORTED] and len(transport.specs) == 1
    spec = transport.specs[0]
    assert spec.trace_id == IDENTITY.trace_id.hex
    assert spec.name == "workflow.workflow"
    assert spec.observation_type == "generation"
    assert spec.level == "DEFAULT" and spec.status_message == "success"
    assert dict(spec.trace_metadata) == {"workflow_id": str(IDENTITY.workflow_id),
                                         "trace_id": str(IDENTITY.trace_id)}
    m = meta(spec)
    assert m["workflow_id"] == str(IDENTITY.workflow_id)
    assert m["span_id"] == str(SPAN) and m["action_id"] == str(ACTION)
    assert m["permission_outcome"] == "allow" and m["safety_outcome"] == "deny"
    assert m["evidence_class"] == "deterministic_fixture"
    assert {"retry_attempt", "attempts", "fallback_used", "fallbacks", "recovered",
            "replayed", "history", "duration_ms", "timing_anchor", "usage",
            "cost_basis", "new_cost_usd", "overage_usd"} <= set(m)
    assert not hasattr(spec, "input") and not hasattr(spec, "output")
    assert json.loads(pipeline.records[0])["delivery"] == "exported"


def test_real_sdk_transport_emits_mapped_span_through_in_process_exporter(sdk) -> None:
    _, sink, memory, _ = sdk()
    _, statuses = run(emit_all(sink, observation()))
    assert statuses == [Delivery.EXPORTED]
    assert run(sink.flush()).state is LifecycleState.FLUSHED
    (span,) = memory.get_finished_spans()
    assert span.name == "workflow.workflow"
    assert span.instrumentation_scope.name == "module7.langfuse"
    assert format(span.context.trace_id, "032x") == IDENTITY.trace_id.hex
    attrs = dict(span.attributes)
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.metadata.span_id"] == str(SPAN)
    assert attrs["langfuse.observation.metadata.action_id"] == str(ACTION)
    assert attrs["langfuse.trace.metadata.workflow_id"] == str(IDENTITY.workflow_id)
    assert attrs["langfuse.internal.as_root"] is True
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {"input": 12,
                                                                       "output": 3}
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"total": 0.25}
    assert not any(key.endswith((".input", ".output")) for key in attrs)


# Group 2 - correlation through real Story 3 retry, fallback and replay.
def test_real_retry_fallback_replay_keep_trace_and_action_identity(provider) -> None:
    async def scenario() -> list[LangfuseExportSpec]:
        controller, auth = controller_for(
            provider, ReliabilityPolicy(attempts_per_target=1,
                                        fallback_on=frozenset({Failure.TIMEOUT})), ("a", "b"))
        state = WorkflowState(identity=IDENTITY, idempotency_key=ACTION, operation="effect")
        keys: list[UUID] = []

        async def primary(key: UUID, content: UntrustedContent) -> AttemptResult:
            keys.append(key)
            return AttemptResult(failure=Failure.TIMEOUT, repeat_safe=True)

        async def fallback(key: UUID, content: UntrustedContent) -> AttemptResult:
            keys.append(key)
            return AttemptResult(output=UntrustedContent(value="Completed action"))

        targets = tuple(Target(n, auth.authorize(principal_id="alice", tool_name=n), op, 0)
                        for n, op in (("a", primary), ("b", fallback)))
        args = dict(principal=Principal(principal_id="alice"), state=state,
                    content=UntrustedContent(value="Perform approved action"), targets=targets)
        first = await controller.execute(**args)
        replay = await controller.execute(**args)
        transport = FakeTransport()
        sink = LangfuseSink(transport, settings=settings(), clock_ns=clock)
        await emit_all(sink, from_recovery(first, cost_basis=CostBasis.FIXTURE),
                       from_recovery(replay, cost_basis=CostBasis.FIXTURE))
        assert keys == [ACTION, ACTION]
        return transport.specs

    first, second = run(scenario())
    a, b = meta(first), meta(second)
    assert first.trace_id == second.trace_id == IDENTITY.trace_id.hex
    assert a["action_id"] == b["action_id"] == str(ACTION)
    assert a["span_id"] != b["span_id"]
    assert a["fallback_used"] == "true" and a["recovered"] == "true"
    assert json.loads(a["history"]) == ["timeout", "success"]
    assert a["fallbacks"] == 1 and a["attempts"] == 2
    assert b["replayed"] == "true" and b["usage_scope"] == "historical"
    assert first.name == second.name == "reliability.recovery"


def test_distinct_actions_and_extra_observations_create_no_new_action() -> None:
    transport = FakeTransport()
    sink = LangfuseSink(transport, settings=settings(), clock_ns=clock)
    run(emit_all(sink, observation(),
                 observation(action_id=UUID(int=8), telemetry=observation().telemetry.model_copy(
                     update={"span_id": UUID(int=9)})),
                 observation(event=Event.ATTEMPT, telemetry=observation().telemetry.model_copy(
                     update={"span_id": UUID(int=10)}))))
    actions = [meta(spec)["action_id"] for spec in transport.specs]
    assert actions == [str(ACTION), str(UUID(int=8)), str(ACTION)]
    assert len({spec.trace_id for spec in transport.specs}) == 1
    assert len(transport.specs) == 3


# Group 3 - exhaustive severity table and exact status preservation.
EXPECTED_LEVEL = {
    "success": "DEFAULT", "succeeded": "DEFAULT", "denied": "WARNING",
    "authorization_denied": "WARNING", "safety_denied": "WARNING",
    "identity_denied": "WARNING", "pending": "WARNING", "cancelled": "WARNING",
}


def test_severity_table_is_total_over_the_code_vocabulary() -> None:
    assert set(SEVERITY) == set(Code)
    assert set(SEVERITY.values()) <= {"DEFAULT", "WARNING", "ERROR"}


@pytest.mark.parametrize("code", list(Code))
def test_every_code_maps_and_is_preserved_verbatim(code: Code) -> None:
    obs = observation(telemetry=observation().telemetry.model_copy(update={
        "status": code.value,
        "error_classification": None if code in {Code.SUCCESS, Code.SUCCEEDED} else code.value,
    }), history=(code,))
    spec = to_export_spec(record_for(obs), max_record_bytes=65_536, clock_ns=clock)
    assert spec.level == EXPECTED_LEVEL.get(code.value, "ERROR")
    assert spec.status_message == meta(spec)["status"] == code.value
    assert json.loads(meta(spec)["history"]) == [code.value]


@pytest.mark.parametrize(("failure", "expected"), [
    (Failure.TRANSIENT, "transient_exhausted"), (Failure.TERMINAL, "terminal_exhausted"),
    (Failure.TIMEOUT, "timeout_exhausted"), (Failure.UNKNOWN, "unknown_exhausted"),
    (None, "unknown"),
])
def test_real_controller_exhaustion_codes_survive_langfuse_mapping(
    failure: Failure | None, expected: str, provider: GuardrailsCredentialProvider,
) -> None:
    async def scenario() -> LangfuseExportSpec:
        controller, auth = controller_for(provider, ReliabilityPolicy())
        state = WorkflowState(identity=IDENTITY, idempotency_key=ACTION, operation="effect",
                              evidence_class=EvidenceClass.SIMULATED_FAILURE)

        async def operation(key: UUID, content: UntrustedContent) -> AttemptResult:
            if failure is None:
                raise RuntimeError(f"{SECRET} uncertain-effect adapter error")
            return AttemptResult(failure=failure, repeat_safe=True)

        target = Target("a", auth.authorize(principal_id="alice", tool_name="a"), operation, 0)
        result = await controller.execute(
            principal=Principal(principal_id="alice"), state=state,
            content=UntrustedContent(value="Perform approved action"), targets=(target,))
        transport = FakeTransport()
        await emit_all(LangfuseSink(transport, settings=settings(), clock_ns=clock),
                       from_recovery(result, span_id=SPAN))
        return transport.specs[0]

    spec = run(scenario())
    assert spec.status_message == meta(spec)["status"] == expected
    assert meta(spec)["error_classification"] == expected
    assert meta(spec)["source_evidence"] == "simulated_failure"
    assert spec.level == "ERROR" and SECRET not in repr(spec)


# Group 4 - latency.
def test_duration_is_preserved_with_export_time_anchor() -> None:
    spec = to_export_spec(record_for(from_recovery(recovery())), max_record_bytes=65_536,
                          clock_ns=clock)
    assert spec.end_time_ns == ANCHOR
    assert spec.end_time_ns - spec.start_time_ns == 125_000_000
    assert meta(spec)["duration_ms"] == "125.0"
    assert meta(spec)["timing_anchor"] == TIMING_ANCHOR == "export_time"


def test_sdk_span_duration_equals_application_duration(sdk) -> None:
    _, sink, memory, _ = sdk()
    policy = ReliabilityPolicy()
    run(emit_all(sink, observation(telemetry=observation().telemetry.model_copy(
        update={"duration_ms": 37.5}))))
    run(sink.flush())
    (span,) = memory.get_finished_spans()
    assert span.end_time == ANCHOR and span.end_time - span.start_time == 37_500_000
    assert policy == ReliabilityPolicy()  # Deadlines are untouched by observation.


def test_duration_larger_than_anchor_is_refused() -> None:
    with pytest.raises(LangfuseExportError):
        to_export_spec(record_for(), max_record_bytes=65_536, clock_ns=lambda: 5)


# Group 5 - usage and cost semantics.
@pytest.mark.parametrize(("basis", "available", "usage", "cost"), [
    (CostBasis.FIXTURE, False, (("input", 12), ("output", 3)), (("total", 0.25),)),
    (CostBasis.SUPPORTED_USAGE, False, (("input", 12), ("output", 3)), (("total", 0.25),)),
    (CostBasis.UNKNOWN, False, None, None),
    (CostBasis.UNKNOWN, True, (("input", 12), ("output", 3)), None),
])
def test_cost_basis_controls_native_usage_and_unknown_is_never_zero(
    basis: CostBasis, available: bool, usage: object, cost: object,
) -> None:
    spec = to_export_spec(record_for(observation(cost_basis=basis, usage_available=available)),
                          max_record_bytes=65_536, clock_ns=clock)
    assert spec.usage_details == usage and spec.cost_details == cost
    assert meta(spec)["cost_basis"] == basis.value
    if basis is CostBasis.UNKNOWN:
        assert "new_cost_usd" not in meta(spec)
        assert json.loads(meta(spec)["usage"])["cost_usd"] is None
        assert spec.observation_type == ("generation" if available else "span")


def test_genuine_fixture_zero_and_replay_and_nb1_pass_through() -> None:
    zero = observation(telemetry=observation().telemetry.model_copy(
        update={"usage": UsageRecord()}))
    spec = to_export_spec(record_for(zero), max_record_bytes=65_536, clock_ns=clock)
    assert spec.cost_details == (("total", 0.0),)
    replay = to_export_spec(record_for(from_recovery(recovery(replayed=True),
                                                     cost_basis=CostBasis.SUPPORTED_USAGE)),
                            max_record_bytes=65_536, clock_ns=clock)
    assert replay.usage_details is None and replay.cost_details == (("total", 0.0),)
    assert json.loads(meta(replay)["usage"])["input_units"] == 12
    assert meta(replay)["usage_scope"] == "historical"
    # NB-1: the starting-state cost (1.5 already in WorkflowState.usage) is part of
    # Story 4's new_cost_usd; Story 5 forwards it unchanged without reinterpretation.
    raw = record_for(from_recovery(recovery(), cost_basis=CostBasis.SUPPORTED_USAGE))
    neutral_new_cost = json.loads(raw)["fields"]["new_cost_usd"]
    spec = to_export_spec(raw, max_record_bytes=65_536, clock_ns=clock)
    assert spec.cost_details == (("total", neutral_new_cost),) and neutral_new_cost == 1.5
    assert json.loads(meta(spec)["budget"]) == {"cost_limit_usd": 1.0, "cost_used_usd": 1.0}
    assert meta(spec)["overage_usd"] == "0.5" and meta(spec)["actual_cost_usd"] == "1.5"


# Group 6 - safe debugging metadata.
def test_debug_metadata_is_useful_minimized_and_has_no_io() -> None:
    raw = record_for(from_recovery(recovery()), metadata={"details": {
        "count": 7, "safe": True, "nested": [UUID(int=11)], "raw": "prompt text"}})
    spec = to_export_spec(raw, max_record_bytes=65_536, clock_ns=clock)
    m = meta(spec)
    assert m["status"] == "budget_exhausted" and m["error_classification"] == "budget_exhausted"
    assert json.loads(m["history"]) == ["transient", "timeout", "budget_exhausted"]
    assert m["remaining_attempts"] == 0 and m["remaining_seconds"] == "0.0"
    details = json.loads(m["details"])
    assert details["details"]["count"] == 7 and details["details"]["safe"] is True
    assert details["details"]["nested"] == [str(UUID(int=11))]
    assert "prompt text" not in raw and "prompt text" not in repr(spec)
    assert set(LangfuseExportSpec.__slots__).isdisjoint({"input", "output"})


# Group 7 - pre-export redaction across every output surface.
@pytest.mark.parametrize("key", FAMILIES)
def test_credentials_and_exceptions_never_reach_langfuse_or_local_evidence(
    key: str, sdk, caplog: pytest.LogCaptureFixture,
) -> None:
    _, sink, memory, config = sdk()
    fake = FakeTransport()
    fake_sink = LangfuseSink(fake, settings=settings(), clock_ns=clock)
    metadata = {"details": {key: SECRET, "nested": [{key: SECRET}, {"safe": SecretStr(SECRET)},
                                                      {"value": f"Bearer {SECRET}"}],
                            "items": [RuntimeError(f"{key}={SECRET}")]}}
    with caplog.at_level(logging.DEBUG):
        pipeline, statuses = run(emit_all(sink, observation(), metadata=metadata))
        fake_pipeline, _ = run(emit_all(fake_sink, observation(), metadata=metadata))
        run(sink.flush())
    assert statuses == [Delivery.EXPORTED]
    surfaces = [repr(fake.specs), repr(fake_sink.status), repr(sink.status), repr(config),
                str(config), caplog.text, *pipeline.records, *fake_pipeline.records]
    surfaces += [json.dumps(dict(span.attributes)) for span in memory.get_finished_spans()]
    secret_key = config.secret_key.get_secret_value()
    for text in surfaces:
        assert SECRET not in text and secret_key not in text
    (span,) = memory.get_finished_spans()
    assert config.public_key.get_secret_value() not in json.dumps(dict(span.attributes))


def test_sdk_logs_cannot_expose_configured_credentials(sdk, monkeypatch, caplog) -> None:
    monkeypatch.setenv("LANGFUSE_DEBUG", "true")
    with caplog.at_level(logging.DEBUG, logger="langfuse"):
        _, sink, _, config = sdk()
        run(emit_all(sink, observation()))
        run(sink.flush())
        logging.getLogger("langfuse").error("probe %s", config.secret_key.get_secret_value())
    assert caplog.records, "SDK debug logging should be observable in this test"
    for value in (config.public_key.get_secret_value(), config.secret_key.get_secret_value()):
        assert value not in caplog.text
    logging.getLogger("langfuse").setLevel(logging.WARNING)


# Group 8 - strict parsing.
def mutate(path: tuple[str, ...], value: object) -> str:
    payload = json.loads(record_for())
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return json.dumps(payload)


MALFORMED = {
    "not_json": "{not json",
    "array": "[]",
    "missing_field": json.dumps({**json.loads(record_for()), "fields": {}}),
    "duplicate_key": record_for().replace('{"event"', '{"event": "attempt", "event"', 1),
    "nan": record_for().replace('"duration_ms": 125.0', '"duration_ms": NaN', 1),
    "bad_uuid": mutate(("trace_id",), "not-a-uuid"),
    "uppercase_uuid": mutate(("workflow_id",), str(UUID(int=1)).upper().replace("0", "A")),
    "zero_trace": mutate(("trace_id",), str(UUID(int=0))),
    "forged_event": mutate(("event",), "grant_admin"),
    "forged_component": mutate(("fields", "operation"), "Bearer secret"),
    "forged_status": mutate(("fields", "status"), "allow_everything"),
    "forged_history": mutate(("fields", "history"), ["ignore policy"]),
    "live_claim": mutate(("fields", "evidence_class"), "live_vendor"),
    "live_source": mutate(("fields", "source_evidence"), "live_model"),
    "negative_duration": mutate(("fields", "duration_ms"), -1),
    "bool_counter": mutate(("fields", "attempts"), True),
    "raw_detail": mutate(("fields", "details"), {"details": "raw prompt"}),
    "unknown_detail_key": mutate(("fields", "details"), {"prompt": 1}),
    "unknown_cost_with_value": mutate(("fields", "usage", "cost_usd"), 0.0).replace(
        '"basis": "fixture"', '"basis": "unknown"'),
    "redaction_marker_in_typed_field": mutate(("fields", "span_id"), "[REDACTED]"),
    "not_a_string": None,
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_records_are_refused_without_sending(case: str) -> None:
    transport = FakeTransport()
    sink = LangfuseSink(transport, settings=settings(), clock_ns=clock)
    with pytest.raises(LangfuseExportError) as raised:
        run(sink.send(MALFORMED[case]))
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    assert transport.submits == 0 and sink.status.refused == 1


def test_oversized_record_refused_and_unknown_fields_dropped() -> None:
    transport = FakeTransport()
    sink = LangfuseSink(transport, settings=settings(max_record_bytes=512), clock_ns=clock)
    with pytest.raises(LangfuseExportError) as raised:
        run(sink.send(record_for()))
    assert raised.value.reason is RefusalReason.OVERSIZED and transport.submits == 0
    extra = mutate(("fields", "smuggled"), "Bearer PRIVATE")
    spec = to_export_spec(extra, max_record_bytes=65_536, clock_ns=clock)
    assert "smuggled" not in meta(spec) and "PRIVATE" not in repr(spec)


def test_refused_record_becomes_local_export_failed_evidence() -> None:
    transport = FakeTransport()
    sink = LangfuseSink(transport, settings=settings(max_observations=1), clock_ns=clock)
    pipeline, statuses = run(emit_all(sink, observation(), observation()))
    assert statuses == [Delivery.EXPORTED, Delivery.EXPORT_FAILED]
    assert [json.loads(r)["delivery"] for r in pipeline.records] == ["exported",
                                                                       "export_failed"]


# Group 9 - configuration and secrets.
def test_settings_hide_secrets_and_default_inactive() -> None:
    config = LangfuseSettings(public_key=SECRET, secret_key=SECRET, host="https://h.example")
    assert not config.enabled
    assert SECRET not in repr(config) and SECRET not in str(config)
    assert SECRET not in repr(config.model_dump())
    assert create_langfuse_sink(RuntimeSettings(), LangfuseSettings()) is None


@pytest.mark.parametrize(("values", "fields"), [
    ({}, ["public_key", "secret_key", "host"]),
    ({"public_key": " ", "secret_key": SECRET, "host": "https://h.example"}, ["public_key"]),
    ({"public_key": SECRET, "secret_key": "", "host": "https://h.example"}, ["secret_key"]),
])
def test_enabled_incomplete_configuration_fails_closed_naming_fields(
    values: dict[str, object], fields: list[str],
) -> None:
    with pytest.raises(ConfigurationError) as raised:
        LangfuseSettings(enabled=True, **values)
    message = str(raised.value)
    assert all(name in message for name in fields)
    assert SECRET not in message and raised.value.__context__ is None


@pytest.mark.parametrize("host", [
    f"http://{SECRET}.example.com", f"https://user:{SECRET}@h.example", f"https://h/?k={SECRET}",
    f"https://h/#{SECRET}", f"https://h/ {SECRET}", f"ftp://{SECRET}", " ",
    f"https://h:{SECRET}/",
])
def test_unsafe_hosts_rejected_without_echo(host: str) -> None:
    with pytest.raises(ConfigurationError) as raised:
        LangfuseSettings(host=host)
    assert SECRET not in str(raised.value) and "host" in str(raised.value)


def test_loopback_http_and_https_hosts_accepted() -> None:
    assert LangfuseSettings(host="http://127.0.0.1:3000/").host == "http://127.0.0.1:3000"
    assert LangfuseSettings(host="http://localhost:3000").host == "http://localhost:3000"
    assert LangfuseSettings(host="https://lf.example/base").host == "https://lf.example/base"


def test_ambient_credentials_never_activate_export(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {"LANGFUSE_PUBLIC_KEY": SECRET, "LANGFUSE_SECRET_KEY": SECRET,
                       "LANGFUSE_HOST": "https://ambient.example",
                       "LANGFUSE_BASE_URL": "https://ambient.example",
                       "MODULE7_LANGFUSE_PUBLIC_KEY": SECRET,
                       "MODULE7_LANGFUSE_SECRET_KEY": SECRET,
                       "MODULE7_LANGFUSE_HOST": "https://configured.example",
                       "MODULE7_PROVIDER_API_KEY": SECRET}.items():
        monkeypatch.setenv(key, value)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Langfuse client constructed without explicit enablement")

    monkeypatch.setattr(LangfuseSdkTransport, "__init__", forbidden)
    loaded = LangfuseSettings()
    assert not loaded.enabled and loaded.host == "https://configured.example"
    assert create_langfuse_sink(RuntimeSettings(), loaded) is None
    assert create_langfuse_sink(live_runtime(), loaded) is None


def test_enablement_requires_explicit_live_runtime_and_provider_key() -> None:
    enabled = sdk_settings()
    with pytest.raises(ConfigurationError, match="live mode"):
        create_langfuse_sink(RuntimeSettings(), enabled)
    with pytest.raises(ConfigurationError):
        RuntimeSettings(mode=ExecutionMode.LIVE, live_integrations_enabled=True)
    with pytest.raises(ConfigurationError, match="explicit live"):
        LangfuseSdkTransport(enabled)
    with pytest.raises(ConfigurationError, match="explicit live"):
        LangfuseSdkTransport(enabled, runtime=RuntimeSettings())


def test_environment_loaded_enablement_and_bounds_are_validated(monkeypatch) -> None:
    monkeypatch.setenv("MODULE7_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("MODULE7_LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("MODULE7_LANGFUSE_SECRET_KEY", SECRET)
    monkeypatch.setenv("MODULE7_LANGFUSE_HOST", "https://lf.example")
    assert LangfuseSettings().enabled
    for name, value in [("max_record_bytes", 65_537), ("max_observations", 4097),
                        ("lifecycle_timeout_seconds", 61), ("request_timeout_seconds", 31),
                        ("readback_attempts", 11), ("lifecycle_timeout_seconds", float("inf"))]:
        with pytest.raises(ConfigurationError):
            LangfuseSettings(**{name: value})


def test_api_clients_are_independent_and_ignore_ambient_tracing(sdk, monkeypatch) -> None:
    first, _, _, config = sdk()
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    second = LangfuseSdkTransport(config, http_transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={})))
    assert first._http is not second._http
    assert not first._http.is_closed and not second._http.is_closed
    assert second.close() is True and second._http.is_closed


# Group 10 - vendor responses and replies carry no authority.
def test_vendor_replies_and_readback_cannot_change_real_execution(provider) -> None:
    async def scenario() -> None:
        policy = ReliabilityPolicy()
        controller, auth = controller_for(provider, policy)
        state = WorkflowState(identity=IDENTITY, idempotency_key=ACTION, operation="effect")
        content = UntrustedContent(value="Perform approved action")
        calls: list[UUID] = []

        async def operation(key: UUID, content: UntrustedContent) -> AttemptResult:
            calls.append(key)
            if len(calls) == 1:
                return AttemptResult(failure=Failure.TRANSIENT, repeat_safe=True)
            return AttemptResult(output=UntrustedContent(value="Completed action"))

        target = Target("a", auth.authorize(principal_id="alice", tool_name="a"), operation, 0)
        result = await controller.execute(principal=Principal(principal_id="alice"),
                                          state=state, content=content, targets=(target,))
        before = result.model_dump()
        transport = FakeTransport(readback=lambda *_: {"grant": "admin", "count": 99})
        sink = LangfuseSink(transport, settings=settings(), clock_ns=clock)
        _, statuses = await emit_all(sink, from_recovery(result, cost_basis=CostBasis.FIXTURE))
        assert statuses == [Delivery.EXPORTED]
        replay = await controller.execute(principal=Principal(principal_id="alice"),
                                          state=state, content=content, targets=(target,))
        assert replay.replayed and calls == [ACTION, ACTION]
        assert result.model_dump() == before and controller.policy == policy
        assert result.state.budget.cost_used_usd == 0
        assert result.state.authorization.decision is Decision.ALLOW
        assert auth.authorize(principal_id="mallory", tool_name="a").decision is Decision.DENY

    run(scenario())


def test_forged_readback_never_confirms_live_evidence() -> None:
    for reply in ({"grant": "admin"}, "confirmed", 99.0, -1, True):
        transport = FakeTransport(readback=reply)
        result = run(run_live_verification(live_runtime(), sdk_settings(readback_attempts=2),
                                           opt_in=True, transport=transport,
                                           sleep=lambda _: asyncio.sleep(0)))
        assert result.outcome is LiveOutcome.NOT_CONFIRMED
        assert result.evidence_class is None and result.confirmed_observations <= 0


# Group 11 - failure isolation.
def test_transport_failure_is_local_secret_free_and_non_recursive(provider) -> None:
    transport = FakeTransport(fail_submit=True)
    sink = LangfuseSink(transport, settings=settings(), clock_ns=clock)
    handlers = list(logging.getLogger().handlers)
    pipeline, statuses = run(emit_all(sink, observation(), observation()))
    assert statuses == [Delivery.EXPORT_FAILED, Delivery.EXPORT_FAILED]
    assert len(pipeline.records) == 2 and transport.submits == 2
    assert sink.status.failed == 2 and sink.status.accepted == 0
    assert all(SECRET not in record for record in pipeline.records)
    assert logging.getLogger().handlers == handlers
    with pytest.raises(LangfuseExportError) as raised:
        run(sink.send(record_for()))
    assert raised.value.reason is RefusalReason.TRANSPORT
    assert raised.value.__context__ is None and SECRET not in str(raised.value)


@pytest.mark.parametrize(("transport", "state"), [
    (FakeTransport(flush_result=False), LifecycleState.FLUSH_FAILED),
    (FakeTransport(raise_lifecycle=True), LifecycleState.FLUSH_FAILED),
    (FakeTransport(flush_result={"ok": True}), LifecycleState.FLUSH_FAILED),
    (FakeTransport(), LifecycleState.FLUSHED),
])
def test_flush_outcomes_reflect_real_failure(transport: FakeTransport,
                                             state: LifecycleState) -> None:
    sink = LangfuseSink(transport, settings=settings(), clock_ns=clock)
    status = run(sink.flush())
    assert status.state is state and SECRET not in repr(status)


def test_hanging_lifecycle_is_bounded_and_workflow_unaffected(provider) -> None:
    release = threading.Event()
    transport = FakeTransport(hang=release)
    sink = LangfuseSink(transport, settings=settings(lifecycle_timeout_seconds=0.05),
                        clock_ns=clock)
    try:
        started = time.perf_counter()
        assert run(sink.flush()).state is LifecycleState.FLUSH_TIMEOUT
        assert time.perf_counter() - started < 2
        assert run(sink.flush()).state is LifecycleState.BUSY
        assert run(sink.close()).state is LifecycleState.BUSY
        assert transport.flushes == 1 and transport.closes == 0
        with pytest.raises(LangfuseExportError):
            run(sink.send(record_for()))
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while transport.flushes == 1 and time.monotonic() < deadline:
        status = run(sink.close())
        if status.state is not LifecycleState.BUSY:
            break
        time.sleep(0.01)
    assert transport.closes == 1 and run(sink.close()).state is LifecycleState.CLOSED


def test_sdk_exporter_failure_and_hang_are_isolated(sdk) -> None:
    class Failing(SpanExporter):
        def export(self, spans: object) -> SpanExportResult:
            return SpanExportResult.FAILURE

        def shutdown(self) -> None:
            return None

    class Raising(Failing):
        def export(self, spans: object) -> SpanExportResult:
            raise RuntimeError(f"Authorization: Basic {SECRET}")

    release = threading.Event()

    class Hanging(Failing):
        def export(self, spans: object) -> SpanExportResult:
            release.wait(10)
            return SpanExportResult.SUCCESS

    for exporter in (Failing(), Raising()):
        _, sink, _, _ = sdk(exporter=exporter)
        _, statuses = run(emit_all(sink, observation()))
        assert statuses == [Delivery.EXPORTED]
        assert run(sink.flush()).state is LifecycleState.FLUSH_FAILED
    _, sink, _, _ = sdk(exporter=Hanging(), lifecycle_timeout_seconds=0.2)
    try:
        started = time.perf_counter()
        _, statuses = run(emit_all(sink, observation()))
        assert statuses == [Delivery.EXPORTED]
        assert time.perf_counter() - started < 1, "submit must not wait for export"
        # The SDK's own force-flush bound equals the application wait, so either
        # bounded outcome is acceptable; neither is reported as a successful flush.
        assert run(sink.flush()).state in {LifecycleState.FLUSH_TIMEOUT,
                                           LifecycleState.FLUSH_FAILED}
        assert time.perf_counter() - started < 3
    finally:
        release.set()


# Group 12 - bounds, no adapter retries, idempotent close.
def test_capacity_no_retry_close_once_and_send_after_close() -> None:
    transport = FakeTransport()
    sink = LangfuseSink(transport, settings=settings(max_observations=2), clock_ns=clock)
    _, statuses = run(emit_all(sink, observation(), observation(), observation()))
    assert statuses == [Delivery.EXPORTED, Delivery.EXPORTED, Delivery.EXPORT_FAILED]
    assert transport.submits == 2 and sink.status.refused == 1
    failing = FakeTransport(fail_submit=True)
    failing_sink = LangfuseSink(failing, settings=settings(), clock_ns=clock)
    run(emit_all(failing_sink, observation()))
    assert failing.submits == 1  # One attempt per record; the adapter never retries.
    assert run(sink.close()).state is LifecycleState.CLOSED
    assert run(sink.close()).state is LifecycleState.CLOSED and transport.closes == 1
    assert run(sink.flush()).state is LifecycleState.CLOSED and transport.flushes == 0
    with pytest.raises(LangfuseExportError) as raised:
        run(sink.send(record_for()))
    assert raised.value.reason is RefusalReason.CLOSED and transport.submits == 2


def test_sdk_close_stops_owned_workers_and_is_idempotent(sdk) -> None:
    before = set(threading.enumerate())
    transport, sink, memory, _ = sdk()
    assert not (set(threading.enumerate()) - before)
    run(emit_all(sink, observation()))
    assert run(sink.close()).state is LifecycleState.CLOSED
    assert len(memory.get_finished_spans()) == 1
    assert transport._http.is_closed
    assert run(sink.close()).state is LifecycleState.CLOSED
    time.sleep(0.01)
    assert not [t for t in set(threading.enumerate()) - before if t.is_alive()]
    with pytest.raises(LangfuseExportError):
        run(sink.send(record_for()))


# Group 13 - global OpenTelemetry isolation.
def test_ambient_context_cannot_bypass_redaction(sdk) -> None:
    from langfuse import propagate_attributes
    from opentelemetry import baggage, context

    _, sink, memory, config = sdk()
    token = context.attach(baggage.set_baggage("password", SECRET))
    try:
        with propagate_attributes(user_id=SECRET, metadata={"password": SECRET}):
            run(emit_all(sink, observation(), metadata={"password": SECRET}))
            assert run(sink.flush()).state is LifecycleState.FLUSHED
            assert baggage.get_baggage("password") == SECRET
        spans = memory.get_finished_spans()
        assert len(spans) == 1
        attrs = json.dumps(dict(spans[0].attributes))
        public = config.public_key.get_secret_value()
        secret = config.secret_key.get_secret_value()
        assert SECRET not in attrs and public not in attrs and secret not in attrs
        wire = memory.requests[0].content
        assert public.encode() not in wire  # API path needs keys only in protocol headers.
        assert secret.encode() not in wire and SECRET.encode() not in wire
        assert memory.requests[0].headers["x-langfuse-public-key"] == public
        assert "authorization" in memory.requests[0].headers
    finally:
        context.detach(token)


def test_cancelled_flush_retains_worker_until_resolution() -> None:
    release = threading.Event()
    transport = FakeTransport(hang=release)
    sink = LangfuseSink(transport, settings=settings(lifecycle_timeout_seconds=0.05))

    async def exercise() -> None:
        task = asyncio.create_task(sink.flush())
        while transport.flushes == 0:
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(3):
            assert (await sink.flush()).state is LifecycleState.BUSY
            assert (await sink.close()).state is LifecycleState.BUSY
        assert transport.flushes == 1 and transport.closes == 0
        release.set()
        for _ in range(100):
            status = await sink.close()
            if status.state is not LifecycleState.BUSY:
                break
            await asyncio.sleep(0.01)
        assert status.state is LifecycleState.CLOSED
        assert transport.closes == 1

    try:
        run(exercise())
    finally:
        release.set()


def test_readback_timeout_does_not_overlap_or_close_active_worker() -> None:
    release = threading.Event()

    def hanging(_: str, __: frozenset[str]) -> int:
        release.wait(5)
        return 2

    transport = FakeTransport(readback=hanging)
    try:
        result = run(run_live_verification(
            live_runtime(), sdk_settings(lifecycle_timeout_seconds=0.05, readback_attempts=3,
                                         readback_interval_seconds=0),
            opt_in=True, transport=transport))
        assert transport.readbacks == 1 and transport.closes == 0
        assert result.close_state is LifecycleState.BUSY
        assert result.evidence_class is None
        again = run(run_live_verification(
            live_runtime(), sdk_settings(lifecycle_timeout_seconds=0.05),
            opt_in=True, transport=transport))
        assert again.outcome is LiveOutcome.EXPORT_FAILED
        assert transport.readbacks == 1 and transport.closes == 0
    finally:
        release.set()
    cleanup = LangfuseSink(transport)
    for _ in range(100):
        status = run(cleanup.close())
        if status.state is not LifecycleState.BUSY:
            break
        time.sleep(0.01)
    assert status.state is LifecycleState.CLOSED and transport.closes == 1


def test_cancelled_readback_blocks_reentry_and_close_until_resolution() -> None:
    release, entered = threading.Event(), threading.Event()

    def hanging(_: str, __: frozenset[str]) -> int:
        entered.set()
        release.wait(5)
        return 2

    transport = FakeTransport(readback=hanging)

    async def exercise() -> None:
        task = asyncio.create_task(run_live_verification(
            live_runtime(), sdk_settings(lifecycle_timeout_seconds=0.05,
                                         readback_attempts=2, readback_interval_seconds=0),
            opt_in=True, transport=transport))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        retry = await run_live_verification(
            live_runtime(), sdk_settings(lifecycle_timeout_seconds=0.05,
                                         readback_attempts=2, readback_interval_seconds=0),
            opt_in=True, transport=transport)
        assert retry.close_state is LifecycleState.BUSY
        assert transport.readbacks == 1 and transport.closes == 0
        release.set()
        cleanup = LangfuseSink(transport)
        for _ in range(100):
            status = await cleanup.close()
            if status.state is not LifecycleState.BUSY:
                break
            await asyncio.sleep(0.01)
        assert status.state is LifecycleState.CLOSED

    try:
        run(exercise())
    finally:
        release.set()


@pytest.mark.parametrize("claim", [None, EvidenceClass.LIVE_VENDOR])
def test_forged_transport_evidence_cannot_become_live(claim) -> None:
    fake = FakeTransport(readback=lambda _, ids: len(ids))
    fake.evidence_class = claim
    result = run(run_live_verification(
        live_runtime(), sdk_settings(), opt_in=True, transport=fake))
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert LangfuseSink(fake).status.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT


def test_substituted_sdk_factory_cannot_establish_live_provenance(monkeypatch) -> None:
    from reliability_safety_observability import langfuse_adapter as adapter

    fake = FakeTransport(readback=lambda _, ids: len(ids))
    fake.evidence_class = EvidenceClass.LIVE_VENDOR
    monkeypatch.setattr(adapter, "LangfuseSdkTransport", lambda *args, **kwargs: fake)
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True,
                                       transport=fake))
    assert result.outcome is LiveOutcome.CONFIRMED
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT


def test_global_provider_unchanged_and_foreign_spans_not_exported(sdk, provider) -> None:
    before = otel_trace.get_tracer_provider()
    _transport, sink, memory, _ = sdk()
    assert otel_trace.get_tracer_provider() is before
    foreign = otel_trace.get_tracer("litellm")
    with foreign.start_as_current_span("raw_gen_ai_request") as span:
        span.set_attribute("gen_ai.prompt", f"Bearer {SECRET}")
    from opentelemetry.sdk.trace import TracerProvider
    private = TracerProvider(shutdown_on_exit=False)
    for scope in ("litellm", "openai", "langfuse-sdk"):
        private.get_tracer(scope).start_span("intruder", attributes={"secret": SECRET}).end()
    private.shutdown()
    # Real local Guardrails execution while the adapter is active (its own OTel
    # instrumentation, if any, uses the global provider and must not be exported).
    SafetyPipeline(providers=[provider]).assess_input(
        UntrustedContent(value="Perform approved action"), identity=IDENTITY)
    run(emit_all(sink, observation()))
    assert run(sink.flush()).state is LifecycleState.FLUSHED
    spans = memory.get_finished_spans()
    assert [s.name for s in spans] == ["workflow.workflow"]
    assert all(SECRET not in json.dumps(dict(s.attributes)) for s in spans)
    assert otel_trace.get_tracer_provider() is before


# Group 14 - import confinement.
def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level and node.module:
            roots.add("." + node.module)
    return roots


def test_langfuse_and_opentelemetry_are_confined_to_the_adapter() -> None:
    importers = {path.name: imported_roots(path) for path in SOURCE_ROOT.rglob("*.py")}
    assert {name for name, roots in importers.items() if "langfuse" in roots} == {
        "langfuse_adapter.py"}
    assert {name for name, roots in importers.items() if "opentelemetry" in roots} == set()
    assert {name for name, roots in importers.items() if ".langfuse_adapter" in roots} == set()
    forbidden = {"aiohttp", "requests", "urllib3", "langsmith", "helicone",
                 "guardrails", "openai", "anthropic"}
    assert importers["langfuse_adapter.py"].isdisjoint(forbidden)
    assert {name for name, roots in importers.items() if "httpx" in roots} == {
        "langfuse_adapter.py"}
    assert importers["langfuse_config.py"].isdisjoint(forbidden | {"langfuse", "httpx"})
    package_init = (SOURCE_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "langfuse" not in package_init


def test_story_one_exception_is_exactly_one_file_and_one_root() -> None:
    text = (MODULE_ROOT / "tests" / "test_package_contract.py").read_text(encoding="utf-8")
    assert "LANGFUSE_ADAPTER = SOURCE_ROOT / 'reliability_safety_observability' / " \
           "'langfuse_adapter.py'" in text
    assert 'else {"langfuse", "httpx"} if path == LANGFUSE_ADAPTER' in text
    for root in ("aiohttp", "httpx", "requests", "urllib3", "langfuse", "langsmith",
                 "helicone", "guardrails", "openai", "anthropic"):
        assert f'"{root}",' in text


# Group 15 - ordinary tests make no external call and need no credentials.
def test_full_sdk_lifecycle_makes_no_external_connection(sdk, no_external_network) -> None:
    _, sink, memory, _ = sdk()
    run(emit_all(sink, observation()))
    run(sink.flush())
    run(sink.close())
    assert no_external_network == [] and len(memory.get_finished_spans()) == 1


def test_live_verification_is_opt_in_and_skipped_by_default() -> None:
    import test_langfuse_live as live

    assert isinstance(live.LIVE_OPT_IN, bool)
    if not live.LIVE_OPT_IN:
        assert live.SKIP_REASON
    with pytest.raises(ConfigurationError, match="opt-in"):
        run(run_live_verification(live_runtime(), sdk_settings(), opt_in=False,
                                  transport=FakeTransport()))
    with pytest.raises(ConfigurationError, match="live mode"):
        run(run_live_verification(RuntimeSettings(), sdk_settings(), opt_in=True,
                                  transport=FakeTransport()))


# Group 16 - evidence classification.
def test_evidence_labels_are_never_upgraded(no_external_network) -> None:
    fake_sink = LangfuseSink(FakeTransport(), settings=settings(), clock_ns=clock)
    assert fake_sink.status.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    spec = to_export_spec(record_for(from_recovery(recovery())), max_record_bytes=65_536,
                          clock_ns=clock)
    assert meta(spec)["evidence_class"] == "deterministic_fixture"
    assert meta(spec)["source_evidence"] == "simulated_failure"
    network = LangfuseSdkTransport(sdk_settings(), runtime=live_runtime())
    try:
        assert network.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    finally:
        assert network.close() is True
    assert no_external_network == []


def test_live_labels_only_after_complete_confirmed_readback() -> None:
    def confirm(_: str, span_ids: frozenset[str]) -> int:
        return len(span_ids)

    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    ok = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True,
                                   transport=FakeTransport(readback=confirm), sleep=sleep))
    assert ok.outcome is LiveOutcome.CONFIRMED
    assert ok.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert ok.confirmed_observations == ok.expected_observations == 2
    assert ok.close_state is LifecycleState.CLOSED and sleeps == []
    partial = FakeTransport(readback=1)
    result = run(run_live_verification(live_runtime(), sdk_settings(readback_attempts=3),
                                       opt_in=True, transport=partial, sleep=sleep))
    assert result.outcome is LiveOutcome.NOT_CONFIRMED and result.evidence_class is None
    assert partial.readbacks == 3 and len(sleeps) == 2
    failed = FakeTransport(fail_submit=True)
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True,
                                       transport=failed, sleep=sleep))
    assert result.outcome is LiveOutcome.EXPORT_FAILED and result.evidence_class is None
    assert failed.readbacks == 0 and failed.closes == 1
    unflushed = FakeTransport(flush_result=False)
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True,
                                       transport=unflushed, sleep=sleep))
    assert result.outcome is LiveOutcome.EXPORT_FAILED and unflushed.readbacks == 0


# Group 17 - dependency contract.
@pytest.mark.parametrize("variant", ["same_type", "subclass", "wrapper", "forged_flags"])
def test_ordinary_transport_cannot_mint_live_for_any_runtime_type(variant) -> None:
    if variant == "same_type":
        fake = object.__new__(LangfuseSdkTransport)
        fake.submit = lambda _: None
        fake.flush = lambda: True
        fake.close = lambda: True
        fake.read_back = lambda _, ids: len(ids)
    elif variant == "subclass":
        class Subclass(LangfuseSdkTransport):
            def __init__(self):
                self.submit = lambda _: None
                self.flush = lambda: True
                self.close = lambda: True
                self.read_back = lambda _, ids: len(ids)
        fake = Subclass()
    elif variant == "wrapper":
        class Wrapper:
            def __init__(self):
                self.inner = FakeTransport(readback=lambda _, ids: len(ids))

            def __getattr__(self, name):
                return getattr(self.inner, name)
        fake = Wrapper()
    else:
        fake = FakeTransport(readback=lambda _, ids: len(ids))
    fake.evidence_class = EvidenceClass.LIVE_VENDOR
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True,
                                       transport=fake))
    assert result.outcome is LiveOutcome.CONFIRMED
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert LangfuseSink(fake).status.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT


def confirming_api_fixture():
    sent = []

    def respond(request):
        if request.method == "POST":
            body = json.loads(request.content)
            for resource in body["resourceSpans"]:
                for scope in resource["scopeSpans"]:
                    sent.extend(scope["spans"])
            return httpx.Response(200, json={}, request=request)
        rows = []
        for span in sent:
            attrs = {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}
            rows.append({"id": span["spanId"], "traceId": span["traceId"],
                         "startTime": "2026-10-18T00:00:00Z", "projectId": "fixture",
                         "type": "SPAN", "metadata": {
                             "span_id": attrs["langfuse.observation.metadata.span_id"]}})
        return httpx.Response(200, json={"data": rows, "meta": {"cursor": None}},
                              request=request)
    return respond


@pytest.fixture
def deny_live_endpoint(monkeypatch):
    def deny(*args, **kwargs):
        raise OSError("No actual endpoint execution authorized in this fixture")
    monkeypatch.setattr(socket, "create_connection", deny)


def test_mocked_network_with_real_api_cannot_become_live(
    monkeypatch, no_external_network, deny_live_endpoint,
) -> None:
    respond = confirming_api_fixture()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _, req: respond(req))
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True))
    assert result.outcome is LiveOutcome.EXPORT_FAILED
    assert result.close_state is LifecycleState.CLOSED
    assert result.evidence_class is None
    assert no_external_network == []


def test_forged_network_stream_cannot_create_a_receipt(
    monkeypatch, no_external_network, deny_live_endpoint,
) -> None:
    respond = confirming_api_fixture()

    def fabricated(_, request):
        response = respond(request)
        response.extensions["network_stream"] = SimpleNamespace(
            get_extra_info=lambda _: SimpleNamespace(getpeername=lambda: ("vendor", 443)))
        return response

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fabricated)
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True))
    assert result.outcome is LiveOutcome.EXPORT_FAILED
    assert result.evidence_class is None
    assert no_external_network == []


@pytest.mark.parametrize("socket_on", ["both", "submit", "readback"])
def test_unrelated_connected_socket_cannot_authorize_fabricated_vendor_io(
    monkeypatch, no_external_network, socket_on,
) -> None:
    """Real socketpair, matching fake API responses, and zero endpoint execution."""
    left, right = socket.socketpair()
    respond = confirming_api_fixture()
    fabricated_calls = []
    endpoint_executions = []
    original_connect = socket.socket.connect

    def deny_endpoint(sock, address):
        if isinstance(address, tuple) and address[1] == 3000:
            endpoint_executions.append(False)
            raise OSError("Fixture denies the configured endpoint before execution")
        return original_connect(sock, address)

    def fabricated(_, request):
        fabricated_calls.append(request.method)
        response = respond(request)
        if (socket_on == "both" or (socket_on == "submit" and request.method == "POST")
                or (socket_on == "readback" and request.method == "GET")):
            response.extensions["network_stream"] = SimpleNamespace(
                get_extra_info=lambda _: left)
        return response

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fabricated)
    monkeypatch.setattr(socket.socket, "connect", deny_endpoint)
    try:
        assert left.getpeername()  # Actual unrelated connectivity, not a dummy object.
        result = run(run_live_verification(
            live_runtime(), sdk_settings(host="http://127.0.0.1:3000"), opt_in=True))
        assert result.evidence_class is not EvidenceClass.LIVE_VENDOR
        assert no_external_network == []
        assert not any(endpoint_executions)  # No HTTP/vendor operation was executed.
        assert fabricated_calls == []  # Replaced HTTPX executor is not used for live I/O.
    finally:
        left.close()
        right.close()


def test_replaced_http_client_executor_cannot_mint_live(
    monkeypatch, no_external_network, deny_live_endpoint,
) -> None:
    respond = confirming_api_fixture()
    monkeypatch.setattr(httpx.Client, "send", lambda _, request, **kwargs: respond(request))
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True))
    assert result.outcome is LiveOutcome.CONFIRMED
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert no_external_network == []


def test_replaced_connector_cannot_substitute_an_unrelated_socket(
    monkeypatch, no_external_network,
) -> None:
    left, right = socket.socketpair()
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: left)
    try:
        result = run(run_live_verification(
            live_runtime(), sdk_settings(host="http://127.0.0.1:3000"), opt_in=True))
        assert result.outcome is LiveOutcome.EXPORT_FAILED
        assert result.evidence_class is None
        right.settimeout(0.5)
        assert right.recv(4096) == b""  # No HTTP bytes sent to the unrelated connection.
        assert result.close_state is LifecycleState.CLOSED
        assert no_external_network == []
    finally:
        left.close()
        right.close()


def test_owned_http_client_cannot_execute_a_replaced_api_origin(
    monkeypatch, no_external_network, deny_live_endpoint,
) -> None:
    import langfuse.api

    original = langfuse.api.LangfuseAPI

    def different_origin(**kwargs):
        kwargs["base_url"] = "http://127.0.0.1:39999"
        return original(**kwargs)

    monkeypatch.setattr(langfuse.api, "LangfuseAPI", different_origin)
    result = run(run_live_verification(
        live_runtime(), sdk_settings(host="http://127.0.0.1:3000"), opt_in=True))
    assert result.outcome is LiveOutcome.EXPORT_FAILED
    assert result.evidence_class is None
    assert result.close_state is LifecycleState.CLOSED
    assert no_external_network == []


@pytest.fixture
def local_http_fixture():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    servers = []

    def make(status=200):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                calls.append(("POST", self.path, body))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                if status == 302:
                    self.send_header("Location", "http://127.0.0.1:1/unrelated")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                return None

        server = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        worker.start()
        servers.append((server, worker))
        return f"http://127.0.0.1:{server.server_port}", calls

    yield make
    for server, worker in servers:
        server.shutdown()
        server.server_close()
        worker.join(2)
        assert not worker.is_alive()


def test_unrelated_loopback_redirect_cannot_gain_live_authority(
    local_http_fixture, no_external_network,
) -> None:
    host, calls = local_http_fixture(status=302)
    result = run(run_live_verification(live_runtime(), sdk_settings(host=host), opt_in=True))
    assert result.outcome is LiveOutcome.EXPORT_FAILED and result.evidence_class is None
    assert len(calls) == 1 and calls[0][1] == "/api/public/otel/v1/traces"
    assert result.close_state is LifecycleState.CLOSED
    assert no_external_network == []


def test_actual_fixture_submission_plus_fabricated_readback_is_not_live(
    local_http_fixture, no_external_network, monkeypatch,
) -> None:
    from reliability_safety_observability import langfuse_adapter as adapter

    host, calls = local_http_fixture()
    monkeypatch.setattr(adapter.LangfuseSdkTransport, "read_back", lambda _, trace, ids: len(ids))
    result = run(run_live_verification(live_runtime(), sdk_settings(host=host), opt_in=True))
    assert result.outcome is LiveOutcome.CONFIRMED
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert len(calls) == 1 and calls[0][0] == "POST"  # No endpoint readback occurred.
    assert result.close_state is LifecycleState.CLOSED
    assert no_external_network == []


def test_same_type_substituted_factory_has_no_live_authority(
    monkeypatch, no_external_network, deny_live_endpoint,
):
    from reliability_safety_observability import langfuse_adapter as adapter

    fake = object.__new__(LangfuseSdkTransport)
    fake.evidence_class = None
    fake.submit = lambda _: None
    fake.flush = lambda: True
    fake.close = lambda: True
    fake.read_back = lambda _, ids: len(ids)
    monkeypatch.setattr(adapter, "LangfuseSdkTransport", lambda *a, **k: fake)
    respond = confirming_api_fixture()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _, req: respond(req))
    result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True))
    assert result.evidence_class is None
    assert no_external_network == []


def test_substituted_official_api_object_cannot_become_live(monkeypatch, no_external_network):
    import langfuse.api

    http = httpx.Client(transport=httpx.MockTransport(confirming_api_fixture()))
    real = langfuse.api.LangfuseAPI(base_url="https://langfuse.invalid", httpx_client=http)
    monkeypatch.setattr(langfuse.api, "LangfuseAPI", lambda **_: real)
    try:
        result = run(run_live_verification(live_runtime(), sdk_settings(), opt_in=True))
        assert result.outcome is LiveOutcome.CONFIRMED
        assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    finally:
        http.close()
    assert no_external_network == []


@pytest.mark.parametrize("reply", [{"partialSuccess": {"rejectedSpans": "1"}},
                                  {"unexpected": "success"}])
def test_public_api_partial_or_unrecognized_success_is_not_success(reply) -> None:
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=reply)

    transport = LangfuseSdkTransport(sdk_settings(), http_transport=httpx.MockTransport(respond))
    sink = LangfuseSink(transport)
    run(emit_all(sink, observation()))
    assert run(sink.flush()).state is LifecycleState.FLUSH_FAILED
    assert len(calls) == 1
    run(sink.close())
    assert transport._http.is_closed


def test_http_cleanup_failure_is_bounded_and_cannot_claim_closed(caplog) -> None:
    release = threading.Event()

    class FailingClose(httpx.MockTransport):
        def close(self):
            release.wait(5)
            raise RuntimeError(SECRET)

    transport = LangfuseSdkTransport(sdk_settings(), http_transport=FailingClose(
        lambda _: httpx.Response(200, json={})))
    sink = LangfuseSink(transport, settings=settings(lifecycle_timeout_seconds=0.05))
    try:
        status = run(sink.close())
        assert status.state is LifecycleState.CLOSE_TIMEOUT
        assert run(sink.close()).state is LifecycleState.BUSY
        assert SECRET not in repr(status) + caplog.text
    finally:
        release.set()
    for _ in range(100):
        if run(sink.close()).state is not LifecycleState.BUSY:
            break
        time.sleep(0.01)
    assert sink.status.state is LifecycleState.CLOSE_TIMEOUT
    assert transport.close() is False  # HTTPX's closed flag cannot erase cleanup failure.


def test_langfuse_dependency_is_constrained_locked_and_registry_sourced() -> None:
    project = tomllib.loads((MODULE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    (requirement,) = [Requirement(entry) for entry in project["project"]["dependencies"]
                      if Requirement(entry).name == "langfuse"]
    assert not requirement.extras and requirement.marker is None
    assert not requirement.specifier.contains("5.0.0")
    assert not requirement.specifier.contains("4.16.0")
    lock = tomllib.loads((MODULE_ROOT / "uv.lock").read_text(encoding="utf-8"))
    (locked,) = [p for p in lock["package"] if p["name"] == "langfuse"]
    assert locked["source"] == {"registry": "https://pypi.org/simple"}
    assert requirement.specifier.contains(locked["version"])
    assert Version(version("langfuse")) == Version(locked["version"])
    (guardrails,) = [p for p in lock["package"] if p["name"] == "guardrails-ai"]
    assert Version(guardrails["version"]) != Version("0.10.1")
