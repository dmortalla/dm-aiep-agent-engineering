"""Fixture exposure, concurrency and SQLite recovery; no real pricing or spending."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from harness_engineering.cost_governance import (
    FixtureLedger,
    FixtureTariff,
    LedgerError,
    LedgerPolicy,
    ProviderAlias,
    TokenPolicy,
    require_real_monetary_admission,
)
from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.errors import AuthorityViolationError, BudgetExceededError
from harness_engineering.governance_facts import GovernanceKind
from harness_engineering.observability import TelemetrySession
from harness_engineering.usage import UsageFacts, UsageState


def policy(cap: int = 100, **changes: object) -> LedgerPolicy:
    """Use one micro-USD per allocated token, not real vendor prices."""
    identity = WorkflowIdentity()
    values = dict(
        workflow_id=identity.workflow_id,
        thread_id=identity.thread_id,
        cap_units=cap,
        tariff=FixtureTariff(
            provider=ProviderAlias.FAKE,
            input_units_per_million=1_000_000,
            output_units_per_million=1_000_000,
        ),
        tokens=TokenPolicy(
            step_count=1, input_per_call=8, output_per_call=2, input_per_step=24, output_per_step=6
        ),
    )
    values.update(changes)
    return LedgerPolicy(**values)


def ledger(tmp_path: Path, cap: int = 100, **changes: object) -> FixtureLedger:
    return FixtureLedger(tmp_path / "cost.sqlite", policy(cap, **changes), create=True)


def reported(input_tokens: int = 1, output_tokens: int = 1) -> UsageFacts:
    return UsageFacts(
        state=UsageState.REPORTED, input_tokens=input_tokens, output_tokens=output_tokens
    )


@pytest.mark.parametrize(
    "live,tariff",
    [
        (False, None),
        (True, None),
        (False, {"approved": True}),
        (True, {"approved": True, "provider": "openai", "price": 0}),
        (True, "stale"),
        (True, "unknown-model"),
    ],
)
def test_live_policy_never_accepts_missing_or_self_asserted_authority(
    live: bool,
    tariff: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "offline-dummy-not-a-real-key")
    with pytest.raises(AuthorityViolationError):
        require_real_monetary_admission(approved_tariff=tariff, live_enabled=live)


def test_fixture_tariff_can_never_be_a_live_tariff() -> None:
    with pytest.raises(AuthorityViolationError):
        require_real_monetary_admission(approved_tariff=policy().tariff, live_enabled=True)


@pytest.mark.parametrize("value", [True, -1, 0, 1.0, float("nan"), float("inf"), 10**20])
def test_strict_tariff_rate_validation(value: object) -> None:
    with pytest.raises(ValidationError):
        FixtureTariff(
            provider=ProviderAlias.FAKE, input_units_per_million=value, output_units_per_million=1
        )


def test_integer_rounding_never_uses_binary_float() -> None:
    tariff = FixtureTariff(
        provider=ProviderAlias.FAKE, input_units_per_million=1, output_units_per_million=1
    )
    assert tariff.estimate(1, 0) == 1
    assert tariff.estimate(0, 0) == 0
    assert tariff.estimate(12000, 2000) == 1
    assert policy().tariff.estimate(8, 2) == 10


def test_cap_equality_and_one_unit_below_required_reservation(tmp_path: Path) -> None:
    cost = ledger(tmp_path, 10)
    first = cost.reserve(1)
    state = cost.snapshot()
    assert state.outstanding_units == 10 and state.committed_units == 0
    assert state.warnings == (80, 100)
    with pytest.raises(BudgetExceededError):
        cost.reserve(1)
    cost.settle(first, reported(0, 0))
    state = cost.snapshot()
    assert state.committed_units == 10 and state.outstanding_units == 0
    assert state.attempts[0].estimated_units == 0
    assert state.attempts[0].verified_billing_units is None
    with pytest.raises(BudgetExceededError):
        cost.reserve(1)  # Zero reported usage refunds no authority.


def test_cap_one_smallest_unit_short_fails(tmp_path: Path) -> None:
    cost = ledger(tmp_path, 9)
    with pytest.raises(BudgetExceededError):
        cost.reserve(1)
    assert cost.snapshot().attempts == ()


def test_step_allocations_are_independent_and_recovery_order_is_fixed(tmp_path: Path) -> None:
    p = policy(
        100,
        tokens=TokenPolicy(
            step_count=2,
            input_per_call=8,
            output_per_call=2,
            input_per_step=8,
            output_per_step=2,
        ),
        action_ids=("first", "second"),
    )
    cost = FixtureLedger(tmp_path / "cost.sqlite", p, create=True)
    cost.reserve(1)
    with pytest.raises(BudgetExceededError):
        cost.reserve(1)
    cost.reserve(2)
    assert [item.reservation.step_index for item in cost.snapshot().attempts] == [1, 2]
    with pytest.raises(LedgerError):
        FixtureLedger(
            tmp_path / "cost.sqlite",
            p.model_copy(
                update={
                    "action_ids": ("second", "first"),
                }
            ),
        )


def test_copied_fixture_policy_is_revalidated_before_authority(tmp_path: Path) -> None:
    p = policy()
    forged = p.model_copy(
        update={
            "tariff": p.tariff.model_copy(
                update={
                    "input_units_per_million": -1,
                }
            )
        }
    )
    with pytest.raises(ValidationError):
        FixtureLedger(tmp_path / "cost.sqlite", forged, create=True)
    assert not (tmp_path / "cost.sqlite").exists()


@pytest.mark.parametrize(
    "state",
    [
        UsageState.TIMEOUT,
        UsageState.CANCELLED,
        UsageState.MISSING,
        UsageState.MALFORMED,
        UsageState.UNAVAILABLE,
        UsageState.LATE,
    ],
)
def test_uncertainty_retains_full_reservation(tmp_path: Path, state: UsageState) -> None:
    cost = ledger(tmp_path, 10)
    reservation = cost.reserve(1)
    result = cost.settle(reservation, UsageFacts(state=state))
    assert result.outstanding_units == 10
    assert result.committed_units == 0
    assert result.attempts[0].usage.state is state
    assert result.attempts[0].estimated_units is None
    with pytest.raises(LedgerError):
        cost.settle(reservation, reported(0, 0))
    with pytest.raises(BudgetExceededError):
        cost.reserve(1)


def test_duplicate_or_forged_settlement_fails_without_releasing_state(tmp_path: Path) -> None:
    cost = ledger(tmp_path)
    reservation = cost.reserve(1)
    forged = reservation.model_copy(update={"attempt_id": uuid4()})
    with pytest.raises(LedgerError):
        cost.settle(forged, reported())
    cost.settle(reservation, reported())
    with pytest.raises(LedgerError):
        cost.settle(reservation, reported())
    assert cost.snapshot().committed_units == 10


def test_report_cannot_exceed_reserved_token_allocation(tmp_path: Path) -> None:
    cost = ledger(tmp_path)
    reservation = cost.reserve(1)
    with pytest.raises(LedgerError):
        cost.settle(reservation, reported(9, 1))
    assert cost.snapshot().outstanding_units == 10
    assert cost.snapshot().attempts[0].usage is None


def test_per_step_allocations_are_cumulative_and_not_refunded(tmp_path: Path) -> None:
    cost = ledger(
        tmp_path,
        tokens=TokenPolicy(
            step_count=1,
            input_per_call=8,
            output_per_call=2,
            input_per_step=8,
            output_per_step=2,
        ),
    )
    cost.settle(cost.reserve(1), reported(0, 0))
    with pytest.raises(BudgetExceededError, match="token"):
        cost.reserve(1)


def test_concurrent_near_cap_admission_across_reopened_handles(tmp_path: Path) -> None:
    cost = ledger(tmp_path, 10)
    other = FixtureLedger(tmp_path / "cost.sqlite", cost.policy)

    def reserve(handle: FixtureLedger) -> bool:
        try:
            handle.reserve(1)
            return True
        except BudgetExceededError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, (cost, other))) == [False, True]
    assert cost.snapshot().outstanding_units == 10


def test_duplicate_settlement_race_exactly_one_commit(tmp_path: Path) -> None:
    cost = ledger(tmp_path)
    reservation = cost.reserve(1)
    other = FixtureLedger(tmp_path / "cost.sqlite", cost.policy)

    def settle(handle: FixtureLedger) -> bool:
        try:
            handle.settle(reservation, reported())
            return True
        except LedgerError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(settle, (cost, other))) == [False, True]
    assert cost.snapshot().committed_units == 10


def test_concurrent_reservation_and_settlement_include_all_exposure(tmp_path: Path) -> None:
    cost = ledger(tmp_path, 20)
    reservation = cost.reserve(1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        operations = [
            pool.submit(cost.settle, reservation, reported()),
            pool.submit(cost.reserve, 1),
        ]
        for operation in operations:
            operation.result()
    state = cost.snapshot()
    assert state.committed_units + state.outstanding_units == 20
    with pytest.raises(BudgetExceededError):
        cost.reserve(1)


def test_crash_after_reservation_reopens_without_reset(tmp_path: Path) -> None:
    cost = ledger(tmp_path, 20)
    first = cost.reserve(1)
    cost.settle(first, reported())
    second = cost.reserve(1)
    recovered = FixtureLedger(tmp_path / "cost.sqlite", cost.policy)
    state = recovered.snapshot()
    assert (state.committed_units, state.outstanding_units) == (10, 10)
    assert state.attempts[-1].reservation == second
    with pytest.raises(BudgetExceededError):
        recovered.reserve(1)
    with pytest.raises(LedgerError):
        recovered.settle(first, reported())
    with pytest.raises(LedgerError):
        FixtureLedger(tmp_path / "cost.sqlite", cost.policy, create=True)


@pytest.mark.parametrize(
    "corruption",
    ["delete", "truncate", "version", "policy", "payload", "schema", "sequence", "duplicate-json"],
)
def test_corrupt_or_missing_recovery_denies_admission(tmp_path: Path, corruption: str) -> None:
    cost = ledger(tmp_path)
    cost.reserve(1)
    path = tmp_path / "cost.sqlite"
    if corruption == "delete":
        path.unlink()
    else:
        with sqlite3.connect(path) as connection:
            if corruption == "truncate":
                connection.execute("DELETE FROM cost_journal")
            elif corruption == "version":
                connection.execute("PRAGMA user_version=99")
            elif corruption == "policy":
                connection.execute("UPDATE cost_header SET payload='{}'")
            elif corruption == "payload":
                connection.execute("UPDATE cost_journal SET payload='not-json'")
            elif corruption == "schema":
                connection.execute("DROP TABLE cost_journal")
            elif corruption == "sequence":
                connection.execute("UPDATE cost_journal SET seq=2")
            else:
                connection.execute(
                    "UPDATE cost_journal SET payload='{" + '"version":1,"version":1' + "}'"
                )
    with pytest.raises(LedgerError):
        FixtureLedger(path, cost.policy)
    with pytest.raises(LedgerError):
        cost.reserve(1)


def test_fresh_policy_cannot_expand_cap_on_resume(tmp_path: Path) -> None:
    cost = ledger(tmp_path, 10)
    cost.reserve(1)
    with pytest.raises(LedgerError):
        FixtureLedger(tmp_path / "cost.sqlite", cost.policy.model_copy(update={"cap_units": 100}))


def test_warning_crossings_are_durable_and_deduplicated_under_race(tmp_path: Path) -> None:
    p = policy(20)
    telemetry = TelemetrySession(
        WorkflowIdentity(workflow_id=p.workflow_id, thread_id=p.thread_id),
        evidence=EvidenceClass.DETERMINISTIC,
    )
    cost = FixtureLedger(tmp_path / "cost.sqlite", p, create=True, telemetry=telemetry)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(lambda _: cost.reserve(1), range(2)))
    for reservation in reservations:
        cost.settle(reservation, reported())
    warnings = [
        event.governance.kind
        for event in telemetry.sink.snapshot()
        if event.governance.kind in (GovernanceKind.WARNING_80, GovernanceKind.WARNING_100)
    ]
    assert warnings.count(GovernanceKind.WARNING_80) == 1
    assert warnings.count(GovernanceKind.WARNING_100) == 1
    assert FixtureLedger(tmp_path / "cost.sqlite", p).snapshot().warnings == (80, 100)


def test_warning_80_percent_exact_boundary(tmp_path: Path) -> None:
    cost = ledger(tmp_path, 25)
    cost.reserve(1)
    assert cost.snapshot().warnings == ()
    cost.reserve(1)
    assert cost.snapshot().warnings == (80,)


def test_telemetry_failure_cannot_release_or_hide_source_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = policy(10)
    telemetry = TelemetrySession(
        WorkflowIdentity(workflow_id=p.workflow_id, thread_id=p.thread_id),
        evidence=EvidenceClass.DETERMINISTIC,
    )
    cost = FixtureLedger(tmp_path / "cost.sqlite", p, create=True, telemetry=telemetry)

    def fail(*args: object) -> None:
        raise RuntimeError("SENSITIVE-FAILURE")

    monkeypatch.setattr(telemetry, "record_governance", fail)
    reservation = cost.reserve(1)
    cost.settle(reservation, reported())
    assert cost.projection_failures == 2
    assert cost.snapshot().warnings == (80, 100)
    assert cost.snapshot().committed_units == 10
    with pytest.raises(BudgetExceededError):
        cost.reserve(1)
