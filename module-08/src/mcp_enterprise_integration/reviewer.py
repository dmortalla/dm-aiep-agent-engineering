"""Bounded local reviewer execution over the accepted enterprise backend."""

import asyncio
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import uvicorn

from mcp_enterprise_integration.capability_policy import CapabilityAuthorization, CapabilityPolicy
from mcp_enterprise_integration.database import CustomerRecord, CustomerRepository
from mcp_enterprise_integration.errors import (
    AuthorizationError,
    ConfigurationError,
    EnterpriseIntegrationError,
)
from mcp_enterprise_integration.evidence import EvidenceClass, ExecutionEvidence
from mcp_enterprise_integration.internal_system import RequestedAction
from mcp_enterprise_integration.live_provider import (
    LiveConsent,
    LiveProviderError,
    LiveProviderSelection,
    LiveProviderWorkflow,
    LiveWorkflowResult,
)
from mcp_enterprise_integration.mcp_client import EnterpriseMcpClient, McpConnectionInfo
from mcp_enterprise_integration.mcp_server import create_enterprise_mcp_server
from mcp_enterprise_integration.workflow import EnterpriseWorkflow, WorkflowResult

_LOGGER = logging.getLogger(__name__)
_DEMO_SLOTS = threading.BoundedSemaphore(2)
# One live run per process: provider spend never multiplies through concurrency.
_LIVE_SLOTS = threading.BoundedSemaphore(1)
_SCENARIO_ROLES = {"Manager review": "account_manager", "Support review": "support_agent"}


class ReviewerError(Exception):
    """Safe actionable error suitable for an ordinary reviewer."""


@dataclass(frozen=True)
class ReviewerResult:
    """Actual discovery, authorization, comparison and workflow evidence."""

    connection: McpConnectionInfo
    capabilities: tuple[str, ...]
    allowed: CapabilityAuthorization
    denied: bool
    customer: CustomerRecord
    direct_customer: CustomerRecord
    workflow: WorkflowResult
    discovery_evidence: ExecutionEvidence


class _FixtureApi(BaseHTTPRequestHandler):
    """Deterministic enterprise HTTP fixture; not an external provider."""

    def do_GET(self) -> None:
        if self.path != "/accounts/CUST-001":
            self.send_error(404)
            return
        payload = json.dumps(
            {
                "customer_id": "CUST-001",
                "service_tier": "gold",
                "risk_status": "low",
                "open_cases": 2,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress fixture request logs."""


@contextmanager
def _local_plane(database: Path) -> Iterator[str]:
    """Start isolated loopback services and stop them after one demonstration."""
    api = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureApi)
    api_thread = threading.Thread(target=api.serve_forever, daemon=True)
    api_thread.start()
    runtime = None
    thread = None
    try:
        server = create_enterprise_mcp_server(
            database_path=database,
            enterprise_api_url=f"http://127.0.0.1:{api.server_port}",
        )
        app = server.streamable_http_app(
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
            host="127.0.0.1",
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            runtime = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
            thread = threading.Thread(
                target=runtime.run,
                kwargs={"sockets": [listener]},
                daemon=True,
            )
            thread.start()
            deadline = time.monotonic() + 5
            while not runtime.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not runtime.started:
                raise ReviewerError("Local services could not start. Retry the demonstration.")
            try:
                yield f"http://127.0.0.1:{port}/mcp"
            finally:
                runtime.should_exit = True
                thread.join(timeout=5)
                if thread.is_alive():
                    runtime.force_exit = True
                    thread.join(timeout=2)
                    raise ReviewerError("Local service cleanup failed. Restart the console.")
    finally:
        if runtime is not None:
            runtime.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        api.shutdown()
        api.server_close()
        api_thread.join(timeout=2)


async def _execute(endpoint: str, database: Path, scenario: str) -> ReviewerResult:
    policy = CapabilityPolicy()
    async with asyncio.timeout(60):
        stage: str | None = "mcp_connect"
        try:
            async with EnterpriseMcpClient(endpoint).connect() as session:
                stage = "mcp_discovery"
                capabilities = await session.discover_tools()
                connection = session.connection_info
                stage = "viewer_customer"
                allowed, payload = await session.invoke_authorized_tool(
                    principal_role="viewer",
                    name="get_customer",
                    arguments={"customer_id": "CUST-001"},
                    policy=policy,
                )
                customer = CustomerRecord.model_validate(payload["result"], strict=True)
                stage = "viewer_policy_denial"
                denied = False
                try:
                    await session.invoke_authorized_tool(
                        principal_role="viewer",
                        name="evaluate_enterprise_policy",
                        arguments={
                            "customer_id": "CUST-001",
                            "requester_role": "viewer",
                            "action": "view_account",
                            "account_status": "active",
                        },
                        policy=policy,
                    )
                except AuthorizationError:
                    denied = True
                if not denied:
                    raise ReviewerError("Expected authorization denial was absent. Stop review.")
                stage = "mcp_cleanup"
            stage = None  # Preflight ownership ends only after successful context exit.
        except EnterpriseIntegrationError:
            if stage is not None:
                _LOGGER.error("Module 8 reviewer preflight backend failed: %s", stage)
            raise
        role = "account_manager" if scenario == "Manager review" else "support_agent"
        workflow = await EnterpriseWorkflow(endpoint).run(
            customer_id="CUST-001",
            principal_role=role,
            action=RequestedAction.ACCOUNT_CHANGE,
        )
        direct = CustomerRepository(database).get_customer("CUST-001")
        if direct is None or direct != customer or customer != workflow.customer:
            raise ReviewerError("Customer comparison failed. Stop review and inspect the backend.")
        return ReviewerResult(
            connection,
            capabilities,
            allowed,
            denied,
            customer,
            direct,
            workflow,
            ExecutionEvidence(
                evidence_id="reviewer-discovery",
                capability_id="mcp-discovery",
                evidence_class=EvidenceClass.LOCAL_INTEGRATION,
                summary="Real loopback MCP initialization and capability discovery; no model.",
            ),
        )


def run_reviewer_demo(scenario: str = "Manager review") -> ReviewerResult:
    """Execute one isolated, key-free demonstration with application-owned identities.

    Args:
        scenario: One of two fixed demonstration scenarios; not authentication.

    Returns:
        Actual backend results and local-integration evidence.

    Raises:
        ReviewerError: If input, execution, validation or cleanup fails safely.
    """
    if scenario not in {"Manager review", "Support review"}:
        raise ReviewerError("Choose Manager review or Support review.")
    if not _DEMO_SLOTS.acquire(blocking=False):
        raise ReviewerError("Two demonstrations are already running. Retry when one finishes.")
    try:
        with TemporaryDirectory(prefix="module08-reviewer-") as directory:
            database = Path(directory) / "customers.db"
            with _local_plane(database) as endpoint:
                return asyncio.run(_execute(endpoint, database, scenario))
    except ReviewerError:
        raise
    except EnterpriseIntegrationError as exc:
        _LOGGER.error(
            "Module 8 reviewer backend failed: %s",
            type(exc).__name__,
        )
        raise ReviewerError(
            "Backend execution failed. Retry or ask the maintainer to inspect it."
        ) from exc
    except Exception as exc:
        # Last application boundary: never render underlying exception text or traceback.
        raise ReviewerError(
            "Demonstration failed safely. Ask the maintainer to inspect it."
        ) from exc
    finally:
        _DEMO_SLOTS.release()


@dataclass(frozen=True)
class LiveReviewerResult:
    """Credential-free results of one explicitly consented live-provider run."""

    scenario: str
    workflow: LiveWorkflowResult


def run_live_provider_demo(
    scenario: str,
    *,
    consent: LiveConsent,
    openai: LiveProviderSelection | None,
    google_adk: LiveProviderSelection | None,
) -> LiveReviewerResult:
    """Execute one opt-in live-provider demonstration over fresh local services.

    Consent and provider selection are checked before any service starts or any
    provider is contacted. Credentials are used only inside this call and are
    never returned, stored, logged or placed in evidence.

    Args:
        scenario: One of the two fixed demonstration scenarios; not authentication.
        consent: Explicit acknowledgements of external calls and possible charges.
        openai: Explicit OpenAI selection with an ephemeral key, or None.
        google_adk: Explicit Gemini selection with an ephemeral key, or None.

    Returns:
        Validated live-mode results with per-stage evidence classification.

    Raises:
        ReviewerError: With a fixed safe message if consent, input, execution,
            validation or cleanup fails.
    """
    if scenario not in _SCENARIO_ROLES:
        raise ReviewerError("Choose Manager review or Support review.")
    providers = consent.provider_policy()
    if not providers.allow_live_provider_calls:
        raise ReviewerError(
            "Confirm both acknowledgements before running live mode. Nothing was sent."
        )
    if openai is None and google_adk is None:
        raise ReviewerError("Select at least one live provider. Nothing was sent.")
    if not _LIVE_SLOTS.acquire(blocking=False):
        raise ReviewerError("A live demonstration is already running. Retry when it finishes.")
    try:
        with (
            TemporaryDirectory(prefix="module08-live-") as directory,
            _local_plane(Path(directory) / "customers.db") as endpoint,
        ):
            workflow = LiveProviderWorkflow(endpoint, providers=providers)
            result = asyncio.run(
                workflow.run(
                    customer_id="CUST-001",
                    principal_role=_SCENARIO_ROLES[scenario],
                    openai=openai,
                    google_adk=google_adk,
                )
            )
        return LiveReviewerResult(scenario=scenario, workflow=result)
    except ReviewerError:
        raise
    except (LiveProviderError, ConfigurationError) as exc:
        # These messages are fixed application text and never contain secrets.
        raise ReviewerError(str(exc)) from exc
    except EnterpriseIntegrationError as exc:
        _LOGGER.error("Module 8 live reviewer backend failed: %s", type(exc).__name__)
        raise ReviewerError(
            "Live demonstration failed safely before completion. No success was recorded."
        ) from exc
    except Exception as exc:
        # Last application boundary: never render underlying exception text or traceback.
        raise ReviewerError(
            "Live demonstration failed safely. Ask the maintainer to inspect it."
        ) from exc
    finally:
        _LIVE_SLOTS.release()
