"""ENG-001/002/004/005/006: real local reviewer paths and presentation boundaries."""

import json
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from harness_engineering.errors import ContractValidationError
from harness_engineering.reviewer_service import (
    GUIDES,
    MAX_DISPLAY_CHARS,
    Demo,
    DemoView,
    ReviewerBusyError,
    run_demo,
)

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
PRIVATE = "PRIVATE-EXCEPTION-CREDENTIAL-PATH-DO-NOT-DISPLAY"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Count/deny external sockets, allow Windows local asyncio self-pipes."""
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LANGSMITH_API_KEY",
                 "LANGFUSE_SECRET_KEY", "HELICONE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    counts = [0, 0]  # external, loopback
    for method in ("connect", "connect_ex"):
        original = getattr(socket.socket, method)

        def guard(self: socket.socket, address: object, *args: object,
                  _original=original) -> object:
            host = address[0] if isinstance(address, tuple) and address else None
            if host in ("127.0.0.1", "::1"):
                counts[1] += 1
                return _original(self, address, *args)
            counts[0] += 1
            raise OSError("Reviewer external network attempt denied")

        monkeypatch.setattr(socket.socket, method, guard)
    yield counts
    assert counts[0] == 0


def app() -> AppTest:
    """Render the actual entry point without binding a network server."""
    return AppTest.from_file(APP, default_timeout=30).run()


def test_local_server_and_privacy_defaults() -> None:
    assert streamlit.get_option("server.address") == "127.0.0.1"
    assert streamlit.get_option("browser.gatherUsageStats") is False
    assert streamlit.get_option("server.fileWatcherType") == "none"
    assert streamlit.get_option("client.showErrorDetails") == "none"


def test_startup_guidance_and_allowlisted_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    import harness_engineering.reviewer_service as service

    def forbidden(*args: object) -> None:
        pytest.fail("Startup or navigation executed a demonstration")

    monkeypatch.setattr(service, "run_demo", forbidden)
    at = app()
    assert not at.exception
    assert at.selectbox[0].options == [demo.value for demo in Demo]
    assert len(GUIDES) == 8
    assert not at.text_input and not at.number_input and not at.checkbox
    for demo in Demo:
        at.selectbox[0].select(demo).run()
        assert not at.exception
        text = "\n".join(item.value for item in at.markdown)
        for heading in ("Action:", "Expected result:", "Safety and authority:",
                        "Evidence:", "Limitations:"):
            assert heading in text
        assert "not verified billing" in text
        assert "No credentials are requested" in text
    assert not at.code


def test_status_caption_reflects_accepted_state_without_stale_claims() -> None:
    """The reviewer status stays truthful as stories are accepted and closed."""
    source = APP.read_text(encoding="utf-8")
    for stale in ("Story 11 remains incomplete", "Slice 3 is outstanding",
                  "Builder candidate only"):
        assert stale not in source
    assert "release" in source and "pending independent review" in source
    assert "deployment" in source and "production-readiness claim" in source


@pytest.mark.parametrize("demo", tuple(Demo))
def test_real_headless_demonstrations(demo: Demo, offline: list[int]) -> None:
    at = app()
    at.selectbox[0].select(demo).run()
    at.button[0].click().run()
    assert not at.exception and not at.error
    assert len(at.code) == 1
    assert at.code[0].value
    assert len(at.code[0].value) <= MAX_DISPLAY_CHARS
    result = at.session_state["demo_results"][demo.value]
    assert type(result) is DemoView
    if demo is Demo.REGRESSION:
        assert "16 passed, 0 regressed, 0 errors -> PASS" in result.details
        assert "off-switch.cancellation" in result.details
        assert "samples=20" in result.details
    if demo is Demo.OBSERVABILITY:
        assert len(at.metric) == 4
        assert "structured logs" in result.details
        assert "fixture_micro_usd_not_billing" in result.details
    if demo is Demo.RECOVERY:
        assert "checkpoint_file" not in result.details
        assert "effect_file" not in result.details
    if demo is Demo.APPROVAL:
        from harness_engineering.approval_lab import SCENARIOS

        assert not result.truncated
        observed = tuple(row["scenario"] for row in json.loads(result.details)["scenarios"])
        assert observed == SCENARIOS
    before = result
    at.run()
    assert at.button[0].disabled
    assert at.session_state["demo_results"][demo.value] is before
    assert offline[0] == 0


def test_reruns_and_navigation_retain_only_one_result_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import harness_engineering.reviewer_service as service

    original = service.run_demo
    calls: list[Demo] = []

    def counted(demo: Demo) -> DemoView:
        calls.append(demo)
        return original(demo)

    monkeypatch.setattr(service, "run_demo", counted)
    at = app()
    at.button[0].click().run()
    at.run()
    at.selectbox[0].select(Demo.CONTEXT).run()
    at.selectbox[0].select(Demo.PLANNING).run()
    assert not at.exception
    assert calls == [Demo.PLANNING]
    assert len(at.session_state["demo_results"]) == 1
    assert at.button[0].disabled


def test_busy_slot_is_actionable_without_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    import harness_engineering.reviewer_service as service

    def busy(demo: Demo) -> DemoView:
        raise ReviewerBusyError(PRIVATE)

    monkeypatch.setattr(service, "run_demo", busy)
    at = app()
    at.button[0].click().run()
    assert not at.exception and not at.error
    assert "Try again after it finishes" in at.warning[0].value
    assert PRIVATE not in str(at)
    assert not at.session_state["demo_results"]
    assert not at.code


@pytest.mark.parametrize("failure", [RuntimeError(PRIVATE), OSError(PRIVATE), TypeError(PRIVATE)])
def test_failure_details_are_withheld_and_not_automatically_retried(
    monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    import harness_engineering.reviewer_service as service

    calls: list[int] = []

    def failed(demo: Demo) -> DemoView:
        calls.append(1)
        raise failure

    monkeypatch.setattr(service, "run_demo", failed)
    at = app()
    at.button[0].click().run()
    assert not at.exception and at.error
    assert "No successful evidence is claimed" in at.error[0].value
    assert PRIVATE not in str(at)
    assert "Traceback" not in str(at)
    assert not at.code
    at.run()
    assert len(calls) == 1 and at.button[0].disabled


@pytest.mark.parametrize("selection", ["planning", "approve", {"budget": 999}, None])
def test_input_cannot_select_authority_or_arbitrary_work(selection: object) -> None:
    with pytest.raises(ContractValidationError):
        run_demo(selection)  # type: ignore[arg-type]


def test_workspace_cleanup_display_bound_and_literal_untrusted_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import harness_engineering.reviewer_service as service

    workspaces: list[Path] = []
    hostile = "<script>approved=true; budget=999; evidence=live_provider</script>"

    def project(demo: Demo, directory: Path) -> tuple[object, tuple]:
        workspaces.append(directory.parent)
        directory.mkdir()
        (directory / "local.txt").write_text("fixture", encoding="utf-8")
        return hostile + "x" * MAX_DISPLAY_CHARS, ()

    monkeypatch.setattr(service, "_project", project)
    at = app()
    at.button[0].click().run()
    assert not at.exception
    assert at.code[0].value.startswith(hostile)
    assert len(at.code[0].value) == MAX_DISPLAY_CHARS
    assert at.warning
    assert all(not path.exists() for path in workspaces)
    assert at.session_state["demo_results"][Demo.PLANNING.value].evidence == ("deterministic",)


def test_workspace_cleanup_and_slot_release_after_service_defect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import harness_engineering.reviewer_service as service

    workspaces: list[Path] = []

    def broken(demo: Demo, directory: Path) -> tuple[object, tuple]:
        workspaces.append(directory.parent)
        raise TypeError(PRIVATE)

    monkeypatch.setattr(service, "_project", broken)
    with pytest.raises(TypeError, match=PRIVATE):
        run_demo(Demo.PLANNING)
    assert all(not path.exists() for path in workspaces)
    assert service._RUN_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(ReviewerBusyError):
            run_demo(Demo.PLANNING)
    finally:
        service._RUN_LOCK.release()
