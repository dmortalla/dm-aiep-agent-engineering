"""Deterministic authority and real local SQLite approval history/restart evidence."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest

from harness_engineering.approval_persistence import (
    MAX_EVENTS,
    MAX_REQUESTS,
    ApprovalEventKind,
    ApprovalNotFoundError,
    ApprovalPersistenceError,
    SQLiteApprovalStore,
)
from harness_engineering.approvals import (
    ActionBinding,
    ApprovalObservation,
    ApprovalPolicy,
    ApprovalPolicyEvaluator,
    ApprovalRequest,
    ApprovalSafetyState,
    BindingStatus,
    HumanDecision,
    HumanDecisionKind,
    HumanIdentity,
)
from harness_engineering.errors import AuthorityViolationError, ContractValidationError
from harness_engineering.permissions import RiskLevel
from harness_engineering.persistence import SQLiteCheckpointStore


def binding(**changes: object) -> ActionBinding:
    return ActionBinding.model_validate(
        {
            "workflow_id": UUID(int=1),
            "thread_id": UUID(int=2),
            "pending_action_id": "work-1",
            "action_version": 1,
            **changes,
        }
    )


def request(**changes: object) -> ApprovalRequest:
    return ApprovalRequest.model_validate(
        {
            "binding": binding(),
            "requester_id": "requester-1",
            "capability_id": "documents",
            "action": "write",
            "risk": RiskLevel.HIGH,
            "consequential": True,
            "privileged_scope": True,
            "escalation_required": True,
            "escalation_reason": "review before local write",
            **changes,
        }
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


def observation() -> ApprovalObservation:
    return ApprovalObservation(confidence=0.5, evidence="bounded pending evidence")


def decision(
    kind: HumanDecisionKind = HumanDecisionKind.APPROVE, **changes: object
) -> HumanDecision:
    return HumanDecision.model_validate(
        {
            "binding": binding(),
            "kind": kind,
            "evidence": "bounded decision evidence",
            "override_reason": "reviewed ordinary policy escalation"
            if kind is HumanDecisionKind.OVERRIDE
            else "",
            **changes,
        }
    )


@pytest.fixture
def actor() -> HumanIdentity:
    return HumanIdentity(principal_id="approver-1")


def evaluator(
    actor: HumanIdentity,
    *,
    pending: ApprovalRequest | None = None,
    policy: ApprovalPolicy | None = None,
) -> ApprovalPolicyEvaluator:
    return ApprovalPolicyEvaluator(
        request() if pending is None else pending,
        ApprovalPolicy() if policy is None else policy,
        approvers=(actor,),
        override_approvers=(actor,),
    )


def pending_store(path: Path, actor: HumanIdentity) -> SQLiteApprovalStore:
    store = SQLiteApprovalStore(path)
    store.request(evaluator(actor), observation(), safety=safety())
    return store


def accepted_store(
    path: Path, actor: HumanIdentity, kind: HumanDecisionKind = HumanDecisionKind.APPROVE
) -> SQLiteApprovalStore:
    store = pending_store(path, actor)
    store.decide(
        binding(), decision(kind), evaluator=evaluator(actor), actor=actor, safety=safety()
    )
    return store


def rewrite_event(path: Path, mutate: object, *, sequence: int = 2) -> None:
    with sqlite3.connect(path) as connection:
        raw = connection.execute(
            "SELECT payload FROM approval_events WHERE sequence = ?", (sequence,)
        ).fetchone()[0]
        data = json.loads(raw)
        mutate(data)
        connection.execute(
            "UPDATE approval_events SET payload = ? WHERE sequence = ?",
            (json.dumps(data), sequence),
        )


def test_pending_survives_reopen_and_preserves_complete_binding_and_audit(
    tmp_path: Path,
    actor: HumanIdentity,
) -> None:
    path = tmp_path / "approvals.sqlite"
    store = pending_store(path, actor)
    prior = store.load(binding())
    reopened = SQLiteApprovalStore(path)
    assert reopened.load(binding()) == prior
    assert prior.binding == binding()
    event = prior.events[0]
    assert event.sequence == 1 and event.kind is ApprovalEventKind.PENDING
    assert event.requested.request == request()
    assert event.requested.confidence_threshold == 0.80
    assert event.requested.observation == observation()
    assert not prior.prior_denial
    assert event.decided is None


@pytest.mark.parametrize(
    "kind,status",
    [
        (HumanDecisionKind.APPROVE, ApprovalEventKind.APPROVED),
        (HumanDecisionKind.DENY, ApprovalEventKind.DENIED),
        (HumanDecisionKind.OVERRIDE, ApprovalEventKind.OVERRIDDEN),
    ],
)
def test_decision_survives_restart_as_history(
    tmp_path: Path, actor: HumanIdentity, kind: HumanDecisionKind, status: ApprovalEventKind
) -> None:
    path = tmp_path / "db"
    store = accepted_store(path, actor, kind)
    prior = store.load(binding())
    history = SQLiteApprovalStore(path).load(binding())
    assert history == prior
    assert history.status is status
    assert history.events[-1].decided.approver_id == actor.principal_id
    assert history.events[-1].decided.decision == decision(kind)
    assert history.events[-1].decided.is_override is (kind is HumanDecisionKind.OVERRIDE)
    assert history.prior_denial is (kind is HumanDecisionKind.DENY)
    assert [event.sequence for event in history.events] == [1, 2]


def test_loaded_approver_text_cannot_mint_authority(tmp_path: Path, actor: HumanIdentity) -> None:
    path = tmp_path / "db"
    accepted_store(path, actor)
    reopened = SQLiteApprovalStore(path)
    historical = reopened.load(binding()).events[-1].decided
    copied = HumanIdentity(principal_id=historical.approver_id)
    with pytest.raises(AuthorityViolationError):
        reopened.consume(binding(), evaluator=evaluator(actor), actor=copied, safety=safety())
    with pytest.raises(AuthorityViolationError):
        reopened.consume(
            binding(), evaluator=evaluator(actor), actor=historical.approver_id, safety=safety()
        )
    assert reopened.load(binding()).status is ApprovalEventKind.APPROVED
    # Restart needs trusted bootstrap to install a handle afresh, not a name lookup in history.
    fresh = HumanIdentity(principal_id="approver-1")
    assert (
        reopened.consume(binding(), evaluator=evaluator(fresh), actor=fresh, safety=safety()).status
        is ApprovalEventKind.CONSUMED
    )


@pytest.mark.parametrize("source", ["dict", "checked-shaped", "loaded-history", "missing-actor"])
def test_no_import_of_decision_shaped_authority(
    tmp_path: Path, actor: HumanIdentity, source: str
) -> None:
    store = pending_store(tmp_path / "db", actor)
    policy = evaluator(actor)
    assessment = policy.check_decision(
        decision(), actor=actor, observation=observation(), safety=safety()
    )
    data = {
        "dict": decision().model_dump(),
        "checked-shaped": assessment,
        "loaded-history": store.load(binding()),
        "missing-actor": decision(),
    }[source]
    with pytest.raises((ContractValidationError, AuthorityViolationError)):
        store.decide(
            binding(),
            data,
            evaluator=policy,
            actor=None if source == "missing-actor" else actor,
            safety=safety(),
        )
    assert store.load(binding()).status is ApprovalEventKind.PENDING


@pytest.mark.parametrize("kind", [HumanDecisionKind.APPROVE, HumanDecisionKind.OVERRIDE])
def test_single_consumption_survives_restart(
    tmp_path: Path, actor: HumanIdentity, kind: HumanDecisionKind
) -> None:
    path = tmp_path / "db"
    store = accepted_store(path, actor, kind)
    consumed = store.consume(binding(), evaluator=evaluator(actor), actor=actor, safety=safety())
    assert consumed.status is ApprovalEventKind.CONSUMED
    assert [e.kind for e in consumed.events] == [
        ApprovalEventKind.PENDING,
        ApprovalEventKind.OVERRIDDEN
        if kind is HumanDecisionKind.OVERRIDE
        else ApprovalEventKind.APPROVED,
        ApprovalEventKind.CONSUMED,
    ]
    assert consumed.events[-1].decided.is_override is (kind is HumanDecisionKind.OVERRIDE)
    reopened = SQLiteApprovalStore(path)
    with pytest.raises(ApprovalPersistenceError, match="unconsumed"):
        reopened.consume(binding(), evaluator=evaluator(actor), actor=actor, safety=safety())
    assert reopened.load(binding()) == consumed


def test_competing_local_consumers_append_once(tmp_path: Path, actor: HumanIdentity) -> None:
    path = tmp_path / "db"
    accepted_store(path, actor)
    stores = (SQLiteApprovalStore(path), SQLiteApprovalStore(path))
    barrier = Barrier(2)

    def consume(store: SQLiteApprovalStore) -> str:
        barrier.wait(timeout=5)
        try:
            store.consume(binding(), evaluator=evaluator(actor), actor=actor, safety=safety())
        except ApprovalPersistenceError:
            return "rejected"
        return "consumed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, stores))
    assert sorted(results) == ["consumed", "rejected"]
    assert len(stores[0].load(binding()).events) == 3


@pytest.mark.parametrize("next_kind", list(HumanDecisionKind))
def test_denial_terminal_after_restart(
    tmp_path: Path, actor: HumanIdentity, next_kind: HumanDecisionKind
) -> None:
    path = tmp_path / "db"
    accepted_store(path, actor, HumanDecisionKind.DENY)
    store = SQLiteApprovalStore(path)
    assert store.load(binding()).prior_denial
    with pytest.raises(ApprovalPersistenceError, match="already decided"):
        store.decide(
            binding(),
            decision(next_kind),
            evaluator=evaluator(actor),
            actor=actor,
            safety=safety(prior_denial=False),
        )
    with pytest.raises(ApprovalPersistenceError):
        store.consume(binding(), evaluator=evaluator(actor), actor=actor, safety=safety())
    revised = request(binding=binding(action_version=2))
    with pytest.raises(ApprovalPersistenceError):
        store.request(evaluator(actor, pending=revised), observation(), safety=safety())
    denied = store.load(binding())
    assert len(denied.events) == 2
    # The durable fact also feeds accepted Slice 1 prior-denial semantics.
    with pytest.raises(AuthorityViolationError):
        evaluator(actor).check_decision(
            decision(next_kind),
            actor=actor,
            observation=observation(),
            safety=safety(prior_denial=denied.prior_denial),
        )


@pytest.mark.parametrize("next_kind", list(HumanDecisionKind))
def test_duplicate_conflicting_decision_fails_closed(
    tmp_path: Path, actor: HumanIdentity, next_kind: HumanDecisionKind
) -> None:
    store = accepted_store(tmp_path / "db", actor)
    with pytest.raises(ApprovalPersistenceError):
        store.decide(
            binding(), decision(next_kind), evaluator=evaluator(actor), actor=actor, safety=safety()
        )
    assert len(store.load(binding()).events) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_id", UUID(int=3)),
        ("thread_id", UUID(int=4)),
        ("pending_action_id", "work-2"),
        ("action_version", 2),
    ],
)
def test_every_exact_binding_dimension_checked(
    tmp_path: Path, actor: HumanIdentity, field: str, value: object
) -> None:
    store = accepted_store(tmp_path / "db", actor)
    other = binding(**{field: value})
    for operation in (
        lambda: store.load(other),
        lambda: store.consume(other, evaluator=evaluator(actor), actor=actor, safety=safety()),
        lambda: store.decide(
            other, decision(), evaluator=evaluator(actor), actor=actor, safety=safety()
        ),
    ):
        with pytest.raises(ApprovalPersistenceError):
            operation()
    assert store.load(binding()).status is ApprovalEventKind.APPROVED


def test_stale_pending_revision_is_never_selected(tmp_path: Path, actor: HumanIdentity) -> None:
    path = tmp_path / "db"
    store = pending_store(path, actor)
    revised_binding = binding(action_version=5)
    revised = request(binding=revised_binding)
    current_policy = evaluator(actor, pending=revised)
    store.request(current_policy, observation(), safety=safety())
    with pytest.raises(ApprovalPersistenceError, match="stale"):
        store.load(binding())
    with pytest.raises(ApprovalPersistenceError):
        store.decide(
            binding(), decision(), evaluator=evaluator(actor), actor=actor, safety=safety()
        )
    with pytest.raises(AuthorityViolationError, match="binding"):
        store.decide(
            revised_binding, decision(), evaluator=current_policy, actor=actor, safety=safety()
        )
    store.decide(
        revised_binding,
        decision(binding=revised_binding),
        evaluator=current_policy,
        actor=actor,
        safety=safety(),
    )
    assert len(store.load(revised_binding).events) == 3


@pytest.mark.parametrize("stage", ["decision", "consumption"])
@pytest.mark.parametrize(
    "facts",
    [
        {"action_blocklisted": True},
        {"capability_blocklisted": True},
        {"cancelled": True},
        {"authority_valid": False},
        {"hard_budget_exhausted": True},
        {"deadline_exhausted": True},
        {"scope_authorized": False},
        {"prior_denial": True},
        *[
            {"binding_status": state}
            for state in BindingStatus
            if state is not BindingStatus.CURRENT
        ],
    ],
)
def test_persistence_never_bypasses_current_hard_safety(
    tmp_path: Path,
    actor: HumanIdentity,
    stage: str,
    facts: dict[str, object],
) -> None:
    store = pending_store(tmp_path / "db", actor)
    if stage == "consumption":
        store.decide(
            binding(),
            decision(HumanDecisionKind.OVERRIDE),
            evaluator=evaluator(actor),
            actor=actor,
            safety=safety(),
        )
    before = store.load(binding())
    with pytest.raises(AuthorityViolationError):
        if stage == "decision":
            store.decide(
                binding(),
                decision(HumanDecisionKind.OVERRIDE),
                evaluator=evaluator(actor),
                actor=actor,
                safety=safety(**facts),
            )
        else:
            store.consume(
                binding(), evaluator=evaluator(actor), actor=actor, safety=safety(**facts)
            )
    assert store.load(binding()) == before


def test_current_policy_not_selected_by_history_and_revocation_is_enforced(
    tmp_path: Path,
    actor: HumanIdentity,
) -> None:
    store = accepted_store(tmp_path / "db", actor)
    revoked = ApprovalPolicyEvaluator(request(), ApprovalPolicy())
    with pytest.raises(AuthorityViolationError):
        store.consume(binding(), evaluator=revoked, actor=actor, safety=safety())
    changed = evaluator(actor, pending=request(capability_id="different"))
    with pytest.raises(ApprovalPersistenceError, match="action differs"):
        store.consume(binding(), evaluator=changed, actor=actor, safety=safety())
    other = HumanIdentity(principal_id="different-human")
    with pytest.raises(ApprovalPersistenceError, match="principal"):
        store.consume(binding(), evaluator=evaluator(other), actor=other, safety=safety())
    current = evaluator(actor, policy=ApprovalPolicy(confidence_threshold=0.99))
    consumed = store.consume(binding(), evaluator=current, actor=actor, safety=safety())
    assert consumed.events[-1].decided.assessment.confidence_threshold == 0.99
    assert consumed.events[0].requested.confidence_threshold == 0.80


@pytest.mark.parametrize(
    "case",
    [
        "schema",
        "state",
        "boolean-version",
        "binding",
        "sequence",
        "override-kind",
        "approver",
        "callback",
        "missing-evidence",
        "reasons",
        "hard-stops",
        "metadata",
    ],
)
def test_corrupt_event_fails_closed_on_reads_and_transitions(
    tmp_path: Path,
    actor: HumanIdentity,
    case: str,
) -> None:
    path = tmp_path / "db"
    store = accepted_store(path, actor)

    def corrupt(data: dict[str, object]) -> None:
        if case == "schema":
            data["schema_version"] = 99
        elif case == "state":
            data["state_version"] = 99
        elif case == "boolean-version":
            data["state_version"] = True
        elif case == "binding":
            data["binding"]["thread_id"] = str(UUID(int=3))
        elif case == "sequence":
            data["sequence"] = 3
        elif case == "override-kind":
            data["decided"]["decision"]["kind"] = "override"
            data["decided"]["decision"]["override_reason"] = "forged rationale"
        elif case == "approver":
            data["decided"]["approver_id"] = "requester-1"
        elif case == "callback":
            data["callback"] = "execute"
        elif case == "missing-evidence":
            del data["decided"]["decision"]["evidence"]
        elif case == "reasons":
            data["decided"]["assessment"]["triggers"] = []
        elif case == "hard-stops":
            data["decided"]["assessment"]["hard_stops"] = ["cancelled"]
        else:
            data["decided"]["assessment"]["request"]["capability_id"] = "forged"

    rewrite_event(path, corrupt)
    for operation in (
        lambda: store.load(binding()),
        lambda: store.audit(binding(), limit=1),
        lambda: store.consume(binding(), evaluator=evaluator(actor), actor=actor, safety=safety()),
    ):
        with pytest.raises(ApprovalPersistenceError):
            operation()


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "null",
        "[]",
        '{"kind":"pending","kind":"pending"}',
        "[" * 1100 + "]" * 1100,
        "x" * 65_537,
    ],
    ids=["broken", "null", "array", "duplicate-key", "deep", "oversized"],
)
def test_invalid_payloads_rejected(tmp_path: Path, actor: HumanIdentity, payload: str) -> None:
    path = tmp_path / "db"
    store = pending_store(path, actor)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE approval_events SET payload = ?", (payload,))
    with pytest.raises(ApprovalPersistenceError):
        store.load(binding())


@pytest.mark.parametrize(
    "case",
    [
        "gap",
        "row-thread",
        "row-version",
        "row-kind",
        "missing-binding",
        "conflicting-binding",
        "deleted-request",
    ],
)
def test_contradictory_row_or_history_rejected(
    tmp_path: Path, actor: HumanIdentity, case: str
) -> None:
    path = tmp_path / "db"
    store = accepted_store(path, actor)
    with sqlite3.connect(path) as connection:
        statements = {
            "gap": "UPDATE approval_events SET sequence=4 WHERE sequence=2",
            "row-thread": "UPDATE approval_events SET thread_id='wrong'",
            "row-version": "UPDATE approval_events SET action_version=3",
            "row-kind": "UPDATE approval_events SET kind='overridden' WHERE sequence=2",
            "missing-binding": "DELETE FROM approval_workflows",
            "conflicting-binding": "UPDATE approval_workflows SET thread_id='wrong'",
            "deleted-request": "DELETE FROM approval_events WHERE sequence=1",
        }
        connection.execute(statements[case])
    with pytest.raises(ApprovalPersistenceError):
        store.load(binding())


def test_conflicting_decision_row_and_altered_schema_fail_closed(
    tmp_path: Path,
    actor: HumanIdentity,
) -> None:
    path = tmp_path / "db"
    store = accepted_store(path, actor)
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT * FROM approval_events WHERE sequence=2").fetchone()
        data = json.loads(row[-1])
        data["sequence"] = 3
        connection.execute(
            "INSERT INTO approval_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (*row[:2], 3, *row[3:-1], json.dumps(data)),
        )
    with pytest.raises(ApprovalPersistenceError, match="history"):
        store.load(binding())
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE approval_events RENAME TO old_events")
        connection.execute("CREATE TABLE approval_events AS SELECT * FROM old_events")
        connection.execute("INSERT INTO approval_events SELECT * FROM old_events")
    with pytest.raises(ApprovalPersistenceError, match="schema"):
        store.load(binding())


def test_bounded_ordered_audit_and_revision_limit(tmp_path: Path, actor: HumanIdentity) -> None:
    store = pending_store(tmp_path / "db", actor)
    for version in range(2, MAX_REQUESTS + 1):
        revised = request(binding=binding(action_version=version))
        store.request(evaluator(actor, pending=revised), observation(), safety=safety())
    current = binding(action_version=MAX_REQUESTS)
    before = store.load(current)
    with pytest.raises(ApprovalPersistenceError, match="limit"):
        store.request(
            evaluator(actor, pending=request(binding=binding(action_version=MAX_REQUESTS + 1))),
            observation(),
            safety=safety(),
        )
    assert store.load(current) == before
    current_evaluator = evaluator(actor, pending=request(binding=current))
    store.decide(
        current,
        decision(binding=current),
        evaluator=current_evaluator,
        actor=actor,
        safety=safety(),
    )
    store.consume(current, evaluator=current_evaluator, actor=actor, safety=safety())
    assert len(store.load(current).events) == MAX_EVENTS
    assert [e.sequence for e in store.audit(current, after_sequence=2, limit=3)] == [3, 4, 5]
    assert store.audit(current, after_sequence=MAX_EVENTS, limit=1) == ()
    for kwargs in [
        {"limit": 0},
        {"limit": True},
        {"limit": MAX_EVENTS + 1},
        {"after_sequence": -1},
        {"after_sequence": True},
        {"after_sequence": "1"},
    ]:
        with pytest.raises(ApprovalPersistenceError):
            store.audit(current, **kwargs)


@pytest.mark.parametrize("target", ["request", "decision", "consume", "commit"])
def test_failed_transaction_never_reports_success_and_resources_close(
    tmp_path: Path,
    actor: HumanIdentity,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    path = tmp_path / "db"
    store = SQLiteApprovalStore(path)
    if target in {"decision", "consume", "commit"}:
        store.request(evaluator(actor), observation(), safety=safety())
    if target in {"consume", "commit"}:
        store.decide(
            binding(), decision(), evaluator=evaluator(actor), actor=actor, safety=safety()
        )
    original = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: tuple[object, ...] = (), /) -> sqlite3.Cursor:
            if sql.startswith("INSERT INTO approval_events") and target != "commit":
                raise sqlite3.OperationalError("injected insert failure")
            return super().execute(sql, parameters)

    def connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = FailingConnection
        connection = original(*args, **kwargs)
        if target == "commit":

            def reject_commit(operation: int, *_args: object) -> int:
                return (
                    sqlite3.SQLITE_DENY
                    if operation == sqlite3.SQLITE_TRANSACTION and _args[0] == "COMMIT"
                    else sqlite3.SQLITE_OK
                )

            connection.set_authorizer(reject_commit)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(ApprovalPersistenceError) as error:
        if target == "request":
            store.request(evaluator(actor), observation(), safety=safety())
        elif target == "decision":
            store.decide(
                binding(), decision(), evaluator=evaluator(actor), actor=actor, safety=safety()
            )
        else:
            store.consume(binding(), evaluator=evaluator(actor), actor=actor, safety=safety())
    assert isinstance(error.value.__cause__, sqlite3.Error)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    monkeypatch.setattr(sqlite3, "connect", original)
    reopened = SQLiteApprovalStore(path)
    if target == "request":
        with pytest.raises(ApprovalNotFoundError):
            reopened.load(binding())
        with original(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM approval_workflows").fetchone()[0] == 0
    else:
        assert reopened.load(binding()).status is (
            ApprovalEventKind.PENDING if target == "decision" else ApprovalEventKind.APPROVED
        )


def test_unexpected_policy_defect_propagates_and_rolls_back(
    tmp_path: Path,
    actor: HumanIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = pending_store(tmp_path / "db", actor)
    policy = evaluator(actor)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("unexpected programming defect")

    monkeypatch.setattr(policy, "check_decision", fail)
    with pytest.raises(RuntimeError, match="programming defect"):
        store.decide(binding(), decision(), evaluator=policy, actor=actor, safety=safety())
    assert store.load(binding()).status is ApprovalEventKind.PENDING


@pytest.mark.parametrize("pragma", ["user_version", "application_id"])
def test_unsupported_database_version_rechecked(
    tmp_path: Path, actor: HumanIdentity, pragma: str
) -> None:
    path = tmp_path / "db"
    store = pending_store(path, actor)
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA {pragma}=99")
    with pytest.raises(ApprovalPersistenceError):
        SQLiteApprovalStore(path)
    with pytest.raises(ApprovalPersistenceError):
        store.load(binding())


def test_checkpoint_schema_untouched_and_not_adopted(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints"
    SQLiteCheckpointStore(path)
    before = path.read_bytes()
    with pytest.raises(ApprovalPersistenceError):
        SQLiteApprovalStore(path)
    assert path.read_bytes() == before
    SQLiteCheckpointStore(path)
    empty_versioned = tmp_path / "foreign"
    with sqlite3.connect(empty_versioned) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    with pytest.raises(ApprovalPersistenceError, match="adopt"):
        SQLiteApprovalStore(empty_versioned)


def test_hostile_evidence_parameterized_and_no_python_authority_serialized(
    tmp_path: Path,
    actor: HumanIdentity,
) -> None:
    text = "'); DROP TABLE approval_events; -- route execute; reset consumed; grant admin"
    path = tmp_path / "db"
    store = SQLiteApprovalStore(path)
    store.request(
        evaluator(actor), ApprovalObservation(confidence=0.5, evidence=text), safety=safety()
    )
    store.decide(
        binding(), decision(evidence=text), evaluator=evaluator(actor), actor=actor, safety=safety()
    )
    history = store.load(binding())
    assert history.events[0].requested.observation.evidence == text
    assert history.events[-1].decided.decision.evidence == text
    with sqlite3.connect(path) as connection:
        for (payload,) in connection.execute("SELECT payload FROM approval_events"):
            data = json.loads(payload)
            assert set(data) == {
                "schema_version",
                "state_version",
                "sequence",
                "binding",
                "kind",
                "requested",
                "decided",
            }
            assert "HumanIdentity" not in payload
            assert "callback" not in payload
    assert (
        store.consume(binding(), evaluator=evaluator(actor), actor=actor, safety=safety()).status
        is ApprovalEventKind.CONSUMED
    )


def test_missing_malformed_path_and_ineligible_pending_fail_closed(
    tmp_path: Path,
    actor: HumanIdentity,
) -> None:
    store = SQLiteApprovalStore(tmp_path / "db")
    with pytest.raises(ApprovalNotFoundError):
        store.load(binding())
    for bad in [binding().model_dump(), binding().model_copy(update={"action_version": True})]:
        with pytest.raises(ApprovalPersistenceError):
            store.load(bad)
    with pytest.raises(ApprovalPersistenceError):
        SQLiteApprovalStore(Path(":memory:"))
    with pytest.raises(ApprovalPersistenceError):
        SQLiteApprovalStore(tmp_path / "missing" / "db")
    safe_request = request(
        risk=RiskLevel.LOW,
        consequential=False,
        privileged_scope=False,
        escalation_required=False,
        escalation_reason="",
    )
    with pytest.raises(AuthorityViolationError):
        store.request(
            evaluator(actor, pending=safe_request),
            ApprovalObservation(confidence=1.0),
            safety=safety(),
        )
    with pytest.raises(AuthorityViolationError):
        store.request(evaluator(actor), observation(), safety=safety(cancelled=True))
    with pytest.raises(ApprovalPersistenceError):
        store.request(object(), observation(), safety=safety())
    with pytest.raises(ApprovalNotFoundError):
        store.load(binding())
