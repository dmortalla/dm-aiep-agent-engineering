"""REQ-OBS-001/002, REQ-COST-002; deterministic/local ENG-002..007 evidence."""

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from pydantic import ValidationError

from harness_engineering.approval_lifecycle import SuspendedWorkflow
from harness_engineering.domain import EvidenceClass, RuntimeBudget, WorkflowIdentity
from harness_engineering.errors import AuthorityViolationError, BudgetExceededError
from harness_engineering.latency import Measurement, Outcome, TimingSource
from harness_engineering.lifecycle_controls import OffSwitch
from harness_engineering.observability import (
    TelemetryError,
    TelemetryEvent,
    TelemetrySession,
    TraceContext,
    bind_trace,
    current_trace,
)
from harness_engineering.orchestration import (
    LifecycleInput,
    LifecyclePhase,
    LifecycleRuntime,
    StepResult,
    TransientStepError,
)
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan
from harness_engineering.providers import (
    FakeProvider,
    ModelRequest,
    OutputFilter,
    ProviderCallContext,
    ProviderEvent,
    ProviderOutputRejected,
    ProviderRuntime,
    ProviderTimeoutError,
)
from harness_engineering.telemetry_projections import observe_step, observe_workflow

SECRET = "SECRET-SENTINEL-https://private.invalid/key-DO-NOT-RETAIN"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("No network permitted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def session(clock: object = None) -> TelemetrySession:
    options = {} if clock is None else {"clock": clock}
    return TelemetrySession(
        WorkflowIdentity(), evidence=EvidenceClass.LOCAL_INTEGRATION, **options,
    )


def serialized(value: TelemetrySession) -> str:
    return json.dumps([event.model_dump(mode="json") for event in value.sink.snapshot()])


def test_nested_real_lifecycle_step_provider_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = session()
    captured: list[TraceContext | None] = []

    def fake(self: FakeProvider, request: ModelRequest, context: ProviderCallContext) -> object:
        assert request.prompt == SECRET
        captured.append(current_trace())
        assert context.trace_context == current_trace()
        return {"text": SECRET}

    monkeypatch.setattr(FakeProvider, "generate", fake)
    provider = ProviderRuntime(telemetry=telemetry)
    plan = ExecutionPlan(
        goal=SECRET, tasks=(ExecutableSubtask(task_id="private", description=SECRET),),
    )
    runtime = LifecycleRuntime(
        plan, observe_step(
            telemetry, lambda task, request: StepResult(
                text=provider.generate({"prompt": request.text}).text,
            ), step_ids=("private",),
        ),
    )
    result = observe_workflow(telemetry, lambda: runtime.run(LifecycleInput(text=SECRET)))
    assert result.phase is LifecyclePhase.COMPLETED
    assert result.results[0].text == SECRET
    events = telemetry.sink.snapshot()
    assert len(events) == 6
    assert [e.measurement for e in events[:3]] == [
        Measurement.WORKFLOW, Measurement.ACTION, Measurement.PROVIDER,
    ]
    assert len({e.trace.trace_id for e in events}) == 1
    assert events[1].parent_span_id == events[0].trace.span_id
    assert events[2].parent_span_id == events[1].trace.span_id
    assert captured == [events[2].trace]
    assert SECRET not in serialized(telemetry)
    assert "private" not in serialized(telemetry)
    assert current_trace() is None
    assert provider.audit == (ProviderEvent.STARTED, ProviderEvent.VALIDATED)
    assert provider.attempts == 1


@pytest.mark.parametrize("header", [
    "", "00-" + "0" * 32 + "-" + "1" * 16 + "-01",
    "00-" + "1" * 32 + "-" + "0" * 16 + "-01",
    "00-" + "A" * 32 + "-" + "1" * 16 + "-01",
    "01-" + "1" * 32 + "-" + "1" * 16 + "-01",
    "00-" + "1" * 32 + "-" + "1" * 16 + "-ff",
    "00-" + "1" * 33 + "-" + "1" * 16 + "-01",
    "00-" + "1" * 32 + "-" + "1" * 16 + "-01,baggage=admin",
    SECRET, None, True,
])
def test_invalid_external_traceparent_rejected(header: object) -> None:
    with pytest.raises(TelemetryError):
        TraceContext.parse_traceparent(header)


def test_external_trace_is_inert_and_never_replaces_identity() -> None:
    header = "00-" + "1" * 32 + "-" + "2" * 16 + "-00"
    external = TraceContext.parse_traceparent(header)
    assert external.traceparent() == header
    identity = WorkflowIdentity()
    telemetry = TelemetrySession(identity, evidence=EvidenceClass.DETERMINISTIC)
    with bind_trace(external):
        telemetry.call(Measurement.ACTION, lambda: None)
        assert current_trace() == external
    event = telemetry.sink.snapshot()[0]
    assert event.trace.trace_id != external.trace_id
    assert event.parent_span_id is None
    assert event.workflow_id == identity.workflow_id
    assert event.evidence is EvidenceClass.DETERMINISTIC
    assert current_trace() is None


@pytest.mark.parametrize("mutation", [
    {"evidence": "deployment"}, {"metadata": {"approved": True, "secret": SECRET}},
    {"elapsed_seconds": float("nan")}, {"sequence": True}, {"step_index": 101},
    {"schema_version": 2}, {"schema_version": True}, {"schema_version": 1.0},
    {"prompt": SECRET}, {"error": SECRET},
])
def test_closed_schema_rejects_hostile_fields(mutation: dict[str, object]) -> None:
    telemetry = session()
    telemetry.call(Measurement.ACTION, lambda: None)
    raw = telemetry.sink.snapshot()[0].model_dump()
    raw.update(mutation)
    with pytest.raises(ValidationError):
        TelemetryEvent.model_validate(raw)


@pytest.mark.parametrize("field,value", [
    ("evidence", EvidenceClass.DEPLOYMENT), ("timing", TimingSource.INJECTED),
    ("workflow_id", uuid4()), ("thread_id", uuid4()), ("segment_id", uuid4()),
    ("trace", TraceContext(trace_id="1" * 32, span_id="2" * 16)),
])
def test_sink_rejects_forged_classification_and_identity(field: str, value: object) -> None:
    telemetry = session()
    telemetry.call(Measurement.ACTION, lambda: None)
    event = telemetry.sink.snapshot()[0].model_copy(update={field: value, "sequence": 3})
    with pytest.raises(TelemetryError):
        telemetry.sink.emit(event)
    assert len(telemetry.sink.snapshot()) == 2


def test_sink_revalidates_forged_event_and_rejects_replay() -> None:
    telemetry = session()
    telemetry.call(Measurement.ACTION, lambda: None)
    event = telemetry.sink.snapshot()[0]
    with pytest.raises(TelemetryError):
        telemetry.sink.emit(event)
    with pytest.raises(TelemetryError):
        telemetry.sink.emit(event.model_copy(update={"sequence": 3, "step_index": SECRET}))
    with pytest.raises(ValidationError):
        event.sequence = 99


def test_ring_event_size_and_high_cardinality_bounds() -> None:
    telemetry = session()
    for index in range(300):
        telemetry.call(Measurement.ACTION, lambda: SECRET, step_index=index % 100 + 1)
    events = telemetry.sink.snapshot()
    assert len(events) == 512
    assert telemetry.sink.dropped == 88
    assert events[-1].sequence == 600
    assert all(len(e.model_dump_json().encode()) <= 4096 for e in events)
    assert SECRET not in serialized(telemetry)
    assert len(telemetry.reports()) == 1
    with pytest.raises(TelemetryError):
        telemetry.call(Measurement.ACTION, lambda: None, step_index=SECRET)


@pytest.mark.parametrize("error", [
    ValueError(SECRET), RuntimeError(SECRET), AuthorityViolationError(SECRET),
    BudgetExceededError(SECRET), ProviderOutputRejected(SECRET),
])
def test_exception_payload_and_cause_are_not_serialized(error: Exception) -> None:
    telemetry = session()
    error.__cause__ = RuntimeError(SECRET)

    def fail() -> None:
        raise error

    with pytest.raises(type(error)) as caught:
        telemetry.call(Measurement.ACTION, fail)
    assert caught.value is error
    assert caught.value.__cause__.args == (SECRET,)
    assert SECRET not in serialized(telemetry)
    assert current_trace() is None
    assert len(telemetry.sink.snapshot()) == 2


@pytest.mark.parametrize("error", [TelemetryError(SECRET), OSError(SECRET), RuntimeError(SECRET)])
def test_local_sink_failure_cannot_reset_provider_authority(
    error: Exception, monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry = session()

    def fail(event: TelemetryEvent) -> None:
        raise error

    monkeypatch.setattr(telemetry.sink, "emit", fail)
    switch = OffSwitch()
    provider = ProviderRuntime(
        telemetry=telemetry, off_switch=switch, budget=RuntimeBudget(max_provider_attempts=1),
    )
    assert provider.generate({"prompt": SECRET}).text
    with pytest.raises(BudgetExceededError):
        provider.generate({"prompt": SECRET})
    switch.activate()
    with pytest.raises(AuthorityViolationError):
        provider.generate({"prompt": SECRET})
    assert provider.attempts == 1
    assert telemetry.failures == 6
    assert not telemetry.sink.snapshot()


@pytest.mark.parametrize("gate,expected_calls", [(True, []), (False, ["step"])])
def test_persistence_observer_failure_propagates_without_retry(
    gate: bool, expected_calls: list[str],
) -> None:
    telemetry = session()
    calls: list[str] = []
    runtime = LifecycleRuntime(
        ExecutionPlan(goal="local", tasks=(ExecutableSubtask(task_id="a", description="local"),)),
        lambda task, request: (calls.append("step"), StepResult(text="safe"))[1],
        before_step=(lambda *_: None) if gate else None,
    )
    failure = OSError(SECRET)

    def observer(snapshot: object) -> None:
        raise failure

    with pytest.raises(OSError) as caught:
        observe_workflow(
            telemetry, lambda: runtime.run_observed(LifecycleInput(), observer=observer),
        )
    assert caught.value is failure
    assert calls == expected_calls
    assert SECRET not in serialized(telemetry)
    assert telemetry.reports()[0].cohort.outcome is Outcome.DEFECT


def test_retries_remain_application_owned_and_step_returns_are_not_success_claims() -> None:
    telemetry = session()
    calls = 0

    def step(task: ExecutableSubtask, request: LifecycleInput) -> StepResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TransientStepError(SECRET)
        return StepResult(text=SECRET)

    runtime = LifecycleRuntime(
        ExecutionPlan(goal="local", tasks=(ExecutableSubtask(task_id="a", description="local"),)),
        observe_step(telemetry, step, step_ids=("a",)), wait=lambda _: None,
    )
    result = observe_workflow(telemetry, lambda: runtime.run(LifecycleInput()))
    assert result.total_attempts == calls == 2
    assert {report.cohort.outcome for report in telemetry.reports()} == {
        Outcome.FAILED, Outcome.RETURNED, Outcome.SUCCEEDED,
    }


def test_distinct_sessions_and_workers_do_not_leak_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(self: FakeProvider, request: ModelRequest, context: ProviderCallContext) -> object:
        assert current_trace() == context.trace_context
        assert current_trace() is not None
        return {"text": "safe"}

    monkeypatch.setattr(FakeProvider, "generate", fake)
    sessions = [session(), session()]

    def run(telemetry: TelemetrySession) -> str:
        provider = ProviderRuntime(telemetry=telemetry)
        provider.generate({"prompt": SECRET})
        assert current_trace() is None
        return telemetry.sink.snapshot()[0].trace.trace_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        roots = list(pool.map(run, sessions))
    assert roots[0] != roots[1]
    plain = ProviderRuntime()
    # Uninstrumented calls reset/bind None instead of inheriting an earlier worker.
    monkeypatch.setattr(FakeProvider, "generate", lambda self, request, context: {
        "text": "safe" if current_trace() is None and context.trace_context is None else "leak",
    })
    assert plain.generate({"prompt": "local"}).text == "safe"


def test_provider_timeout_has_one_caller_sample_and_no_late_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry = session()
    entered, release, finished = Event(), Event(), Event()

    def slow(self: FakeProvider, request: ModelRequest, context: ProviderCallContext) -> object:
        entered.set()
        try:
            release.wait(5)
            return {"text": SECRET}
        finally:
            finished.set()

    monkeypatch.setattr(FakeProvider, "generate", slow)
    provider = ProviderRuntime(
        telemetry=telemetry, budget=RuntimeBudget(action_timeout_seconds=0.1),
    )
    try:
        with pytest.raises(ProviderTimeoutError):
            provider.generate({"prompt": "local"})
        assert entered.is_set()
        before = telemetry.sink.snapshot()
        assert len(before) == 2
        assert telemetry.reports()[0].sample_count == 1
    finally:
        release.set()
        assert finished.wait(5)
    assert telemetry.sink.snapshot() == before
    assert provider.attempts == 1


def test_injected_clock_durations_and_deadline_separation() -> None:
    readings = iter([10.0, 12.5])
    telemetry = session(lambda: next(readings))
    telemetry.call(Measurement.WORKFLOW, lambda: None, classify=lambda _: Outcome.SUCCEEDED)
    report = telemetry.reports()[0]
    assert report.p50_seconds == report.p95_seconds == 2.5
    assert report.cohort.timing is TimingSource.INJECTED
    assert report.slo_p95_seconds == 5.0 and report.slo_met is None
    assert RuntimeBudget().workflow_deadline_seconds == 180.0


@pytest.mark.parametrize("readings", [
    [10.0, 9.0], [float("nan"), 10.0], [10.0, float("inf")], [True, 10.0],
    [10.0, 100000.0], [10**1000, 10.0],
])
def test_bad_clocks_never_fabricate_samples_or_change_results(readings: list[float]) -> None:
    ticks = iter(readings)
    telemetry = session(lambda: next(ticks))
    assert telemetry.call(Measurement.ACTION, lambda: SECRET) == SECRET
    assert telemetry.failures >= 1
    assert not telemetry.reports()


def test_clock_defect_cannot_mask_business_error() -> None:
    def clock() -> float:
        raise RuntimeError(SECRET)

    telemetry = session(clock)
    failure = ValueError("business error")

    def operation() -> None:
        raise failure

    with pytest.raises(ValueError) as caught:
        telemetry.call(Measurement.ACTION, operation)
    assert caught.value is failure
    assert telemetry.failures == 2
    assert SECRET not in serialized(telemetry)


def test_suspended_hitl_result_is_not_a_completed_sample(tmp_path: Path) -> None:
    from harness_engineering.approvals import HumanIdentity
    from tests.test_approval_lifecycle import INPUT, build

    calls: list[str] = []
    approval = build(tmp_path, calls, [0.0], (
        HumanIdentity(principal_id="approver-1"), HumanIdentity(principal_id="override-1"),
    ))
    telemetry = session()
    suspension = observe_workflow(telemetry, lambda: approval.start(INPUT))
    assert type(suspension) is SuspendedWorkflow
    assert calls == ["a"]
    report = telemetry.reports()[0]
    assert report.cohort.outcome is Outcome.SUSPENDED
    assert report.slo_met is None


def test_malformed_suspension_is_not_accepted_as_evidence() -> None:
    telemetry = session()
    forged = SuspendedWorkflow.model_construct()
    assert observe_workflow(telemetry, lambda: forged) is forged
    assert telemetry.failures == 1
    assert telemetry.reports()[0].cohort.outcome is Outcome.REJECTED


def test_resume_is_a_separate_segment_not_end_to_end_workflow_latency() -> None:
    telemetry = session()
    runtime = LifecycleRuntime(
        ExecutionPlan(goal="local", tasks=(ExecutableSubtask(task_id="a", description="local"),)),
        lambda *_: StepResult(text=SECRET),
    )
    result = observe_workflow(telemetry, lambda: runtime.run(LifecycleInput()), resumed=True)
    assert result.phase is LifecyclePhase.COMPLETED
    report = telemetry.reports()[0]
    assert report.cohort.measurement is Measurement.SEGMENT
    assert report.slo_met is None


def test_tool_data_and_raw_handler_failure_never_enter_projection() -> None:
    from tests.test_execution import executor
    from tests.test_permissions import proposal, registry

    capabilities = registry.__wrapped__()
    telemetry = session()
    runner = executor(capabilities, lambda *_: {"text": SECRET})
    returned = telemetry.call(
        Measurement.ACTION, lambda: runner.execute(proposal(), {"text": SECRET}),
    )
    assert returned.text == SECRET
    assert SECRET not in serialized(telemetry)

    def fail(*args: object) -> object:
        raise ValueError(SECRET)

    runner = executor(capabilities, fail)
    from harness_engineering.errors import ToolExecutionError

    with pytest.raises(ToolExecutionError) as caught:
        telemetry.call(Measurement.ACTION, lambda: runner.execute(proposal(), {"text": SECRET}))
    assert caught.value.__cause__.args == (SECRET,)
    assert SECRET not in serialized(telemetry)


def test_filtering_and_unknown_adapter_semantics_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = session()
    monkeypatch.setattr(FakeProvider, "generate", lambda *args: {"text": SECRET})
    provider = ProviderRuntime(
        telemetry=telemetry, output_filter=OutputFilter(blocked_terms=("secret",)),
    )
    with pytest.raises(ProviderOutputRejected):
        provider.generate({"prompt": SECRET})
    assert provider.attempts == 1
    assert provider.audit[-1] is ProviderEvent.REJECTED
    assert SECRET not in serialized(telemetry)
    with pytest.raises(Exception, match="telemetry session"):
        ProviderRuntime(telemetry=object())


def test_concurrent_sequences_are_unique_and_bounded() -> None:
    telemetry = session()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: telemetry.call(Measurement.ACTION, lambda: None), range(50)))
    events = telemetry.sink.snapshot()
    assert [event.sequence for event in events] == list(range(1, 101))
    assert telemetry.failures == 0
    assert telemetry.reports()[0].sample_count == 50


def test_classifier_failure_is_visible_and_does_not_change_callback_result() -> None:
    telemetry = session()
    result = telemetry.call(Measurement.ACTION, lambda: SECRET, classify=lambda _: "deployment")
    assert result == SECRET
    assert telemetry.failures == 1
    assert telemetry.reports()[0].cohort.outcome is Outcome.REJECTED
    assert SECRET not in serialized(telemetry)
