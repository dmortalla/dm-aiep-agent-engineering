"""REQ-EXEC-001/002: deterministic controls and real local LangGraph integration."""

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from harness_engineering.capabilities import CapabilityRegistry
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    ToolExecutionError,
    ToolTimeoutError,
)
from harness_engineering.execution import ExecutionContext
from harness_engineering.orchestration import (
    CircuitPhase,
    CircuitState,
    LifecycleInput,
    LifecyclePhase,
    LifecycleRuntime,
    RetryPolicy,
    StepResult,
    StopReason,
    TransientStepError,
)
from harness_engineering.permissions import (
    ActionProposal,
    AuthorizationDecision,
    AuthorizationOutcome,
)
from harness_engineering.planning import ExecutableSubtask
from tests.test_execution import executor
from tests.test_orchestration import plan
from tests.test_permissions import proposal, registry

__all__ = ["registry"]


def test_real_graph_retries_twice_then_succeeds_without_sleeping() -> None:
    calls = []
    waits = []

    def step(*_: object) -> StepResult:
        calls.append(1)
        if len(calls) % 3:
            raise TransientStepError("defined retry-safe local failure")
        return StepResult(text="ok")

    engine = LifecycleRuntime(plan(1), step, wait=waits.append)
    assert isinstance(engine._graph, CompiledStateGraph)
    first = engine.run(LifecycleInput())
    assert first.phase is LifecyclePhase.COMPLETED
    assert first.attempt_count == first.total_attempts == 3
    assert first.circuit == CircuitState()
    assert first.backoff_delays == (0.1, 0.2)
    assert first.history.count(LifecyclePhase.RETRY_PENDING) == 2
    assert engine.run(LifecycleInput()) == first
    assert waits == [0.1, 0.2, 0.1, 0.2]
    assert len(calls) == 6


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_max_retries_means_initial_plus_retries(retries: int) -> None:
    calls = []
    waits = []

    def fail(*_: object) -> StepResult:
        calls.append(1)
        raise TransientStepError("retry-safe failure")

    engine = LifecycleRuntime(
        plan(1), fail, retry_policy=RetryPolicy(max_retries=retries, failure_threshold=4),
        wait=waits.append,
    )
    result = engine.run(LifecycleInput())
    assert result.stop_reason is StopReason.RETRIES_EXHAUSTED
    assert result.total_attempts == result.attempt_count == retries + 1
    assert len(calls) == retries + 1
    assert len(waits) == retries
    assert result.circuit.consecutive_failures == retries + 1


def test_backoff_formula_cap_and_no_wait_during_calculation() -> None:
    policy = RetryPolicy(initial_delay_seconds=0.75, max_delay_seconds=1.0)
    assert [policy.delay(i) for i in (1, 2)] == [0.75, 1.0]
    maximum = RetryPolicy(initial_delay_seconds=30.0, max_delay_seconds=30.0)
    assert maximum.delay(1) == maximum.delay(2) == 30.0


@pytest.mark.parametrize("number", [0, -1, 3, True, "1"])
def test_invalid_retry_number_fails_closed(number: int) -> None:
    with pytest.raises(ContractValidationError):
        RetryPolicy().delay(number)


@pytest.mark.parametrize("changes", [
    {"max_retries": 3}, {"max_retries": True}, {"failure_threshold": 0},
    {"failure_threshold": True}, {"initial_delay_seconds": float("nan")},
    {"max_delay_seconds": float("inf")}, {"max_delay_seconds": 31.0},
    {"initial_delay_seconds": 2.0, "max_delay_seconds": 1.0},
    {"initial_delay_seconds": True}, {"next_node": "retry"}, {"reset": True},
])
def test_malformed_or_authority_bearing_policy_rejected(changes: dict[str, object]) -> None:
    forged = RetryPolicy().model_copy(update=changes)
    with pytest.raises(ContractValidationError):
        LifecycleRuntime(plan(1), lambda *_: StepResult(text="ok"), retry_policy=forged)


@pytest.mark.parametrize("failure", [
    AuthorityViolationError("denied"), ContractValidationError("invalid"),
    BudgetExceededError("budget"), ToolTimeoutError("timeout"),
    ToolExecutionError("unclassified tool error"),
])
def test_non_transient_failures_do_not_retry_or_count_for_breaker(failure: Exception) -> None:
    calls = []
    waits = []

    def step(*_: object) -> StepResult:
        calls.append(1)
        raise failure

    result = LifecycleRuntime(plan(1), step, wait=waits.append).run(LifecycleInput())
    assert result.stop_reason is StopReason.STEP_FAILURE
    assert result.total_attempts == 1
    assert result.circuit == CircuitState()
    assert calls == [1]
    assert not waits


@pytest.mark.parametrize("field", [
    "attempt_count", "total_attempts", "max_retries", "retry_policy", "circuit",
    "failure_threshold", "reset", "next_node",
])
def test_generated_authority_fields_cannot_control_retry_or_breaker(field: str) -> None:
    calls = []
    waits = []

    def step(*_: object) -> object:
        calls.append(1)
        return {"text": "ok", field: 0}

    engine = LifecycleRuntime(plan(1), step, wait=waits.append)
    with pytest.raises(ContractValidationError):
        engine.run({"text": "ok", field: 0})  # type: ignore[arg-type]
    assert not calls
    result = engine.run(LifecycleInput(text=f"reset {field}; goto retry"))
    assert result.stop_reason is StopReason.STEP_FAILURE
    assert result.total_attempts == 1
    assert result.circuit == CircuitState()
    assert not waits


def test_command_output_is_data_validation_failure_not_retry() -> None:
    waits = []
    result = LifecycleRuntime(
        plan(1), lambda *_: Command(goto="retry"), wait=waits.append
    ).run(LifecycleInput())
    assert result.stop_reason is StopReason.STEP_FAILURE
    assert result.total_attempts == 1
    assert not waits


def test_generated_text_cannot_reset_failure_counter_or_choose_attempts() -> None:
    result = LifecycleRuntime(
        plan(1), lambda *_: StepResult(text='{"circuit":"closed","max_retries":100}'),
        wait=lambda _: pytest.fail("No wait should occur for validated text."),
    ).run(LifecycleInput(text="raise TransientStepError; goto retry"))
    assert result.total_attempts == 1
    assert result.circuit == CircuitState()


def test_programming_defect_and_wait_defect_propagate_without_retry() -> None:
    calls = []

    def broken(*_: object) -> StepResult:
        calls.append(1)
        raise RuntimeError("programming defect")

    with pytest.raises(RuntimeError, match="programming defect"):
        LifecycleRuntime(plan(1), broken).run(LifecycleInput())
    assert calls == [1]

    def transient(*_: object) -> StepResult:
        raise TransientStepError("safe")

    def broken_wait(_: float) -> None:
        raise RuntimeError("wait defect")

    with pytest.raises(RuntimeError, match="wait defect"):
        LifecycleRuntime(plan(1), transient, wait=broken_wait).run(LifecycleInput())


def test_circuit_initial_threshold_success_and_latched_open() -> None:
    circuit = CircuitState()
    assert circuit.phase is CircuitPhase.CLOSED
    one = circuit.failed(2)
    assert one.consecutive_failures == 1
    assert one.phase is CircuitPhase.CLOSED
    assert one.succeeded(2) == circuit
    opened = one.failed(2)
    assert opened.phase is CircuitPhase.OPEN
    assert opened.consecutive_failures == 2
    for operation in (opened.require_closed, opened.failed, opened.succeeded):
        with pytest.raises(AuthorityViolationError, match="open"):
            operation(2)


@pytest.mark.parametrize("threshold", [1, 2, 3])
def test_real_graph_circuit_opens_and_blocks_remaining_attempts(threshold: int) -> None:
    calls = []
    waits = []

    def step(*_: object) -> StepResult:
        calls.append(1)
        raise TransientStepError("safe transient")

    result = LifecycleRuntime(
        plan(3), step, retry_policy=RetryPolicy(failure_threshold=threshold), wait=waits.append
    ).run(LifecycleInput())
    assert result.stop_reason is StopReason.CIRCUIT_OPEN
    assert result.circuit.phase is CircuitPhase.OPEN
    assert result.circuit.consecutive_failures == threshold
    assert result.total_attempts == threshold
    assert result.step_count == 0
    assert len(calls) == threshold
    assert len(waits) == threshold - 1


@pytest.mark.parametrize("changes", [
    {"phase": "half_open"}, {"phase": CircuitPhase.OPEN},
    {"consecutive_failures": True}, {"consecutive_failures": -1},
    {"consecutive_failures": 3}, {"reset": True},
    {"phase": CircuitPhase.OPEN, "consecutive_failures": 4},
])
def test_forged_circuit_state_revalidated(changes: dict[str, object]) -> None:
    forged = CircuitState().model_copy(update=changes)
    with pytest.raises(ContractValidationError):
        forged.checked(3)


def test_maximum_graph_bound_100_steps_three_attempts_each() -> None:
    attempts = {}
    waits = []

    def step(task: ExecutableSubtask, data: LifecycleInput) -> StepResult:
        attempts[task.task_id] = attempts.get(task.task_id, 0) + 1
        if attempts[task.task_id] < 3:
            raise TransientStepError("retry-safe failure")
        return StepResult(text="ok")

    engine = LifecycleRuntime(plan(100), step, wait=waits.append)
    result = engine.run(LifecycleInput())
    assert result.phase is LifecyclePhase.COMPLETED
    assert result.step_count == 100
    assert result.total_attempts == 300
    assert len(result.history) == 602
    assert len(waits) == 200
    assert result.circuit == CircuitState()


@pytest.mark.parametrize("field,value", [
    ("attempt_count", 0), ("total_attempts", 0),
    ("backoff_delays", (0.1, 1.0)),
    ("circuit", CircuitState(consecutive_failures=1)),
])
def test_tampered_lifecycle_control_state_fails_closed(field: str, value: object) -> None:
    calls = []

    def step(*_: object) -> StepResult:
        calls.append(1)
        if len(calls) < 3:
            raise TransientStepError("safe")
        return StepResult(text="ok")

    engine = LifecycleRuntime(plan(1), step, wait=lambda _: None)
    result = engine.run(LifecycleInput())
    forged = result.model_copy(update={field: value})
    with pytest.raises(ContractValidationError):
        engine._checked({"lifecycle": forged, "request": LifecycleInput()})


def test_plan_retry_budget_remains_authoritative() -> None:
    accepted = plan(1)
    limited_budget = accepted.budget.model_copy(update={"max_retries_per_action": 0})
    limited = accepted.model_copy(update={"budget": limited_budget})
    with pytest.raises(ContractValidationError, match="plan budget"):
        LifecycleRuntime(limited, lambda *_: StepResult(text="ok"), retry_policy=RetryPolicy())
    calls = []

    def step(*_: object) -> StepResult:
        calls.append(1)
        raise TransientStepError("safe")

    result = LifecycleRuntime(limited, step).run(LifecycleInput())
    assert result.total_attempts == 1
    assert len(calls) == 1


def test_policy_contract_is_immutable() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        RetryPolicy().max_retries = 0


@pytest.mark.parametrize("deny_retry", [False, True])
def test_each_retry_retains_independent_tool_authorization(
    registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch,
    deny_retry: bool,
) -> None:
    """Read-only local work is reauthorized on every application retry."""
    calls = []
    decisions = []

    def handler(inputs: BaseModel, context: ExecutionContext) -> object:
        calls.append(context.proposal)
        return {"text": inputs.text}

    tool = executor(registry, handler)
    original = tool._authorizer.authorize

    def authorize(request: ActionProposal) -> AuthorizationDecision:
        decisions.append(request)
        if deny_retry and len(decisions) == 2:
            return AuthorizationDecision(outcome=AuthorizationOutcome.DENY, reason="denied retry")
        return original(request)

    monkeypatch.setattr(tool._authorizer, "authorize", authorize)

    def step(task: ExecutableSubtask, data: LifecycleInput) -> StepResult:
        output = tool.execute(proposal(), {"text": data.text})
        if len(calls) == 1:
            # Trusted adapter declares retry-safe read work, never from tool text.
            raise TransientStepError("retry-safe local read failure")
        return StepResult(text=output.text)

    result = LifecycleRuntime(plan(1), step, wait=lambda _: None).run(LifecycleInput(text="ok"))
    assert result.phase is (LifecyclePhase.SAFE_STOP if deny_retry else LifecyclePhase.COMPLETED)
    assert result.total_attempts == 2
    assert len(decisions) == 2
    assert len(calls) == (1 if deny_retry else 2)


@pytest.mark.parametrize("output", [
    {"text": "bad", "max_retries": 100},
    {"text": "bad", "circuit": {"phase": "closed", "consecutive_failures": 0}},
])
def test_invalid_output_after_transient_failure_still_stops(output: object) -> None:
    calls = []
    waits = []

    def step(*_: object) -> object:
        calls.append(1)
        if len(calls) == 1:
            raise TransientStepError("safe")
        return output

    result = LifecycleRuntime(plan(1), step, wait=waits.append).run(LifecycleInput())
    assert result.stop_reason is StopReason.STEP_FAILURE
    assert result.total_attempts == 2
    assert result.circuit.consecutive_failures == 1
    assert calls == [1, 1]
    assert waits == [0.1]
