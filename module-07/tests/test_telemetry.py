"""Story 4 deterministic and mocked neutral-boundary behavioral evidence."""

import asyncio
import json
import logging
import socket
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from reliability_safety_observability.authorization import AuthorizationPolicy, ToolPermission
from reliability_safety_observability.domain import (
    BudgetState,
    Decision,
    EvidenceClass,
    TelemetryRecord,
    UntrustedContent,
    UsageRecord,
    WorkflowIdentity,
    WorkflowState,
)
from reliability_safety_observability.guardrails_adapter import GuardrailsCredentialProvider
from reliability_safety_observability.logging import _is_sensitive_key, log_event
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
    Component,
    CostBasis,
    Delivery,
    Event,
    Observation,
    TelemetryLimits,
    TelemetryPipeline,
    elapsed_ms,
    from_recovery,
    minimize,
)

IDENTITY = WorkflowIdentity(workflow_id=UUID(int=1), trace_id=UUID(int=2))
ACTION = UUID(int=3)
SPAN = UUID(int=4)


@pytest.fixture(scope="module")
def provider():
    return GuardrailsCredentialProvider()


def observation(**changes: object) -> Observation:
    """Create fixed identity and explicit fixture-usage facts."""
    values = dict(
        telemetry=TelemetryRecord(
            **IDENTITY.model_dump(), span_id=SPAN, operation="Bearer PRIVATE",
            status="success", duration_ms=125, authorization_decision=Decision.ALLOW,
            safety_decision=Decision.DENY,
            usage=UsageRecord(input_tokens=12, output_tokens=3, cost_usd=0.25),
        ),
        action_id=ACTION, cost_basis=CostBasis.FIXTURE,
    )
    values.update(changes)
    return Observation(**values)


class Sink:
    """Fake neutral adapter: immutable JSON enters, arbitrary replies are untrusted."""

    def __init__(self, *, fail=False, reply=None):
        self.records = []
        self.fail = fail
        self.reply = reply

    async def send(self, record):
        self.records.append(record)
        if self.fail:
            raise RuntimeError("PRIVATE password=hidden")
        return self.reply


def emit(obs=None, **kwargs):
    pipeline = TelemetryPipeline(**kwargs)
    status = asyncio.run(pipeline.emit(obs or observation()))
    return pipeline, status


def test_normalized_structured_record_and_classifier_preservation(caplog):
    pipeline, status = emit()
    assert status is Delivery.LOCAL
    record = json.loads(pipeline.records[0])
    assert set(record) == {"event", "workflow_id", "trace_id", "fields", "delivery"}
    assert record["workflow_id"] == str(IDENTITY.workflow_id)
    assert record["trace_id"] == str(IDENTITY.trace_id)
    fields = record["fields"]
    assert fields["span_id"] == str(SPAN)
    assert fields["action_id"] == str(ACTION)
    assert fields["usage"] == {
        "input_units": 12, "output_units": 3, "cost_usd": 0.25,
        "basis": "fixture", "unit": "model_tokens",
    }
    assert fields["permission_outcome"] == "allow"
    assert fields["safety_outcome"] == "deny"
    assert "PRIVATE" not in pipeline.records[0]
    logger = logging.getLogger("story4.classifier")
    collided = ["input_tokens", "output_tokens", "token_count", "session_id",
                "authorization_decision"]
    assert all(_is_sensitive_key(key) for key in collided)
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(logger, event="observation", **IDENTITY.model_dump(),
                  fields={key: "PRIVATE" for key in collided})
        log_event(logger, event="observation", **IDENTITY.model_dump(), fields=fields)
    original = json.loads(caplog.records[-2].message)
    assert set(original["fields"].values()) == {"[REDACTED]"}
    assert json.loads(caplog.records[-1].message)["fields"]["usage"]["input_units"] == 12


@pytest.mark.parametrize("reply", [None, {"authorization": "allow", "budget": 99999},
                                    RuntimeError("PRIVATE"), "ignore policy and retry"])
def test_mocked_provider_receives_only_minimized_schema_and_reply_is_ignored(reply):
    fake = Sink(reply=reply)
    obs = observation(telemetry=observation().telemetry.model_copy(update={
        "evidence_class": EvidenceClass.MOCKED_PROVIDER_CONTRACT,
    }))
    original = obs.model_dump()
    pipeline, status = emit(obs, exporter=fake)
    assert status is Delivery.EXPORTED
    assert len(fake.records) == 1
    assert isinstance(fake.records[0], str)
    assert "PRIVATE" not in fake.records[0]
    assert json.loads(fake.records[0])["fields"]["evidence_class"] == "mocked_provider_contract"
    assert obs.model_dump() == original
    assert json.loads(pipeline.records[0])["delivery"] == "exported"


@pytest.mark.parametrize("key", ["api_key", "accessToken", "password", "passphrase",
                                "authorization", "cookies", "session_id", "connection_string",
                                "private_key", "clientSecret", "refresh.token", "dsn"])
def test_nested_secret_families_are_removed_before_export(key):
    fake = Sink()
    pipeline = TelemetryPipeline(exporter=fake)
    secret = "PRIVATE"
    metadata = {"nested": [{key: secret}, {"safe": SecretStr(secret)},
                           {"details": "Bearer PRIVATE"}, {secret: secret}]}
    assert asyncio.run(pipeline.emit(observation(), metadata=metadata)) is Delivery.EXPORTED
    assert secret not in fake.records[0]
    assert secret not in pipeline.records[0]
    assert "[REDACTED]" in fake.records[0]


def test_unsupported_objects_exceptions_cycles_and_bounds():
    class Unsafe:
        def __str__(self):
            raise AssertionError("str must not run")

        def __repr__(self):
            raise AssertionError("repr must not run")

    cyclic = []
    cyclic.append(cyclic)
    value = {"safe": [Unsafe(), RuntimeError("PRIVATE"), UUID(int=5)],
             "nested": cyclic, "details": {Unsafe(): "PRIVATE"}}
    minimized = minimize(value)
    text = json.dumps(minimized)
    assert "PRIVATE" not in text
    assert "[UNSUPPORTED_TYPE]" in text
    assert "[TRUNCATED]" in text
    assert str(UUID(int=5)) in text
    assert len(minimize(list(range(10000)), TelemetryLimits(max_nodes=4))) <= 5
    assert minimize(float("nan")) == "[UNSUPPORTED_TYPE]"
    fake = Sink()
    small = TelemetryPipeline(exporter=fake, limits=TelemetryLimits(max_bytes=512))
    assert asyncio.run(small.emit(observation())) is Delivery.INVALID
    assert not fake.records and not small.records


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_duration_cost_and_resource_values_rejected(value):
    with pytest.raises(ValidationError):
        TelemetryRecord(**IDENTITY.model_dump(), operation="x", status="failed", duration_ms=value)
    with pytest.raises(ValidationError):
        UsageRecord(cost_usd=value)
    with pytest.raises(ValidationError):
        observation(overage_usd=value)


def test_clock_and_unknown_usage_provenance():
    assert elapsed_ms(2, clock=lambda: 2.125) == 125
    for start, end in [(3, 2), (float("nan"), 2), (0, float("inf"))]:
        with pytest.raises(ValueError, match="finite nonnegative"):
            elapsed_ms(start, clock=lambda end=end: end)
    pipeline, _ = emit(observation(cost_basis=CostBasis.UNKNOWN))
    usage = json.loads(pipeline.records[0])["fields"]["usage"]
    assert usage["basis"] == "unknown"
    assert usage["cost_usd"] is None and usage["input_units"] is None
    pipeline, _ = emit(observation(cost_basis=CostBasis.UNKNOWN, usage_available=True))
    usage = json.loads(pipeline.records[0])["fields"]["usage"]
    assert usage["input_units"] == 12 and usage["cost_usd"] is None
    zero = observation(telemetry=observation().telemetry.model_copy(
        update={"usage": UsageRecord()}))
    pipeline, _ = emit(zero)
    assert json.loads(pipeline.records[0])["fields"]["usage"]["cost_usd"] == 0


def recovery(**changes):
    state = WorkflowState(identity=IDENTITY, idempotency_key=ACTION, operation="PRIVATE",
                          budget=BudgetState(cost_limit_usd=1, cost_used_usd=1),
                          usage=UsageRecord(input_tokens=12, cost_usd=1.5),
                          evidence_class=EvidenceClass.SIMULATED_FAILURE)
    values = dict(state=state, classification="budget_exhausted", attempts=3, fallbacks=1,
                  elapsed_seconds=0.125, remaining_attempts=0, remaining_seconds=0,
                  actual_cost_usd=1.5, overage_usd=0.5,
                  history=("transient", "timeout", "budget_exhausted"))
    values.update(changes)
    return RecoveryResult(**values)


def test_recovery_budget_overage_debug_correlation_and_replay():
    original = recovery()
    before = original.model_dump()
    obs = from_recovery(original, span_id=SPAN, cost_basis=CostBasis.SUPPORTED_USAGE)
    pipeline, _ = emit(obs)
    f = json.loads(pipeline.records[0])["fields"]
    assert f["duration_ms"] == 125
    assert f["attempts"] == 3 and f["fallbacks"] == 1
    assert f["history"] == ["transient", "timeout", "budget_exhausted"]
    assert f["error_classification"] == "budget_exhausted"
    assert f["budget"] == {"cost_limit_usd": 1, "cost_used_usd": 1}
    assert f["actual_cost_usd"] == 1.5 and f["overage_usd"] == 0.5
    assert f["source_evidence"] == "simulated_failure"
    assert original.model_dump() == before
    replay = from_recovery(recovery(replayed=True), cost_basis=CostBasis.SUPPORTED_USAGE)
    pipeline, _ = emit(replay)
    r = json.loads(pipeline.records[0])["fields"]
    assert r["replayed"] and r["new_cost_usd"] == 0
    assert r["actual_cost_usd"] == 1.5
    assert r["action_id"] == f["action_id"]
    assert replay.telemetry.trace_id == obs.telemetry.trace_id
    assert replay.telemetry.span_id != obs.telemetry.span_id


@pytest.mark.parametrize("kind", ["pending", "authorization_denied", "timeout_unresolved"])
def test_zero_attempts_and_error_content_not_fabricated(kind):
    obs = from_recovery(recovery(classification=kind, attempts=0, history=("PRIVATE",)))
    assert obs.attempts == 0 and not obs.recovered
    pipeline, _ = emit(obs)
    assert "PRIVATE" not in pipeline.records[0]
    assert json.loads(pipeline.records[0])["fields"]["history"] == ["unknown"]


def test_primary_and_local_failure_are_independently_observable_and_bounded():
    fake = Sink(fail=True)
    local = Sink(fail=True)
    pipeline, status = emit(exporter=fake, local_sink=local)
    assert status is Delivery.EXPORT_FAILED
    assert len(fake.records) == len(local.records) == len(pipeline.records) == 1
    assert "PRIVATE" not in pipeline.records[0]
    assert json.loads(pipeline.records[0])["delivery"] == "export_failed"


def test_sink_self_cancellation_is_failure_not_caller_cancellation():
    class SelfCancelled:
        async def send(self, record):
            raise asyncio.CancelledError

    pipeline, status = emit(exporter=SelfCancelled())
    assert status is Delivery.EXPORT_FAILED
    assert json.loads(pipeline.records[0])["delivery"] == "export_failed"


@pytest.mark.parametrize("changes", [{"max_events": 0}, {"max_depth": 100},
                                    {"max_nodes": 0}, {"max_bytes": 0},
                                    {"sink_timeout_seconds": float("inf")}])
def test_invalid_telemetry_limits_fail_before_observation(changes):
    with pytest.raises(ValidationError):
        TelemetryLimits(**changes)


def test_timeout_reentrancy_and_capacity_are_bounded():
    async def scenario():
        class Slow:
            calls = 0

            async def send(self, record):
                self.calls += 1
                await asyncio.Event().wait()

        slow = Slow()
        pipeline = TelemetryPipeline(exporter=slow, limits=TelemetryLimits(
            max_events=1, sink_timeout_seconds=0.01))
        assert await pipeline.emit(observation()) is Delivery.EXPORT_FAILED
        await asyncio.sleep(0)
        assert await pipeline.emit(observation()) is Delivery.FULL
        assert slow.calls == 1 and len(pipeline.records) == 1

        class Reentrant:
            async def send(self, record):
                assert await other.emit(observation()) is Delivery.BUSY

        other = TelemetryPipeline(exporter=Reentrant())
        assert await other.emit(observation()) is Delivery.EXPORTED
        assert len(other.records) == 1

    asyncio.run(scenario())


def test_unresolved_sink_cannot_accumulate_tasks_or_retry():
    async def scenario():
        release = asyncio.Event()

        class UncooperativeUntilReleased:
            calls = 0

            async def send(self, record):
                self.calls += 1
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                raise RuntimeError("PRIVATE late failure")

        sink = UncooperativeUntilReleased()
        pipeline = TelemetryPipeline(exporter=sink, limits=TelemetryLimits(
            sink_timeout_seconds=0.01))
        assert await pipeline.emit(observation()) is Delivery.EXPORT_FAILED
        assert await pipeline.emit(observation()) is Delivery.BUSY
        assert sink.calls == 1 and len(pipeline.records) == 1
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert "PRIVATE" not in pipeline.records[0]

    asyncio.run(scenario())


def test_redaction_serialization_and_forged_models_fail_without_raw_export(monkeypatch):
    import reliability_safety_observability.telemetry as telemetry

    fake = Sink()
    forged = observation().model_copy(update={"actual_cost_usd": float("inf")})
    pipeline, status = emit(forged, exporter=fake)
    assert status is Delivery.INVALID and not fake.records

    def fail(value):
        raise RuntimeError("PRIVATE")

    monkeypatch.setattr(telemetry, "_redact", fail)
    pipeline, status = emit(exporter=fake)
    assert status is Delivery.INVALID and not fake.records and not pipeline.records


def test_real_fallback_and_replay_projection_preserves_identity_and_accounting(provider):
    async def scenario():
        auth = AuthorizationPolicy(
            policy_id="committed", tools=[ToolPermission(tool_name=n) for n in ("a", "b")],
            grants={"alice": ["a", "b"]})
        state = WorkflowState(identity=IDENTITY, idempotency_key=ACTION, operation="effect")
        keys = []

        async def primary(key, content):
            keys.append(key)
            return AttemptResult(failure=Failure.TIMEOUT, repeat_safe=True)

        async def fallback(key, content):
            keys.append(key)
            return AttemptResult(output=UntrustedContent(value="Completed action"))

        # Attested timeouts recover only when explicitly permitted by Story 3 policy.
        controller = ReliabilityController(
            policy=ReliabilityPolicy(attempts_per_target=1,
                                     fallback_on=frozenset({Failure.TIMEOUT})),
            authorization=auth, safety=SafetyPipeline(providers=[provider]))
        targets = tuple(Target(n, auth.authorize(principal_id="alice", tool_name=n), op, 0)
                        for n, op in (("a", primary), ("b", fallback)))
        args = dict(principal=Principal(principal_id="alice"), state=state,
                    content=UntrustedContent(value="Perform approved action"), targets=targets)
        result = await controller.execute(**args)
        assert result.classification == "success" and result.fallbacks == 1
        pipeline = TelemetryPipeline()
        assert await pipeline.emit(
            from_recovery(result, cost_basis=CostBasis.FIXTURE)) is Delivery.LOCAL
        replay = await controller.execute(**args)
        assert replay.replayed
        assert await pipeline.emit(
            from_recovery(replay, cost_basis=CostBasis.FIXTURE)) is Delivery.LOCAL
        first, second = [json.loads(r)["fields"] for r in pipeline.records]
        assert first["fallback_used"] and first["recovered"]
        assert first["history"] == ["timeout", "success"]
        assert first["action_id"] == second["action_id"] == str(ACTION)
        assert keys == [ACTION, ACTION]
        assert second["new_cost_usd"] == 0 and second["replayed"]

    asyncio.run(scenario())


@pytest.mark.parametrize("evidence", [EvidenceClass.LIVE_VENDOR, EvidenceClass.LIVE_MODEL])
def test_no_live_claims_or_live_enablement(evidence, monkeypatch):
    monkeypatch.setenv("MODULE7_PROVIDER_API_KEY", "PRIVATE")
    original_connect = socket.socket.connect

    def local_only(sock, address):
        # Windows asyncio bootstraps an OS loopback socketpair, not a vendor call.
        if address[0] != "127.0.0.1":
            pytest.fail("external call")
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    obs = observation(telemetry=observation().telemetry.model_copy(
        update={"evidence_class": evidence}))
    pipeline, status = emit(obs)
    assert status is Delivery.INVALID and not pipeline.records
    pipeline, status = emit()
    assert status is Delivery.LOCAL
    assert json.loads(pipeline.records[0])["fields"]["evidence_class"] == "deterministic_fixture"


def test_evaluation_join_and_distinct_actions_without_execution():
    obs = observation(event=Event.EVALUATION, component=Component.EVALUATION,
                      evaluation_id=UUID(int=9), action_id=UUID(int=8), history=(Code.UNKNOWN,))
    pipeline, _ = emit(obs)
    fields = json.loads(pipeline.records[0])["fields"]
    assert fields["evaluation_id"] == str(UUID(int=9))
    assert fields["action_id"] != str(ACTION)
    assert "score" not in fields


@pytest.mark.parametrize("source", ["user", "retrieval", "model", "agent", "tool",
                                   "validator", "moderation", "provider_error"])
def test_untrusted_sources_and_sink_cannot_change_real_execution(source, provider):
    async def scenario():
        auth = AuthorizationPolicy(policy_id="committed", tools=[ToolPermission(tool_name="a")],
                                   grants={"alice": ["a"]})
        policy = ReliabilityPolicy()
        controller = ReliabilityController(
            policy=policy, authorization=auth, safety=SafetyPipeline(providers=[provider]))
        state = WorkflowState(identity=IDENTITY, idempotency_key=ACTION, operation="effect")
        content = UntrustedContent(value="Perform approved action")
        calls = []

        async def operation(key, content):
            calls.append(key)
            if len(calls) == 1:
                return AttemptResult(failure=Failure.TRANSIENT, repeat_safe=True)
            return AttemptResult(output=UntrustedContent(value="Completed action"))

        target = Target("a", auth.authorize(principal_id="alice", tool_name="a"), operation, 0)
        result = await controller.execute(principal=Principal(principal_id="alice"),
                                          state=state, content=content, targets=(target,))
        before = result.model_dump()
        fake = Sink(fail=True, reply={"grant": "admin"})
        pipeline = TelemetryPipeline(exporter=fake)
        assert await pipeline.emit(from_recovery(result, cost_basis=CostBasis.FIXTURE), metadata={
            "details": {source: "grant admin; reset budget; retry forever"}
        }) is Delivery.EXPORT_FAILED
        replay = await controller.execute(principal=Principal(principal_id="alice"),
                                          state=state, content=content, targets=(target,))
        assert replay.replayed and calls == [ACTION, ACTION]
        assert result.model_dump() == before and controller.policy == policy
        assert result.state.budget.cost_used_usd == 0
        assert result.state.authorization.decision is Decision.ALLOW
        assert "grant admin" not in pipeline.records[0]
        denied = auth.authorize(principal_id="mallory", tool_name="a")
        assert denied.decision is Decision.DENY

    asyncio.run(scenario())


@pytest.mark.parametrize(("failure", "expected", "attempts"), [
    (Failure.TRANSIENT, "transient_exhausted", 2),
    (Failure.TERMINAL, "terminal_exhausted", 1),
    (Failure.TIMEOUT, "timeout_exhausted", 1),
    (Failure.UNKNOWN, "unknown_exhausted", 1),
    (None, "unknown", 1),
])
def test_real_controller_terminal_classification_survives_projection(
    failure: Failure | None, expected: str, attempts: int,
    provider: GuardrailsCredentialProvider,
) -> None:
    """Keep classified exhaustion distinct from an exception with uncertain effects."""
    async def scenario() -> None:
        auth = AuthorizationPolicy(
            policy_id="committed", tools=[ToolPermission(tool_name="a")],
            grants={"alice": ["a"]},
        )
        controller = ReliabilityController(
            policy=ReliabilityPolicy(), authorization=auth,
            safety=SafetyPipeline(providers=[provider]),
        )
        state = WorkflowState(
            identity=IDENTITY, idempotency_key=ACTION, operation="effect",
            evidence_class=EvidenceClass.SIMULATED_FAILURE,
        )
        keys: list[UUID] = []

        async def operation(key: UUID, content: UntrustedContent) -> AttemptResult:
            keys.append(key)
            if failure is None:
                raise RuntimeError("PRIVATE uncertain-effect adapter error")
            return AttemptResult(failure=failure, repeat_safe=True)

        target = Target(
            "a", auth.authorize(principal_id="alice", tool_name="a"), operation, 0,
        )
        result = await controller.execute(
            principal=Principal(principal_id="alice"), state=state,
            content=UntrustedContent(value="Perform approved action"), targets=(target,),
        )
        assert result.classification == expected
        assert result.attempts == attempts and keys == [ACTION] * attempts
        history = ((failure.value if failure is not None else "unknown"),) * attempts
        assert result.history == history
        before = result.model_dump()
        obs = from_recovery(result, span_id=SPAN)
        assert obs.telemetry.status == expected
        assert obs.telemetry.error_classification == expected
        fake = Sink()
        pipeline = TelemetryPipeline(exporter=fake)
        assert await pipeline.emit(obs) is Delivery.EXPORTED
        for record in (fake.records[0], pipeline.records[0]):
            fields = json.loads(record)["fields"]
            assert fields["status"] == fields["error_classification"] == expected
            assert fields["history"] == list(history)
            assert fields["action_id"] == str(ACTION)
            assert fields["source_evidence"] == "simulated_failure"
            assert fields["evidence_class"] == "deterministic_fixture"
            assert "PRIVATE" not in record
            if failure is not None:
                assert fields["status"] != "unknown"
        assert result.model_dump() == before

    asyncio.run(scenario())
