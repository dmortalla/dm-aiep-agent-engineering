"""Real reviewer execution and safe presentation failure verification."""

import socket
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agents import Runner
from google.adk.runners import Runner as AdkRunner
from streamlit.testing.v1 import AppTest

from mcp_enterprise_integration import reviewer
from mcp_enterprise_integration.mcp_client import EnterpriseMcpSession


@pytest.fixture(autouse=True)
def no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent either SDK model runner from being used."""
    monkeypatch.setattr(Runner, "run", AsyncMock(side_effect=AssertionError("model forbidden")))
    monkeypatch.setattr(
        AdkRunner,
        "run_async",
        AsyncMock(
            side_effect=AssertionError("model forbidden"),
        ),
    )

    original_connect = socket.socket.connect

    def local_only(self: socket.socket, address: tuple) -> None:
        if address[0] not in {"127.0.0.1", "::1"}:
            raise AssertionError("external provider/network connection forbidden")
        return original_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.mark.parametrize(
    "scenario,decision",
    [
        ("Manager review", "allow"),
        ("Support review", "deny"),
    ],
)
def test_real_reviewer_console(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    decision: str,
) -> None:
    """Run real services through UI, including discovery and no unauthorized invocation."""
    invoked: list[str] = []
    original = EnterpriseMcpSession.invoke_tool

    async def track(self: EnterpriseMcpSession, name: str, arguments: dict) -> dict:
        invoked.append(name)
        return await original(self, name, arguments)

    monkeypatch.setattr(EnterpriseMcpSession, "invoke_tool", track)
    path = Path(reviewer.__file__).with_name("console.py")
    app = AppTest.from_file(str(path), default_timeout=90).run()
    assert not app.exception
    assert "reviewer_result" not in app.session_state
    app.selectbox[0].select(scenario)
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    result = app.session_state["reviewer_result"]
    assert result.connection.protocol_version
    assert set(result.capabilities) == {
        "get_customer",
        "get_account_status",
        "evaluate_enterprise_policy",
    }
    assert invoked == ["get_customer"]  # denied request never reaches remote invocation
    assert result.allowed.allowed and result.denied
    assert result.customer == result.direct_customer == result.workflow.customer
    assert result.workflow.policy_result.decision == decision
    assert [stage.framework.value for stage in result.workflow.stages] == [
        "openai",
        "google_adk",
        "openai",
    ]
    assert all(
        stage.evidence.evidence_class == "local-integration"
        and not stage.evidence.live_provider_executed
        and not stage.evidence.deployment_executed
        for stage in result.workflow.stages
    )
    assert result.discovery_evidence.evidence_class == "local-integration"
    assert len(app.dataframe) == 8
    assert "denied" in app.warning[0].value
    assert any("does not establish" in element.value for element in app.markdown)
    assert app.metric[2].value == "0"


def test_invalid_scenario_never_starts_services(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("invalid input started services")

    monkeypatch.setattr(reviewer, "_local_plane", forbidden)
    with pytest.raises(reviewer.ReviewerError, match="Choose"):
        reviewer.run_reviewer_demo("self_declared_admin")


def test_failure_clears_stale_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocked failure injection: render a safe error, never a stale success."""

    def failed(*args: object) -> None:
        raise reviewer.ReviewerError("Backend unavailable. Retry the demonstration.")

    monkeypatch.setattr(reviewer, "run_reviewer_demo", failed)
    app = AppTest.from_file(
        str(Path(reviewer.__file__).with_name("console.py")), default_timeout=30
    ).run()
    app.session_state["reviewer_result"] = "stale result"
    app.session_state["reviewer_scenario"] = "Manager review"
    app.button[0].click().run()
    assert not app.exception
    assert app.error[0].value == "Backend unavailable. Retry the demonstration."
    assert not app.success
    assert "reviewer_result" not in app.session_state


def test_unexpected_failure_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> None:
        raise RuntimeError("secret /private/filesystem")

    monkeypatch.setattr(reviewer, "_local_plane", broken)
    with pytest.raises(reviewer.ReviewerError) as caught:
        reviewer.run_reviewer_demo()
    assert "secret" not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_busy_console_rejects_without_startup() -> None:
    """Bound concurrent demonstrations without queueing more service work."""
    assert reviewer._DEMO_SLOTS.acquire(blocking=False)
    assert reviewer._DEMO_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(reviewer.ReviewerError, match="already running"):
            reviewer.run_reviewer_demo()
    finally:
        reviewer._DEMO_SLOTS.release()
        reviewer._DEMO_SLOTS.release()
