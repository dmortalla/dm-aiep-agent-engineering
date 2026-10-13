"""Integration tests for the bounded enterprise HTTP API client."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from mcp_enterprise_integration.enterprise_api import EnterpriseApiClient
from mcp_enterprise_integration.errors import EnterpriseIntegrationError


class EnterpriseApiHandler(BaseHTTPRequestHandler):
    """Serve deterministic local enterprise API responses."""

    def do_GET(self) -> None:
        """Return deterministic responses for integration tests."""
        if self.path == "/accounts/CUST-001":
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
            return

        if self.path == "/accounts/INVALID":
            payload = b'{"unexpected": "payload"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress local test-server logging."""
        return


@pytest.fixture
def api_server() -> str:
    """Run an isolated deterministic HTTP server."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), EnterpriseApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_local_http_request_returns_validated_result(api_server: str) -> None:
    """Exercise genuine HTTP transport against the deterministic local API."""
    client = EnterpriseApiClient(api_server)

    result = client.get_account_status("CUST-001")

    assert result.customer_id == "CUST-001"
    assert result.service_tier == "gold"
    assert result.risk_status == "low"
    assert result.open_cases == 2


def test_invalid_api_payload_is_rejected(api_server: str) -> None:
    """Reject untrusted API output that violates the typed contract."""
    client = EnterpriseApiClient(api_server)

    with pytest.raises(EnterpriseIntegrationError, match="invalid response payload"):
        client.get_account_status("INVALID")


def test_http_error_is_translated(api_server: str) -> None:
    """Translate HTTP failures at the enterprise integration boundary."""
    client = EnterpriseApiClient(api_server)

    with pytest.raises(EnterpriseIntegrationError, match="HTTP status 404") as captured:
        client.get_account_status("CUST-999")

    assert captured.value.__cause__ is not None


def test_customer_identifier_cannot_control_request_path(api_server: str) -> None:
    """Reject path-control characters before making an HTTP request."""
    client = EnterpriseApiClient(api_server)

    with pytest.raises(EnterpriseIntegrationError, match="unsupported characters"):
        client.get_account_status("../admin")


def test_execution_bounds_are_enforced(api_server: str) -> None:
    """Reject unsafe HTTP execution bounds during configuration."""
    with pytest.raises(ValueError, match="timeout_seconds"):
        EnterpriseApiClient(api_server, timeout_seconds=0)

    with pytest.raises(ValueError, match="max_response_bytes"):
        EnterpriseApiClient(api_server, max_response_bytes=100)
