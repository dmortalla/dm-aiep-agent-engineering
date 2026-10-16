"""Explicit application orchestration across independent SDK MCP consumers."""

import asyncio
import json
import logging
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from mcp_enterprise_integration.capability_policy import CapabilityAuthorization, CapabilityPolicy
from mcp_enterprise_integration.database import CustomerRecord
from mcp_enterprise_integration.domain import ClientFramework, TransportKind
from mcp_enterprise_integration.enterprise_api import AccountStatus
from mcp_enterprise_integration.errors import (
    AuthorizationError,
    ContractValidationError,
    EnterpriseIntegrationError,
)
from mcp_enterprise_integration.evidence import EvidenceClass, ExecutionEvidence
from mcp_enterprise_integration.google_adk_mcp import GoogleAdkMcpIntegration
from mcp_enterprise_integration.internal_system import (
    PolicyDecision,
    PolicyRequest,
    PolicyResult,
    RequestedAction,
)
from mcp_enterprise_integration.openai_mcp import OpenAiMcpIntegration

_LOGGER = logging.getLogger(__name__)


def _validated[Model: BaseModel](model: type[Model], data: Any) -> Model:
    """Validate bounded untrusted data without exposing its contents in errors."""
    try:
        if len(json.dumps(data, allow_nan=False).encode("utf-8")) > 8192:
            raise ValueError("oversized context")
        result = model.model_validate(data, strict=True)
        for value in result.model_dump().values():
            if isinstance(value, str) and (not value.strip() or len(value) > 500):
                raise ValueError("invalid context string")
        return result
    except (ValidationError, ValueError, TypeError) as exc:
        raise ContractValidationError(f"Invalid {model.__name__} workflow context.") from exc


class _CustomerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result: CustomerRecord


class WorkflowStage(BaseModel):
    """Actual invocation evidence, separate from the enterprise action decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    framework: ClientFramework
    transport: Literal[TransportKind.STREAMABLE_HTTP] = TransportKind.STREAMABLE_HTTP
    authorization: CapabilityAuthorization
    evidence: ExecutionEvidence


class WorkflowResult(BaseModel):
    """Validated read-only workflow results for a later reviewer presentation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    customer: CustomerRecord
    account: AccountStatus
    policy_request: PolicyRequest
    policy_result: PolicyResult
    stages: tuple[WorkflowStage, WorkflowStage, WorkflowStage]


class EnterpriseWorkflow:
    """Coordinate three MCP invocations without executing either agent's model.

    This local reviewer path accepts only loopback endpoints. Authentication is
    the calling application's responsibility; roles never come from MCP data.
    Policy evaluation is read-only and does not execute the requested action.
    """

    def __init__(self, endpoint: str, *, policy: CapabilityPolicy | None = None) -> None:
        """Configure the shared plane and application-owned capability policy.

        Args:
            endpoint: Loopback Streamable HTTP server URL without credentials.
            policy: Application-owned grants used independently by both SDKs.
        """
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Workflow requires a credential-free loopback HTTP MCP endpoint.")
        self._endpoint = endpoint
        self._policy = policy if policy is not None else CapabilityPolicy()

    async def run(
        self,
        *,
        customer_id: str,
        principal_role: str,
        action: RequestedAction = RequestedAction.VIEW_ACCOUNT,
    ) -> WorkflowResult:
        """Run bounded customer -> account -> policy context exchange.

        Args:
            customer_id: Untrusted business identifier, never an authority source.
            principal_role: Role supplied by the authenticated application.
            action: Read-only policy question; no consequential action executes.

        Returns:
            Validated enterprise results and local integration evidence.

        Raises:
            ContractValidationError: If input or cross-stage data is invalid.
            AuthorizationError: If any independent capability check denies access.
            EnterpriseIntegrationError: If transport fails or the deadline expires.
        """
        # Reuse the bounded policy contract to validate input before connecting.
        request = _validated(
            PolicyRequest,
            {
                "customer_id": customer_id,
                "requester_role": principal_role,
                "action": action,
                "account_status": "pending",
            },
        )
        try:
            async with asyncio.timeout(45.0):
                return await self._run(request)
        except TimeoutError as exc:
            raise EnterpriseIntegrationError(
                "Enterprise workflow exceeded its 45s deadline."
            ) from exc

    async def _run(self, request: PolicyRequest) -> WorkflowResult:
        stages: list[WorkflowStage] = []
        stage = "openai_customer"
        try:
            # Sequential SDK lifecycles preserve SDK-owned task/session cleanup.
            async with OpenAiMcpIntegration(self._endpoint, policy=self._policy) as sdk:
                response = await sdk.invoke_authorized_tool(
                    principal_role=request.requester_role,
                    name="get_customer",
                    arguments={"customer_id": request.customer_id},
                )
                envelope = _validated(_CustomerEnvelope, response.structured_content)
                customer = _validated(CustomerRecord, envelope.result.model_dump())
                if customer.customer_id != request.customer_id:
                    raise ContractValidationError(
                        "Customer result does not match workflow identity."
                    )
                stages.append(self._stage(ClientFramework.OPENAI, response.authorization))

            stage = "google_adk_account"
            async with GoogleAdkMcpIntegration(self._endpoint, policy=self._policy) as sdk:
                try:
                    response = await sdk.invoke_authorized_tool(
                        principal_role=request.requester_role,
                        name="get_account_status",
                        arguments={"customer_id": customer.customer_id},
                    )
                except AuthorizationError:
                    _LOGGER.error(
                        "Module 8 workflow backend failed: google_adk_account_authorization"
                    )
                    raise
                try:
                    account = _validated(AccountStatus, response.structured_content)
                except Exception:
                    _LOGGER.error("Module 8 workflow backend failed: google_adk_account_validation")
                    raise
                try:
                    if (
                        account.customer_id != customer.customer_id
                        or not 0 <= account.open_cases <= 10000
                    ):
                        raise ContractValidationError(
                            "Account result violates workflow identity or bounds."
                        )
                    stages.append(self._stage(ClientFramework.GOOGLE_ADK, response.authorization))
                except Exception:
                    _LOGGER.error("Module 8 workflow backend failed: google_adk_account_invariants")
                    raise

            stage = "openai_policy"
            context = _validated(
                PolicyRequest,
                {
                    "customer_id": account.customer_id,
                    "requester_role": request.requester_role,
                    "action": request.action,
                    "account_status": customer.account_status,
                },
            )
            async with OpenAiMcpIntegration(self._endpoint, policy=self._policy) as sdk:
                response = await sdk.invoke_authorized_tool(
                    principal_role=request.requester_role,
                    name="evaluate_enterprise_policy",
                    arguments=context.model_dump(mode="json"),
                )
                # Decode only the two declared enum fields; do not coerce other data.
                try:
                    decoded = dict(response.structured_content)
                    decoded["action"] = RequestedAction(decoded["action"])
                    decoded["decision"] = PolicyDecision(decoded["decision"])
                except (KeyError, ValueError, TypeError) as exc:
                    raise ContractValidationError("Invalid PolicyResult workflow context.") from exc
                decision = _validated(PolicyResult, decoded)
                if (
                    decision.customer_id != customer.customer_id
                    or decision.action != request.action
                ):
                    raise ContractValidationError("Policy result does not match workflow context.")
                stages.append(self._stage(ClientFramework.OPENAI, response.authorization))

        except EnterpriseIntegrationError:
            # Stage comes only from sequential application control flow.
            _LOGGER.error("Module 8 workflow backend failed: %s", stage)
            raise

        return WorkflowResult(
            customer=customer,
            account=account,
            policy_request=context,
            policy_result=decision,
            stages=tuple(stages),
        )

    @staticmethod
    def _stage(
        framework: ClientFramework,
        authorization: CapabilityAuthorization,
    ) -> WorkflowStage:
        return WorkflowStage(
            framework=framework,
            authorization=authorization,
            evidence=ExecutionEvidence(
                evidence_id=f"{framework}-{authorization.capability}",
                evidence_class=EvidenceClass.LOCAL_INTEGRATION,
                capability_id=authorization.capability,
                summary="Authorized MCP invocation over loopback HTTP; validated result; no model.",
            ),
        )
