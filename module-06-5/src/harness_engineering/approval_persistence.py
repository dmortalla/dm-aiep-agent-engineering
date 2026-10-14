"""Application-owned approval history and atomic consumption in a separate SQLite file.

No runtime, callback, human handle, or execution token is serialized. Installed
Slice 1 authority is rechecked inside each decision/consumption transaction.
Loaded history is inert and unauthenticated; direct database writers can forge
coherent history. Application APIs only append and never clear terminal state.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, ValidationError, model_validator

from harness_engineering.approvals import (
    ActionBinding,
    ApprovalAssessment,
    ApprovalContract,
    ApprovalObservation,
    ApprovalPolicyEvaluator,
    ApprovalSafetyState,
    ApprovalTrigger,
    DecisionAssessment,
    HumanDecision,
    HumanDecisionKind,
    HumanIdentity,
)
from harness_engineering.errors import AuthorityViolationError
from harness_engineering.persistence import PersistenceError

APPROVAL_SCHEMA_VERSION = 1
APPROVAL_STATE_VERSION = 1
APPLICATION_ID = 0x41505052
MAX_REQUESTS = 32
MAX_EVENTS = MAX_REQUESTS + 2
MAX_EVENT_BYTES = 65_536
WORKFLOWS_SQL = (
    "CREATE TABLE approval_workflows (workflow_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL)"
)
EVENTS_SQL = (
    "CREATE TABLE approval_events "
    "(workflow_id TEXT NOT NULL REFERENCES approval_workflows(workflow_id), "
    "pending_action_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 34), "
    "thread_id TEXT NOT NULL, action_version INTEGER NOT NULL, kind TEXT NOT NULL, "
    "payload TEXT NOT NULL, PRIMARY KEY(workflow_id, pending_action_id, sequence))"
)


class ApprovalPersistenceError(PersistenceError):
    """Durable approval data is invalid, conflicting, or unavailable for transition."""


class ApprovalNotFoundError(ApprovalPersistenceError):
    """The requested logical pending action has no durable history."""


class ApprovalEventKind(StrEnum):
    """Append-only lifecycle events; denial and override are explicit audit events."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    OVERRIDDEN = "overridden"
    CONSUMED = "consumed"


def _validate[Contract: ApprovalContract](value: Contract, model: type[Contract]) -> Contract:
    if type(value) is not model:
        raise ApprovalPersistenceError(f"An explicit {model.__name__} is required.")
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise ApprovalPersistenceError(f"Malformed {model.__name__}.") from exc


def _check_assessment(assessment: ApprovalAssessment) -> None:
    """Check reconstructable audit invariants, without selecting current policy."""
    request = assessment.request
    expected = {
        ApprovalTrigger.LOW_CONFIDENCE: assessment.observation.confidence
        < assessment.confidence_threshold,
        ApprovalTrigger.CONSEQUENTIAL: request.consequential,
        ApprovalTrigger.PRIVILEGED_SCOPE: request.privileged_scope,
        ApprovalTrigger.ESCALATION: request.escalation_required,
    }
    reasons = assessment.triggers
    if (
        assessment.hard_stops
        or reasons != tuple(reason for reason in ApprovalTrigger if reason in reasons)
        or any((reason in reasons) != active for reason, active in expected.items())
    ):
        raise ValueError("Contradictory approval assessment or hard-stop claim.")
    # CONFIGURED_RISK is historical evidence: its original configured risk set
    # is not a source of current policy. Current evaluator recomputes it on writes.


class ApprovalAuditEvent(ApprovalContract):
    """Versioned inert audit event, never a fresh approval authority object."""

    schema_version: int = Field(strict=True)
    state_version: int = Field(strict=True)
    sequence: int = Field(ge=1, le=MAX_EVENTS, strict=True)
    binding: ActionBinding
    kind: ApprovalEventKind
    requested: ApprovalAssessment | None
    decided: DecisionAssessment | None

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        """Reject unsupported versions, inconsistent event kinds, and mismatched binding."""
        if (
            self.schema_version != APPROVAL_SCHEMA_VERSION
            or self.state_version != APPROVAL_STATE_VERSION
        ):
            raise ValueError("Unsupported approval schema/state version.")
        if self.kind is ApprovalEventKind.PENDING:
            if self.requested is None or self.decided is not None:
                raise ValueError("Pending event requires only a request assessment.")
            _check_assessment(self.requested)
            if (
                not self.requested.approval_required
                or self.requested.request.binding != self.binding
            ):
                raise ValueError("Pending approval must be required and exactly bound.")
        else:
            if self.requested is not None or self.decided is None:
                raise ValueError("Decision/consumption event requires only a decision assessment.")
            checked = self.decided
            _check_assessment(checked.assessment)
            if (
                checked.decision.binding != self.binding
                or checked.assessment.request.binding != self.binding
            ):
                raise ValueError("Decision assessment and event binding disagree.")
            expected = {
                HumanDecisionKind.APPROVE: ApprovalEventKind.APPROVED,
                HumanDecisionKind.DENY: ApprovalEventKind.DENIED,
                HumanDecisionKind.OVERRIDE: ApprovalEventKind.OVERRIDDEN,
            }[checked.decision.kind]
            if self.kind is ApprovalEventKind.CONSUMED:
                if checked.terminal_for_action:
                    raise ValueError("Denial cannot be consumed.")
            elif self.kind is not expected:
                raise ValueError("Event kind contradicts human decision/override classification.")
            if (
                checked.approver_id == checked.assessment.request.requester_id
                and not checked.terminal_for_action
            ):
                raise ValueError("Persisted requester self-approval is invalid.")
        return self


class ApprovalHistory(ApprovalContract):
    """Bounded historical events; status derives from history, never a submitted flag."""

    binding: ActionBinding
    events: tuple[ApprovalAuditEvent, ...] = Field(min_length=1, max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        """Validate consecutive ordering, revisions, decision uniqueness, and consumption."""
        pending: ApprovalAuditEvent | None = None
        decision: DecisionAssessment | None = None
        consumed = False
        requests = 0
        for sequence, event in enumerate(self.events, 1):
            if event.sequence != sequence:
                raise ValueError("Approval history has gaps, duplicates, or ambiguous ordering.")
            if (
                event.binding.workflow_id != self.binding.workflow_id
                or event.binding.thread_id != self.binding.thread_id
                or event.binding.pending_action_id != self.binding.pending_action_id
            ):
                raise ValueError("History contains another workflow/thread/action binding.")
            if event.kind is ApprovalEventKind.PENDING:
                requests += 1
                if (
                    decision is not None
                    or requests > MAX_REQUESTS
                    or (
                        pending is not None
                        and event.binding.action_version <= pending.binding.action_version
                    )
                ):
                    raise ValueError(
                        "Request revision is duplicate, regressed, or already decided."
                    )
                pending = event
            else:
                if pending is None or consumed or event.binding != pending.binding:
                    raise ValueError(
                        "Decision/consumption lacks the current exact pending binding."
                    )
                checked = event.decided
                if (
                    checked.assessment.request != pending.requested.request
                    or checked.assessment.observation != pending.requested.observation
                ):
                    raise ValueError(
                        "Decision metadata or observation differs from pending request."
                    )
                if event.kind is ApprovalEventKind.CONSUMED:
                    if (
                        decision is None
                        or decision.terminal_for_action
                        or checked.decision != decision.decision
                        or checked.approver_id != decision.approver_id
                    ):
                        raise ValueError("Consumption lacks a unique matching accepted approval.")
                    consumed = True
                else:
                    if decision is not None:
                        raise ValueError("Duplicate or conflicting human decisions.")
                    decision = checked
        if self.events[-1].binding != self.binding:
            raise ValueError("Requested action version is stale or mismatched.")
        return self

    @property
    def status(self) -> ApprovalEventKind:
        """Read current durable status, without issuing execution authority."""
        return self.events[-1].kind

    @property
    def prior_denial(self) -> bool:
        """Provide the durable terminal-denial fact for later trusted revalidation."""
        return self.status is ApprovalEventKind.DENIED


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def _encode(event: ApprovalAuditEvent) -> str:
    checked = _validate(event, ApprovalAuditEvent)
    payload = json.dumps(
        checked.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    _decode(payload)
    return payload


def _decode(payload: str) -> ApprovalAuditEvent:
    if type(payload) is not str or len(payload) > MAX_EVENT_BYTES:
        raise ApprovalPersistenceError("Approval payload must be bounded JSON text.")
    try:
        if len(payload.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("Approval event exceeds its byte limit.")
        raw = json.loads(payload, object_pairs_hook=_unique_object)
        event = ApprovalAuditEvent.model_validate_json(payload)
        if event.model_dump(mode="json") != raw:
            raise ValueError("Approval record contains missing/defaulted or noncanonical data.")
        return event
    except (ValueError, RecursionError) as exc:
        raise ApprovalPersistenceError("Malformed or unsupported durable approval event.") from exc


class SQLiteApprovalStore:
    """Dedicated append-only SQLite approval journal, compatible with untouched Story 6.

    Use a separate application-selected file. Reads/writes validate the whole
    bounded logical action history; a decision is accepted once and consumption
    is appended once. No public import/replace/clear-authority API exists.
    """

    def __init__(self, path: Path) -> None:
        """Initialize or validate this store's database without adopting another schema.

        Args:
            path: Dedicated local approval file, never persisted configuration.

        Raises:
            ApprovalPersistenceError: For foreign, incompatible, or unavailable databases.
        """
        if not isinstance(path, Path) or str(path) == ":memory:":
            raise ApprovalPersistenceError("Use a dedicated local approval database Path.")
        self._path = path
        with self._connection(write=True, initialize=True) as connection:
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if application == 0 and version == 0:
                if connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                    raise ApprovalPersistenceError("Refusing to adopt an existing database schema.")
                connection.execute(WORKFLOWS_SQL)
                connection.execute(EVENTS_SQL)
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                connection.execute("PRAGMA user_version = 1")
            self._metadata(connection)

    @contextmanager
    def _connection(
        self, *, write: bool = False, initialize: bool = False
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self._path, timeout=1.0)
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                if not initialize:
                    self._metadata(connection)
                yield connection
        except sqlite3.Error as exc:
            raise ApprovalPersistenceError(
                "Approval SQLite operation failed; no transition succeeded."
            ) from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _metadata(connection: sqlite3.Connection) -> None:
        if (
            connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or connection.execute("PRAGMA user_version").fetchone()[0] != APPROVAL_SCHEMA_VERSION
        ):
            raise ApprovalPersistenceError("Unsupported approval database identity/schema version.")
        tables = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE name IN (?, ?)",
                ("approval_workflows", "approval_events"),
            ).fetchall()
        )
        if tables != {"approval_workflows": WORKFLOWS_SQL, "approval_events": EVENTS_SQL}:
            raise ApprovalPersistenceError("Approval table schema is missing or altered.")

    @staticmethod
    def _workflow(connection: sqlite3.Connection, binding: ActionBinding) -> bool:
        rows = connection.execute(
            "SELECT thread_id FROM approval_workflows WHERE workflow_id = ? LIMIT 2",
            (str(binding.workflow_id),),
        ).fetchall()
        if rows and (len(rows) != 1 or rows[0][0] != str(binding.thread_id)):
            raise ApprovalPersistenceError("Conflicting workflow/thread approval binding.")
        return bool(rows)

    def _read(
        self, connection: sqlite3.Connection, binding: ActionBinding
    ) -> ApprovalHistory | None:
        bound = self._workflow(connection, binding)
        rows = connection.execute(
            "SELECT sequence, thread_id, action_version, kind, "
            "CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload ELSE NULL END "
            "FROM approval_events WHERE workflow_id = ? AND pending_action_id = ? "
            "ORDER BY sequence LIMIT ?",
            (MAX_EVENT_BYTES, str(binding.workflow_id), binding.pending_action_id, MAX_EVENTS + 1),
        ).fetchall()
        if not rows:
            return None
        if not bound or len(rows) > MAX_EVENTS:
            raise ApprovalPersistenceError(
                "Approval history is unbound or exceeds its event limit."
            )
        events = []
        for sequence, thread, version, kind, payload in rows:
            event = _decode(payload)
            if (
                type(sequence) is not int
                or type(version) is not int
                or event.sequence != sequence
                or str(event.binding.thread_id) != thread
                or event.binding.action_version != version
                or event.kind.value != kind
            ):
                raise ApprovalPersistenceError("Approval row contradicts its payload.")
            events.append(event)
        try:
            # Use the stored latest version only to reconstruct historical data,
            # never to nominate the caller's expected binding or current policy.
            return ApprovalHistory(binding=events[-1].binding, events=tuple(events))
        except ValidationError as exc:
            raise ApprovalPersistenceError("Contradictory or ambiguous approval history.") from exc

    @staticmethod
    def _current(history: ApprovalHistory | None, binding: ActionBinding) -> ApprovalHistory:
        if history is None:
            raise ApprovalNotFoundError("No approval request exists for this action.")
        if history.binding != binding:
            raise ApprovalPersistenceError("Expected approval binding is stale or mismatched.")
        return history

    def _append(self, connection: sqlite3.Connection, event: ApprovalAuditEvent) -> ApprovalHistory:
        binding = event.binding
        if not self._workflow(connection, binding):
            connection.execute(
                "INSERT INTO approval_workflows VALUES (?, ?)",
                (str(binding.workflow_id), str(binding.thread_id)),
            )
        connection.execute(
            "INSERT INTO approval_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(binding.workflow_id),
                binding.pending_action_id,
                event.sequence,
                str(binding.thread_id),
                binding.action_version,
                event.kind.value,
                _encode(event),
            ),
        )
        return self._current(self._read(connection, binding), binding)

    @staticmethod
    def _evaluator(evaluator: ApprovalPolicyEvaluator) -> None:
        if type(evaluator) is not ApprovalPolicyEvaluator:
            raise ApprovalPersistenceError("Supply an application-owned Slice 1 policy evaluator.")

    def request(
        self,
        evaluator: ApprovalPolicyEvaluator,
        observation: ApprovalObservation,
        *,
        safety: ApprovalSafetyState,
    ) -> ApprovalHistory:
        """Append a pending request or a strictly newer still-undecided action revision.

        Args:
            evaluator: Current trusted request, policy, and installed human allowlists.
            observation: Bounded untrusted confidence/evidence to retain for audit.
            safety: Current application facts; no hard stop may apply.

        Returns:
            Inert history after atomic pending-request append.

        Raises:
            ApprovalPersistenceError: For duplicates, terminal action, bounds, or storage failure.
            AuthorityViolationError: If approval is not required or a hard stop applies.
            ContractValidationError: If Slice 1 inputs are malformed.
        """
        self._evaluator(evaluator)
        assessment = evaluator.evaluate(observation, safety=safety)
        if assessment.hard_stops or not assessment.approval_required:
            raise AuthorityViolationError("Pending approval requires an eligible approval trigger.")
        binding = assessment.request.binding
        with self._connection(write=True) as connection:
            history = self._read(connection, binding)
            count = 0 if history is None else len(history.events)
            if history is not None and (
                history.status is not ApprovalEventKind.PENDING
                or binding.action_version <= history.binding.action_version
            ):
                raise ApprovalPersistenceError("Request is already decided, duplicate, or stale.")
            if count >= MAX_REQUESTS:
                raise ApprovalPersistenceError(
                    "Pending revision limit reached; no authority was reset."
                )
            return self._append(
                connection,
                ApprovalAuditEvent(
                    schema_version=1,
                    state_version=1,
                    sequence=count + 1,
                    binding=binding,
                    kind=ApprovalEventKind.PENDING,
                    requested=assessment,
                    decided=None,
                ),
            )

    def decide(
        self,
        binding: ActionBinding,
        decision: HumanDecision,
        *,
        evaluator: ApprovalPolicyEvaluator,
        actor: HumanIdentity | None,
        safety: ApprovalSafetyState,
    ) -> ApprovalHistory:
        """Check live Slice 1 authority inside a transaction, then append one human decision.

        Args:
            binding: Trusted exact currently pending action.
            decision: Human intent data; an assessment/loaded record is not accepted.
            evaluator: Current application-owned Slice 1 evaluator, never loaded configuration.
            actor: Original currently installed ordinary/override human handle.
            safety: Current trusted safety facts, not a persisted consumed/denied flag.

        Returns:
            Inert accepted/denied history only after successful commit.

        Raises:
            ApprovalPersistenceError: For missing/stale/decided/corrupt records or SQL failure.
            AuthorityViolationError: When current Slice 1 authority or safety rejects the decision.
            ContractValidationError: When Slice 1 inputs fail validation.
        """
        binding = _validate(binding, ActionBinding)
        self._evaluator(evaluator)
        with self._connection(write=True) as connection:
            history = self._current(self._read(connection, binding), binding)
            if history.status is not ApprovalEventKind.PENDING:
                raise ApprovalPersistenceError(
                    "Approval already decided; denial/consumption cannot be replaced."
                )
            pending = history.events[-1].requested
            checked = evaluator.check_decision(
                decision, actor=actor, observation=pending.observation, safety=safety
            )
            if checked.assessment.request != pending.request:
                raise ApprovalPersistenceError(
                    "Current trusted action metadata differs from the pending request."
                )
            kind = {
                HumanDecisionKind.APPROVE: ApprovalEventKind.APPROVED,
                HumanDecisionKind.DENY: ApprovalEventKind.DENIED,
                HumanDecisionKind.OVERRIDE: ApprovalEventKind.OVERRIDDEN,
            }[checked.decision.kind]
            return self._append(
                connection,
                ApprovalAuditEvent(
                    schema_version=1,
                    state_version=1,
                    sequence=len(history.events) + 1,
                    binding=binding,
                    kind=kind,
                    requested=None,
                    decided=checked,
                ),
            )

    def consume(
        self,
        binding: ActionBinding,
        *,
        evaluator: ApprovalPolicyEvaluator,
        actor: HumanIdentity | None,
        safety: ApprovalSafetyState,
    ) -> ApprovalHistory:
        """Atomically append consumption once, rechecking current installed authority and safety.

        Args:
            binding: Current trusted exact approved action.
            evaluator: Current application policy/request/allowlists, not historical policy data.
            actor: Freshly installed handle for the recorded approving/overriding principal.
            safety: Current trusted safety facts; store history determines consumption/denial.

        Returns:
            Inert consumed history. This method executes nothing and issues no execution token.

        Raises:
            ApprovalPersistenceError: For unavailable/invalid state or SQL failure.
            AuthorityViolationError: If current authority or safety rejects consumption.
            ContractValidationError: If current Slice 1 inputs are malformed.
        """
        binding = _validate(binding, ActionBinding)
        self._evaluator(evaluator)
        with self._connection(write=True) as connection:
            history = self._current(self._read(connection, binding), binding)
            if history.status not in (ApprovalEventKind.APPROVED, ApprovalEventKind.OVERRIDDEN):
                raise ApprovalPersistenceError(
                    "Only an unconsumed accepted approval can be consumed."
                )
            prior = history.events[-1].decided
            checked = evaluator.check_decision(
                prior.decision, actor=actor, observation=prior.assessment.observation, safety=safety
            )
            if (
                checked.approver_id != prior.approver_id
                or checked.assessment.request != prior.assessment.request
            ):
                raise ApprovalPersistenceError(
                    "Current principal/action differs from recorded approval."
                )
            return self._append(
                connection,
                ApprovalAuditEvent(
                    schema_version=1,
                    state_version=1,
                    sequence=len(history.events) + 1,
                    binding=binding,
                    kind=ApprovalEventKind.CONSUMED,
                    requested=None,
                    decided=checked,
                ),
            )

    def load(self, binding: ActionBinding) -> ApprovalHistory:
        """Load bounded inert history for the caller's exact current binding.

        Args:
            binding: Trusted expected workflow/thread/action/version.

        Returns:
            Validated historical data; approver names do not reconstruct human handles.

        Raises:
            ApprovalPersistenceError: For missing, stale, mismatched, corrupt, or unsupported state.
        """
        binding = _validate(binding, ActionBinding)
        with self._connection() as connection:
            return self._current(self._read(connection, binding), binding)

    def audit(
        self, binding: ActionBinding, *, after_sequence: int = 0, limit: int = MAX_EVENTS
    ) -> tuple[ApprovalAuditEvent, ...]:
        """Read a bounded ordered page after validating the entire bounded action history.

        Args:
            binding: Trusted current exact binding, not a wildcard workflow query.
            after_sequence: Exclusive cursor between zero and MAX_EVENTS.
            limit: Number of returned events, from one to MAX_EVENTS.

        Returns:
            Immutable audit page in deterministic ascending sequence order.

        Raises:
            ApprovalPersistenceError: For invalid cursor/limit or unusable history.
        """
        if (
            type(after_sequence) is not int
            or not 0 <= after_sequence <= MAX_EVENTS
            or type(limit) is not int
            or not 1 <= limit <= MAX_EVENTS
        ):
            raise ApprovalPersistenceError("Audit cursor/limit must be bounded integers.")
        history = self.load(binding)
        return tuple(event for event in history.events if event.sequence > after_sequence)[:limit]
