"""Story 9 deterministic presentation and boundary tests."""

import ast
import copy
import gc
import os
import subprocess
import sys
import threading
import weakref
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.console_presenter import (
    BenchmarkInFlightError,
    BenchmarkReceipt,
    ConsoleBoundary,
    LiveAuthorizationReceipt,
    LiveReceiptState,
    evidence_badge,
    lab_projection,
    recovery_projection,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "streamlit_app.py"


def app() -> AppTest:
    """Return a fresh headless reviewer console."""
    return AppTest.from_file(str(APP), default_timeout=30).run(timeout=30)


def live_runtime() -> RuntimeSettings:
    """Return controlled live-opt-in settings; no verifier or transport is built."""
    return RuntimeSettings(
        mode="live", live_integrations_enabled=True, provider_api_key="safe-test-credential"
    )


def live_config() -> dict[str, tuple[str, int]]:
    """Return mutable, non-secret controlled provider configuration for binding tests."""
    return {
        "Langfuse": ("https://langfuse.invalid", 5),
        "LangSmith": ("https://langsmith.invalid", 10),
        "Helicone": ("https://helicone.invalid", 10),
    }


def test_01_app_entry_renders_title_notice_and_legend() -> None:
    """Render the credential-free entry point."""
    at = app()
    assert not at.exception
    text = " ".join(item.value for item in at.markdown)
    assert "Demonstrates:" in text and at.table


def test_02_all_major_journeys_render_four_part_guidance() -> None:
    """Keep reviewer guidance beside every workflow."""
    at = app()
    text = " ".join(item.value for item in at.markdown)
    assert text.count("**Demonstrates:**") >= 5
    assert text.count("**Do this:**") >= 5
    assert text.count("**Expect:**") >= 5
    assert text.count("**Proves:**") >= 5


def test_03_core_import_is_streamlit_free_and_presentation_has_no_sdk_import() -> None:
    """Keep Streamlit and direct vendor SDKs outside the package startup."""
    completed = subprocess.run(
        [sys.executable, "-c", "import reliability_safety_observability; print('ok')"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0 and completed.stdout.strip() == "ok"
    tree = ast.parse((ROOT / "streamlit_app.py").read_text(encoding="utf-8"))
    names = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {"langfuse", "langsmith", "guardrails", "httpx", "requests"} & names


def test_04_default_startup_has_no_network_or_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ordinary startup does not activate a transport."""
    monkeypatch.setenv("MODULE7_PROVIDER_API_KEY", "credential-shaped-value")
    at = app()
    assert not at.exception and at.button(key="run_live_verifier").disabled


def test_05_workflow_click_runs_once_and_rerun_does_not_repeat() -> None:
    """Verify explicit workflow execution and ordinary-rerun non-repetition."""
    at = app()
    at.button(key="run_workflow").click().run(timeout=30)
    assert not at.exception and at.session_state["workflow"] is not None
    first = at.session_state["workflow"].recovery.state.idempotency_key
    at.run(timeout=30)
    assert at.session_state["workflow"].recovery.state.idempotency_key == first


def test_06_workflow_renders_minimized_observation() -> None:
    """Project only neutral, already-redacted telemetry records."""
    result = ConsoleBoundary().run_workflow()
    assert result.records and "trace_id" in result.records[0]
    assert "deterministic_demo_complete" not in str(result.records)


def test_07_recovery_projection_preserves_returned_facts() -> None:
    """Do not synthesize retry, fallback, replay, or recovery values."""
    view = recovery_projection(ConsoleBoundary().run_workflow().recovery)
    assert view["classification"] == "success"
    assert view["attempts"] == 1 and view["replayed"] is False


def test_08_authority_and_safety_are_read_only_results() -> None:
    """Render decisions without an allow/deny control."""
    at = app()
    labels = [button.label for button in at.button]
    assert not any(label.casefold() in {"allow", "deny", "authorize"} for label in labels)


def test_09_cost_projection_keeps_units_and_zero_values() -> None:
    """Keep actual cost distinct from absent values and label USD fields."""
    view = recovery_projection(ConsoleBoundary().run_workflow().recovery)
    assert view["actual_cost_usd"] == 0.0 and view["budget_limit_usd"] == 0.0


def test_10_secret_and_prompt_canaries_are_not_projected() -> None:
    """Never retain workflow output or browser-sensitive content in projections."""
    text = str(recovery_projection(ConsoleBoundary().run_workflow().recovery))
    assert "deterministic_demo_complete" not in text and "sk-" not in text


def test_11_safe_error_does_not_render_rejected_content() -> None:
    """Unexpected errors use a fixed safe UX message."""
    from reliability_safety_observability.console_presenter import safe_error

    assert "PRIVATE" not in safe_error(RuntimeError("PRIVATE"))


def test_12_provider_tab_is_non_authoritative_before_live_confirmation() -> None:
    """Provider status is evidence-only and does not run a verifier."""
    at = app()
    assert at.button(key="run_live_verifier").disabled
    assert at.info and "No provider verifier" in at.info[-1].value


def test_13_benchmark_uses_committed_public_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse concurrent benchmark work before the accepted composition begins."""
    console = ConsoleBoundary()
    original = console._execute_benchmark
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def held(ordinal: int):
        calls.append(ordinal)
        entered.set()
        assert release.wait(timeout=10)
        return original(ordinal)

    monkeypatch.setattr(console, "_execute_benchmark", held)
    result: list[object] = []
    worker = threading.Thread(target=lambda: result.append(console.run_benchmark()))
    worker.start()
    assert entered.wait(timeout=10)
    with pytest.raises(BenchmarkInFlightError):
        console.run_benchmark()
    assert calls == [0] and console.comparison_receipts() is None
    release.set()
    worker.join(timeout=30)
    assert not worker.is_alive() and len(result) == 1
    evidence = result[0]
    assert evidence.output.verdict.value == "pass" and len(evidence.output.report_digest) == 64
    assert evidence.receipt.ordinal == 0

    monkeypatch.setattr(console, "_execute_benchmark", original)
    sequential = console.run_benchmark()
    assert sequential.receipt.ordinal == 1

    def failing(_: int):
        raise RuntimeError("controlled benchmark failure")

    monkeypatch.setattr(console, "_execute_benchmark", failing)
    with pytest.raises(RuntimeError, match="controlled benchmark failure"):
        console.run_benchmark()
    monkeypatch.setattr(console, "_execute_benchmark", original)
    assert console.run_benchmark().receipt.ordinal == 2

    # Eight simultaneous attempts yield exactly one real action and receipt.
    crowded = ConsoleBoundary()
    crowded_original = crowded._execute_benchmark
    crowded_entered, crowded_release = threading.Event(), threading.Event()
    crowded_calls: list[int] = []

    def crowded_held(ordinal: int):
        crowded_calls.append(ordinal)
        crowded_entered.set()
        assert crowded_release.wait(timeout=10)
        return crowded_original(ordinal)

    monkeypatch.setattr(crowded, "_execute_benchmark", crowded_held)
    barrier = threading.Barrier(9)
    outcomes: list[object] = []
    refusals: list[Exception] = []

    def simultaneous_attempt() -> None:
        barrier.wait(timeout=10)
        try:
            outcomes.append(crowded.run_benchmark())
        except BenchmarkInFlightError as exc:
            refusals.append(exc)

    workers = [threading.Thread(target=simultaneous_attempt) for _ in range(8)]
    for item in workers:
        item.start()
    barrier.wait(timeout=10)
    assert crowded_entered.wait(timeout=10)
    crowded_release.set()
    for item in workers:
        item.join(timeout=30)
    assert not any(item.is_alive() for item in workers)
    assert crowded_calls == [0] and len(outcomes) == 1 and len(refusals) == 7
    assert outcomes[0].receipt.ordinal == 0 and crowded.comparison_receipts() is None

    # Independent boundaries do not share an in-flight refusal state.
    session_a, session_b = ConsoleBoundary(), ConsoleBoundary()
    session_a_original = session_a._execute_benchmark
    session_a_entered, session_a_release = threading.Event(), threading.Event()

    def session_a_held(ordinal: int):
        session_a_entered.set()
        assert session_a_release.wait(timeout=10)
        return session_a_original(ordinal)

    monkeypatch.setattr(session_a, "_execute_benchmark", session_a_held)
    session_a_result: list[object] = []
    session_a_worker = threading.Thread(
        target=lambda: session_a_result.append(session_a.run_benchmark())
    )
    session_a_worker.start()
    assert session_a_entered.wait(timeout=10)
    assert session_b.run_benchmark().receipt.ordinal == 0
    session_a_release.set()
    session_a_worker.join(timeout=30)
    assert not session_a_worker.is_alive() and session_a_result[0].receipt.ordinal == 0


def test_14_evaluation_rows_keep_authoritative_evidence_labels() -> None:
    """Each returned evaluation row remains deterministic fixture evidence."""
    output = ConsoleBoundary().run_benchmark().output
    assert output.run.result.evaluations
    assert {row.evidence_class.value for row in output.run.result.evaluations} == {
        "deterministic_fixture"
    }


def test_15_regression_result_is_not_promoted_by_presentation() -> None:
    """Expose the actual local regression outcome unchanged."""
    regression = ConsoleBoundary().run_benchmark().output.regression
    assert regression is not None and regression.outcome.value == "pass"


def test_16_improvement_requires_boundary_owned_distinct_receipts() -> None:
    """Keep A/B/C provenance bounded and benchmark authority owned per session."""
    session_a, session_b = ConsoleBoundary(), ConsoleBoundary()
    assert session_a.owner != session_b.owner
    a1 = session_a.run_benchmark()
    # B starts with no retained authority from A and cannot use A1.
    assert session_b.comparison_receipts() is None
    b1 = session_b.run_benchmark()
    assert session_b.comparison_receipts() is None and b1.receipt.ordinal == 0
    assert session_b.improvement(a1.receipt, b1.receipt) is None
    assert session_a.improvement(a1.receipt, b1.receipt) is None
    a2 = session_a.run_benchmark()
    assert session_a.comparison_receipts() == (a1.receipt, a2.receipt)
    assert session_a.improvement(a1.receipt, a2.receipt) is not None
    b2 = session_b.run_benchmark()
    assert session_b.comparison_receipts() == (b1.receipt, b2.receipt)
    assert session_b.improvement(b1.receipt, b2.receipt) is not None
    # Each boundary rejects the other session's receipts, alone or mixed.
    assert session_b.improvement(a1.receipt, a2.receipt) is None
    assert session_a.improvement(b1.receipt, b2.receipt) is None
    assert session_b.improvement(a1.receipt, b2.receipt) is None
    # Copied, re-owned, altered, and type-valid substitutes never transfer authority.
    for before in (
        copy.copy(a1.receipt),
        replace(a1.receipt, owner=session_b.owner),
        BenchmarkReceipt(a1.receipt.token, 0, a1.receipt.report_digest, session_b.owner),
        replace(b1.receipt, report_digest="0" * 64),
        replace(b1.receipt, owner=session_a.owner),
        b1.output.run.result,
    ):
        assert session_b.improvement(before, b2.receipt) is None
    assert session_b.improvement(copy.copy(b1.receipt), b2.receipt) is None
    # A/B/C rolling: A3 rolls A's pair; B's pair is never evicted by A activity.
    a3 = session_a.run_benchmark()
    assert session_a.comparison_receipts() == (a2.receipt, a3.receipt)
    assert session_a.improvement(a2.receipt, a3.receipt) is not None
    assert session_a.improvement(a3.receipt, a2.receipt) is None
    assert session_a.improvement(a1.receipt, a3.receipt) is None
    assert session_b.comparison_receipts() == (b1.receipt, b2.receipt)
    assert session_b.improvement(b1.receipt, b2.receipt) is not None
    assert session_a.improvement(object(), a3.receipt) is None
    # Ownership is bounded: each session keeps only its current pair, and a
    # released session boundary leaves no process-global retention behind.
    assert len(session_a._runs) == 2 and len(session_b._runs) == 2
    released = weakref.ref(session_b)
    del session_b, b1, b2
    gc.collect()
    assert released() is None


def test_17_lab_selector_is_exact_and_selected_run_is_typed() -> None:
    """Expose only the accepted S01-S20 taxonomy."""
    from reliability_safety_observability.failure_lab import ScenarioKind

    assert [kind.name for kind in ScenarioKind] == [f"S{number:02}" for number in range(1, 21)]
    assert ConsoleBoundary().run_selected_lab(ScenarioKind.S01).kind == "s01"


def test_18_full_lab_returns_summary_and_individual_facts() -> None:
    """Run the accepted complete matrix once and preserve its summary."""
    rows, summary = ConsoleBoundary().run_full_lab()
    assert len(rows) == 20 and summary.scenario_count == 20
    assert rows[-1].kind == "s20" and rows[-1].extra["post_resolution"] == "closed"
    assert lab_projection(rows[0])["evidence_class"] in {
        "simulated_failure",
        "mocked_provider_contract",
        "deterministic_fixture",
    }


def test_19_evidence_badges_never_promote_unknown_values() -> None:
    """Preserve classifications and fail closed for malformed values."""
    assert evidence_badge("simulated_failure") == "simulated_failure"
    assert evidence_badge("live_vendor") == "live_vendor"
    assert evidence_badge("invented_live") == "unresolved"


def test_20_empty_and_invalid_states_use_safe_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep absent/invalid states reviewer-safe and isolate Streamlit sessions."""
    session_a, session_b = app(), app()
    assert any("No workflow has been run." in item.value for item in session_a.caption)
    assert ConsoleBoundary().improvement(object(), object()) is None
    boundary_a = session_a.session_state["_console_boundary"]
    boundary_b = session_b.session_state["_console_boundary"]
    assert boundary_a is not boundary_b and boundary_a.owner != boundary_b.owner

    # A1 then B1: B must not compare against A's retained ordinal 0.
    session_a.button(key="run_benchmark").click().run(timeout=30)
    session_b.button(key="run_benchmark").click().run(timeout=30)
    assert session_b.session_state["before"] is None
    assert any(item.proto.title == "Comparison unavailable" for item in session_b.info)
    a1 = session_a.session_state["benchmark"].receipt
    assert session_b.session_state["benchmark"].receipt.owner == boundary_b.owner

    # A2 completes A's own pair.
    session_a.button(key="run_benchmark").click().run(timeout=30)
    assert session_a.session_state["before"] is a1
    assert not session_a.warning and session_a.subheader[-1].value == "Improvement-cycle evidence"

    # Substituting A's receipts into B's presentation state is rejected by B's boundary.
    session_b.session_state["before"] = session_a.session_state["before"]
    session_b.session_state["after"] = session_a.session_state["after"]
    session_b.run(timeout=30)
    assert any("invalid or incompatible" in item.value for item in session_b.warning)
    assert not any(item.value == "Improvement-cycle evidence" for item in session_b.subheader)

    # Substituting A's whole boundary into B is recognized as foreign and replaced.
    session_b.session_state["_console_boundary"] = boundary_a
    session_b.run(timeout=30)
    replacement = session_b.session_state["_console_boundary"]
    assert replacement is not boundary_a and replacement.owner != boundary_a.owner
    assert replacement.comparison_receipts() is None
    assert any("invalid or incompatible" in item.value for item in session_b.warning)

    # B's activity never mutated A's comparison authority.
    assert boundary_a.comparison_receipts() == (
        session_a.session_state["before"],
        session_a.session_state["after"],
    )
    session_a.run(timeout=30)
    assert not session_a.warning

    # The private compatibility boundary rejects missing, malformed, and shared
    # sentinel anchors before a transferred boundary can be accepted. Its sole
    # supported runtime is pinned to the locally inspected 1.66.1 semantics.
    sys.path.insert(0, str(ROOT))
    from streamlit.runtime.state import SafeSessionState, SessionState

    import streamlit_app

    valid = SessionState()
    valid_context = SimpleNamespace(session_state=SafeSessionState(valid, lambda: None))
    monkeypatch.setattr(streamlit_app, "get_script_run_ctx", lambda: valid_context)
    assert streamlit_app._session_anchor() is valid
    monkeypatch.setattr(streamlit_app.st, "__version__", "1.66.2")
    with pytest.raises(RuntimeError, match="ownership"):
        streamlit_app._session_anchor()
    monkeypatch.setattr(streamlit_app.st, "__version__", "1.66.1")
    monkeypatch.setattr(streamlit_app, "get_script_run_ctx", lambda: None)
    with pytest.raises(RuntimeError, match="No reviewer session"):
        streamlit_app._session_anchor()
    for context in (
        SimpleNamespace(),
        SimpleNamespace(session_state=SimpleNamespace(_state=object())),
        SimpleNamespace(session_state=SafeSessionState(object(), lambda: None)),
    ):
        monkeypatch.setattr(streamlit_app, "get_script_run_ctx", lambda context=context: context)
        with pytest.raises(RuntimeError, match="ownership"):
            streamlit_app._session_anchor()
    sentinel = object()
    for _ in range(2):
        monkeypatch.setattr(
            streamlit_app,
            "get_script_run_ctx",
            lambda: SimpleNamespace(session_state=SimpleNamespace(_state=sentinel)),
        )
        with pytest.raises(RuntimeError, match="ownership"):
            streamlit_app._session_anchor()
    # Two wrappers around one genuine state are intentionally not claimed as a
    # type-detectable attack. They model semantics outside the pinned 1.66.1
    # AppSession contract, whose source constructs a fresh SessionState per
    # AppSession; a future runtime must fail the version gate until revalidated.
    shared = SessionState()
    contexts = [
        SimpleNamespace(session_state=SafeSessionState(shared, lambda: None)),
        SimpleNamespace(session_state=SafeSessionState(shared, lambda: None)),
    ]
    for context in contexts:
        monkeypatch.setattr(streamlit_app, "get_script_run_ctx", lambda context=context: context)
        assert streamlit_app._session_anchor() is shared


def test_21_reruns_and_live_selection_do_not_enable_transport() -> None:
    """Reruns and selection never enable transport; the boundary owns live authority."""
    at = app()
    at.selectbox(key="live_provider").select("LangSmith").run()
    assert at.button(key="run_live_verifier").disabled
    at.run()
    assert at.button(key="run_live_verifier").disabled
    # Credentials never grant authority: deterministic settings issue nothing.
    assert ConsoleBoundary(RuntimeSettings()).issue_live_confirmation("Langfuse") is None

    config = live_config()
    console = ConsoleBoundary(live_runtime(), live_config_resolver=config.__getitem__)
    held = console.issue_live_confirmation("Langfuse")
    assert held is not None and console.live_receipt_state(held) is LiveReceiptState.ISSUED
    # G/H/I: copied, forged, and mutated references are unauthorized and harmless.
    forged = LiveAuthorizationReceipt(held.token, held.provider)
    assert console.consume_live_confirmation(copy.copy(held), "Langfuse") is None
    assert console.consume_live_confirmation(forged, "Langfuse") is None
    assert console.consume_live_confirmation(replace(held), "Langfuse") is None
    assert console.consume_live_confirmation(None, "Langfuse") is None
    assert console.live_confirmation_is_current(held, "Langfuse")
    # C: the exact current receipt yields exactly one grant bound to its configuration.
    grant = console.consume_live_confirmation(held, "Langfuse")
    assert grant is not None and grant.provider == "Langfuse"
    assert grant.settings == config["Langfuse"] and grant.runtime is console._settings
    # E/F/P/R: consumed authority never returns, including the exact restored object.
    assert console.live_receipt_state(held) is LiveReceiptState.CONSUMED
    assert console.consume_live_confirmation(held, "Langfuse") is None
    assert not console.live_confirmation_is_current(held, "Langfuse")

    mutated = console.issue_live_confirmation("Langfuse")
    object.__setattr__(mutated, "token", "0" * 43)
    assert console.consume_live_confirmation(mutated, "Langfuse") is None
    object.__setattr__(mutated, "token", ["unhashable"])
    assert console.live_receipt_state(mutated) is None
    assert console.consume_live_confirmation(mutated, "Langfuse") is None
    # A newer confirmation supersedes an older one.
    older = console.issue_live_confirmation("Langfuse")
    newer = console.issue_live_confirmation("Langfuse")
    assert console.live_receipt_state(older) is LiveReceiptState.SUPERSEDED
    assert console.consume_live_confirmation(older, "Langfuse") is None
    # J/K: provider away invalidates; changing back does not resurrect it.
    assert not console.live_confirmation_is_current(newer, "LangSmith")
    assert not console.live_confirmation_is_current(newer, "Langfuse")
    assert console.live_receipt_state(newer) is LiveReceiptState.INVALIDATED
    # L/M: provider configuration away and back keeps the old confirmation invalid.
    bound = console.issue_live_confirmation("Langfuse")
    original = config["Langfuse"]
    config["Langfuse"] = ("https://other.invalid", 5)
    assert not console.live_confirmation_is_current(bound, "Langfuse")
    config["Langfuse"] = original
    assert console.consume_live_confirmation(bound, "Langfuse") is None
    # Runtime configuration away and back is equally final.
    runtime_bound = console.issue_live_confirmation("Langfuse")
    console.update_runtime_settings(RuntimeSettings())
    console.update_runtime_settings(live_runtime())
    assert console.consume_live_confirmation(runtime_bound, "Langfuse") is None
    # Unresolvable configuration fails closed at issue and at consumption.
    del config["Helicone"]
    assert console.issue_live_confirmation("Helicone") is None
    assert console.issue_live_confirmation("Unlisted") is None

    # O/Q: a fresh confirmation permits exactly one of many concurrent attempts.
    fresh = console.issue_live_confirmation("Langfuse")
    barrier = threading.Barrier(16)
    invocations: list[object] = []

    def attempt() -> None:
        barrier.wait(timeout=10)
        granted = console.consume_live_confirmation(fresh, "Langfuse")
        if granted is not None:
            invocations.append(granted)

    workers = [threading.Thread(target=attempt) for _ in range(16)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert not any(worker.is_alive() for worker in workers) and len(invocations) == 1
    # The authoritative ledger itself stays bounded.
    for _ in range(20):
        console.issue_live_confirmation("LangSmith")
    assert len(console._live_ledger) <= 8


def test_22_confirmed_live_result_is_not_repeated_on_ordinary_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay attacks through Streamlit session state never reach the verifier."""
    sys.path.insert(0, str(ROOT))
    import streamlit_app

    calls: list[str] = []
    fail_next = False
    config = live_config()
    fake = ConsoleBoundary(live_runtime(), live_config_resolver=config.__getitem__)

    def fake_verifier(grant: object) -> dict[str, str]:
        nonlocal fail_next
        calls.append(grant.provider)
        if fail_next:
            fail_next = False
            raise RuntimeError("handled test failure")
        return {"outcome": "confirmed"}

    def confirm() -> object:
        at.checkbox(key="live_confirmation").uncheck().run()
        at.checkbox(key="live_confirmation").check().run()
        return at.session_state["_live_confirmation"]

    def refused_by_boundary() -> None:
        # Streamlit ignores triggers on disabled controls, so also present the
        # session-held reference straight to the action boundary, as a forged
        # request bypassing the presentation would.
        held_reference = at.session_state["_live_confirmation"]
        assert fake.consume_live_confirmation(held_reference, "Langfuse") is None

    def replay(reference: object, expected: list[str]) -> None:
        at.session_state["live_confirmation"] = True
        at.session_state["_live_confirmation"] = reference
        at.run()
        assert at.button(key="run_live_verifier").disabled
        at.session_state["_live_confirmation"] = reference
        refused_by_boundary()
        assert calls == expected

    monkeypatch.setattr(streamlit_app, "run_live_verifier", fake_verifier)
    monkeypatch.setattr(streamlit_app, "boundary", lambda: fake)
    # A/B: startup and live-enabled-but-unconfirmed make no call.
    at = AppTest.from_string("import streamlit_app\nstreamlit_app.main()").run()
    assert calls == [] and at.button(key="run_live_verifier").disabled
    at.run()
    assert calls == []
    # C/D/E: one confirmation yields one call; reruns and re-clicks add none.
    at.checkbox(key="live_confirmation").check().run()
    held = at.session_state["_live_confirmation"]
    assert not at.button(key="run_live_verifier").disabled
    at.button(key="run_live_verifier").click().run()
    assert calls == ["Langfuse"]
    assert "confirmed result" in at.info[-1].value
    assert "No provider verifier has been run" not in at.info[-1].value
    at.run()
    assert calls == ["Langfuse"] and at.button(key="run_live_verifier").disabled
    assert "confirmed result" in at.info[-1].value
    refused_by_boundary()
    assert calls == ["Langfuse"]
    # F/G/H/R: restored, copied, and forged presentation state stays unauthorized.
    replay(held, ["Langfuse"])
    replay(copy.copy(held), ["Langfuse"])
    replay(LiveAuthorizationReceipt(held.token, held.provider), ["Langfuse"])
    # O: a new explicit acknowledgement authorizes exactly one new invocation.
    confirm()
    at.button(key="run_live_verifier").click().run()
    assert calls == ["Langfuse", "Langfuse"]
    at.run()
    assert calls == ["Langfuse", "Langfuse"]
    # J/K: provider away and back never resurrects the earlier confirmation.
    stale = confirm()
    at.selectbox(key="live_provider").select("LangSmith").run()
    assert at.button(key="run_live_verifier").disabled
    at.selectbox(key="live_provider").select("Langfuse").run()
    replay(stale, ["Langfuse", "Langfuse"])
    # Provider substitution without the selection callback is refused as well.
    stale = confirm()
    at.session_state["live_provider"] = "Helicone"
    at.run()
    at.session_state["live_provider"] = "Langfuse"
    replay(stale, ["Langfuse", "Langfuse"])
    # L/M: configuration away and back keeps the old confirmation invalid.
    stale = confirm()
    original = config["Langfuse"]
    config["Langfuse"] = ("https://other.invalid", 5)
    at.run()
    config["Langfuse"] = original
    replay(stale, ["Langfuse", "Langfuse"])
    # N: a handled verifier failure consumes its confirmation and cannot replay.
    attempted = confirm()
    fail_next = True
    at.button(key="run_live_verifier").click().run()
    assert calls == ["Langfuse", "Langfuse", "Langfuse"]
    assert at.error and at.session_state["live_result"] == {"outcome": "confirmed"}
    assert "failed or was unavailable" in at.info[-1].value
    assert any("Previous returned result" in item.value for item in at.caption)
    assert fake.live_receipt_state(attempted) is LiveReceiptState.CONSUMED
    replay(attempted, ["Langfuse", "Langfuse", "Langfuse"])
    assert "failed or was unavailable" in at.info[-1].value
    # O after failure: a fresh confirmation permits exactly one more invocation.
    confirm()
    at.button(key="run_live_verifier").click().run()
    at.run()
    assert calls == ["Langfuse"] * 4 and at.button(key="run_live_verifier").disabled


@pytest.mark.parametrize(
    ("outcome", "evidence_class", "expected"),
    [
        ("confirmed", "mocked_provider_contract", "confirmed result"),
        ("confirmed", "deterministic_fixture", "confirmed result"),
        ("export_failed", None, "did not confirm a result"),
        ("readback_not_confirmed", None, "did not confirm a result"),
        ("timeout_unresolved", None, "did not confirm a result"),
        (None, None, "failed or was unavailable"),
    ],
)
def test_25_verifier_attempt_status_survives_rerender(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str | None,
    evidence_class: str | None,
    expected: str,
) -> None:
    """Render observed attempt outcomes without promoting a mock to live evidence."""
    monkeypatch.syspath_prepend(str(ROOT))
    import streamlit_app

    console = ConsoleBoundary(live_runtime(), live_config_resolver=live_config().__getitem__)
    calls = []
    returned = {"outcome": outcome, "evidence_class": evidence_class}

    def verifier(grant: object) -> dict[str, object]:
        calls.append(grant)
        if outcome is None:
            raise RuntimeError("controlled-failure-do-not-display")
        return returned

    monkeypatch.setattr(streamlit_app, "boundary", lambda: console)
    monkeypatch.setattr(streamlit_app, "run_live_verifier", verifier)
    at = AppTest.from_string("import streamlit_app\nstreamlit_app.main()", default_timeout=30).run(
        timeout=30
    )
    assert not at.exception and not calls
    assert "No provider verifier has been run" in at.info[-1].value
    at.checkbox(key="live_confirmation").check().run(timeout=30)
    at.button(key="run_live_verifier").click().run(timeout=30)
    assert not at.exception and len(calls) == 1
    assert expected in at.info[-1].value
    assert "No provider verifier has been run" not in at.info[-1].value
    assert "live_vendor" not in at.info[-1].value
    assert "live_model" not in at.info[-1].value
    if outcome is not None:
        assert at.session_state["live_result"] == returned
        assert any(outcome in item.value for item in at.json)
    else:
        assert at.session_state["live_result"] is None and at.error
        assert "controlled-failure" not in at.error[-1].value
    at.run(timeout=30)
    assert not at.exception and len(calls) == 1
    assert expected in at.info[-1].value
    assert at.button(key="run_live_verifier").disabled


def test_23_accessible_labels_and_textual_statuses_are_present() -> None:
    """Provide labelled controls and non-color-only reviewer status text."""
    at = app()
    assert at.selectbox(key="scenario").label == "Scenario"
    assert at.checkbox(key="live_confirmation").label
    assert at.info and "Execution mode:" in at.info[0].proto.title


def test_24_subprocess_default_is_zero_network_with_ambient_shape() -> None:
    """Guard no-key import and deterministic actions against non-loopback sockets."""
    script = """
import socket
from reliability_safety_observability.console_presenter import ConsoleBoundary
from reliability_safety_observability.failure_lab import ScenarioKind
original = socket.socket.connect
def guard(sock, address):
    host = address[0]
    if host not in {'127.0.0.1', '::1'}:
        raise AssertionError('network')
    return original(sock, address)
socket.socket.connect = guard
console = ConsoleBoundary()
console.run_benchmark()
console.run_selected_lab(ScenarioKind.S01)
print('ok')
"""
    env = {**os.environ, "MODULE7_PROVIDER_API_KEY": "credential-shaped-value"}
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
