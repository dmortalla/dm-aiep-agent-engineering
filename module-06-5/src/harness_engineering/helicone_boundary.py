"""Non-executable Helicone configuration evidence (REQ-TECH-007).

Header names and gateway shape follow the official Helicone header directory.
Headers alone do not establish safe gateway behavior. Future retries, caching,
fallback, transformations and handling require independent review and live
routing requires separate human authorization. No auth/key field is needed here.
"""

import json
from typing import Literal

from pydantic import field_validator

from harness_engineering.anomaly_signals import validate_fixture_projection
from harness_engineering.domain import EvidenceClass
from harness_engineering.latency import LatencyData
from harness_engineering.observability import TelemetrySession


class HeliconeOfflineConfig(LatencyData):
    """Closed disabled configuration, with no transport or credential storage."""

    enabled: Literal[False] = False
    endpoint: Literal["https://gateway.helicone.ai/v1"] = "https://gateway.helicone.ai/v1"

    @field_validator("enabled", mode="before")
    @classmethod
    def disabled(cls, value: object) -> object:
        """Reject coercion and every attempt to activate the gateway."""
        if value is not False:
            raise ValueError("Only disabled offline Helicone configuration is authorized.")
        return value

    def describe(self, source: TelemetrySession) -> str:
        """Serialize non-secret hypothetical headers from application provenance.

        This is an evidence document, deliberately not a provider request config:
        authentication and a provider target are absent. No endpoint is installed.
        Source evidence is preserved; boundary evidence is always deterministic.
        """
        HeliconeOfflineConfig.model_validate(self)
        if type(source) is not TelemetrySession:
            raise ValueError("Bind application-owned telemetry provenance.")
        validate_fixture_projection(source.identity, source.evidence, source)
        return json.dumps({
            "enabled": False,
            "endpoint": self.endpoint,
            "boundary_evidence": EvidenceClass.DETERMINISTIC.value,
            "source_evidence": source.evidence.value,
            "headers": {
                "Helicone-Session-Id": str(source.identity.thread_id),
                "Helicone-Property-Workflow": str(source.identity.workflow_id),
                "Helicone-Property-Evidence": source.evidence.value,
                "Helicone-Omit-Request": "true",
                "Helicone-Omit-Response": "true",
                "Helicone-Retry-Enabled": "false",
                "Helicone-Cache-Enabled": "false",
            },
        }, sort_keys=True, separators=(",", ":"))
