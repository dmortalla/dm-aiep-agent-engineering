"""Bounded HTTP integration for an enterprise account-status API."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, ValidationError

from mcp_enterprise_integration.errors import EnterpriseIntegrationError


class AccountStatus(BaseModel):
    """Validated response returned by the enterprise API boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: str
    service_tier: str
    risk_status: str
    open_cases: int


class EnterpriseApiClient:
    """Call a bounded enterprise HTTP API and validate its response."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 65_536,
    ) -> None:
        """Initialize the enterprise API client.

        Args:
            base_url: HTTP endpoint root for the enterprise API.
            timeout_seconds: Maximum duration for one HTTP request.
            max_response_bytes: Maximum accepted response payload.

        Raises:
            ValueError: If execution bounds are invalid.
        """
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        if max_response_bytes < 1024 or max_response_bytes > 1_000_000:
            raise ValueError("max_response_bytes must be between 1024 and 1000000")

        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def get_account_status(self, customer_id: str) -> AccountStatus:
        """Retrieve and validate one enterprise account-status response.

        Args:
            customer_id: Customer identifier sent as an HTTP path component.

        Returns:
            Validated account-status data.

        Raises:
            EnterpriseIntegrationError: If transport, payload, or validation fails.
        """
        if not customer_id or not customer_id.strip():
            raise EnterpriseIntegrationError("customer_id must not be blank")

        if not all(character.isalnum() or character in "-_" for character in customer_id):
            raise EnterpriseIntegrationError("customer_id contains unsupported characters")

        url = f"{self._base_url}/accounts/{customer_id}"
        request = Request(url, headers={"Accept": "application/json"}, method="GET")

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content_type = response.headers.get_content_type()
                if content_type != "application/json":
                    raise EnterpriseIntegrationError(
                        f"Enterprise API returned unsupported content type: {content_type}"
                    )

                payload = response.read(self._max_response_bytes + 1)

                if len(payload) > self._max_response_bytes:
                    raise EnterpriseIntegrationError(
                        "Enterprise API response exceeded configured size limit"
                    )

        except HTTPError as exc:
            raise EnterpriseIntegrationError(
                f"Enterprise API returned HTTP status {exc.code}"
            ) from exc
        except URLError as exc:
            raise EnterpriseIntegrationError(
                f"Enterprise API transport failed: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise EnterpriseIntegrationError(
                "Enterprise API request timed out"
            ) from exc

        try:
            decoded = json.loads(payload.decode("utf-8"))
            return AccountStatus.model_validate(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise EnterpriseIntegrationError(
                "Enterprise API returned an invalid response payload"
            ) from exc
