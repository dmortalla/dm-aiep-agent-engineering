"""MCP 2.x server exposing application-owned enterprise capabilities."""

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from mcp_enterprise_integration.database import CustomerRecord, CustomerRepository
from mcp_enterprise_integration.enterprise_api import AccountStatus, EnterpriseApiClient
from mcp_enterprise_integration.internal_system import (
    InternalPolicyService,
    PolicyRequest,
    PolicyResult,
    RequestedAction,
)


def create_enterprise_mcp_server(
    *,
    database_path: Path,
    enterprise_api_url: str,
) -> MCPServer:
    """Create the enterprise integration MCP server.

    Args:
        database_path: SQLite database containing enterprise customer records.
        enterprise_api_url: Base URL for the enterprise account-status API.

    Returns:
        Configured MCP 2.x enterprise server.
    """
    repository = CustomerRepository(database_path)
    repository.initialize()
    api_client = EnterpriseApiClient(enterprise_api_url)
    policy_service = InternalPolicyService()

    server = MCPServer(
        "module-08-enterprise-integration",
        description="MCP boundary for validated enterprise capabilities.",
        instructions="Discover and invoke enterprise tools through typed MCP contracts.",
        version="0.8.0",
    )

    @server.tool()
    def get_customer(customer_id: str) -> CustomerRecord | None:
        """Retrieve one validated enterprise customer record.

        Args:
            customer_id: Enterprise customer identifier.

        Returns:
            Customer record when found, otherwise None.
        """
        return repository.get_customer(customer_id)

    @server.tool()
    def get_account_status(customer_id: str) -> AccountStatus:
        """Retrieve account status through the enterprise HTTP boundary.

        Args:
            customer_id: Enterprise customer identifier.

        Returns:
            Validated enterprise account status.
        """
        return api_client.get_account_status(customer_id)

    @server.tool()
    def evaluate_enterprise_policy(
        customer_id: str,
        requester_role: str,
        action: RequestedAction,
        account_status: str,
    ) -> PolicyResult:
        """Evaluate application-owned enterprise authorization policy.

        Args:
            customer_id: Enterprise customer identifier.
            requester_role: Application role to evaluate.
            action: Requested enterprise action.
            account_status: Validated enterprise account state.

        Returns:
            Auditable application-owned policy decision.
        """
        request = PolicyRequest(
            customer_id=customer_id,
            requester_role=requester_role,
            action=action,
            account_status=account_status,
        )
        return policy_service.evaluate(request)

    return server
