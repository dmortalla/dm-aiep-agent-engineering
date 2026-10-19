"""Fixture-only durable exposure authority; no tariff grants live dispatch.

Integer micro-USD bounds are conservative application exposure, never verified
billing. Dedicated version-1 SQLite journal leaves checkpoint schemas untouched.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, model_validator

from harness_engineering.anomaly_signals import AnomalyDetector, validate_fixture_projection
from harness_engineering.domain import Identifier, WorkflowIdentity
from harness_engineering.errors import AuthorityViolationError, BudgetExceededError, HarnessError
from harness_engineering.governance_facts import GovernanceFacts, GovernanceKind
from harness_engineering.latency import LatencyData
from harness_engineering.observability import TelemetrySession
from harness_engineering.usage import UsageFacts, UsageState

MAX_UNITS = 10**12
APPLICATION_ID = 0x48363543
HEADER_SQL = (
    "CREATE TABLE cost_header (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, "
    "last_sequence INTEGER NOT NULL CHECK(last_sequence BETWEEN 0 AND 16))"
)
JOURNAL_SQL = "CREATE TABLE cost_journal (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)"


class LedgerError(HarnessError):
    """Ledger unavailable/inconsistent: deny admission, never rebuild empty authority."""


class ProviderAlias(StrEnum):
    """Finite application aliases, never arbitrary provider response strings."""

    FAKE = "fake"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


Units = Annotated[int, Field(ge=0, le=MAX_UNITS)]


class FixtureTariff(LatencyData):
    """Explicit fixture policy; cannot represent an approved live provider tariff."""

    policy_class: Literal["fixture_only"] = "fixture_only"
    provider: ProviderAlias
    model: Literal["fixture-model"] = "fixture-model"
    input_units_per_million: Annotated[int, Field(ge=1, le=10**9)]
    output_units_per_million: Annotated[int, Field(ge=1, le=10**9)]

    def estimate(self, input_tokens: int, output_tokens: int) -> int:
        """Compute ceiling of fixture micro-USD using integer arithmetic only."""
        tariff = FixtureTariff.model_validate(self)
        facts = UsageFacts(
            state=UsageState.REPORTED,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        numerator = (
            facts.input_tokens * tariff.input_units_per_million
            + facts.output_tokens * tariff.output_units_per_million
        )
        return (numerator + 999_999) // 1_000_000


class TokenPolicy(LatencyData):
    """Trusted per-step cumulative allocation caps; reports never refund tokens."""

    step_count: Annotated[int, Field(ge=1, le=12)]
    input_per_call: Annotated[int, Field(ge=1, le=12_000)] = 12_000
    output_per_call: Annotated[int, Field(ge=1, le=2_000)] = 2_000
    input_per_step: Annotated[int, Field(ge=1, le=36_000)] = 36_000
    output_per_step: Annotated[int, Field(ge=1, le=6_000)] = 6_000
    attempts_per_step: Annotated[int, Field(ge=1, le=3)] = 3
    workflow_attempts: Annotated[int, Field(ge=1, le=8)] = 8


class LedgerPolicy(LatencyData):
    """Trusted fixture bootstrap, never reconstructed from provider or telemetry."""

    workflow_id: UUID
    thread_id: UUID
    cap_units: Annotated[int, Field(ge=1, le=MAX_UNITS)]
    tariff: FixtureTariff
    tokens: TokenPolicy
    action_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=12)] = ("model",)

    @model_validator(mode="after")
    def bind_order(self) -> "LedgerPolicy":
        """Persist exact trusted step order so resume cannot reinterpret ordinals."""
        if len(self.action_ids) != self.tokens.step_count or len(set(self.action_ids)) != len(
            self.action_ids
        ):
            raise ValueError("Bind unique action IDs matching the declared step count.")
        return self


class Reservation(LatencyData):
    """Application-generated attempt reference; serialized possession grants nothing."""

    attempt_id: UUID
    step_index: Annotated[int, Field(ge=1, le=12)]
    reserved_units: Units


class LedgerEntry(LatencyData):
    """Versioned journal record. Settlement commits the full reserved bound."""

    version: Literal[1] = 1
    sequence: Annotated[int, Field(ge=1, le=16)]
    operation: Literal["reserve", "settle"]
    reservation: Reservation
    usage: UsageFacts | None = None


class AttemptAccount(LatencyData):
    """Usage claims, allocation authority and monetary estimates stay distinct."""

    reservation: Reservation
    settled: bool
    usage: UsageFacts | None
    allocated_input_tokens: Annotated[int, Field(ge=1, le=12_000)]
    allocated_output_tokens: Annotated[int, Field(ge=1, le=2_000)]
    estimated_units: Units | None
    # No verified-billing field is populated by this implementation.
    verified_billing_units: None = None


class LedgerSnapshot(LatencyData):
    """Read-only attribution; not admission or settlement authority."""

    workflow_id: UUID
    thread_id: UUID
    cap_units: Units
    committed_units: Units
    outstanding_units: Units
    warnings: tuple[Literal[80, 100], ...]
    attempts: Annotated[tuple[AttemptAccount, ...], Field(max_length=8)]


def require_real_monetary_admission(
    *,
    approved_tariff: object = None,
    live_enabled: bool = False,
) -> None:
    """Deny real dispatch: this slice has no supported approved live tariff type.

    Missing enablement or pricing is independently insufficient. A fixture or
    self-asserted approval object cannot become a live tariff. Future support
    requires human-approved trusted policy, not deserializing an approved flag.
    """
    if live_enabled is not True:
        raise AuthorityViolationError("Live monetary execution is disabled.")
    if approved_tariff is None:
        raise AuthorityViolationError("An approved live tariff policy is required.")
    raise AuthorityViolationError("No approved live tariff implementation is supported.")


def _encode(value: LatencyData) -> str:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _decode[T: LatencyData](payload: object, model: type[T]) -> T:
    if type(payload) is not str or len(payload.encode()) > 16_384:
        raise LedgerError("Cost journal payload exceeds the supported profile.")
    try:
        value = model.model_validate_json(payload)
        if _encode(value) != payload:
            raise LedgerError("Cost journal is not canonical or contains unsupported fields.")
        return value
    except (ValidationError, ValueError):
        raise LedgerError("Cost journal validation failed; admission denied.") from None


class FixtureLedger:
    """One workflow's durable fixture journal; SQLite serializes authoritative writes.

    Explicit create cannot overwrite; reopen cannot create. Recovery validates
    the full bounded journal against fresh trusted policy on every operation.
    Existing checkpoint records are never monetary authority.
    """

    def __init__(
        self,
        path: Path,
        policy: LedgerPolicy,
        *,
        create: bool = False,
        telemetry: TelemetrySession | None = None,
        anomalies: AnomalyDetector | None = None,
    ) -> None:
        """Create exclusively or reopen an existing dedicated version-1 database.

        Args:
            path: Application-owned dedicated ledger file.
            policy: Fresh trusted expected identity, cap, fixture tariff and token limits.
            create: Explicit new workflow only; never use to recover missing state.
            telemetry: Optional local safe projection, never accounting authority.
            anomalies: Optional advisory rule observer for budget spikes.
        """
        if not isinstance(path, Path) or str(path) == ":memory:":
            raise LedgerError("Use a dedicated application-owned ledger Path.")
        self._path = path.resolve()
        self._policy = LedgerPolicy.model_validate(policy)
        accounting_identity = WorkflowIdentity(
            workflow_id=self._policy.workflow_id, thread_id=self._policy.thread_id,
        )
        try:
            if telemetry is not None:
                if type(telemetry) is not TelemetrySession:
                    raise ValueError("Bind an application-owned local telemetry session.")
                validate_fixture_projection(accounting_identity, telemetry.evidence, telemetry)
            if anomalies is not None:
                if type(anomalies) is not AnomalyDetector:
                    raise ValueError("Bind an application-owned advisory detector.")
                anomalies.bind_fixture(accounting_identity)
        except ValueError:
            raise LedgerError(
                "Fixture projection identity/evidence conflicts with bootstrap."
            ) from None
        self._telemetry = telemetry
        self._anomalies = anomalies
        self._projection_failures = 0
        self._projection_lock = Lock()
        if create:
            try:
                with self._path.open("xb"):
                    pass
            except OSError:
                raise LedgerError("New cost ledger cannot overwrite existing state.") from None
            with self._connection(initialize=True) as connection:
                connection.execute(HEADER_SQL)
                connection.execute(JOURNAL_SQL)
                connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                connection.execute("PRAGMA user_version=1")
                connection.execute(
                    "INSERT INTO cost_header VALUES (1, ?, 0)", (_encode(self._policy),)
                )
        self.snapshot()  # Failed recovery never acquires usable execution authority.

    @property
    def policy(self) -> LedgerPolicy:
        """Return immutable bootstrap policy for exact runtime reconciliation."""
        return self._policy

    @property
    def projection_failures(self) -> int:
        """Count advisory-only failures; authoritative transactions remain committed."""
        with self._projection_lock:
            return self._projection_failures

    def _project(
        self,
        snapshot: LedgerSnapshot,
        previous_warnings: tuple[int, ...],
        *,
        added_units: int = 0,
    ) -> None:
        if self._anomalies is not None and added_units * 4 >= snapshot.cap_units:
            try:
                self._anomalies.observe(GovernanceKind.BUDGET_SPIKE)
            except Exception:
                with self._projection_lock:
                    self._projection_failures += 1
        try:
            if self._telemetry is not None:
                exposure = snapshot.committed_units + snapshot.outstanding_units
                self._telemetry.record_governance(
                    GovernanceFacts(
                        kind=GovernanceKind.EXPOSURE,
                        exposure_units=exposure,
                        cap_units=snapshot.cap_units,
                    )
                )
                for level in snapshot.warnings:
                    if level not in previous_warnings:
                        self._telemetry.record_governance(
                            GovernanceFacts(
                                kind=GovernanceKind.WARNING_80
                                if level == 80
                                else GovernanceKind.WARNING_100,
                                exposure_units=exposure,
                                cap_units=snapshot.cap_units,
                            )
                        )
        except Exception:
            # Advisory-only boundary after commit: count loss, never release exposure.
            with self._projection_lock:
                self._projection_failures += 1

    @contextmanager
    def _connection(self, *, initialize: bool = False) -> Iterator[sqlite3.Connection]:
        connection = None
        try:
            connection = sqlite3.connect(self._path.as_uri() + "?mode=rw", uri=True, timeout=1.0)
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                if not initialize:
                    self._metadata(connection)
                yield connection
        except sqlite3.Error:
            raise LedgerError(
                "Cost storage unavailable; admission denied, exposure retained."
            ) from None
        finally:
            if connection is not None:
                connection.close()

    def _metadata(self, connection: sqlite3.Connection) -> None:
        tables = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_master",
            ).fetchall()
        )
        if (
            connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or connection.execute("PRAGMA user_version").fetchone()[0] != 1
            or tables != {"cost_header": HEADER_SQL, "cost_journal": JOURNAL_SQL}
        ):
            raise LedgerError("Cost ledger schema is foreign, missing or unsupported.")
        rows = connection.execute(
            "SELECT id,substr(payload,1,16385) FROM cost_header LIMIT 2"
        ).fetchall()
        if len(rows) != 1 or rows[0][0] != 1 or _decode(rows[0][1], LedgerPolicy) != self._policy:
            raise LedgerError("Cost identity/policy differs from trusted bootstrap.")

    def _read(self, connection: sqlite3.Connection) -> tuple[LedgerSnapshot, int]:
        rows = connection.execute(
            "SELECT seq,substr(payload,1,16385) FROM cost_journal ORDER BY seq LIMIT 17"
        ).fetchall()
        if len(rows) > 16:
            raise LedgerError("Cost journal exceeds bounded attempt history.")
        if connection.execute("SELECT last_sequence FROM cost_header WHERE id=1").fetchone()[
            0
        ] != len(rows):
            raise LedgerError("Cost journal is truncated or its sequence watermark is corrupt.")
        p = self._policy
        reserve = p.tariff.estimate(p.tokens.input_per_call, p.tokens.output_per_call)
        accounts: dict[UUID, AttemptAccount] = {}
        for sequence, (stored_sequence, payload) in enumerate(rows, 1):
            event = _decode(payload, LedgerEntry)
            r = event.reservation
            if (
                stored_sequence != sequence
                or event.sequence != sequence
                or r.step_index > p.tokens.step_count
                or r.reserved_units != reserve
            ):
                raise LedgerError("Cost journal sequence/reservation conflicts with policy.")
            if event.operation == "reserve":
                count = sum(a.reservation.step_index == r.step_index for a in accounts.values()) + 1
                if (
                    r.attempt_id in accounts
                    or event.usage is not None
                    or len(accounts) >= p.tokens.workflow_attempts
                    or count > p.tokens.attempts_per_step
                    or count * p.tokens.input_per_call > p.tokens.input_per_step
                    or count * p.tokens.output_per_call > p.tokens.output_per_step
                ):
                    raise LedgerError("Cost journal violates attempt/token allocation limits.")
                accounts[r.attempt_id] = AttemptAccount(
                    reservation=r,
                    settled=False,
                    usage=None,
                    estimated_units=None,
                    allocated_input_tokens=p.tokens.input_per_call,
                    allocated_output_tokens=p.tokens.output_per_call,
                )
            else:
                old = accounts.get(r.attempt_id)
                if (
                    old is None
                    or old.usage is not None
                    or old.reservation != r
                    or event.usage is None
                ):
                    raise LedgerError("Cost journal contains duplicate/unbound settlement.")
                usage = event.usage
                estimate = None
                if usage.state is UsageState.REPORTED:
                    if (
                        usage.input_tokens > p.tokens.input_per_call
                        or usage.output_tokens > p.tokens.output_per_call
                    ):
                        raise LedgerError("Reported usage exceeds the reserved token allocation.")
                    estimate = p.tariff.estimate(usage.input_tokens, usage.output_tokens)
                accounts[r.attempt_id] = old.model_copy(
                    update={
                        "settled": usage.state in (UsageState.REPORTED, UsageState.LOCAL),
                        "usage": usage,
                        "estimated_units": estimate,
                    }
                )
            if len(accounts) * reserve > p.cap_units:
                raise LedgerError("Cost journal exceeds the trusted exposure cap.")
        committed = sum(a.reservation.reserved_units for a in accounts.values() if a.settled)
        outstanding = sum(a.reservation.reserved_units for a in accounts.values() if not a.settled)
        exposure = committed + outstanding
        warnings = tuple(level for level in (80, 100) if exposure * 100 >= p.cap_units * level)
        return LedgerSnapshot(
            workflow_id=p.workflow_id,
            thread_id=p.thread_id,
            cap_units=p.cap_units,
            committed_units=committed,
            outstanding_units=outstanding,
            warnings=warnings,
            attempts=tuple(accounts.values()),
        ), len(rows)

    def snapshot(self) -> LedgerSnapshot:
        """Reconcile durable history; no missing state can become empty authority."""
        with self._connection() as connection:
            return self._read(connection)[0]

    def reserve(self, step_index: int) -> Reservation:
        """Atomically reserve full per-call tokens and conservative fixture exposure."""
        p = self._policy
        if type(step_index) is not int or not 1 <= step_index <= p.tokens.step_count:
            raise LedgerError("Bind a step ordinal from trusted workflow policy.")
        units = p.tariff.estimate(p.tokens.input_per_call, p.tokens.output_per_call)
        with self._connection() as connection:
            snapshot, sequence = self._read(connection)
            count = sum(a.reservation.step_index == step_index for a in snapshot.attempts) + 1
            if (
                len(snapshot.attempts) >= p.tokens.workflow_attempts
                or count > p.tokens.attempts_per_step
                or count * p.tokens.input_per_call > p.tokens.input_per_step
                or count * p.tokens.output_per_call > p.tokens.output_per_step
            ):
                raise BudgetExceededError(
                    "Cumulative step token or provider-attempt budget exhausted."
                )
            if snapshot.committed_units + snapshot.outstanding_units + units > p.cap_units:
                raise BudgetExceededError("Application hard fixture exposure budget exhausted.")
            reservation = Reservation(
                attempt_id=uuid4(), step_index=step_index, reserved_units=units
            )
            event = LedgerEntry(sequence=sequence + 1, operation="reserve", reservation=reservation)
            connection.execute(
                "INSERT INTO cost_journal VALUES (?,?)", (event.sequence, _encode(event))
            )
            connection.execute(
                "UPDATE cost_header SET last_sequence=? WHERE id=1", (event.sequence,)
            )
            updated = self._read(connection)[0]
        self._project(updated, snapshot.warnings, added_units=units)
        return reservation

    def settle(self, reservation: Reservation, usage: UsageFacts) -> LedgerSnapshot:
        """Commit once without refund; valid usage only adds a separate fixture estimate.

        No provider report proves a safe authority refund. Unknown outcomes keep
        the full bound outstanding, including crashes. Both exposure categories count
        identically toward admission. Duplicate settlement is rejected.
        """
        checked = Reservation.model_validate(reservation)
        facts = UsageFacts.model_validate(usage)
        with self._connection() as connection:
            snapshot, sequence = self._read(connection)
            old = next((a for a in snapshot.attempts if a.reservation == checked), None)
            if old is None or old.usage is not None:
                raise LedgerError("Settlement is duplicate or not bound to this ledger.")
            event = LedgerEntry(
                sequence=sequence + 1,
                operation="settle",
                reservation=checked,
                usage=facts,
            )
            connection.execute(
                "INSERT INTO cost_journal VALUES (?,?)", (event.sequence, _encode(event))
            )
            connection.execute(
                "UPDATE cost_header SET last_sequence=? WHERE id=1", (event.sequence,)
            )
            updated = self._read(connection)[0]
        self._project(updated, snapshot.warnings)
        return updated
