"""Deterministic REQ-TOOL-004 and ENG-002/004/007 evidence."""

from contextlib import suppress
from threading import Event

import pytest
from pydantic import BaseModel

from harness_engineering.capabilities import CapabilityRegistry, CapabilitySelectionCriteria
from harness_engineering.domain import RuntimeBudget, WorkflowIdentity
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    ContractValidationError,
    ToolExecutionError,
    ToolTimeoutError,
)
from harness_engineering.execution import (
    BoundedToolExecutor,
    ExecutionContext,
    ExecutionLimits,
    ToolHandler,
)
from harness_engineering.permissions import AuthorizationPolicy
from tests.test_permissions import authorizer, grant, proposal, registry, rule

__all__ = ["registry"]


def executor(
    registry: CapabilityRegistry,
    handler: ToolHandler,
    *,
    permitted: bool = True,
    policy: AuthorizationPolicy | None = None,
    limits: ExecutionLimits | None = None,
    budget: RuntimeBudget | None = None,
) -> BoundedToolExecutor:
    """Bind a local handler to application-owned workflow policy."""
    identity = WorkflowIdentity()
    return BoundedToolExecutor(
        registry,
        authorizer(
            registry, identity, grants=(grant(identity),) if permitted else (), policy=policy
        ),
        {"documents": handler},
        {"documents": limits or ExecutionLimits()},
        budget or RuntimeBudget(),
    )


def test_valid_invocation_once_and_exact_target(registry: CapabilityRegistry) -> None:
    calls = []

    def handler(inputs: BaseModel, context: ExecutionContext) -> object:
        calls.append(context.proposal)
        context.checkpoint(1)
        return {"text": inputs.text}

    assert executor(registry, handler).execute(proposal(), {"text": "hello"}).text == "hello"
    assert calls == [proposal()]


@pytest.mark.parametrize("case", ["missing", "blocked", "approval", "risk", "scope", "action"])
def test_denials_repeat_without_invoking(registry: CapabilityRegistry, case: str) -> None:
    calls = []
    policy = AuthorizationPolicy(
        capabilities=(
            rule(approval_required=case == "approval", risk="high" if case == "risk" else "low"),
        ),
        blocked_actions=("read",) if case == "blocked" else (),
    )
    runner = executor(
        registry, lambda *_: calls.append(1), permitted=case != "missing", policy=policy
    )
    requested = (
        proposal(resource_id="doc-c")
        if case == "scope"
        else proposal(action="write" if case == "action" else "read")
    )
    for _ in range(2):
        with pytest.raises(AuthorityViolationError):
            runner.execute(requested, {"text": "x"})
    assert calls == []


@pytest.mark.parametrize(
    "field",
    [
        "approved",
        "decision",
        "trust",
        "credentials",
        "grants",
        "principal_id",
        "identity",
        "policy",
    ],
)
def test_forged_authority_never_invokes(registry: CapabilityRegistry, field: str) -> None:
    calls = []
    with pytest.raises(ContractValidationError):
        executor(registry, lambda *_: calls.append(1)).execute(
            {**proposal().model_dump(), field: True}, {"text": "x"}
        )
    assert calls == []


@pytest.mark.parametrize("inputs", [{"text": 3}, {"text": "x", "approved": True}, [], None])
def test_invalid_input_never_invokes(registry: CapabilityRegistry, inputs: object) -> None:
    calls = []
    with pytest.raises(ContractValidationError):
        executor(registry, lambda *_: calls.append(1)).execute(proposal(), inputs)
    assert calls == []


def test_selection_tags_unknown_and_unbound_never_execute(registry: CapabilityRegistry) -> None:
    calls = []
    runner = executor(registry, lambda *_: calls.append(1), permitted=False)
    selected = registry.select(CapabilitySelectionCriteria(required_tags=("approved",)))
    with pytest.raises(ContractValidationError):
        runner.execute(selected[0], {"text": "x"})
    with pytest.raises(AuthorityViolationError):
        runner.execute(proposal(), {"text": "x"})
    with pytest.raises(ContractValidationError, match="Unknown"):
        runner.execute(proposal(capability_id="unknown"), {"text": "x"})
    runner = BoundedToolExecutor(
        registry, authorizer(registry, WorkflowIdentity()), {}, {}, RuntimeBudget()
    )
    with pytest.raises(ContractValidationError, match="no application handler"):
        runner.execute(proposal(), {"text": "x"})
    assert calls == []


@pytest.mark.parametrize(
    "output", [{"text": 1}, {"text": "x", "approved": True}, None, {"text": object()}]
)
def test_invalid_output_fails_closed(registry: CapabilityRegistry, output: object) -> None:
    with pytest.raises(ContractValidationError):
        executor(registry, lambda *_: output).execute(proposal(), {"text": "x"})


def test_constructed_instances_revalidated(registry: CapabilityRegistry) -> None:
    schema = registry.lookup("documents").input_schema
    calls = []
    with (
        pytest.warns(UserWarning, match="Pydantic serializer warnings"),
        pytest.raises(ContractValidationError),
    ):
        executor(registry, lambda *_: calls.append(1)).execute(
            proposal(), schema.model_construct(text=1)
        )
    assert not calls
    with (
        pytest.warns(UserWarning, match="Pydantic serializer warnings"),
        pytest.raises(ContractValidationError),
    ):
        executor(registry, lambda *_: schema.model_construct(text=1)).execute(
            proposal(), {"text": "x"}
        )


def test_handler_failure_chained_and_call_consumed(registry: CapabilityRegistry) -> None:
    cause = ValueError("local failure")

    def handler(*_) -> object:
        raise cause

    runner = executor(registry, handler, budget=RuntimeBudget(max_tool_calls=1))
    with pytest.raises(ToolExecutionError) as error:
        runner.execute(proposal(), {"text": "x"})
    assert error.value.__cause__ is cause
    with pytest.raises(BudgetExceededError, match="tool-call"):
        runner.execute(proposal(), {"text": "x"})


@pytest.mark.parametrize("side", ["input", "output"])
def test_payload_bytes_enforced(registry: CapabilityRegistry, side: str) -> None:
    calls = []

    def handler(*_) -> object:
        calls.append(1)
        return {"text": "x" * 100}

    runner = executor(
        registry,
        handler,
        limits=ExecutionLimits(
            max_input_bytes=20 if side == "input" else 1000,
            max_output_bytes=20 if side == "output" else 1000,
        ),
    )
    with pytest.raises(BudgetExceededError, match="byte limit"):
        runner.execute(proposal(), {"text": "x" * 100})
    assert len(calls) == (side == "output")


@pytest.mark.parametrize("units", [2, -1, True])
def test_work_exhaustion_latches(registry: CapabilityRegistry, units: int) -> None:
    def handler(inputs: BaseModel, context: ExecutionContext) -> object:
        with suppress(BudgetExceededError):
            context.checkpoint(units)
        return {"text": "x"}

    with pytest.raises(BudgetExceededError, match="work-unit"):
        executor(registry, handler, limits=ExecutionLimits(max_work_units=1)).execute(
            proposal(), {"text": "x"}
        )


@pytest.mark.parametrize("bound", ["capability", "action", "workflow"])
def test_timeout_rejects_result_and_bounds_concurrency(
    registry: CapabilityRegistry, bound: str
) -> None:
    entered, release, exited = Event(), Event(), Event()
    contexts = []

    def handler(inputs: BaseModel, context: ExecutionContext) -> object:
        contexts.append(context)
        entered.set()
        try:
            assert release.wait(5)
            return {"text": "late"}
        finally:
            exited.set()

    budget = RuntimeBudget(
        action_timeout_seconds=0.05 if bound == "action" else 30,
        workflow_deadline_seconds=0.05 if bound == "workflow" else 180,
        latency_slo_p95_seconds=0.01,
    )
    runner = executor(
        registry,
        handler,
        budget=budget,
        limits=ExecutionLimits(
            timeout_seconds=0.05 if bound == "capability" else 30,
        ),
    )
    try:
        with pytest.raises(ToolTimeoutError):
            runner.execute(proposal(), {"text": "x"})
        assert entered.is_set()
        with pytest.raises(BudgetExceededError, match="busy"):
            runner.execute(proposal(), {"text": "x"})
        with pytest.raises(ToolTimeoutError):
            contexts[0].checkpoint()
    finally:
        release.set()
        assert exited.wait(5)


def test_zero_calls_never_invokes(registry: CapabilityRegistry) -> None:
    calls = []
    with pytest.raises(BudgetExceededError):
        executor(
            registry, lambda *_: calls.append(1), budget=RuntimeBudget(max_tool_calls=0)
        ).execute(proposal(), {"text": "x"})
    assert not calls


def test_bootstrap_limits_revalidated(registry: CapabilityRegistry) -> None:
    with pytest.raises(ContractValidationError):
        executor(
            registry,
            lambda *_: {},
            limits=ExecutionLimits.model_construct(timeout_seconds=float("nan")),
        )


def test_successful_calls_are_bounded(registry: CapabilityRegistry) -> None:
    calls: list[int] = []

    def handler(inputs: BaseModel, context: ExecutionContext) -> object:
        calls.append(1)
        return {"text": "x"}

    runner = executor(registry, handler, budget=RuntimeBudget(max_tool_calls=1))
    runner.execute(proposal(), {"text": "x"})
    with pytest.raises(BudgetExceededError):
        runner.execute(proposal(), {"text": "x"})
    assert calls == [1]


def test_decision_is_not_an_execution_token(registry: CapabilityRegistry) -> None:
    identity = WorkflowIdentity()
    decision = authorizer(registry, identity, grants=(grant(identity),)).authorize(proposal())
    assert decision.allowed
    calls: list[int] = []
    with pytest.raises(ContractValidationError):
        executor(registry, lambda *_: calls.append(1)).execute(decision, {"text": "x"})
    assert calls == []


def test_expired_workflow_never_invokes(
    registry: CapabilityRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness_engineering.execution as execution

    now = [0.0]
    monkeypatch.setattr(execution, "monotonic", lambda: now[0])
    calls: list[int] = []
    runner = executor(registry, lambda *_: calls.append(1))
    now[0] = 181.0
    with pytest.raises(ToolTimeoutError):
        runner.execute(proposal(), {"text": "x"})
    assert calls == []


def test_thread_exit_cannot_be_success(registry: CapabilityRegistry) -> None:
    def handler(inputs: BaseModel, context: ExecutionContext) -> object:
        raise SystemExit("handler exited")

    with pytest.raises(ToolExecutionError) as error:
        executor(registry, handler).execute(proposal(), {"text": "x"})
    assert isinstance(error.value.__cause__, SystemExit)
