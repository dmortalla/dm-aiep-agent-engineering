"""Application-owned data snapshots and local SQLite storage, without resume authority.

Snapshot counters describe consumed resources, never configured limits. Work IDs
are inert references, not graph routes. Approval/effect slots must remain empty
until later application-owned verification contracts are implemented.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness_engineering.errors import HarnessError

SCHEMA_VERSION = 1
STATE_VERSION = 1
MAX_PAYLOAD_BYTES = 1_048_576
Reference = Annotated[str, Field(min_length=1, max_length=128, strict=True)]
Counter = Annotated[int, Field(ge=0, le=1_000_000, strict=True)]


class PersistenceError(HarnessError):
    """Invalid checkpoint or failed local storage operation; never retry execution."""


class CheckpointNotFoundError(PersistenceError):
    """No checkpoint exists for the requested identity and sequence."""


class SnapshotData(BaseModel):
    """Immutable, strictly validated persistence data with no executable configuration."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class CheckpointIdentity(SnapshotData):
    """Explicit stable identity; deserialization never generates missing IDs."""

    workflow_id: UUID
    thread_id: UUID


class ConsumedBudget(SnapshotData):
    """Historical consumption only; trusted bootstrap must supply all future limits."""

    tool_calls: Counter
    provider_attempts: Counter
    context_tokens: Counter
    output_tokens: Counter
    elapsed_milliseconds: Counter


class RetrySnapshot(SnapshotData):
    """Bounded historical attempt count, without retry policy or callbacks."""

    work_id: Reference
    attempts: Annotated[int, Field(ge=0, le=3, strict=True)]


class CompletedWork(SnapshotData):
    """Untrusted result text associated with an inert work reference."""

    work_id: Reference
    result: Annotated[str, Field(max_length=4096, strict=True)]


class Checkpoint(SnapshotData):
    """Versioned snapshot, validated data only; never usable as runtime authority.

    Every field is required, including empty reserved slots. Sequence is a
    caller-owned positive integer, not a timestamp. Work ordering is preserved.
    """

    schema_version: Annotated[int, Field(strict=True)]
    state_version: Annotated[int, Field(strict=True)]
    identity: CheckpointIdentity
    sequence: Annotated[int, Field(ge=1, le=1000, strict=True)]
    completed_work: Annotated[tuple[CompletedWork, ...], Field(max_length=100)]
    pending_work: Annotated[tuple[Reference, ...], Field(max_length=100)]
    consumed_budget: ConsumedBudget
    retry_state: Annotated[tuple[RetrySnapshot, ...], Field(max_length=100)]
    cancelled: bool
    approval_records: tuple[()]
    committed_effects: tuple[()]

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        """Reject unsupported versions and inconsistent or duplicate work references."""
        if self.schema_version != SCHEMA_VERSION or self.state_version != STATE_VERSION:
            raise ValueError("Unsupported checkpoint schema/state version.")
        completed = [item.work_id for item in self.completed_work]
        work = completed + list(self.pending_work)
        retries = [item.work_id for item in self.retry_state]
        if len(work) > 100 or len(set(work)) != len(work):
            raise ValueError("Work references must be unique and total at most 100.")
        if len(set(retries)) != len(retries) or not set(retries).issubset(work):
            raise ValueError("Retry references must be unique and refer to recorded work.")
        return self


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def _decode(payload: str) -> Checkpoint:
    if type(payload) is not str or len(payload) > MAX_PAYLOAD_BYTES:
        raise PersistenceError("Checkpoint payload must be bounded UTF-8 JSON text.")
    try:
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("Checkpoint exceeds payload byte limit.")
        json.loads(payload, object_pairs_hook=_unique_object)
        return Checkpoint.model_validate_json(payload)
    except (ValueError, RecursionError) as exc:
        raise PersistenceError("Malformed or unsupported checkpoint payload.") from exc


class SQLiteCheckpointStore:
    """Append-only local snapshots with one stable thread per workflow.

    Each operation opens and closes its own connection. Explicit BEGIN IMMEDIATE
    transactions atomically bind identity and insert a snapshot. No persistent
    connection, framework checkpointer, or runtime execution is involved.
    """

    def __init__(self, path: Path) -> None:
        """Initialize a file database.

        Args:
            path: Application-selected local file, never a persisted setting.

        Raises:
            PersistenceError: If initialization or database version validation fails.
        """
        if not isinstance(path, Path) or str(path) == ":memory:":
            raise PersistenceError("Supply a local SQLite file Path, not :memory:.")
        self._path = path
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise PersistenceError("Unsupported SQLite database schema version.")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS workflow_bindings "
                "(workflow_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS checkpoints "
                "(workflow_id TEXT NOT NULL REFERENCES workflow_bindings(workflow_id), "
                "sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 1000), "
                "thread_id TEXT NOT NULL, payload TEXT NOT NULL, "
                "PRIMARY KEY(workflow_id, sequence))"
            )
            connection.execute("PRAGMA user_version = 1")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self._path, timeout=1.0)
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        except sqlite3.Error as exc:
            raise PersistenceError(
                "SQLite operation failed; inspect local database integrity."
            ) from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _identity(identity: CheckpointIdentity) -> tuple[str, str]:
        try:
            checked = CheckpointIdentity.model_validate(identity)
        except ValidationError as exc:
            raise PersistenceError("Explicit valid workflow/thread identity required.") from exc
        return str(checked.workflow_id), str(checked.thread_id)

    @staticmethod
    def _binding(connection: sqlite3.Connection, workflow: str, thread: str) -> bool:
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise PersistenceError("Unsupported SQLite database schema version.")
        rows = connection.execute(
            "SELECT thread_id FROM workflow_bindings WHERE workflow_id = ? LIMIT 2", (workflow,)
        ).fetchall()
        if rows and (len(rows) != 1 or rows[0][0] != thread):
            raise PersistenceError("Conflicting or mismatched workflow/thread binding.")
        return bool(rows)

    def save(self, checkpoint: Checkpoint) -> None:
        """Atomically append a validated snapshot; reject overwrite or sequence regression.

        Args:
            checkpoint: Explicit application snapshot, not bootstrap configuration.

        Raises:
            PersistenceError: For invalid data, identity/sequence conflict, or SQL failure.
        """
        try:
            checked = Checkpoint.model_validate(checkpoint)
        except ValidationError as exc:
            raise PersistenceError("Invalid checkpoint for save.") from exc
        payload = json.dumps(
            checked.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        _decode(payload)
        workflow, thread = self._identity(checked.identity)
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            bound = self._binding(connection, workflow, thread)
            latest = connection.execute(
                "SELECT MAX(sequence) FROM checkpoints WHERE workflow_id = ?", (workflow,)
            ).fetchone()[0]
            if latest is not None and (
                type(latest) is not int
                or not 1 <= latest <= 1000
                or not bound
                or checked.sequence <= latest
            ):
                raise PersistenceError(
                    "Conflicting checkpoint sequence or missing identity binding."
                )
            if not bound:
                connection.execute(
                    "INSERT INTO workflow_bindings VALUES (?, ?)", (workflow, thread)
                )
            connection.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?)",
                (workflow, checked.sequence, thread, payload),
            )

    def load(self, identity: CheckpointIdentity, *, sequence: int | None = None) -> Checkpoint:
        """Load an exact sequence or the greatest stored sequence, failing closed.

        Args:
            identity: Trusted caller's expected workflow and thread.
            sequence: Exact positive sequence; None selects latest without fallback on corruption.

        Returns:
            Validated inert snapshot. It does not authorize resume or certify effects/approvals.

        Raises:
            CheckpointNotFoundError: When no requested checkpoint exists.
            PersistenceError: For malformed, mismatched, ambiguous, or unsupported records.
        """
        workflow, thread = self._identity(identity)
        if sequence is not None and (type(sequence) is not int or not 1 <= sequence <= 1000):
            raise PersistenceError("Exact sequence must be an integer from 1 to 1000.")
        with self._connection() as connection, connection:
            connection.execute("BEGIN")
            bound = self._binding(connection, workflow, thread)
            sql = (
                "SELECT sequence, thread_id, "
                "CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload ELSE NULL END "
                "FROM checkpoints WHERE workflow_id = ?"
            )
            parameters: tuple[object, ...] = (MAX_PAYLOAD_BYTES, workflow)
            if sequence is not None:
                sql += " AND sequence = ?"
                parameters += (sequence,)
            rows = connection.execute(
                sql + " ORDER BY sequence DESC LIMIT 2", parameters
            ).fetchall()
            if not rows:
                raise CheckpointNotFoundError("Requested checkpoint does not exist.")
            if not bound or (len(rows) > 1 and rows[0][0] == rows[1][0]):
                raise PersistenceError("Missing binding or ambiguous checkpoint lookup.")
            stored_sequence, stored_thread, payload = rows[0]
            checked = _decode(payload)
            if (
                stored_thread != thread
                or checked.identity != identity
                or type(stored_sequence) is not int
                or checked.sequence != stored_sequence
            ):
                raise PersistenceError("Checkpoint row and payload identity/sequence mismatch.")
            return checked
