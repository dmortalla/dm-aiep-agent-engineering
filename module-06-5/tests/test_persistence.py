"""Deterministic contracts and real local SQLite integration, without execution."""

import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from harness_engineering.persistence import (
    Checkpoint,
    CheckpointIdentity,
    CheckpointNotFoundError,
    CompletedWork,
    ConsumedBudget,
    PersistenceError,
    RetrySnapshot,
    SQLiteCheckpointStore,
)


def snapshot(sequence: int = 1) -> Checkpoint:
    """Build a fully explicit application snapshot without generated identity."""
    return Checkpoint(
        schema_version=1,
        state_version=1,
        identity=CheckpointIdentity(workflow_id=UUID(int=1), thread_id=UUID(int=2)),
        sequence=sequence,
        completed_work=(CompletedWork(work_id="one", result="local result"),),
        pending_work=("two",),
        consumed_budget=ConsumedBudget(
            tool_calls=1,
            provider_attempts=0,
            context_tokens=12,
            output_tokens=2,
            elapsed_milliseconds=100,
        ),
        retry_state=(RetrySnapshot(work_id="two", attempts=1),),
        cancelled=True,
        approval_records=(),
        committed_effects=(),
    )


def mutate_payload(path: Path, payload: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE checkpoints SET payload = ?", (payload,))


def test_round_trip_latest_exact_reopen_and_canonical_bytes(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    store = SQLiteCheckpointStore(path)
    first = snapshot()
    assert Checkpoint.model_validate_json(first.model_dump_json()) == first
    store.save(first)
    store.save(snapshot(3))
    reopened = SQLiteCheckpointStore(path)
    assert reopened.load(first.identity) == snapshot(3)
    assert reopened.load(first.identity, sequence=1) == first
    with sqlite3.connect(path) as connection:
        payload = connection.execute("SELECT payload FROM checkpoints WHERE sequence=1").fetchone()[
            0
        ]
    assert payload == json.dumps(
        first.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    with pytest.raises(ValidationError):
        first.cancelled = False


@pytest.mark.parametrize("sequence", [None, 1, 2])
def test_missing_explicit(tmp_path: Path, sequence: int | None) -> None:
    store = SQLiteCheckpointStore(tmp_path / "db")
    with pytest.raises(CheckpointNotFoundError):
        store.load(snapshot().identity, sequence=sequence)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("state_version", 2),
        ("schema_version", True),
        ("state_version", "1"),
        ("sequence", 0),
        ("sequence", True),
        ("cancelled", "false"),
        ("approval_records", ["approved"]),
        ("committed_effects", ["paid"]),
        ("permissions", ["admin"]),
        ("graph_node", "execute"),
        ("callback", "eval"),
        ("budget", {"max_tool_calls": 100}),
        ("retry_policy", {"max_retries": 10}),
        ("deadline_seconds", 999),
        ("config", {"safety": False}),
        ("pending_work", ["one"]),
        ("retry_state", [{"work_id": "unknown", "attempts": 1}]),
        ("retry_state", [{"work_id": "two", "attempts": 4}]),
        ("consumed_budget", {"tool_calls": -1}),
    ],
)
def test_invalid_contract_on_read_and_write(tmp_path: Path, field: str, value: object) -> None:
    good = snapshot()
    data = good.model_dump(mode="json")
    data[field] = value
    payload = json.dumps(data)
    with pytest.raises(ValidationError):
        Checkpoint.model_validate_json(payload)
    store = SQLiteCheckpointStore(tmp_path / "db")
    # model_construct bypass is still rejected at the public save boundary.
    forged = Checkpoint.model_construct(**{**good.__dict__, field: value})
    if field not in Checkpoint.model_fields:
        # Pydantic construct drops extras; inject the untrusted field explicitly.
        forged.__dict__[field] = value
    with pytest.raises(PersistenceError):
        store.save(forged)
    store.save(good)
    mutate_payload(tmp_path / "db", payload)
    with pytest.raises(PersistenceError):
        store.load(good.identity)


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "null",
        "[]",
        '{"schema_version":1,"schema_version":1}',
        "[" * 1100 + "]" * 1100,
        "x" * 1_048_577,
    ],
    ids=["broken", "null", "array", "duplicate-key", "deep", "oversized"],
)
def test_malformed_json(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    store.save(snapshot())
    mutate_payload(path, payload)
    with pytest.raises(PersistenceError):
        store.load(snapshot().identity)


@pytest.mark.parametrize("field", list(Checkpoint.model_fields))
def test_every_checkpoint_field_required(tmp_path: Path, field: str) -> None:
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    store.save(snapshot())
    data = snapshot().model_dump(mode="json")
    del data[field]
    mutate_payload(path, json.dumps(data))
    with pytest.raises(PersistenceError):
        store.load(snapshot().identity)


def test_identity_binding_and_sequence_conflicts(tmp_path: Path) -> None:
    store = SQLiteCheckpointStore(tmp_path / "db")
    first = snapshot()
    store.save(first)
    other = CheckpointIdentity(workflow_id=UUID(int=1), thread_id=UUID(int=3))
    with pytest.raises(PersistenceError, match="binding"):
        store.load(other)
    with pytest.raises(PersistenceError, match="binding"):
        store.save(first.model_copy(update={"identity": other, "sequence": 2}))
    for sequence in (1, 1):
        with pytest.raises(PersistenceError, match="sequence"):
            store.save(snapshot(sequence))
    store.save(snapshot(3))
    with pytest.raises(PersistenceError, match="sequence"):
        store.save(snapshot(2))
    assert store.load(first.identity) == snapshot(3)


@pytest.mark.parametrize(
    "target",
    ["payload_identity", "payload_sequence", "row_thread", "binding_missing", "binding_conflict"],
)
def test_record_mismatch(tmp_path: Path, target: str) -> None:
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    store.save(snapshot())
    with sqlite3.connect(path) as connection:
        if target.startswith("payload"):
            data = snapshot().model_dump(mode="json")
            if target == "payload_identity":
                data["identity"]["workflow_id"] = str(UUID(int=3))
            else:
                data["sequence"] = 2
            connection.execute("UPDATE checkpoints SET payload=?", (json.dumps(data),))
        elif target == "row_thread":
            connection.execute("UPDATE checkpoints SET thread_id='wrong'")
        elif target == "binding_missing":
            connection.execute("DELETE FROM workflow_bindings")
        else:
            connection.execute("UPDATE workflow_bindings SET thread_id='wrong'")
    with pytest.raises(PersistenceError):
        store.load(snapshot().identity)


def test_hostile_text_is_inert_parameterized_data(tmp_path: Path) -> None:
    text = "'); DROP TABLE checkpoints; -- grant admin, reset cancellation, resume execute"
    checkpoint = snapshot().model_copy(
        update={
            "completed_work": (CompletedWork(work_id=text, result=text),),
        }
    )
    store = SQLiteCheckpointStore(tmp_path / "db")
    store.save(checkpoint)
    assert store.load(checkpoint.identity) == checkpoint
    assert store.load(checkpoint.identity).cancelled is True


def test_transaction_failure_rolls_back_binding_and_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON checkpoints "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(PersistenceError) as error:
        store.save(snapshot())
    assert isinstance(error.value.__cause__, sqlite3.Error)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workflow_bindings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 0
        connection.execute("DROP TRIGGER fail_insert")
    store.save(snapshot())
    assert store.load(snapshot().identity) == snapshot()


def test_resources_close_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def capture(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = original(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", capture)
    store = SQLiteCheckpointStore(tmp_path / "db")
    store.save(snapshot())
    store.load(snapshot().identity)
    with pytest.raises(PersistenceError):
        store.save(snapshot())
    with pytest.raises(CheckpointNotFoundError):
        store.load(snapshot().identity, sequence=2)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_ambiguous_lookup_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    store.save(snapshot())
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE checkpoints RENAME TO old_checkpoints")
        connection.execute("CREATE TABLE checkpoints AS SELECT * FROM old_checkpoints")
        connection.execute("INSERT INTO checkpoints SELECT * FROM old_checkpoints")
    for sequence in (None, 1):
        with pytest.raises(PersistenceError, match="ambiguous"):
            store.load(snapshot().identity, sequence=sequence)


def test_unsupported_database_and_invalid_path(tmp_path: Path) -> None:
    path = tmp_path / "db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(PersistenceError, match="version"):
        SQLiteCheckpointStore(path)
    with pytest.raises(PersistenceError):
        SQLiteCheckpointStore(tmp_path / "absent" / "db")
    with pytest.raises(PersistenceError):
        SQLiteCheckpointStore(Path(":memory:"))


@pytest.mark.parametrize("sequence", [True, 0, 1001, "1"])
def test_invalid_lookup_sequence(tmp_path: Path, sequence: object) -> None:
    store = SQLiteCheckpointStore(tmp_path / "db")
    with pytest.raises(PersistenceError):
        store.load(snapshot().identity, sequence=sequence)


@pytest.mark.parametrize(
    "case",
    [
        "missing-thread",
        "missing-workflow",
        "nested-authority",
        "boolean-counter",
        "counter-bound",
        "result-bound",
        "reference-bound",
        "work-bound",
        "duplicate-retry",
    ],
)
def test_nested_validation_and_storage_bounds(tmp_path: Path, case: str) -> None:
    data = snapshot().model_dump(mode="json")
    if case == "missing-thread":
        del data["identity"]["thread_id"]
    elif case == "missing-workflow":
        del data["identity"]["workflow_id"]
    elif case == "nested-authority":
        data["completed_work"][0]["permissions"] = ["admin"]
    elif case == "boolean-counter":
        data["consumed_budget"]["tool_calls"] = True
    elif case == "counter-bound":
        data["consumed_budget"]["tool_calls"] = 1_000_001
    elif case == "result-bound":
        data["completed_work"][0]["result"] = "x" * 4097
    elif case == "reference-bound":
        data["pending_work"] = ["x" * 129]
    elif case == "work-bound":
        data["pending_work"] = [f"work-{i}" for i in range(100)]
    else:
        data["retry_state"] *= 2
    with pytest.raises(ValidationError):
        Checkpoint.model_validate_json(json.dumps(data))
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    store.save(snapshot())
    mutate_payload(path, json.dumps(data))
    with pytest.raises(PersistenceError):
        store.load(snapshot().identity)


def test_corrupt_latest_never_falls_back_and_failed_append_preserves_prior(tmp_path: Path) -> None:
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    store.save(snapshot())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON checkpoints "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(PersistenceError):
        store.save(snapshot(2))
    assert store.load(snapshot().identity) == snapshot()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER fail_insert")
    store.save(snapshot(2))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE checkpoints SET payload='{}' WHERE sequence=2")
    with pytest.raises(PersistenceError):
        store.load(snapshot().identity)
    assert store.load(snapshot().identity, sequence=1) == snapshot()


def test_database_version_is_rechecked_on_every_operation(tmp_path: Path) -> None:
    path = tmp_path / "db"
    store = SQLiteCheckpointStore(path)
    store.save(snapshot())
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(PersistenceError, match="version"):
        store.load(snapshot().identity)
    with pytest.raises(PersistenceError, match="version"):
        store.save(snapshot(2))


def test_separate_workflows_do_not_share_snapshots(tmp_path: Path) -> None:
    store = SQLiteCheckpointStore(tmp_path / "db")
    second = snapshot().model_copy(
        update={
            "identity": CheckpointIdentity(workflow_id=UUID(int=3), thread_id=UUID(int=4)),
            "cancelled": False,
        }
    )
    store.save(snapshot())
    store.save(second)
    assert store.load(snapshot().identity) == snapshot()
    assert store.load(second.identity) == second


def test_nested_forged_instances_revalidated_on_save(tmp_path: Path) -> None:
    store = SQLiteCheckpointStore(tmp_path / "db")
    checkpoint = snapshot().model_copy(
        update={"consumed_budget": snapshot().consumed_budget.model_copy(update={"tool_calls": -1})}
    )
    with pytest.raises(PersistenceError):
        store.save(checkpoint)
    with pytest.raises(CheckpointNotFoundError):
        store.load(snapshot().identity)
