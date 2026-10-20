"""Closed read-only Story 10 presentation contracts, never runtime authority."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from harness_engineering.anomaly_signals import AnomalySignal
from harness_engineering.cost_governance import LedgerSnapshot, TokenPolicy
from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.helicone_boundary import HeliconeOfflineConfig
from harness_engineering.latency import LatencyData, LatencyReport
from harness_engineering.observability import TelemetryEvent
from harness_engineering.observability_adapters import ExportHealth, Vendor
from harness_engineering.usage import UsageReceipt


class LabConfig(LatencyData):
    """Finite local fixture choices; no identity, content or authority overrides."""

    samples: Annotated[int, Field(ge=1, le=20)] = 1
    offline_sdk: bool = False


class IntegrationView(LatencyData):
    """Advisory SDK integration state, explicitly offline even when enabled."""

    vendor: Vendor
    enabled: bool
    health: ExportHealth


class ObservabilityReport(LatencyData):
    """One detailed workflow plus a bounded cross-workflow latency cohort."""

    evidence: Literal[EvidenceClass.DETERMINISTIC] = EvidenceClass.DETERMINISTIC
    identity: WorkflowIdentity
    phase: Literal["completed"] = "completed"
    fixture_unit: Literal["fixture_micro_usd_not_billing"] = "fixture_micro_usd_not_billing"
    tokens: TokenPolicy
    cost: LedgerSnapshot
    usage: Annotated[tuple[UsageReceipt, ...], Field(max_length=8)]
    events: Annotated[tuple[TelemetryEvent, ...], Field(max_length=512)]
    latency: Annotated[tuple[LatencyReport, ...], Field(max_length=36)]
    workflow_cohort: LatencyReport
    anomalies: Annotated[tuple[AnomalySignal, ...], Field(max_length=64)]
    # Tool-frequency observations are explicit fixtures, not executor activity.
    fixture_tool_observations: Literal[10] = 10
    hard_cap_denied: bool
    recovery_preserved: bool
    telemetry_failures: Annotated[int, Field(ge=0)]
    advisory_failures: Annotated[int, Field(ge=0)] = 0
    integrations: Annotated[tuple[IntegrationView, ...], Field(min_length=2, max_length=2)]
    helicone: HeliconeOfflineConfig

    @model_validator(mode="after")
    def provenance(self) -> "ObservabilityReport":
        """Reject foreign source facts and caller-promoted presentation evidence."""
        identity = self.identity
        values = (self.cost, *self.usage, *self.events)
        if any(v.workflow_id != identity.workflow_id or v.thread_id != identity.thread_id
               for v in values):
            raise ValueError("Presentation facts must share application provenance.")
        if any(event.evidence is not self.evidence for event in self.events):
            raise ValueError("Presentation cannot promote source evidence.")
        if any(r.cohort.evidence is not self.evidence
               for r in (*self.latency, self.workflow_cohort)):
            raise ValueError("Latency presentation cannot promote source evidence.")
        if any(s.identity != identity or s.evidence is not self.evidence for s in self.anomalies):
            raise ValueError("Anomaly presentation requires the same owner and evidence.")
        if {item.vendor for item in self.integrations} != set(Vendor):
            raise ValueError("Present exactly the two supported SDK integrations.")
        return self
