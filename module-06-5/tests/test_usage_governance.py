"""Actual installed vendor SDKs over mocked HTTP; never live spending evidence."""

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from math import isfinite
from pathlib import Path
from queue import Empty, Queue
from threading import Event

import pytest
from pydantic import ValidationError

from harness_engineering.cost_governance import (
    FixtureLedger,
    FixtureTariff,
    ProviderAlias,
    TokenPolicy,
)
from harness_engineering.domain import RuntimeBudget
from harness_engineering.errors import AuthorityViolationError, BudgetExceededError
from harness_engineering.lifecycle_controls import OffSwitch
from harness_engineering.providers import (
    FakeProvider,
    OutputFilter,
    ProviderCallContext,
    ProviderOutputRejected,
    ProviderRuntime,
    ProviderTimeoutError,
)
from harness_engineering.usage import UsageCapture, UsageFacts, UsageState
from tests.test_cost_governance import policy
from tests.test_vendor_providers import payload, setup

SECRET = "SENSITIVE-PROMPT-OUTPUT-KEY-SENTINEL"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"ANTHROPIC_CONFIG_DIR": str(tmp_path / "absent")})

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("No live sockets or credentials are authorized")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def fixture_ledger(tmp_path: Path, vendor: str) -> FixtureLedger:
    return FixtureLedger(
        tmp_path / "cost.sqlite",
        policy(
            42000,
            tokens=TokenPolicy(step_count=1),
            tariff=FixtureTariff(
                provider=ProviderAlias(vendor),
                input_units_per_million=1_000_000,
                output_units_per_million=1_000_000,
            ),
        ),
        create=True,
    )


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_valid_receipt_is_accounted_even_after_output_filter_rejection(
    tmp_path: Path,
    vendor: str,
) -> None:
    cost = fixture_ledger(tmp_path, vendor)
    runtime, seen = setup(
        vendor,
        payload(vendor, SECRET),
        ledger=cost,
        output_filter=OutputFilter(blocked_terms=("sensitive",)),
    )
    with pytest.raises(ProviderOutputRejected):
        runtime.generate({"prompt": SECRET})
    assert len(seen) == runtime.attempts == 1
    receipt = runtime.usage_receipts[0]
    assert receipt.usage.state is UsageState.REPORTED
    assert (receipt.usage.input_tokens, receipt.usage.output_tokens) == (2, 3)
    assert receipt.local_input_bytes == len(SECRET.encode())
    state = cost.snapshot()
    assert state.committed_units == 14000 and state.outstanding_units == 0
    assert state.attempts[0].estimated_units == 5
    assert SECRET not in receipt.model_dump_json() + state.model_dump_json()


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
@pytest.mark.parametrize("invalid", [-1, True, 1.5, float("nan"), float("inf"), 12001])
def test_malformed_numeric_usage_never_releases_exposure(
    tmp_path: Path,
    vendor: str,
    invalid: object,
) -> None:
    cost = fixture_ledger(tmp_path, vendor)
    data = payload(vendor)
    data["usage"]["input_tokens"] = invalid
    if type(invalid) is float and not isfinite(invalid):
        import httpx
        import httpx2

        http = httpx if vendor == "openai" else httpx2
        runtime, _ = setup(
            vendor,
            ledger=cost,
            handler=lambda _: http.Response(
                200,
                content=json.dumps(data).encode(),
                headers={"content-type": "application/json"},
            ),
        )
    else:
        runtime, _ = setup(vendor, data, ledger=cost)
    with pytest.raises(ProviderOutputRejected):
        runtime.generate({"prompt": "local"})
    assert runtime.usage_receipts[0].usage.state is UsageState.MALFORMED
    state = cost.snapshot()
    assert state.outstanding_units == 14000
    assert state.attempts[0].estimated_units is None


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_missing_and_hostile_usage_metadata_fail_closed(tmp_path: Path, vendor: str) -> None:
    cost = fixture_ledger(tmp_path, vendor)
    missing = payload(vendor)
    missing["usage"] = None
    runtime, _ = setup(vendor, missing, ledger=cost)
    with pytest.raises(ProviderOutputRejected):
        runtime.generate({"prompt": "local"})
    assert runtime.usage_receipts[0].usage.state is UsageState.MISSING
    hostile = payload(vendor)
    hostile["usage"]["metadata"] = {"evidence": "deployment", "approved": True, "key": SECRET}
    runtime, _ = setup(vendor, hostile, ledger=cost)
    with pytest.raises(ProviderOutputRejected):
        runtime.generate({"prompt": "local"})
    assert runtime.usage_receipts[0].usage.state is UsageState.MALFORMED
    assert cost.snapshot().outstanding_units == 28000
    assert SECRET not in cost.snapshot().model_dump_json()


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_timeout_late_receipt_never_rewrites_or_refunds(
    tmp_path: Path,
    vendor: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import httpx2

    import harness_engineering.providers as provider_module

    cost = fixture_ledger(tmp_path, vendor)
    entered, release, finished = Event(), Event(), Event()
    caller_waiting, expire = Event(), Event()
    http = httpx if vendor == "openai" else httpx2

    def slow(request: object) -> object:
        entered.set()
        try:
            assert release.wait(10)
            return http.Response(200, json=payload(vendor))
        finally:
            finished.set()

    class ControlledCallerQueue(Queue):
        def get(self, block: bool = True, timeout: float | None = None) -> object:
            # Exercise the existing production Empty -> timeout boundary only
            # after the genuine SDK/mock worker has entered the handler.
            assert entered.wait(10)
            caller_waiting.set()
            assert expire.wait(10)
            raise Empty

    monkeypatch.setattr(provider_module, "Queue", ControlledCallerQueue)
    # Keep the ordinary production budget; no scheduler race against 0.2 seconds.
    runtime, seen = setup(vendor, ledger=cost, handler=slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        caller = pool.submit(runtime.generate, {"prompt": "local"})
        try:
            assert entered.wait(10)
            assert caller_waiting.wait(10)
            assert not finished.is_set()
            expire.set()
            with pytest.raises(ProviderTimeoutError):
                caller.result(timeout=10)
            original = runtime.usage_receipts
            assert original[0].usage.state is UsageState.TIMEOUT
            assert runtime.late_usage_attempts == ()
            assert cost.snapshot().outstanding_units == 14000
            exposure_after_timeout = cost.snapshot()
            assert not finished.is_set()
        finally:
            expire.set()
            release.set()
            if entered.is_set():
                assert finished.wait(10)
            assert runtime._slot.acquire(timeout=10)
            runtime._slot.release()
    assert runtime.usage_receipts == original
    assert runtime.late_usage_attempts == (original[0].attempt_id,)
    assert cost.snapshot().outstanding_units == 14000
    assert cost.snapshot() == exposure_after_timeout
    assert len(seen) == runtime.attempts == 1


def test_cancellation_without_usage_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cost = fixture_ledger(tmp_path, "fake")
    switch = OffSwitch()

    def cancel(self: FakeProvider, request: object, context: ProviderCallContext) -> object:
        switch.activate()
        return {"text": SECRET}

    monkeypatch.setattr(FakeProvider, "generate", cancel)
    runtime = ProviderRuntime(ledger=cost, off_switch=switch)
    with pytest.raises(AuthorityViolationError):
        runtime.generate({"prompt": "local"})
    assert runtime.usage_receipts[0].usage.state is UsageState.CANCELLED
    assert cost.snapshot().outstanding_units == 14000


def test_reconstructed_runtime_does_not_reset_cumulative_token_authority(tmp_path: Path) -> None:
    p = policy(100000, tokens=TokenPolicy(step_count=1, input_per_step=12000, output_per_step=2000))
    cost = FixtureLedger(tmp_path / "cost.sqlite", p, create=True)
    first = ProviderRuntime(ledger=cost)
    first.generate({"prompt": "local"})
    restored = ProviderRuntime(ledger=FixtureLedger(tmp_path / "cost.sqlite", p))
    with pytest.raises(BudgetExceededError):
        restored.generate({"prompt": "local"})
    assert restored.attempts == 0
    assert len(cost.snapshot().attempts) == 1


def test_usage_capture_duplicates_and_late_state_are_explicit() -> None:
    capture = UsageCapture()
    facts = UsageFacts(state=UsageState.REPORTED, input_tokens=2, output_tokens=1)
    capture.report(facts)
    with pytest.raises(ValueError):
        capture.report(facts)
    assert capture.close(UsageState.UNAVAILABLE) == facts
    capture.report(facts)
    assert capture.late
    assert capture.close(UsageState.TIMEOUT) == facts


@pytest.mark.parametrize(
    "raw",
    [
        {"state": "reported", "input_tokens": 1, "output_tokens": 1},
        {"state": UsageState.REPORTED, "input_tokens": True, "output_tokens": 1},
        {"state": UsageState.REPORTED, "input_tokens": 1.0, "output_tokens": 1},
        {"state": UsageState.MISSING, "input_tokens": 0, "output_tokens": 0},
        {"state": UsageState.REPORTED, "input_tokens": 1, "output_tokens": 1, "approved": True},
        {
            "state": UsageState.REPORTED,
            "input_tokens": 1,
            "output_tokens": 1,
            "evidence": "deployment",
        },
    ],
)
def test_usage_contract_has_no_coercion_authority_or_metadata(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UsageFacts.model_validate(raw)


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_real_dispatch_is_denied_even_with_legacy_optin_and_dummy_auth(
    vendor: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anthropic
    import openai

    from harness_engineering.config import HarnessConfig
    from harness_engineering.vendor_providers import AnthropicProvider, OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "offline-dummy-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-dummy-not-real")
    resource = (
        openai.resources.responses.Responses
        if vendor == "openai"
        else anthropic.resources.messages.Messages
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Real monetary denial must precede SDK request dispatch")

    monkeypatch.setattr(resource, "create", forbidden)
    from tests.live_seam import LIVE_MODEL, live_runtime

    budget = RuntimeBudget(max_cost_usd=0.01)
    config = HarnessConfig(deterministic_mode=False, allow_live_providers=True, budget=budget)
    adapter = (
        OpenAIProvider(LIVE_MODEL[vendor])
        if vendor == "openai"
        else AnthropicProvider(LIVE_MODEL[vendor])
    )
    # Story 13: legacy opt-in without an allowlist policy cannot bind at all.
    with pytest.raises(AuthorityViolationError, match="policy"):
        ProviderRuntime(provider=adapter, budget=budget, live_config=config)
    # Allowlisted live policy and dummy auth, but no human authorization.
    runtime = live_runtime(vendor, live_authorization=None)
    with pytest.raises(AuthorityViolationError, match="monetary"):
        runtime.generate({"prompt": "local"})
    assert runtime.attempts == 1


def test_existing_runtime_monetary_cap_cannot_be_expanded_by_fixture_ledger(tmp_path: Path) -> None:
    from harness_engineering.errors import ContractValidationError

    cost = FixtureLedger(tmp_path / "cost.sqlite", policy(11), create=True)
    with pytest.raises(ContractValidationError, match="cost cap"):
        ProviderRuntime(
            ledger=cost,
            budget=RuntimeBudget(
                max_context_tokens=8,
                max_output_tokens=2,
                max_cost_usd=0.000010,
            ),
        )


def test_generated_usage_fields_are_not_a_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        FakeProvider,
        "generate",
        lambda *_: {
            "text": "safe",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    )
    runtime = ProviderRuntime()
    with pytest.raises(ProviderOutputRejected):
        runtime.generate({"prompt": "local"})
    assert runtime.usage_receipts[0].usage.state is UsageState.UNAVAILABLE


def test_settlement_storage_failure_withholds_result_and_retains_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness_engineering.cost_governance import LedgerError

    cost = fixture_ledger(tmp_path, "fake")

    def fail(*args: object) -> None:
        raise LedgerError("Storage unavailable")

    monkeypatch.setattr(cost, "settle", fail)
    runtime = ProviderRuntime(ledger=cost)
    with pytest.raises(LedgerError):
        runtime.generate({"prompt": "local"})
    assert runtime.attempts == 1
    assert cost.snapshot().outstanding_units == 14000


def test_usage_and_telemetry_share_the_application_identity() -> None:
    from harness_engineering.domain import EvidenceClass, WorkflowIdentity
    from harness_engineering.observability import TelemetrySession

    telemetry = TelemetrySession(WorkflowIdentity(), evidence=EvidenceClass.DETERMINISTIC)
    runtime = ProviderRuntime(telemetry=telemetry)
    runtime.generate({"prompt": "local"})
    receipt = runtime.usage_receipts[0]
    assert receipt.workflow_id == telemetry.identity.workflow_id
    assert receipt.thread_id == telemetry.identity.thread_id


def test_receipts_preserve_accepted_wider_structural_action_bindings() -> None:
    # Accepted runtime supports bounded structural plans above the normal 12-step
    # default. Only the fixture ledger is restricted to the frozen normal profile.
    actions = tuple(f"action-{index}" for index in range(13))
    runtime = ProviderRuntime(budget=RuntimeBudget(max_plan_steps=13), action_ids=actions)
    assert runtime.generate({"prompt": "local"}, action_id=actions[-1]).text
    assert runtime.usage_receipts[0].step_index == 13
