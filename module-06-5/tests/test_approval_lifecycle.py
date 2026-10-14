"""Application-owned HITL over real LangGraph and real local SQLite, without native HITL."""

import gc
import json
import sqlite3
import weakref
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from harness_engineering.approval_lifecycle import (
    ApprovalAction,
    ApprovalLifecycle,
    ApprovalLifecycleError,
    SuspendedWorkflow,
)
from harness_engineering.approval_persistence import ApprovalEventKind, SQLiteApprovalStore
from harness_engineering.approvals import (
    ActionBinding,
    ApprovalObservation,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalSafetyState,
    BindingStatus,
    HumanDecision,
    HumanDecisionKind,
    HumanIdentity,
)
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.orchestration import (
    LifecycleInput,
    LifecyclePhase,
    PreferredPathUnavailable,
    StepResult,
    StopReason,
    TransientStepError,
)
from harness_engineering.permissions import RiskLevel
from harness_engineering.persistence import CheckpointIdentity, SQLiteCheckpointStore
from harness_engineering.planning import ExecutableSubtask, ExecutionPlan

IDENTITY = CheckpointIdentity(workflow_id=UUID(int=1), thread_id=UUID(int=2))
INPUT = LifecycleInput(text="exact accepted local action input")


def plan(*, deadline: float = 180.0, second_id: str = "b") -> ExecutionPlan:
    return ExecutionPlan(
        goal="Application-owned HITL",
        tasks=(
            ExecutableSubtask(task_id="a", description="safe local prelude"),
            ExecutableSubtask(
                task_id=second_id, description="protected local result", dependencies=("a",)
            ),
        ),
        budget=RuntimeBudget(
            workflow_deadline_seconds=deadline, latency_slo_p95_seconds=min(5.0, deadline)
        ),
    )


def safety(**changes: object) -> ApprovalSafetyState:
    return ApprovalSafetyState.model_validate(
        {
            "action_blocklisted": False,
            "capability_blocklisted": False,
            "cancelled": False,
            "binding_status": BindingStatus.CURRENT,
            "authority_valid": True,
            "hard_budget_exhausted": False,
            "deadline_exhausted": False,
            "scope_authorized": True,
            "prior_denial": False,
            **changes,
        }
    )


def declaration(
    task_id: str,
    actor: HumanIdentity,
    override: HumanIdentity,
    *,
    identity: CheckpointIdentity = IDENTITY,
    version: int = 1,
    confidence: float | None = None,
    **facts: object,
) -> ApprovalAction:
    return ApprovalAction(
        request=ApprovalRequest.model_validate(
            {
                "binding": ActionBinding(
                    workflow_id=identity.workflow_id,
                    thread_id=identity.thread_id,
                    pending_action_id=task_id,
                    action_version=version,
                ),
                "requester_id": "requester-1",
                "capability_id": "local",
                "action": "evaluate",
                "risk": RiskLevel.LOW,
                "consequential": False,
                "privileged_scope": False,
                "escalation_required": False,
                "escalation_reason": "",
                **facts,
            }
        ),
        observation=ApprovalObservation(
            confidence=(1.0 if task_id == "a" else 0.5) if confidence is None else confidence
        ),
        policy=ApprovalPolicy(),
        approvers=(actor,),
        override_approvers=(override,),
        safety=lambda: safety(),
    )


@pytest.fixture
def humans() -> tuple[HumanIdentity, HumanIdentity]:
    return HumanIdentity(principal_id="approver-1"), HumanIdentity(principal_id="override-1")


def actions(
    humans: tuple[HumanIdentity, HumanIdentity], **kwargs: object
) -> tuple[ApprovalAction, ...]:
    return declaration("a", *humans), declaration("b", *humans, **kwargs)


def build(
    path: Path,
    calls: list[str],
    now: list[float],
    humans: tuple[HumanIdentity, HumanIdentity],
    *,
    declarations: tuple[ApprovalAction, ...] | None = None,
    accepted: ExecutionPlan | None = None,
    identity: CheckpointIdentity = IDENTITY,
    **options: object,
) -> ApprovalLifecycle:
    def execute(task: ExecutableSubtask, _data: LifecycleInput) -> StepResult:
        calls.append(task.task_id)
        now[0] += 1.0
        return StepResult(text=f"done:{task.task_id}")

    chosen = plan() if accepted is None else accepted
    configuration = {
        "elapsed_seconds": lambda: now[0],
        "clock": lambda: now[0],
        "cancellation": lambda: False,
        "wait": lambda _: None,
        **options,
    }
    return ApprovalLifecycle(
        chosen,
        execute,
        SQLiteCheckpointStore(path / "checkpoints.sqlite"),
        SQLiteApprovalStore(path / "approvals.sqlite"),
        identity,
        actions(humans) if declarations is None else declarations,
        restart_safe_work=frozenset(task.task_id for task in chosen.tasks),
        **configuration,
    )


def checkpoint(path: Path):
    return SQLiteCheckpointStore(path / "checkpoints.sqlite").load(IDENTITY)


def approve(
    path: Path,
    declaration: ApprovalAction,
    actor: HumanIdentity,
    kind: HumanDecisionKind = HumanDecisionKind.APPROVE,
) -> None:
    # Independently constructed store/evaluator; no original runtime is used.
    store = SQLiteApprovalStore(path / "approvals.sqlite")
    store.decide(
        declaration.request.binding,
        HumanDecision(
            binding=declaration.request.binding,
            kind=kind,
            evidence="local review",
            override_reason="authorized ordinary override"
            if kind is HumanDecisionKind.OVERRIDE
            else "",
        ),
        evaluator=declaration.evaluator(),
        actor=actor,
        safety=declaration.safety(),
    )


def test_real_graph_suspends_without_human_wait_and_returns_only_inert_references(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    waits: list[float] = []
    now = [0.0]
    lifecycle = build(tmp_path, calls, now, humans, wait=waits.append)
    assert isinstance(lifecycle._runtime._graph, CompiledStateGraph)
    assert lifecycle._runtime._graph.checkpointer is None
    result = lifecycle.start(INPUT)
    assert isinstance(result, SuspendedWorkflow)
    assert calls == ["a"] and waits == []
    assert result.binding == actions(humans)[1].request.binding
    assert set(result.model_dump()) == {
        "status",
        "binding",
        "checkpoint_sequence",
        "approval_sequence",
    }
    assert "HumanIdentity" not in result.model_dump_json()
    assert checkpoint(tmp_path).completed_work[0].work_id == "a"
    assert checkpoint(tmp_path).pending_work == ("b",)
    assert [r.work_id for r in checkpoint(tmp_path).retry_state] == ["a"]
    history = SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(result.binding)
    assert history.status is ApprovalEventKind.PENDING
    assert result.checkpoint_sequence == checkpoint(tmp_path).sequence
    assert result.approval_sequence == 1


def test_discard_original_and_fresh_explicit_resume_consumes_once(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    now = [0.0]
    original = build(tmp_path, calls, now, humans)
    suspended = original.start(INPUT)
    reference = weakref.ref(original)
    del original
    gc.collect()
    assert reference() is None
    fresh_humans = (
        HumanIdentity(principal_id="approver-1"),
        HumanIdentity(principal_id="override-1"),
    )
    current_actions = actions(fresh_humans)
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(suspended.binding).status
        is ApprovalEventKind.PENDING
    )
    now[0] = 30.0  # Independent trusted workflow age includes human waiting.
    approve(tmp_path, current_actions[1], fresh_humans[0])
    assert calls == ["a"]
    fresh = build(tmp_path, calls, now, fresh_humans, declarations=current_actions)
    outcome = fresh.resume(INPUT, actor=fresh_humans[0])
    assert outcome.phase is LifecyclePhase.COMPLETED
    assert outcome.completed_task_ids == ("a", "b")
    assert calls == ["a", "b"]
    history = SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(suspended.binding)
    assert history.status is ApprovalEventKind.CONSUMED
    assert len(history.events) == 3
    assert checkpoint(tmp_path).consumed_budget.elapsed_milliseconds >= 31_000
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, fresh_humans).resume(INPUT, actor=fresh_humans[0])
    assert calls == ["a", "b"]


@pytest.mark.parametrize("status", ["missing", "pending", "denied"])
def test_missing_pending_denied_cannot_resume_or_execute(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    status: str,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    if status == "missing":
        with sqlite3.connect(tmp_path / "approvals.sqlite") as connection:
            connection.execute("DELETE FROM approval_events")
    elif status == "denied":
        approve(tmp_path, actions(humans)[1], humans[0], HumanDecisionKind.DENY)
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0])
    assert calls == ["a"]
    if status == "denied":
        denied = SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(
            actions(humans)[1].request.binding
        )
        assert denied.prior_denial
        for kind, actor in [
            (HumanDecisionKind.APPROVE, humans[0]),
            (HumanDecisionKind.OVERRIDE, humans[1]),
        ]:
            with pytest.raises(HarnessError):
                approve(tmp_path, actions(humans)[1], actor, kind)
        with pytest.raises(HarnessError):
            build(tmp_path, calls, now, humans, declarations=actions(humans, version=2)).resume(
                INPUT, actor=humans[0]
            )
        # Loosening policy cannot make the same denied logical action runnable.
        loosened = tuple(
            replace(a, policy=ApprovalPolicy(confidence_threshold=0.0, approval_risks=()))
            for a in actions(humans)
        )
        with pytest.raises(HarnessError):
            build(tmp_path, calls, now, humans, declarations=loosened).resume(
                INPUT, actor=humans[0]
            )


@pytest.mark.parametrize(
    "dimension", ["workflow", "thread", "action", "version", "input", "task-input"]
)
def test_changed_exact_binding_and_callback_inputs_fail_closed(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    dimension: str,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    identity = IDENTITY
    accepted = plan()
    declarations = actions(humans)
    data = INPUT
    if dimension in {"workflow", "thread"}:
        identity = CheckpointIdentity(
            workflow_id=UUID(int=3) if dimension == "workflow" else IDENTITY.workflow_id,
            thread_id=UUID(int=4) if dimension == "thread" else IDENTITY.thread_id,
        )
        declarations = (
            declaration("a", *humans, identity=identity),
            declaration("b", *humans, identity=identity),
        )
    elif dimension == "action":
        accepted = plan(second_id="disguised-replacement")
        declarations = (declaration("a", *humans), declaration("disguised-replacement", *humans))
    elif dimension == "version":
        declarations = actions(humans, version=2)
    elif dimension == "input":
        data = LifecycleInput(text="changed tool input after review")
    else:
        changed_task = accepted.tasks[1].model_copy(
            update={"description": "changed accepted action"}
        )
        accepted = accepted.model_copy(update={"tasks": (accepted.tasks[0], changed_task)})
    with pytest.raises(HarnessError):
        build(
            tmp_path,
            calls,
            now,
            humans,
            identity=identity,
            accepted=accepted,
            declarations=declarations,
        ).resume(data, actor=humans[0])
    assert calls == ["a"]


@pytest.mark.parametrize(
    "source", ["copied", "persisted", "string", "unknown", "missing", "revoked"]
)
def test_current_human_authority_not_reconstructed_from_history(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    source: str,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    candidates = {
        "copied": humans[0].model_copy(),
        "persisted": HumanIdentity.model_validate_json(humans[0].model_dump_json()),
        "string": humans[0].principal_id,
        "unknown": HumanIdentity(principal_id="unknown"),
        "missing": None,
        "revoked": humans[0],
    }
    current = actions(humans)
    if source == "revoked":
        current = tuple(replace(a, approvers=()) for a in current)
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans, declarations=current).resume(
            INPUT, actor=candidates[source]
        )
    assert calls == ["a"]
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(current[1].request.binding).status
        is ApprovalEventKind.APPROVED
    )


@pytest.mark.parametrize(
    "change", ["tightened-threshold", "new-risk-trigger", "loosened-threshold"]
)
def test_current_policy_revalidated_independently_of_history(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    change: str,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    policy = {
        "tightened-threshold": ApprovalPolicy(confidence_threshold=0.9),
        "new-risk-trigger": ApprovalPolicy(approval_risks=(RiskLevel.LOW,)),
        "loosened-threshold": ApprovalPolicy(confidence_threshold=0.7),
    }[change]
    current = actions(humans)
    current = (current[0], replace(current[1], policy=policy))
    fresh = build(tmp_path, calls, now, humans, declarations=current)
    if change == "loosened-threshold":
        assert fresh.resume(INPUT, actor=humans[0]).phase is LifecyclePhase.COMPLETED
        history = SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(
            current[1].request.binding
        )
        assert history.events[-1].decided.assessment.confidence_threshold == 0.7
    else:
        with pytest.raises(ApprovalLifecycleError, match="policy tightened"):
            fresh.resume(INPUT, actor=humans[0])
        assert calls == ["a"]


@pytest.mark.parametrize("kind", [HumanDecisionKind.APPROVE, HumanDecisionKind.OVERRIDE])
@pytest.mark.parametrize(
    "facts",
    [
        {"action_blocklisted": True},
        {"capability_blocklisted": True},
        {"cancelled": True},
        {"hard_budget_exhausted": True},
        {"deadline_exhausted": True},
        {"scope_authorized": False},
        {"authority_valid": False},
        {"prior_denial": True},
        {"binding_status": BindingStatus.STALE},
        {"binding_status": BindingStatus.FORGED},
    ],
)
def test_current_hard_safety_cannot_be_overridden(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    kind: HumanDecisionKind,
    facts: dict[str, object],
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    actor = humans[1] if kind is HumanDecisionKind.OVERRIDE else humans[0]
    approve(tmp_path, actions(humans)[1], actor, kind)
    current = actions(humans)
    current = (current[0], replace(current[1], safety=lambda: safety(**facts)))
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans, declarations=current).resume(INPUT, actor=actor)
    assert calls == ["a"]


def test_valid_separately_authorized_override_can_resume(
    tmp_path: Path, humans: tuple[HumanIdentity, HumanIdentity]
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[1], HumanDecisionKind.OVERRIDE)
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0])
    assert (
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[1]).phase
        is LifecyclePhase.COMPLETED
    )


@pytest.mark.parametrize(
    "control",
    [
        "cancellation-source",
        "runtime-switch",
        "human-wait-deadline",
        "regressed-age",
        "persisted-budget",
        "checkpoint-capacity",
    ],
)
def test_real_runtime_controls_and_recovery_bounds_checked_before_consumption(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    control: str,
) -> None:
    calls: list[str] = []
    now = [0.0]
    accepted = plan(deadline=10.0)
    build(tmp_path, calls, now, humans, accepted=accepted).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    options = {}
    if control == "cancellation-source":
        options["cancellation"] = lambda: True
    elif control == "human-wait-deadline":
        now[0] = 10.0
    elif control == "regressed-age":
        options["elapsed_seconds"] = lambda: 0.0
    elif control in {"persisted-budget", "checkpoint-capacity"}:
        latest = checkpoint(tmp_path)
        update = {"sequence": latest.sequence + 1}
        if control == "persisted-budget":
            update["consumed_budget"] = latest.consumed_budget.model_copy(update={"tool_calls": 13})
        else:
            update["sequence"] = 995
        SQLiteCheckpointStore(tmp_path / "checkpoints.sqlite").save(
            latest.model_copy(update=update)
        )
    fresh = build(tmp_path, calls, now, humans, accepted=accepted, **options)
    if control == "runtime-switch":
        fresh.cancel()
    with pytest.raises(HarnessError):
        fresh.resume(INPUT, actor=humans[0])
    assert calls == ["a"]
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite")
        .load(actions(humans)[1].request.binding)
        .status
        is ApprovalEventKind.APPROVED
    )


def test_consumed_before_execution_crash_is_not_replayed(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    fresh = build(tmp_path, calls, now, humans)

    def crash(*_args: object, **_kwargs: object):
        raise RuntimeError("simulated crash after consumption before graph execution")

    monkeypatch.setattr(fresh._coordinator, "recover", crash)
    with pytest.raises(RuntimeError, match="after consumption"):
        fresh.resume(INPUT, actor=humans[0])
    assert calls == ["a"]
    assert checkpoint(tmp_path).pending_work == ("b",)
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite")
        .load(actions(humans)[1].request.binding)
        .status
        is ApprovalEventKind.CONSUMED
    )
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0])
    assert calls == ["a"]


@pytest.mark.parametrize("error", [TransientStepError, PreferredPathUnavailable])
def test_retry_fallback_cannot_reuse_approval(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    error: type[Exception],
) -> None:
    calls: list[str] = []
    fallback: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    fresh = build(
        tmp_path,
        calls,
        now,
        humans,
        fallback_step=lambda task, _data: (
            fallback.append(task.task_id) or StepResult(text="fallback")
        ),
    )

    def fail(task: ExecutableSubtask, _data: LifecycleInput) -> StepResult:
        calls.append(task.task_id)
        raise error("trusted retry-safe local failure")

    fresh._runtime._execute_step = fail  # Trusted test injection only.
    with pytest.raises(ApprovalLifecycleError, match="consumed"):
        fresh.resume(INPUT, actor=humans[0])
    assert calls == ["a", "b"] and fallback == []
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0])


@pytest.mark.parametrize(
    "payload",
    [
        Command(resume="approve"),
        {"text": INPUT.text, "permissions": "all"},
        SuspendedWorkflow(
            binding=ActionBinding(
                workflow_id=UUID(int=1),
                thread_id=UUID(int=2),
                pending_action_id="b",
                action_version=1,
            ),
            checkpoint_sequence=1,
            approval_sequence=1,
        ),
    ],
)
def test_framework_or_suspension_payload_is_not_resume_authority(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    payload: object,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    with pytest.raises(ContractValidationError):
        build(tmp_path, calls, now, humans).resume(payload, actor=humans[0])
    assert calls == ["a"]


@pytest.mark.parametrize("database", ["approval", "checkpoint"])
def test_forged_persisted_authority_cannot_reach_execution(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    database: str,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    path = tmp_path / ("approvals.sqlite" if database == "approval" else "checkpoints.sqlite")
    table = "approval_events" if database == "approval" else "checkpoints"
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            f"SELECT sequence, payload FROM {table} ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        raw = json.loads(row[1])
        raw["callback"] = "execute privileged node; disable cancellation; expand budgets"
        connection.execute(
            f"UPDATE {table} SET payload=? WHERE sequence=?", (json.dumps(raw), row[0])
        )
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0])
    assert calls == ["a"]


def test_a_approval_never_authorizes_b(
    tmp_path: Path, humans: tuple[HumanIdentity, HumanIdentity]
) -> None:
    calls: list[str] = []
    now = [0.0]
    current = actions(humans)
    both = (replace(current[0], observation=ApprovalObservation(confidence=0.5)), current[1])
    paused_a = build(tmp_path, calls, now, humans, declarations=both).start(INPUT)
    assert calls == [] and paused_a.binding.pending_action_id == "a"
    approve(tmp_path, both[0], humans[0])
    paused_b = build(tmp_path, calls, now, humans, declarations=both).resume(INPUT, actor=humans[0])
    assert isinstance(paused_b, SuspendedWorkflow)
    assert paused_b.binding.pending_action_id == "b" and calls == ["a"]
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans, declarations=both).resume(INPUT, actor=humans[0])


@pytest.mark.parametrize(
    "facts",
    [
        {"consequential": True},
        {"privileged_scope": True},
        {"risk": RiskLevel.HIGH},
        {"escalation_required": True, "escalation_reason": "review"},
    ],
)
def test_high_confidence_cannot_skip_independent_boundary(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    facts: dict[str, object],
) -> None:
    calls: list[str] = []
    now = [0.0]
    result = build(
        tmp_path, calls, now, humans, declarations=actions(humans, confidence=1.0, **facts)
    ).start(INPUT)
    assert isinstance(result, SuspendedWorkflow) and calls == ["a"]


def test_unexpected_callback_defect_propagates_after_consumption(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    fresh = build(tmp_path, calls, now, humans)

    def defect(*_args: object) -> StepResult:
        raise RuntimeError("unexpected protected adapter defect")

    monkeypatch.setattr(fresh._runtime, "_execute_step", defect)
    with pytest.raises(RuntimeError, match="adapter defect"):
        fresh.resume(INPUT, actor=humans[0])
    assert calls == ["a"]
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite")
        .load(actions(humans)[1].request.binding)
        .status
        is ApprovalEventKind.CONSUMED
    )


def test_invalid_bootstrap_and_safety_fail_closed(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    now = [0.0]
    with pytest.raises(ContractValidationError):
        build(tmp_path, calls, now, humans, declarations=())
    malformed = actions(humans)
    malformed = (malformed[0], replace(malformed[1], safety=lambda: {"scope_authorized": True}))
    with pytest.raises(ContractValidationError):
        build(tmp_path, calls, now, humans, declarations=malformed).start(INPUT)
    assert calls == ["a"]


def test_recorded_cancellation_survives_fresh_false_source(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    now = [0.0]
    original = build(tmp_path, calls, now, humans)
    original.start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    original.cancel()
    assert checkpoint(tmp_path).cancelled
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans, cancellation=lambda: False).resume(
            INPUT, actor=humans[0]
        )
    assert calls == ["a"]


def test_active_callback_cancellation_retains_completed_prefix(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    now = [0.0]
    original = build(tmp_path, calls, now, humans)

    def step(task: ExecutableSubtask, _data: LifecycleInput) -> StepResult:
        calls.append(task.task_id)
        original.cancel()
        return StepResult(text="completed before cooperative cancellation")

    original._runtime._execute_step = step
    result = original.start(INPUT)
    assert result.phase is LifecyclePhase.SAFE_STOP
    assert result.stop_reason is StopReason.CANCELLED
    assert result.completed_task_ids == ("a",)
    assert checkpoint(tmp_path).cancelled
    assert checkpoint(tmp_path).completed_work[0].work_id == "a"
    assert calls == ["a"]


@pytest.mark.parametrize("control", ["cancelled", "scope"])
def test_safety_changed_after_consumption_prevents_actual_execution(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    monkeypatch: pytest.MonkeyPatch,
    control: str,
) -> None:
    calls: list[str] = []
    now = [0.0]
    switched = [False]
    current = actions(humans)
    current = (
        current[0],
        replace(current[1], safety=lambda: safety(scope_authorized=not switched[0])),
    )
    build(tmp_path, calls, now, humans, declarations=current).start(INPUT)
    approve(tmp_path, current[1], humans[0])
    fresh = build(
        tmp_path,
        calls,
        now,
        humans,
        declarations=current,
        cancellation=lambda: switched[0] if control == "cancelled" else False,
    )
    real_consume = fresh._approvals.consume

    def consume(*args: object, **kwargs: object):
        result = real_consume(*args, **kwargs)
        switched[0] = True
        return result

    monkeypatch.setattr(fresh._approvals, "consume", consume)
    if control == "cancelled":
        outcome = fresh.resume(INPUT, actor=humans[0])
        assert outcome.phase is LifecyclePhase.SAFE_STOP
        assert outcome.stop_reason is StopReason.CANCELLED
        assert checkpoint(tmp_path).cancelled
    else:
        with pytest.raises(ApprovalLifecycleError, match="hard safety"):
            fresh.resume(INPUT, actor=humans[0])
    assert calls == ["a"]
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(current[1].request.binding).status
        is ApprovalEventKind.CONSUMED
    )
    with pytest.raises(HarnessError):
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0])


def test_out_of_band_consumption_is_not_a_transferable_execution_token(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    action = actions(humans)[1]
    approve(tmp_path, action, humans[0])
    SQLiteApprovalStore(tmp_path / "approvals.sqlite").consume(
        action.request.binding, evaluator=action.evaluator(), actor=humans[0], safety=safety()
    )
    with pytest.raises(ApprovalLifecycleError):
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0])
    assert calls == ["a"]


def test_suspended_instance_cannot_reuse_its_old_authority_bootstrap(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    now = [0.0]
    original = build(tmp_path, calls, now, humans)
    original.start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    with pytest.raises(ApprovalLifecycleError, match="fresh lifecycle"):
        original.resume(INPUT, actor=humans[0])
    assert calls == ["a"]
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite")
        .load(actions(humans)[1].request.binding)
        .status
        is ApprovalEventKind.APPROVED
    )
    assert (
        build(tmp_path, calls, now, humans).resume(INPUT, actor=humans[0]).phase
        is LifecyclePhase.COMPLETED
    )


def test_real_graph_node_execution_follows_application_owned_consumption(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])
    fresh = build(tmp_path, calls, now, humans)
    observed: list[str] = []

    class Nodes(BaseCallbackHandler):
        raise_error = True

        def on_chain_start(
            self,
            serialized: dict[str, object] | None,
            inputs: object,
            *,
            metadata: dict[str, object] | None = None,
            **kwargs: object,
        ) -> None:
            if (
                kwargs.get("name") == "execute"
                and metadata is not None
                and metadata.get("langgraph_node") == "execute"
            ):
                observed.append("real_graph_execute_node")

    real_invoke = fresh._runtime._graph.invoke
    real_consume = fresh._approvals.consume
    real_step = fresh._runtime._execute_step

    def invoke(data: object, config: dict, **kwargs: object):
        assert isinstance(data, dict) and not isinstance(data, Command)
        return real_invoke(data, config={**config, "callbacks": [Nodes()]}, **kwargs)

    def consume(*args: object, **kwargs: object):
        result = real_consume(*args, **kwargs)
        observed.append("application_store_consumption_committed")
        return result

    def step(task: ExecutableSubtask, data: LifecycleInput) -> StepResult:
        observed.append("protected_adapter_entered")
        return real_step(task, data)

    monkeypatch.setattr(fresh._runtime._graph, "invoke", invoke)
    monkeypatch.setattr(fresh._approvals, "consume", consume)
    monkeypatch.setattr(fresh._runtime, "_execute_step", step)
    assert fresh.resume(INPUT, actor=humans[0]).phase is LifecyclePhase.COMPLETED
    assert observed == [
        "application_store_consumption_committed",
        "real_graph_execute_node",
        "protected_adapter_entered",
    ]
    assert calls == ["a", "b"]
    assert fresh._runtime._graph.checkpointer is None


def test_unexpected_current_safety_defect_propagates_before_consumption(
    tmp_path: Path,
    humans: tuple[HumanIdentity, HumanIdentity],
) -> None:
    calls: list[str] = []
    now = [0.0]
    build(tmp_path, calls, now, humans).start(INPUT)
    approve(tmp_path, actions(humans)[1], humans[0])

    def defect() -> ApprovalSafetyState:
        raise RuntimeError("current trusted safety source defect")

    current = actions(humans)
    current = (current[0], replace(current[1], safety=defect))
    with pytest.raises(RuntimeError, match="source defect"):
        build(tmp_path, calls, now, humans, declarations=current).resume(INPUT, actor=humans[0])
    assert calls == ["a"]
    assert (
        SQLiteApprovalStore(tmp_path / "approvals.sqlite").load(current[1].request.binding).status
        is ApprovalEventKind.APPROVED
    )
