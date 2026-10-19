"""Bounded numeric provider usage, distinct from local accounting and billing."""

from enum import StrEnum
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from harness_engineering.latency import LatencyData


class UsageState(StrEnum):
    """Availability observations; absence never means zero cost."""

    REPORTED = "reported"
    MISSING = "missing"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    LATE = "late"
    LOCAL = "local"


class UsageFacts(LatencyData):
    """Validated provider claims only; no authority, model selector or metadata."""

    state: UsageState
    input_tokens: Annotated[int, Field(ge=0, le=12_000)] | None = None
    output_tokens: Annotated[int, Field(ge=0, le=2_000)] | None = None

    @model_validator(mode="after")
    def coherent(self) -> "UsageFacts":
        """Require numeric counts only for available, structurally valid reports."""
        available = self.state is UsageState.REPORTED
        if available != (self.input_tokens is not None and self.output_tokens is not None):
            raise ValueError("Only reported usage can carry both token counts.")
        if not available and (self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("Unavailable usage cannot invent counts.")
        return self


class UsageCapture:
    """One-shot worker-to-caller receipt channel; closing freezes caller evidence."""

    def __init__(self) -> None:
        self._facts = UsageFacts(state=UsageState.MISSING)
        self._closed = False
        self._late = False
        self._reported = False
        self._lock = Lock()

    def report(self, facts: UsageFacts) -> None:
        """Revalidate a normalized report; duplicate reports are not cumulative."""
        checked = UsageFacts.model_validate(facts)
        with self._lock:
            if self._closed:
                self._late = True
                return
            if self._reported:
                raise ValueError("Usage was already reported for this attempt.")
            self._facts = checked
            self._reported = True

    def close(self, fallback: UsageState) -> UsageFacts:
        """Freeze once; missing/timeout/cancellation never receive invented zeros."""
        with self._lock:
            if not self._closed:
                if not self._reported:
                    self._facts = UsageFacts(state=fallback)
                self._closed = True
            return self._facts

    @property
    def late(self) -> bool:
        """Expose late receipt arrival without changing the frozen caller receipt."""
        with self._lock:
            return self._late


class UsageReceipt(LatencyData):
    """Application attribution around numeric claims; no generated identity or price."""

    workflow_id: UUID
    thread_id: UUID
    attempt_id: UUID
    step_index: Annotated[int, Field(ge=1, le=100)]
    provider: Literal["fake", "openai", "anthropic"]
    local_input_bytes: Annotated[int, Field(ge=0, le=12_000)]
    usage: UsageFacts
