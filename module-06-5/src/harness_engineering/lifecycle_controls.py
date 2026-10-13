"""Trusted bootstrap controls; never construct these from generated authority."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from threading import Event

from pydantic import BaseModel, ConfigDict, Field

from harness_engineering.errors import ContractValidationError


class WorkflowPolicy(BaseModel):
    """Validated safety deadline, distinct from the latency SLO."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    deadline_seconds: float = Field(
        default=180.0, gt=0, le=180, allow_inf_nan=False, strict=True
    )


class OffSwitch:
    """Application-owned, thread-safe, one-way cancellation source.

    A cancelled source cannot be reset. New approved work requires a new source
    and fresh invocation; this provides no durable resume authority.
    """

    def __init__(self) -> None:
        self._event = Event()

    def activate(self) -> None:
        """Latch cancellation for this source and all runs bound to it."""
        self._event.set()

    def is_active(self) -> bool:
        """Read trusted application cancellation state."""
        return self._event.is_set()


def checked_time(clock: Callable[[], float]) -> float:
    """Reject non-finite or malformed application clock readings."""
    reading = clock()
    if type(reading) not in {int, float} or not isfinite(reading):
        raise ContractValidationError("Monotonic clock must return a finite number.")
    return float(reading)


@dataclass
class RunControls:
    """Private invocation-local time accounting, never a public data contract."""

    started: float
    last_reading: float

    def expired(self, clock: Callable[[], float], policy: WorkflowPolicy) -> bool:
        """Check elapsed time without permitting clock regression or reset."""
        if any(type(v) is not float or not isfinite(v)
               for v in (self.started, self.last_reading)):
            raise ContractValidationError("Malformed internal workflow time accounting.")
        if self.last_reading < self.started:
            raise ContractValidationError("Workflow clock accounting regressed.")
        reading = checked_time(clock)
        if reading < self.last_reading:
            raise ContractValidationError("Application monotonic clock regressed.")
        self.last_reading = reading
        return reading - self.started >= policy.deadline_seconds
