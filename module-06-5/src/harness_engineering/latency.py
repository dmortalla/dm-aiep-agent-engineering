"""Bounded nearest-rank latency projections (REQ-COST-002), without deadlines."""

from collections import deque
from enum import StrEnum
from math import ceil
from threading import Lock
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.domain import EvidenceClass


class Measurement(StrEnum):
    """Finite measurement boundaries, never user-selected metric labels."""

    WORKFLOW = "workflow"
    SEGMENT = "segment"
    ACTION = "action"
    PROVIDER = "provider"


class Outcome(StrEnum):
    """Operational observations; none grant execution authority."""

    RETURNED = "returned"
    SUCCEEDED = "succeeded"
    STOPPED = "stopped"
    SUSPENDED = "suspended"
    DENIED = "denied"
    TIMEOUT = "timeout"
    REJECTED = "rejected"
    FAILED = "failed"
    DEFECT = "defect"


class TimingSource(StrEnum):
    """Separate injected calculation evidence from actual measurements."""

    MONOTONIC = "monotonic"
    INJECTED = "injected"


class LatencyData(BaseModel):
    """Immutable validated operational data, not policy input."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always",
        hide_input_in_errors=True,
    )


Duration = Annotated[float, Field(ge=0, le=86_400, allow_inf_nan=False)]


class Cohort(LatencyData):
    """Finite cohort key; workflow, task and model IDs are deliberately absent."""

    measurement: Measurement
    outcome: Outcome
    evidence: EvidenceClass
    timing: TimingSource


class LatencyReport(LatencyData):
    """Retained-window report; an insufficient/synthetic cohort cannot pass SLO."""

    cohort: Cohort
    sample_count: Annotated[int, Field(ge=0, le=1000)]
    p50_seconds: Duration | None
    p95_seconds: Duration | None
    sufficient_samples: bool
    slo_p95_seconds: Annotated[float, Field(gt=0, le=5, allow_inf_nan=False)]
    slo_met: bool | None
    evicted_samples: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def coherent(self) -> "LatencyReport":
        """Reject fabricated percentile availability or unsupported SLO conclusions."""
        n = self.sample_count
        if self.sufficient_samples != (n >= 20):
            raise ValueError("Sample sufficiency requires at least 20 retained samples.")
        if n == 0:
            if self.p50_seconds is not None or self.p95_seconds is not None:
                raise ValueError("Empty cohorts have no percentiles.")
        elif (self.p50_seconds is None or self.p95_seconds is None
              or self.p50_seconds > self.p95_seconds):
            raise ValueError("Nonempty cohorts require ordered percentile values.")
        if self.slo_met is not None:
            c = self.cohort
            if not (n >= 20 and c.measurement is Measurement.WORKFLOW
                    and c.outcome is Outcome.SUCCEEDED and c.timing is TimingSource.MONOTONIC
                    and c.evidence in (
                        EvidenceClass.DETERMINISTIC, EvidenceClass.LOCAL_INTEGRATION,
                    )):
                raise ValueError("This cohort cannot assess the workflow SLO.")
            if self.slo_met != (self.p95_seconds <= self.slo_p95_seconds):
                raise ValueError("SLO assessment must match the measured p95.")
        return self


class LatencyWindow:
    """One bounded cohort with at most 1,000 samples and no identity registry."""

    def __init__(self, cohort: Cohort, *, slo_p95_seconds: float = 5.0) -> None:
        """Bind trusted cohort and SLO, which may tighten the frozen five seconds."""
        self._cohort = Cohort.model_validate(cohort)
        # Validate configuration through the same strict public report contract.
        LatencyReport(
            cohort=self._cohort, sample_count=0, p50_seconds=None, p95_seconds=None,
            sufficient_samples=False, slo_p95_seconds=slo_p95_seconds, slo_met=None,
            evicted_samples=0,
        )
        self._slo = slo_p95_seconds
        self._samples: deque[float] = deque(maxlen=1000)
        self._evicted = 0
        self._lock = Lock()

    def add(self, seconds: float) -> None:
        """Validate before retaining a duration; invalid values never become evidence."""
        # Pydantic's strict float accepts integers; explicitly reject bool/non-floats.
        if type(seconds) is not float:
            raise ValueError("Latency duration must be a finite float in seconds.")
        checked = LatencyReport(
            cohort=self._cohort, sample_count=1, p50_seconds=seconds, p95_seconds=seconds,
            sufficient_samples=False, slo_p95_seconds=self._slo, slo_met=None,
            evicted_samples=0,
        )
        with self._lock:
            self._evicted += int(len(self._samples) == 1000)
            self._samples.append(checked.p50_seconds)

    def report(self) -> LatencyReport:
        """Return p50/p95 using x[ceil(p*n)-1], including explicit empty behavior.

        Only actual monotonic deterministic/local successful workflow cohorts with
        at least 20 retained samples can receive a numerical SLO assessment.
        This assessment alone is not a regression-run or production SLO claim.
        """
        with self._lock:
            values = sorted(self._samples)
            evicted = self._evicted
        n = len(values)
        p50 = values[ceil(0.50 * n) - 1] if n else None
        p95 = values[ceil(0.95 * n) - 1] if n else None
        c = self._cohort
        eligible = (
            n >= 20 and c.measurement is Measurement.WORKFLOW
            and c.outcome is Outcome.SUCCEEDED and c.timing is TimingSource.MONOTONIC
            and c.evidence in (EvidenceClass.DETERMINISTIC, EvidenceClass.LOCAL_INTEGRATION)
        )
        return LatencyReport(
            cohort=c, sample_count=n, p50_seconds=p50, p95_seconds=p95,
            sufficient_samples=n >= 20, slo_p95_seconds=self._slo,
            slo_met=p95 <= self._slo if eligible else None, evicted_samples=evicted,
        )
