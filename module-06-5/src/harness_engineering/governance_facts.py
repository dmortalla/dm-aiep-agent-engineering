"""Finite safe cost/anomaly projection fields; no tariffs or content."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from harness_engineering.latency import LatencyData


class GovernanceKind(StrEnum):
    """Operational event types, never authority commands."""

    EXPOSURE = "exposure"
    WARNING_80 = "warning_80"
    WARNING_100 = "warning_100"
    RETRY_BURST = "retry_burst"
    DENIAL_BURST = "denial_burst"
    PROVIDER_FAILURE_BURST = "provider_failure_burst"
    BUDGET_SPIKE = "budget_spike"


class GovernanceFacts(LatencyData):
    """Only bounded numbers and finite enums cross into Slice 1 telemetry."""

    kind: GovernanceKind
    exposure_units: Annotated[int, Field(ge=0, le=10**12)] | None = None
    cap_units: Annotated[int, Field(ge=1, le=10**12)] | None = None
    observation_count: Annotated[int, Field(ge=1, le=64)] | None = None

    @model_validator(mode="after")
    def coherent(self) -> "GovernanceFacts":
        """Reject contradictory warnings/counts before they can look like evidence."""
        if self.kind in (
            GovernanceKind.EXPOSURE,
            GovernanceKind.WARNING_80,
            GovernanceKind.WARNING_100,
        ):
            if (
                self.exposure_units is None
                or self.cap_units is None
                or self.exposure_units > self.cap_units
                or self.observation_count is not None
            ):
                raise ValueError("Exposure projections require bounded exposure and cap only.")
            threshold = {
                GovernanceKind.EXPOSURE: 0,
                GovernanceKind.WARNING_80: 80,
                GovernanceKind.WARNING_100: 100,
            }[self.kind]
            if self.exposure_units * 100 < self.cap_units * threshold:
                raise ValueError("Warning contradicts exposure utilization.")
        else:
            threshold = {
                GovernanceKind.RETRY_BURST: 2,
                GovernanceKind.DENIAL_BURST: 3,
                GovernanceKind.PROVIDER_FAILURE_BURST: 3,
                GovernanceKind.BUDGET_SPIKE: 1,
            }[self.kind]
            if (
                self.observation_count is None
                or self.observation_count < threshold
                or self.exposure_units is not None
                or self.cap_units is not None
            ):
                raise ValueError("Anomaly projections require a sufficient bounded count only.")
        return self
