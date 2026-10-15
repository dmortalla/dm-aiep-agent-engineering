"""Real reviewer execution and safe presentation failure verification."""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agents import Runner
from google.adk.runners import Runner as AdkRunner
from streamlit.testing.v1 import AppTest

from mcp_enterprise_integration import reviewer
from mcp_enterprise_integration.database import CustomerRecord
from mcp_enterprise_integration.errors import EnterpriseIntegrationError
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


def test_reviewer_logs_safe_backend_exception_type(monkeypatch, caplog) -> None:
    """Log only the backend exception class while preserving the safe reviewer error."""
    from mcp_enterprise_integration import reviewer
    from mcp_enterprise_integration.errors import EnterpriseIntegrationError

    def fail_execute(*args, **kwargs):
        raise EnterpriseIntegrationError("sensitive backend detail")

    monkeypatch.setattr(reviewer.asyncio, "run", fail_execute)
    with caplog.at_level("ERROR", logger=reviewer.__name__):
        try:
            reviewer.run_reviewer_demo("Manager review")
        except reviewer.ReviewerError as exc:
            assert str(exc) == (
                "Backend execution failed. Retry or ask the maintainer to inspect it."
            )
        else:
            raise AssertionError("Expected ReviewerError")

    assert "Module 8 reviewer backend failed: EnterpriseIntegrationError" in caplog.text
    assert "sensitive backend detail" not in caplog.text


@pytest.fixture
def preflight_seam(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Mock transport only; retain strict customer validation and real denial policy."""
    customer = CustomerRecord(
        customer_id="CUST-001", name="private customer record", region="private region",
        segment="private segment", account_status="active",
    )
    seam = SimpleNamespace(
        failure_stage=None, failure=None, customer=customer,
        endpoint="http://127.0.0.1:54321/mcp", connection=object(),
        capabilities=("get_customer", "evaluate_enterprise_policy"),
    )

    async def discover() -> tuple[str, ...]:
        if seam.failure_stage == "mcp_discovery":
            raise seam.failure
        return seam.capabilities

    async def invoke(
        *, principal_role: str, name: str, arguments: dict, policy: reviewer.CapabilityPolicy,
    ) -> tuple[reviewer.CapabilityAuthorization, dict[str, object]]:
        stage = "viewer_customer" if name == "get_customer" else "viewer_policy_denial"
        if seam.failure_stage == stage:
            raise seam.failure
        authorization = policy.authorize(
            principal_role=principal_role, capability=name,
            discovered_capabilities=seam.capabilities,
        )  # The expected policy denial is genuine application-owned behavior.
        return authorization, {"result": customer.model_dump()}

    session = SimpleNamespace(
        discover_tools=discover, invoke_authorized_tool=invoke, connection_info=seam.connection,
    )

    @asynccontextmanager
    async def connect() -> AsyncIterator[SimpleNamespace]:
        if seam.failure_stage == "mcp_connect":
            raise seam.failure
        yield session
        if seam.failure_stage == "cleanup":
            raise seam.failure

    monkeypatch.setattr(
        reviewer, "EnterpriseMcpClient", lambda endpoint: SimpleNamespace(connect=connect),
    )
    monkeypatch.setattr(reviewer, "_local_plane", lambda database: nullcontext(seam.endpoint))
    monkeypatch.setattr(reviewer.CustomerRepository, "get_customer", lambda *args: customer)
    seam.workflow = AsyncMock(return_value=SimpleNamespace(customer=customer))
    monkeypatch.setattr(
        reviewer, "EnterpriseWorkflow", lambda endpoint: SimpleNamespace(run=seam.workflow),
    )
    return seam


@pytest.mark.parametrize("through_reviewer", [False, True])
@pytest.mark.parametrize("stage", [
    "mcp_connect", "mcp_discovery", "viewer_customer", "viewer_policy_denial",
])
def test_preflight_failure_logs_only_fixed_stage(
    preflight_seam: SimpleNamespace, caplog: pytest.LogCaptureFixture,
    stage: str, through_reviewer: bool,
) -> None:
    """Attribute entry and operation failures without disclosing untrusted diagnostics."""
    seam = preflight_seam
    failure = EnterpriseIntegrationError(
        "secret message /private/files Traceback injected", {"payload": "private MCP output",
        "customer": seam.customer.model_dump(), "endpoint": seam.endpoint},
    )
    seam.failure_stage, seam.failure = stage, failure
    with caplog.at_level("ERROR", logger=reviewer.__name__):
        if through_reviewer:
            with pytest.raises(reviewer.ReviewerError) as caught:
                reviewer.run_reviewer_demo()
            assert str(caught.value) == (
                "Backend execution failed. Retry or ask the maintainer to inspect it."
            )
            assert caught.value.__cause__ is failure
        else:
            with pytest.raises(EnterpriseIntegrationError) as caught:
                asyncio.run(reviewer._execute(seam.endpoint, Path("unused.db"), "Manager review"))
            assert caught.value is failure
    records = [record for record in caplog.records if record.name == reviewer.__name__]
    expected = [f"Module 8 reviewer preflight backend failed: {stage}"]
    if through_reviewer:
        expected.append("Module 8 reviewer backend failed: EnterpriseIntegrationError")
    assert [record.getMessage() for record in records] == expected
    assert records[0].args == (stage,)
    assert all(record.exc_info is None and record.stack_info is None for record in records)
    for sensitive in ("secret message", "/private/files", "Traceback", "private MCP output",
                      "CUST-001", "private customer record", "private region", "private segment",
                      seam.endpoint, "54321", "unused.db"):
        assert sensitive not in caplog.text
    seam.workflow.assert_not_awaited()


def test_preflight_client_construction_failure_is_connect(
    preflight_seam: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fixed stage precedes client construction as well as async context entry."""
    failure = EnterpriseIntegrationError("sensitive initialization detail")

    def fail(endpoint: str) -> None:
        raise failure

    monkeypatch.setattr(reviewer, "EnterpriseMcpClient", fail)
    with caplog.at_level("ERROR"), pytest.raises(EnterpriseIntegrationError) as caught:
        asyncio.run(reviewer._execute(preflight_seam.endpoint, Path("unused.db"), "Manager review"))
    assert caught.value is failure
    assert [record.getMessage() for record in caplog.records] == [
        "Module 8 reviewer preflight backend failed: mcp_connect",
    ]


def test_expected_denial_is_success_without_failure_diagnostic(
    preflight_seam: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    """Mocked transport success preserves reviewer results and evidence classification."""
    with caplog.at_level("ERROR"):
        result = reviewer.run_reviewer_demo()
    assert result.denied and result.allowed.allowed
    assert result.customer == result.direct_customer == result.workflow.customer
    assert result.connection is preflight_seam.connection
    assert result.capabilities == preflight_seam.capabilities
    assert result.discovery_evidence.evidence_class == "local-integration"
    assert not result.discovery_evidence.live_provider_executed
    assert not result.discovery_evidence.deployment_executed
    assert not caplog.records
    preflight_seam.workflow.assert_awaited_once()


@pytest.mark.parametrize("through_reviewer", [False, True])
@pytest.mark.parametrize("outside", ["cleanup", "workflow"])
def test_completed_preflight_attributes_cleanup_only(
    preflight_seam: SimpleNamespace, caplog: pytest.LogCaptureFixture, outside: str,
    through_reviewer: bool,
) -> None:
    """Attribute context exit to cleanup; release preflight ownership before workflow."""
    failure = EnterpriseIntegrationError(
        "secret message /private/files Traceback injected",
        {"payload": "private MCP output", "customer": preflight_seam.customer.model_dump(),
         "endpoint": preflight_seam.endpoint},
    )
    if outside == "cleanup":
        preflight_seam.failure_stage, preflight_seam.failure = outside, failure
    else:
        preflight_seam.workflow.side_effect = failure
    with caplog.at_level("ERROR"):
        if through_reviewer:
            with pytest.raises(reviewer.ReviewerError) as caught:
                reviewer.run_reviewer_demo()
            assert str(caught.value) == (
                "Backend execution failed. Retry or ask the maintainer to inspect it."
            )
            assert caught.value.__cause__ is failure
        else:
            with pytest.raises(EnterpriseIntegrationError) as caught:
                asyncio.run(reviewer._execute(
                    preflight_seam.endpoint, Path("unused.db"), "Manager review",
                ))
            assert caught.value is failure
    expected = []
    if outside == "cleanup":
        expected.append("Module 8 reviewer preflight backend failed: mcp_cleanup")
        preflight_seam.workflow.assert_not_awaited()
    else:
        preflight_seam.workflow.assert_awaited_once()
    if through_reviewer:
        expected.append("Module 8 reviewer backend failed: EnterpriseIntegrationError")
    assert [record.getMessage() for record in caplog.records] == expected
    if outside == "cleanup":
        assert caplog.records[0].args == ("mcp_cleanup",)
    assert all(record.exc_info is None and record.stack_info is None for record in caplog.records)
    for sensitive in ("secret message", "/private/files", "Traceback", "private MCP output",
                      "CUST-001", "private customer record", "private region", "private segment",
                      preflight_seam.endpoint, "54321", "unused.db"):
        assert sensitive not in caplog.text
