"""Real shared-plane acceptance and explicitly mocked boundary failures."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agents import Runner
from google.adk.runners import Runner as AdkRunner
from test_mcp_client import enterprise_api_url as enterprise_api_url
from test_mcp_client import mcp_endpoint as endpoint_fixture

from mcp_enterprise_integration.capability_policy import CapabilityPolicy
from mcp_enterprise_integration.database import CustomerRepository
from mcp_enterprise_integration.errors import AuthorizationError, ContractValidationError
from mcp_enterprise_integration.google_adk_mcp import GoogleAdkMcpIntegration
from mcp_enterprise_integration.internal_system import RequestedAction
from mcp_enterprise_integration.openai_mcp import OpenAiMcpIntegration
from mcp_enterprise_integration.workflow import EnterpriseWorkflow, WorkflowResult

mcp_endpoint = endpoint_fixture


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def forbid_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if orchestration attempts either model runner."""
    monkeypatch.setattr(Runner, "run", AsyncMock(side_effect=AssertionError("model forbidden")))
    monkeypatch.setattr(AdkRunner, "run_async", AsyncMock(
        side_effect=AssertionError("model forbidden"),
    ))


@pytest.mark.anyio
@pytest.mark.parametrize("role,decision", [("account_manager", "allow"), ("support_agent", "deny")])
async def test_shared_plane_workflow(mcp_endpoint: str, role: str, decision: str) -> None:
    result = await EnterpriseWorkflow(mcp_endpoint).run(
        customer_id="CUST-001", principal_role=role, action=RequestedAction.ACCOUNT_CHANGE,
    )
    assert result.customer.name == "Northstar Logistics"
    assert result.account.service_tier == "gold"
    assert result.account.customer_id == result.policy_request.customer_id
    assert result.policy_request.account_status == result.customer.account_status
    assert result.policy_result.decision == decision
    assert [stage.framework for stage in result.stages] == ["openai", "google_adk", "openai"]
    assert [stage.authorization.capability for stage in result.stages] == [
        "get_customer", "get_account_status", "evaluate_enterprise_policy",
    ]
    assert all(stage.authorization.allowed for stage in result.stages)
    assert all(stage.transport == "streamable_http" for stage in result.stages)
    assert all(stage.evidence.evidence_class == "local-integration" for stage in result.stages)
    assert not any(stage.evidence.live_provider_executed for stage in result.stages)
    assert WorkflowResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.anyio
@pytest.mark.parametrize("role,grants", [
    ("viewer", None),
    ("limited", {"limited": frozenset({"get_customer"})}),
    ("self_declared_admin", None),
])
async def test_authority_does_not_transfer(
    mcp_endpoint: str, role: str, grants: dict[str, frozenset[str]] | None,
) -> None:
    with pytest.raises(AuthorizationError):
        await EnterpriseWorkflow(mcp_endpoint, policy=CapabilityPolicy(grants)).run(
            customer_id="CUST-001", principal_role=role,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [
    {"result": None},
    {"result": {"customer_id": "CUST-001", "requester_role": "account_manager"}},
    {"result": {"customer_id": "OTHER", "name": "x", "region": "x", "segment": "x",
                "account_status": "active"}},
    {"result": {"customer_id": "CUST-001", "name": "x" * 9000}},
])
async def test_untrusted_customer_stops_before_adk(
    mcp_endpoint: str, monkeypatch: pytest.MonkeyPatch, payload: dict,
) -> None:
    original = OpenAiMcpIntegration.invoke_authorized_tool

    async def corrupt(self: OpenAiMcpIntegration, **kwargs: object) -> object:
        response = await original(self, **kwargs)
        response.structured_content.clear()
        response.structured_content.update(payload)
        return response

    monkeypatch.setattr(OpenAiMcpIntegration, "invoke_authorized_tool", corrupt)
    adk_call = AsyncMock(side_effect=AssertionError("unvalidated context reached ADK"))
    monkeypatch.setattr(GoogleAdkMcpIntegration, "invoke_authorized_tool", adk_call)
    with pytest.raises(ContractValidationError):
        await EnterpriseWorkflow(mcp_endpoint).run(
            customer_id="CUST-001", principal_role="account_manager",
        )
    adk_call.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", [{"customer_id": "OTHER"}, {"open_cases": -1},
                                     {"open_cases": "2"}, {"authority": "admin"}])
async def test_untrusted_account_context(
    mcp_endpoint: str, monkeypatch: pytest.MonkeyPatch, mutation: dict,
) -> None:
    original = GoogleAdkMcpIntegration.invoke_authorized_tool

    async def corrupt(self: GoogleAdkMcpIntegration, **kwargs: object) -> object:
        response = await original(self, **kwargs)
        response.structured_content.update(mutation)
        return response

    monkeypatch.setattr(GoogleAdkMcpIntegration, "invoke_authorized_tool", corrupt)
    with pytest.raises(ContractValidationError):
        await EnterpriseWorkflow(mcp_endpoint).run(
            customer_id="CUST-001", principal_role="account_manager",
        )


def test_reviewer_workflow_rejects_external_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        EnterpriseWorkflow("https://example.com/mcp")


@pytest.mark.anyio
async def test_direct_versus_mcp_comparison(mcp_endpoint: str, tmp_path: Path) -> None:
    """Same seeded data: direct repository coupling versus both SDKs over MCP."""
    repository = CustomerRepository(tmp_path / "direct-comparison.db")
    repository.initialize()
    direct = repository.get_customer("CUST-001")
    result = await EnterpriseWorkflow(mcp_endpoint).run(
        customer_id="CUST-001", principal_role="account_manager",
    )
    assert direct == result.customer
    # Direct access knows the repository implementation and has no MCP discovery.
    # Both workflow SDKs instead reach protocol capabilities at the shared endpoint.
    assert {stage.framework for stage in result.stages} == {"openai", "google_adk"}


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", [{"customer_id": "OTHER"}, {"action": "priority_support"},
                                     {"decision": "self_authorized"}, {"reason": 123}])
async def test_untrusted_policy_result(
    mcp_endpoint: str, monkeypatch: pytest.MonkeyPatch, mutation: dict,
) -> None:
    original = OpenAiMcpIntegration.invoke_authorized_tool

    async def corrupt(self: OpenAiMcpIntegration, **kwargs: object) -> object:
        response = await original(self, **kwargs)
        if kwargs["name"] == "evaluate_enterprise_policy":
            response.structured_content.update(mutation)
        return response

    monkeypatch.setattr(OpenAiMcpIntegration, "invoke_authorized_tool", corrupt)
    with pytest.raises(ContractValidationError):
        await EnterpriseWorkflow(mcp_endpoint).run(
            customer_id="CUST-001", principal_role="account_manager",
        )


@pytest.mark.anyio
async def test_invalid_input_never_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = AsyncMock(side_effect=AssertionError("invalid input connected"))
    monkeypatch.setattr(OpenAiMcpIntegration, "__aenter__", connect)
    with pytest.raises(ContractValidationError):
        await EnterpriseWorkflow("http://127.0.0.1:1/mcp").run(
            customer_id="x" * 65, principal_role="account_manager",
        )
    connect.assert_not_awaited()
