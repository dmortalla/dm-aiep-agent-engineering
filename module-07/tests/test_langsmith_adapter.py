"""Story 6 LangSmith adapter tests: plans, bounded lanes, owned boundary."""

import asyncio

import pytest
import requests
from pydantic import SecretStr

from reliability_safety_observability.evaluation_benchmark import (
    BenchmarkRunner,
    benchmark_report,
)
from reliability_safety_observability.evaluation_contracts import canonical_digest
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import EvaluationEngine
from reliability_safety_observability.evaluation_target import ReferenceTarget
from reliability_safety_observability.langsmith_adapter import (
    LANGSMITH_NAMESPACE,
    FakeLangSmithSdkTransport,
    LangSmithExportError,
    RefusalSource,
    build_export_plan,
    close_bounded,
    read_back_bounded,
    submit_plan_bounded,
)
from reliability_safety_observability.langsmith_config import LangSmithSettings


def settings_for(**override):
    """Build one enabled, budgeted settings object for planning tests."""
    return LangSmithSettings(
        enabled=True,
        api_key="lsv2_pt_test",
        api_url="https://api.smith.langchain.com",
        reservation_per_request_usd=0.001,
        run_cost_limit_usd=1.0,
        **override,
    )


def run_reference():
    """Produce one passing local reference benchmark."""
    dataset = load_benchmark_dataset()
    runner = BenchmarkRunner(EvaluationEngine())
    output = asyncio.run(runner.run_full(
        dataset,
        target_factory=ReferenceTarget.build,
        target_id="reference_default",
        target_version=1,
    ))
    digest = canonical_digest(benchmark_report(output.run, None, None))
    return output, dataset, digest


def export_plan():
    """Build one full deterministic export plan."""
    output, dataset, digest = run_reference()
    return build_export_plan(
        output.run.result,
        dataset,
        settings_for(),
        report_digest=digest,
        exported_subset=None,
    )


def test_build_export_plan_carries_allowlisted_fact_fields_only() -> None:
    """Plans expose exactly the deterministic, minimized evidence surface."""
    plan = export_plan()
    values = plan.examples[0].outputs
    assert set(values) == {
        "classification", "attempts", "fallbacks", "replayed",
        "effect_count", "authorization", "safety", "budget_outcome",
    }
    assert all(not str(raw).casefold().count("canary") for raw in (
        plan.dataset_description, plan.project_name,
    ))
    raw = str(plan)
    assert "DUP 11" not in raw and "FLB 88" not in raw


def test_plan_feedback_covers_every_evaluated_pair() -> None:
    """One feedback row exists per (scenario, evaluator) evaluation pair."""
    output, dataset, digest = run_reference()
    subset = tuple(sorted(dataset.scenario_ids)[:2])
    plan = build_export_plan(
        output.run.result,
        dataset,
        settings_for(),
        report_digest=digest,
        exported_subset=subset,
    )
    expected_pair_count = sum(
        1 for row in output.run.result.evaluations
        if row.scenario_id in subset
    )
    assert len(plan.feedback) == expected_pair_count
    assert len(plan.examples) == len(subset)
    assert len(plan.runs) == len(subset)
    assert plan.worst_case_requests() == (
        5 + len(plan.runs) + len(plan.feedback) + 2
    )


def test_plan_ids_are_deterministic_and_namespaced() -> None:
    """Plan identifiers repeat exactly for the same inputs and run."""
    plan = export_plan()
    second = export_plan()
    assert plan == second
    assert plan.examples[0].example_id
    assert plan.runs[0].reference_example_id == plan.examples[0].example_id


def test_plan_refuses_export_limit_exceeding_partial_subsets() -> None:
    """Subset construction enforces the configured export limit."""
    output, dataset, digest = run_reference()
    with pytest.raises(ValueError):
        build_export_plan(
            output.run.result,
            dataset,
            settings_for(max_exported_scenarios=2),
            report_digest=digest,
            exported_subset=tuple(sorted(dataset.scenario_ids)[:3]),
        )


def test_fake_transport_submit_and_readback_succeed() -> None:
    """The deterministic fake records submitted plans and matches its readback."""
    plan = export_plan()
    fake = FakeLangSmithSdkTransport()
    status, _payload, _thread = asyncio.run(submit_plan_bounded(fake, plan, 5.0))
    assert status == "ok"
    status, counts, _thread = asyncio.run(read_back_bounded(fake, plan, 5.0))
    assert status == "ok"
    assert counts == {"examples": len(plan.examples), "feedback": len(plan.feedback)}


def test_fake_transport_configuration_failures_are_reported() -> None:
    """Fakes and misconfigured plans are contained failures without content."""
    plan = export_plan()
    failing = FakeLangSmithSdkTransport(failure=RefusalSource.TRANSPORT)
    status, _payload, _thread = asyncio.run(submit_plan_bounded(failing, plan, 5.0))
    assert status == "failed"
    assert not failing.submitted

    mismatch = FakeLangSmithSdkTransport(mismatched_readback=True)
    asyncio.run(submit_plan_bounded(mismatch, plan, 5.0))
    status, counts, _thread = asyncio.run(read_back_bounded(mismatch, plan, 5.0))
    assert status == "ok"
    assert counts == {
        "examples": len(plan.examples) - 1,
        "feedback": len(plan.feedback) - 1,
    }

    malformed = FakeLangSmithSdkTransport(malformed_readback=True)
    status, _payload, _thread = asyncio.run(read_back_bounded(malformed, plan, 5.0))
    assert status == "failed"

    with pytest.raises(LangSmithExportError, match="LangSmith export refused"):
        FakeLangSmithSdkTransport(failure=RefusalSource.TRANSPORT).submit_plan(plan)


def test_bounded_close_is_exact_and_reported() -> None:
    """Closure runs exactly once and reports the single clean close."""
    fake = FakeLangSmithSdkTransport()
    status, value, _thread = asyncio.run(close_bounded(fake, 5.0))
    assert status == "ok" and value is True
    assert fake.close_calls == 1
    status, value, _thread = asyncio.run(close_bounded(fake, 5.0))
    assert status == "ok" and value is False


def test_fake_transport_close_repeats_and_reports_itself() -> None:
    """Close ownership is not silently retained across replays."""
    fake = FakeLangSmithSdkTransport()
    assert asyncio.run(close_bounded(fake, 5.0))[:2] == ("ok", True)
    assert asyncio.run(close_bounded(fake, 5.0))[:2] == ("ok", False)


def test_langsmith_namespace_is_a_fixed_documented_uuid() -> None:
    """The adapter namespace is a fixed documented UUID, non-conflicting."""
    from uuid import UUID

    assert UUID("7cc2a8e6-6d2c-5eb1-884f-c309ac2ca5c5") == LANGSMITH_NAMESPACE


# ---------------------------------------------------------------------------
# B-2 repair: the owned boundary hand-off and redirect refusal (Test 21(g)).
# ---------------------------------------------------------------------------


class _RecordingRaw:
    """A ``raw``-shaped object for bounded reads of a fixed body."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, size: int, decode_content: bool = False) -> bytes:
        if not self._body:
            return b""
        # One bounded chunk per read, mimicking a streamed socket.
        chunk = self._body[:65536]
        self._body = self._body[len(chunk):]
        return chunk

    def release_conn(self) -> None:
        return None

    def close(self) -> None:
        return None


class _RecordingAdapter(requests.adapters.HTTPAdapter):
    """Send-counting adapter double returning a fixed canned response."""

    def __init__(
        self, status: int = 200, body: bytes = b"{",
        content_length: int | None = None,
    ) -> None:
        self._status = status
        self._body = body
        self._content_length = content_length
        self.send_calls = 0
        self.send_kwargs: dict = {}

    def send(self, request, **kwargs):
        self.send_calls += 1
        self.send_kwargs = kwargs
        response = requests.Response()
        response.status_code = self._status
        response.headers["Location"] = "http://127.0.0.1:9/redirect"
        if self._content_length is not None:
            response.headers["Content-Length"] = str(self._content_length)
        response.raw = _RecordingRaw(self._body)
        response.request = request
        return response


def _boundary_settings():
    """Build one budgeted settings object for boundary unit tests."""
    return LangSmithSettings(
        enabled=True,
        api_key=SecretStr("lsv2_pt_unit_boundary"),
        api_url="https://1.1.1.1",
        reservation_per_request_usd=0.001,
        run_cost_limit_usd=1.0,
        request_timeout_seconds=3,
    )


def _prepared_request(settings: LangSmithSettings, path: str):
    """Prepare one minimal request for the boundary."""
    prepared = requests.PreparedRequest()
    prepared.prepare(method="POST", url=settings.api_url + path)
    return prepared


def _boundary(
    status: int = 200, body: bytes = b"{}", content_length: int | None = None,
):
    """Build one boundary over a recording adapter and its ledger."""
    from reliability_safety_observability.langsmith_adapter import (
        _OwnedHttpBoundary,
        _RequestLedger,
    )

    settings = _boundary_settings()
    inner = _RecordingAdapter(
        status=status, body=body, content_length=content_length
    )
    ledger = _RequestLedger(
        max_requests=8, reservation_per_request_usd=0.001, run_cost_limit_usd=1.0
    )
    return _OwnedHttpBoundary(settings, ledger, inner, seam=None), inner, ledger


def test_boundary_unit_send_is_supported_and_counted_once() -> None:
    """A normal response flows through one counted zero-argument send.

    The prior implementation passed ``allow_redirects`` to
    ``HTTPAdapter.send`` and every request died as ``transport_rejected``;
    the supported kwargs now flow and each request is sent exactly once.
    """
    settings = _boundary_settings()
    boundary, inner, ledger = _boundary(body=b'{"ok": true}')
    prepared = _prepared_request(_boundary_settings(), "/datasets")
    response = boundary.send(prepared)
    assert inner.send_calls == 1
    assert "allow_redirects" not in inner.send_kwargs
    assert inner.send_kwargs["timeout"] == settings.request_timeout_seconds
    assert response.json() == {"ok": True}
    assert ledger.requests_sent == 1
    assert ledger.requests_refused == 0


def test_boundary_refuses_every_redirect_without_following() -> None:
    """Any 3xx status is refused outright; a loopback Location is never used.

    Contract Test 21(g): a redirect (or proxy bounce) toward loopback is
    detected and refused, and no redirect is followed.
    """
    for status in (301, 302, 303, 307, 308):
        boundary, inner, ledger = _boundary(status=status, body=b"")
        prepared = _prepared_request(_boundary_settings(), "/info")
        with pytest.raises(LangSmithExportError) as exc_info:
            boundary.send(prepared)
        assert exc_info.value.reason == RefusalSource.REDIRECT
        assert inner.send_calls == 1  # Never followed or repeated at boundary level.
        assert ledger.requests_sent == 1  # The reservation is never refunded.


def test_boundary_is_the_only_zero_retry_send_lane() -> None:
    """Failing responses are never retried by the boundary or its adapter.

    The mounted adapter uses ``max_retries=0`` and the boundary never repeats
    a send, so one failing response means exactly one adapter send.
    """
    boundary, inner, _ledger = _boundary(status=500, body=b"temporary failure")
    prepared = _prepared_request(_boundary_settings(), "/runs")
    # Flushed into the SDK, a 500 raises for status; boundary passes it through.
    response = boundary.send(prepared)
    assert response.status_code == 500
    assert inner.send_calls == 1  # Zero retries at the owned lane.


def test_transport_constructs_client_only_with_explicit_opt_in(monkeypatch) -> None:
    """B-1: the opt-in gate is actually forwarded to the activation check.

    A fully configured live transport without opt-in is refused with the
    opt-in message; with opt-in it reaches real construction over a publicly
    routable literal origin while nothing is sent.
    """
    import langsmith.client as langsmith_client_module
    import test_langsmith_live as live_for

    import reliability_safety_observability.langsmith_adapter as adapter_module
    from reliability_safety_observability.errors import ConfigurationError

    runtime = live_for.runtime
    settings_for = live_for.settings_for

    constructed: list = []

    class _StubClient:
        def __init__(self, **kwargs) -> None:
            constructed.append(kwargs)

    gate_spy_calls: list[tuple] = []
    real_gate = adapter_module.require_live_langsmith

    def gate_spy(*args, **kwargs):
        gate_spy_calls.append((args, kwargs))
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(langsmith_client_module, "Client", _StubClient)
    monkeypatch.setattr(adapter_module, "require_live_langsmith", gate_spy)
    transport_settings = settings_for(api_url="https://1.1.1.1")
    with pytest.raises(ConfigurationError, match="opt_in"):
        adapter_module.LangSmithSdkTransport(transport_settings, runtime=runtime())
    assert not constructed
    assert not gate_spy_calls or gate_spy_calls[0][1].get("opt_in") is not True
    transport = adapter_module.LangSmithSdkTransport(
        transport_settings, runtime=runtime(), opt_in=True
    )
    assert constructed, "The SDK client must be the only construction lane."
    assert isinstance(transport._client, _StubClient)
    assert transport.accounting()["requests_sent"] == 0
    assert gate_spy_calls[-1][1]["opt_in"] is True


def test_transport_refuses_prohibited_endpoint_before_client_construction(
    monkeypatch,
) -> None:
    """B-5: qualification precedes any SDK construction or credential use."""
    import langsmith.client as langsmith_client_module
    import test_langsmith_live as live_for

    import reliability_safety_observability.langsmith_adapter as adapter_module
    from reliability_safety_observability.errors import ConfigurationError

    runtime = live_for.runtime
    settings_for = live_for.settings_for

    constructed: list = []

    class _StubClient:
        def __init__(self, **kwargs) -> None:
            constructed.append(kwargs)

    monkeypatch.setattr(langsmith_client_module, "Client", _StubClient)
    with pytest.raises(ConfigurationError, match="qualifica"):
        adapter_module.LangSmithSdkTransport(
            settings_for(api_url="https://127.1"), runtime=runtime(), opt_in=True
        )
    assert not constructed  # Nothing was built, and the key was never unwrapped.


def test_client_construction_disables_batching_and_prompt_cache(monkeypatch) -> None:
    """The construction call never enables batch tracing or prompt caching.

    Contract Test 22: no prompt-cache or tracing thread can start because the
    parameters that create them are hard-disabled at construction.
    """
    import langsmith.client as langsmith_client_module
    import test_langsmith_live as live_for

    import reliability_safety_observability.langsmith_adapter as adapter_module

    runtime = live_for.runtime
    settings_for = live_for.settings_for

    captured: list = []

    class _StubClient:
        def __init__(self, **kwargs) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(langsmith_client_module, "Client", _StubClient)
    adapter_module.LangSmithSdkTransport(
        settings_for(api_url="https://1.1.1.1"), runtime=runtime(), opt_in=True
    )
    assert captured[0]["auto_batch_tracing"] is False
    assert captured[0]["disable_prompt_cache"] is True
    assert captured[0]["retry_config"].total == 0


_RELEVANT_THREAD_PREFIXES = ("langsmith", "LangSmith", "module7")


def test_transport_thread_lifecycle_leaves_no_relevant_thread_behind():
    """Construction, use and close leave no LangSmith/Story 6 thread running.

    Contract Test 22 durability: the accepted configuration disables batch
    tracing and prompt caching, so no background vendor thread starts; the
    only relevant thread is the bounded lifecycle worker, which exists only
    during an in-flight bounded operation. The comparison observes relevant
    thread state before construction, after construction, after use and
    after close — never globally asserting Python has no threads at all.
    """
    import threading
    import time

    import test_langsmith_seam as seam_support

    from reliability_safety_observability.langsmith_adapter import (
        _operation_busy,
    )

    def relevant_threads() -> list[str]:
        return [
            thread.name
            for thread in threading.enumerate()
            if any(
                thread.name.startswith(prefix)
                for prefix in _RELEVANT_THREAD_PREFIXES
            )
        ]

    plan = seam_support.subset_plan(1)
    before = relevant_threads()
    transport = seam_support.gated_transport(seam_support.SeamDouble(plan))
    after_construction = relevant_threads()
    transport.submit_plan(plan)
    counts = transport.read_back(plan)
    _ = counts
    after_use = relevant_threads()
    assert transport.close() is True
    for _ in range(300):
        if not relevant_threads():
            break
        time.sleep(0.01)
    after_close = relevant_threads()
    assert before == []
    assert after_construction == []  # No background vendor thread started.
    assert after_use == []  # No bounded-operation thread remained after use.
    assert _operation_busy(transport) is False
    assert after_close == []  # Nothing relevant left behind after close.


def test_repeated_export_of_the_same_run_is_refused_without_requests() -> None:
    """Test 20: a repeated export of one run_id is refused with no requests."""
    plan = export_plan_subset()
    fake = FakeLangSmithSdkTransport()
    fake.submit_plan(plan)
    assert len(fake.submitted) == 1
    with pytest.raises(LangSmithExportError) as exc_info:
        fake.submit_plan(plan)
    assert exc_info.value.reason == RefusalSource.REPEAT_EXPORT
    assert len(fake.submitted) == 1  # No second submission happened.


def export_plan_subset():
    """Build one deterministic export plan over a two-scenario subset."""
    dataset = load_benchmark_dataset()
    engine = EvaluationEngine()
    exported_subset = tuple(dataset.scenario_ids[:2])
    output = asyncio.run(engine.run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
        scenario_ids=exported_subset,
    ))
    return build_export_plan(
        output.result,
        dataset,
        settings_for(),
        report_digest=canonical_digest(benchmark_report(output, exported_subset, None)),
        exported_subset=exported_subset,
    )


# ---------------------------------------------------------------------------
# Test 20: application-owned budget behavior and accounting.
# ---------------------------------------------------------------------------


def _ledger(**override):
    """Build one request ledger for bounded budget tests."""
    from reliability_safety_observability.langsmith_adapter import _RequestLedger

    values = {
        "max_requests": 4,
        "reservation_per_request_usd": 0.01,
        "run_cost_limit_usd": 0.05,
    }
    values.update(override)
    return _RequestLedger(**values)


def test_ledger_pre_run_planning_refuses_without_sending() -> None:
    """A plan that cannot fit is refused before the first request."""
    ledger = _ledger()
    assert ledger.plan_requests(4) is True
    exhausted = _ledger(max_requests=3)
    assert exhausted.plan_requests(4) is False
    assert exhausted.requests_refused == 4
    assert exhausted.requests_sent == 0
    over_budget = _ledger()
    assert over_budget.plan_requests(6) is False  # 6 * 0.01 > 0.05
    assert over_budget.requests_sent == 0


def test_ledger_charges_before_send_and_never_refunds() -> None:
    """Reservations are charged before sending and never refunded."""
    ledger = _ledger(max_requests=2, run_cost_limit_usd=0.02)
    assert ledger.charge() is True
    assert ledger.cost_used_usd == 0.01
    assert ledger.charge() is True
    assert ledger.cost_used_usd == 0.02
    assert ledger.charge() is False  # The run cost limit is exhausted.
    assert ledger.requests_refused == 1
    assert ledger.requests_sent == 2
    assert ledger.cost_used_usd == 0.02  # Never refunded.
    assert ledger.accounting() == {
        "cost_limit_usd": 0.02,
        "cost_used_usd": 0.02,
        "reservation_per_request_usd": 0.01,
        "requests_sent": 2,
        "requests_refused": 1,
        "basis": "configured_reservation",
    }


def test_ledger_missing_reservation_is_refused_everywhere() -> None:
    """A missing reservation refuses both planning and sending."""
    ledger = _ledger(reservation_per_request_usd=None)
    assert ledger.plan_requests(1) is False
    assert ledger.charge() is False
    assert ledger.requests_sent == 0


def test_ledger_explicit_zero_reservation_permits_bounded_requests() -> None:
    """An explicit zero reservation still respects the request cap."""
    ledger = _ledger(reservation_per_request_usd=0.0)
    assert ledger.plan_requests(4) is True
    assert all(ledger.charge() for _ in range(4)) is True
    assert ledger.charge() is False  # Only the request count caps here.
    assert ledger.cost_used_usd == 0.0  # Deterministic zero accounting.
    assert ledger.accounting()["cost_used_usd"] == 0.0


def test_ledger_planned_count_is_validated() -> None:
    """A negative planned count is refused as malformed input."""
    with pytest.raises(ValueError):
        _ledger().plan_requests(-1)


# ---------------------------------------------------------------------------
# Test 14 (unit): log sanitization behavior.
# ---------------------------------------------------------------------------


def test_log_filter_collapses_sdk_records_without_any_vendor_text() -> None:
    """The configured key value never survives, nor any vendor text at all.

    Contract Test 14(c): for SDK-owned records the whole vendor message is
    collapsed to the fixed application-owned representation; configured
    values, shaped secrets, password-style content and arbitrary canaries are
    all physically absent, and no "[REDACTED]" fragment remains either.
    """
    import logging

    from reliability_safety_observability.langsmith_adapter import _SecretLogFilter

    secret = "lsv2_pt_synthetic_credential_value_9"
    canary = "arbitrary-unconfigured-canary-token-q9"
    filtre = _SecretLogFilter([secret])
    record = logging.LogRecord(
        "langsmith.client", logging.ERROR, "x", 0, "failed: %s", (secret,),
        exc_info=None,
    )
    assert filtre.filter(record) is True
    message = record.getMessage()
    assert secret not in message
    assert "[REDACTED]" not in message
    # The rendered record is the fixed elision, nothing else.
    assert "vendor message text is not rendered" in message

    shaped = logging.LogRecord(
        "langsmith.client", logging.WARNING, "x", 0,
        f"error Authorization: Bearer {canary}", (), exc_info=None,
    )
    assert filtre.filter(shaped) is True
    assert canary not in shaped.getMessage()

    password_record = logging.LogRecord(
        "langsmith.client", logging.ERROR, "x", 0,
        f"discardable vendor text password=hunter2 {canary}", (), exc_info=None,
    )
    assert filtre.filter(password_record) is True
    assert "hunter2" not in password_record.getMessage()
    assert canary not in password_record.getMessage()
    # Application-side severity survives; the message content does not.
    assert shaped.levelname == "WARNING"
    assert password_record.levelname == "ERROR"


def test_log_filter_via_attached_filter_absorbs_interpolated_records() -> None:
    """An actual attached filter absorbs a LangSmith-style interpolated record.

    The Reviewer-style probe: a real transport attaches the filter to the
    ``langsmith.client`` logger; an interpolated record carrying arbitrary,
    non-configured, non-pattern secret tokens plus an exception object is
    emitted through it and a handler captures both record and rendered text.
    The arbitrary tokens, the rendered vendor text and the traceback are
    physically absent from both.
    """
    import logging

    from reliability_safety_observability.config import RuntimeSettings
    from reliability_safety_observability.domain import ExecutionMode
    from reliability_safety_observability.langsmith_adapter import (
        LangSmithSdkTransport,
    )

    arbitrary = "unauthorized-tls-fingerprint-canary-7f3a"
    second = "vendor-internal-email-canary@example.invalid"

    captured: list[tuple[object, str]] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append((record, record.getMessage()))

    runtime = RuntimeSettings(
        mode=ExecutionMode.LIVE,
        live_integrations_enabled=True,
        provider_api_key=SecretStr("provider-key"),
    )
    settings = LangSmithSettings(
        enabled=True,
        api_key=SecretStr("lsv2_pt_seam_synthetic"),
        api_url="https://198.51.100.1",
        reservation_per_request_usd=0.001,
        run_cost_limit_usd=1.0,
    )
    transport = LangSmithSdkTransport(
        settings, runtime=runtime, in_process_seam=lambda observed, prepared: b"",
        opt_in=True,
    )
    try:
        logger = logging.getLogger("langsmith.client")
        handler = _Capture()
        logger.addHandler(handler)
        try:
            error = RuntimeError(
                f"post https://api.smith.langchain.com/runs failed for "
                f"token {arbitrary} and key {second}"
            )
            logger.error(
                "SDK create_run request failed for token %s key %s",
                arbitrary, second,
            )
            logger.exception("SDK batch failure", exc_info=error)
        finally:
            logger.removeHandler(handler)
    finally:
        transport.close()
    assert captured
    for _record, rendered in captured:
        assert arbitrary not in rendered
        assert second not in rendered
        assert "create_run" not in rendered
        assert "api.smith.langchain.com" not in rendered
        assert "[REDACTED]" not in rendered
        assert rendered.count("LangSmith SDK log record elided") >= 0
    for record, rendered in captured:
        assert record.exc_info is None and record.exc_text is None
        assert record.stack_info is None
        assert rendered.startswith("LangSmith SDK log record elided")


def test_log_filter_keeps_application_records_rendering_normally() -> None:
    """Ordinary application records during containment render normally."""
    import logging

    from reliability_safety_observability.langsmith_adapter import _SecretLogFilter

    configured = "lsv2_pt_app_lane_value"
    filtre = _SecretLogFilter([configured])
    record = logging.LogRecord(
        "app.components.evaluated", logging.INFO, "x", 0,
        "evaluation completed for %s rows", (27,), exc_info=None,
    )
    assert filtre.filter(record) is True
    assert record.getMessage() == "evaluation completed for 27 rows"
    secret_record = logging.LogRecord(
        "app.components.export", logging.ERROR, "x", 0,
        f"unexpected pass-through of {configured}", (), exc_info=None,
    )
    assert filtre.filter(secret_record) is True
    assert configured not in secret_record.getMessage()
    assert "[REDACTED]" in secret_record.getMessage()


def test_log_filter_scrubs_unknown_secret_bearing_exception_text() -> None:
    """Secret-shaped exception text is scrubbed even with no known values.

    Contract Test 14(c)+(d): unknown credential material inside exception text
    is redacted, and tracebacks can never bypass the sanitization.
    """
    import logging

    from reliability_safety_observability.langsmith_adapter import _SecretLogFilter

    filtre = _SecretLogFilter([])
    for secret_text in (
        "Connection refused: Authorization: Bearer lsv2_pt_unknown_123",
        "config error api_key: lsv2_pt_unknown_123 (see docs)",
        'header {"Authorization": "Bearer lsv2_pt_unknown_123"}',
        "password=hunter2 unexpected",
    ):
        record = logging.LogRecord(
            "langsmith.client", logging.ERROR, "x", 0, secret_text, (), exc_info=None
        )
        assert filtre.filter(record) is True
        message = record.getMessage()
        assert "lsv2_pt_unknown_123" not in message
        assert "hunter2" not in message
    traceback_record = logging.LogRecord(
        "langsmith.client", logging.ERROR, "x", 0, "op failed", (), exc_info=None
    )
    normalized = filtre.filter(traceback_record)
    assert normalized is True
    assert traceback_record.exc_info is None
    assert traceback_record.exc_text is None
    assert traceback_record.stack_info is None


def test_log_filter_survives_unformattable_records() -> None:
    """Unformattable third-party records collapse to a fixed safe message."""
    import logging

    from reliability_safety_observability.langsmith_adapter import _SecretLogFilter

    filtre = _SecretLogFilter(["whatever"])
    record = logging.LogRecord(
        "langsmith.client", logging.ERROR, "x", 0, "%d %s", ("not-a-number",), None
    )
    assert filtre.filter(record) is True
    assert record.getMessage() == (
        "LangSmith SDK log record elided; vendor message text is not rendered."
    )
    assert "whatever" not in record.getMessage()


# ---------------------------------------------------------------------------
# Test 18 (durable): whole-run deadline and response-size cap.
# ---------------------------------------------------------------------------


def _stub_benchmark(run_id: str):
    """Minimal benchmark-shaped object for direct supervisor tests."""
    import types

    return types.SimpleNamespace(
        run=types.SimpleNamespace(
            result=types.SimpleNamespace(run_id=run_id)
        )
    )


def _clock_sequence(values: list[float]):
    """One deterministic monotonic clock returning scheduled values."""
    state = {"calls": 0, "values": values}

    def clock() -> float:
        index = min(state["calls"], len(state["values"]) - 1)
        state["calls"] += 1
        return state["values"][index]

    return clock, state


def test_response_body_cap_refuses_oversized_content_length(monkeypatch) -> None:
    """A declared body over the fixed ceiling is refused without reads.

    Contract Test 18: Content-Length above ``MAX_RESPONSE_BODY_BYTES`` yields
    the fixed ``response_too_large`` refusal, exactly one charged request and
    zero retries; the refusal is a transport refusal and can never mint
    ``live_vendor``.
    """
    from reliability_safety_observability.domain import EvidenceClass
    from reliability_safety_observability.langsmith_adapter import (
        MAX_RESPONSE_BODY_BYTES,
    )

    oversized = MAX_RESPONSE_BODY_BYTES + 1
    boundary, inner, ledger = _boundary(
        body=b'{"ok": true}', content_length=oversized
    )
    prepared = _prepared_request(_boundary_settings(), "/info")
    with pytest.raises(LangSmithExportError) as exc_info:
        boundary.send(prepared)
    assert exc_info.value.reason == RefusalSource.OVERSIZED_RESPONSE
    assert inner.send_calls == 1
    assert ledger.requests_sent == 1  # Charged and never refunded.
    # A transport-level refusal never mints live_vendor anywhere.
    from reliability_safety_observability.langsmith_adapter import (
        FakeLangSmithSdkTransport,
        LangSmithSdkTransport,
    )
    assert LangSmithSdkTransport.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert FakeLangSmithSdkTransport.evidence_class is not EvidenceClass.LIVE_VENDOR


def test_response_body_cap_refuses_oversized_streamed_body() -> None:
    """An actually-streamed body over the cap is refused during the read."""
    from reliability_safety_observability.langsmith_adapter import (
        MAX_RESPONSE_BODY_BYTES,
    )

    oversized_body = b"x" * (MAX_RESPONSE_BODY_BYTES + 1)
    boundary, inner, ledger = _boundary(
        body=oversized_body, content_length=None
    )
    prepared = _prepared_request(_boundary_settings(), "/feedback")
    with pytest.raises(LangSmithExportError) as exc_info:
        boundary.send(prepared)
    assert exc_info.value.reason == RefusalSource.OVERSIZED_RESPONSE
    assert inner.send_calls == 1
    assert ledger.requests_sent == 1


def test_whole_run_deadline_already_exhausted_before_first_request(monkeypatch):
    """An exhausted deadline refuses the run before any request begins.

    Direct supervisor test with injected deterministic timing: the deadline
    reading is already beyond the whole-run bound, so no request starts, the
    ledger is never charged, and the fixed ``timeout_unresolved`` status is
    returned without minting ``live_vendor``.
    """
    import test_langsmith_seam as seam_support

    from reliability_safety_observability.langsmith_adapter import _execute_live

    plan = seam_support.subset_plan(1)
    transport = seam_support.gated_transport(seam_support.SeamDouble(plan))
    monkeypatch.setattr(
        "reliability_safety_observability.langsmith_adapter._MONOTONIC_CLOCK",
        lambda: 10_000.0,
    )
    result = _execute_live(
        transport, plan, _stub_benchmark(plan.run_id), "0" * 64, None,
        deadline=0.0,
    )
    assert result.outcome == "timeout_unresolved"
    assert result.evidence_class is None
    assert result.expected_examples == len(plan.examples)
    assert result.confirmed_examples == 0
    assert transport.accounting()["requests_sent"] == 0
    assert transport._boundary.observed == []
    assert transport.close() is True


def test_whole_run_deadline_exhausted_between_bounded_operations(monkeypatch):
    """Exhaustion between two bounded ops never begins the second request.

    The submit fits within the deadline; the readback returns partial counts
    (never confirmed), and before the next readback attempt the injected
    clock exhausts the whole-run bound. The second request never begins, the
    submit's charged requests and cost reservations remain correct (never
    refunded), and the fixed ``timeout_unresolved`` status is returned
    without minting ``live_vendor``.
    """
    import test_langsmith_seam as seam_support

    from reliability_safety_observability.langsmith_adapter import _execute_live

    plan = seam_support.subset_plan(1)
    missing_row = seam_support.SeamDouble(plan).readback_feedback_rows()[:-1]
    seam = seam_support.SeamDouble(plan, feedback_rows=missing_row)
    settings = seam_support.settings_for(readback_interval_seconds=0.0)
    transport = seam_support.LangSmithSdkTransport(
        settings, runtime=seam_support.runtime(), in_process_seam=seam, opt_in=True
    )
    clock, _state = _clock_sequence([10.0] * 4 + [100_000.0])
    monkeypatch.setattr(
        "reliability_safety_observability.langsmith_adapter._MONOTONIC_CLOCK",
        clock,
    )
    result = _execute_live(
        transport, plan, _stub_benchmark(plan.run_id), "0" * 64, None,
        deadline=50.0,
    )
    assert result.outcome == "timeout_unresolved"
    assert result.evidence_class is None
    accounting = transport.accounting()
    assert accounting["requests_sent"] > 0  # Submit stayed charged.
    assert accounting["requests_sent"] == len(transport._boundary.observed)
    observed_at_end = len(transport._boundary.observed)
    transport.close()
    # Closing issues nothing further; the log snapshot is final and stable.
    assert len(transport._boundary.observed) == observed_at_end


def test_readback_loop_cannot_begin_after_deadline(monkeypatch):
    """A matching first readback cannot be extended past the deadline.

    Even when a matching readback can succeed in time, exhaustion before the
    next attempt keeps the loop bounded: no further request begins, and the
    run reports the fixed unresolved status never minting ``live_vendor``.
    """
    import test_langsmith_seam as seam_support

    from reliability_safety_observability.langsmith_adapter import _execute_live

    plan = seam_support.subset_plan(1)
    # Partial counts force the loop to try again, confronting the deadline.
    missing_row = seam_support.SeamDouble(plan).readback_feedback_rows()[:-1]
    seam = seam_support.SeamDouble(plan, feedback_rows=missing_row)
    settings = seam_support.settings_for(readback_interval_seconds=0.0)
    transport = seam_support.LangSmithSdkTransport(
        settings, runtime=seam_support.runtime(), in_process_seam=seam, opt_in=True
    )
    clock, _state = _clock_sequence([10.0, 10.0, 10.0, 100_000.0])
    monkeypatch.setattr(
        "reliability_safety_observability.langsmith_adapter._MONOTONIC_CLOCK",
        clock,
    )
    result = _execute_live(
        transport, plan, _stub_benchmark(plan.run_id), "0" * 64, None,
        deadline=50.0,
    )
    assert result.outcome == "timeout_unresolved"
    assert result.evidence_class is None
    assert result.confirmed_examples == 0 and result.confirmed_feedback == 0
    # The exhaustion itself issues nothing further; the run is unresolved.
    assert transport.close() is True


def test_deadline_refused_mid_submit_keeps_charges_and_refuses_rest(monkeypatch):
    """Exhaustion inside one submit: charged requests stay; later ones refuse."""
    import test_langsmith_seam as seam_support

    from reliability_safety_observability.langsmith_adapter import _execute_live

    plan = seam_support.subset_plan(1)
    transport = seam_support.gated_transport(seam_support.SeamDouble(plan))
    transport._boundary._live_deadline = 50.0  # Whole-run deadline applied.
    # First few clock readings run under the deadline, then exhaust forever.
    clock, _state = _clock_sequence(
        [10.0, 10.0, 10.0, 10.0, 10.0, 100_000.0]
    )
    monkeypatch.setattr(
        "reliability_safety_observability.langsmith_adapter._MONOTONIC_CLOCK",
        clock,
    )
    result = _execute_live(
        transport, plan, _stub_benchmark(plan.run_id), "0" * 64, None,
        deadline=50.0,
    )
    assert result.outcome == "timeout_unresolved"
    assert result.evidence_class is None
    accounting = transport.accounting()
    assert accounting["requests_sent"] >= 1  # Earlier requests stay charged.
    # No refund: accounting equals the requests actually sent.
    assert accounting["requests_sent"] == len(transport._boundary.observed)
    transport.close()


def test_ownership_timeout_close_busy_and_eventual_release(monkeypatch):
    """Test 19 ownership: per-op bound, busy conflict, close_busy, release.

    A blocked submit keeps ownership past the per-operation bound; a
    conflicting readback is refused as ``busy``; closing an unresolved
    operation reports ``close_busy`` without a completed close or an
    early release; ownership releases exactly when the underlying
    operation genuinely resolves, with no duplicate side effect and no
    evidence upgrade.

    The per-operation bound times out while the whole-run deadline still has
    time left: the result is still the fixed unresolved status, but the
    deadline enforcement itself never fired (no boundary refusal flag), and
    ownership is retained while unresolved — the two controls stay distinct.
    """
    import threading

    import test_langsmith_seam as seam_support

    from reliability_safety_observability.langsmith_adapter import (
        _close_state,
        _operation_busy,
        read_back_bounded,
        submit_plan_bounded,
    )

    plan = seam_support.subset_plan(1)
    transport = seam_support.gated_transport(seam_support.SeamDouble(plan))
    release = threading.Event()
    executed: list[int] = []

    def blocking_execute(plan_argument):
        executed.append(1)
        release.wait(30)
        raise LangSmithExportError(RefusalSource.MALFORMED_PLAN)

    monkeypatch.setattr(transport, "_execute_plan", blocking_execute)
    submit_result, _payload, _thread = asyncio.run(submit_plan_bounded(
        transport, plan, 0.05
    ))
    assert submit_result == "timeout"
    assert _operation_busy(transport) is True
    assert transport._boundary._deadline_refused is False
    busy_result, _counts, _thread = asyncio.run(read_back_bounded(transport, plan, 0.05))
    assert busy_result == "busy"  # Conflicting operation refused.
    close_outcome = asyncio.run(_close_state(transport, 0.05))
    assert close_outcome == "close_busy"  # Unresolved ownership never closes.
    release.set()
    import time

    for _ in range(200):
        if not _operation_busy(transport):
            break
        time.sleep(0.01)
    assert not _operation_busy(transport)
    close_outcome = asyncio.run(_close_state(transport, 30))
    assert close_outcome == "closed"  # Released only after resolution.
    assert executed == [1]  # Side effect ran exactly once.
