"""Bounded deterministic advisory rules, never an execution/authority controller."""

from collections import deque
from collections.abc import Callable
from math import isfinite
from threading import Lock
from time import monotonic
from types import MappingProxyType

from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.governance_facts import GovernanceFacts, GovernanceKind
from harness_engineering.latency import LatencyData
from harness_engineering.observability import TelemetrySession

RULES = MappingProxyType(
    {
        GovernanceKind.RETRY_BURST: 2,
        GovernanceKind.DENIAL_BURST: 3,
        GovernanceKind.PROVIDER_FAILURE_BURST: 3,
        GovernanceKind.BUDGET_SPIKE: 1,
    }
)


def validate_fixture_projection(
    identity: WorkflowIdentity,
    evidence: EvidenceClass,
    telemetry: TelemetrySession | None = None,
) -> None:
    """Reject incompatible fixture provenance without coercing identity/evidence."""
    if type(evidence) is not EvidenceClass or evidence not in (
        EvidenceClass.DETERMINISTIC,
        EvidenceClass.MOCKED,
        EvidenceClass.ADAPTER,
        EvidenceClass.LOCAL_INTEGRATION,
    ):
        raise ValueError("Fixture projections cannot claim live/deployment evidence.")
    if telemetry is not None and (
        type(telemetry) is not TelemetrySession
        or telemetry.identity != identity
        or telemetry.evidence is not evidence
    ):
        raise ValueError("Fixture projection identity/evidence conflicts with accounting.")


class AnomalySignal(LatencyData):
    """Application-assigned evidence around finite advisory facts."""

    facts: GovernanceFacts
    evidence: EvidenceClass
    identity: WorkflowIdentity | None = None


class AnomalyDetector:
    """Four rules, 60-second windows, <=64 timestamps per rule and <=64 signals.

    Trusted application boundaries feed one observation per actual event. Retry,
    denial and provider-failure rules need 2/3/3 events respectively. Budget-spike
    observation means a reservation >=25% of the cap (checked by the ledger).
    A rule re-arms only after its rolling count drops below threshold. No
    telemetry read, routing callback, model content or user dimensions exist.
    """

    def __init__(
        self,
        *,
        evidence: EvidenceClass,
        clock: Callable[[], float] = monotonic,
        telemetry: TelemetrySession | None = None,
    ) -> None:
        """Bind trusted evidence/clock and optional local projection only."""
        if type(evidence) is not EvidenceClass or not callable(clock):
            raise ValueError("Bind application evidence and a monotonic observation clock.")
        if telemetry is not None and type(telemetry) is not TelemetrySession:
            raise ValueError("Use an application-owned local telemetry session.")
        if telemetry is not None and telemetry.evidence is not evidence:
            raise ValueError("Anomaly and telemetry evidence classifications must agree.")
        self._evidence = evidence
        self._clock = clock
        self._telemetry = telemetry
        self._identity = telemetry.identity if telemetry is not None else None
        self._times = {kind: deque(maxlen=64) for kind in RULES}
        self._armed = dict.fromkeys(RULES, True)
        self._signals: deque[AnomalySignal] = deque(maxlen=64)
        self._last = 0.0
        self._lock = Lock()

    def bind_fixture(self, identity: WorkflowIdentity) -> None:
        """Bind trusted accounting identity once, before any fixture source observation.

        An existing telemetry/owner identity must match. An unbound detector with
        prior observations cannot be reassigned to an accounting workflow.
        """
        checked = WorkflowIdentity.model_validate(identity.model_dump())
        validate_fixture_projection(checked, self._evidence, self._telemetry)
        with self._lock:
            if self._identity is not None and self._identity != checked:
                raise ValueError("Anomaly detector already belongs to another workflow.")
            if self._identity is None and any(self._times.values()):
                raise ValueError("Cannot bind unattributed prior anomaly observations.")
            self._identity = checked

    def observe(self, kind: GovernanceKind) -> AnomalySignal | None:
        """Consume one trusted observation, deduplicating within a bounded window."""
        if type(kind) is not GovernanceKind or kind not in RULES:
            raise ValueError("Unsupported anomaly observation.")
        signal = None
        with self._lock:
            now = self._clock()
            if type(now) not in (float, int) or not isfinite(now) or now < self._last:
                raise ValueError("Anomaly clock must be finite and monotonic.")
            self._last = float(now)
            times = self._times[kind]
            while times and times[0] <= now - 60.0:
                times.popleft()
            if len(times) < RULES[kind]:
                self._armed[kind] = True
            times.append(float(now))
            if len(times) >= RULES[kind] and self._armed[kind]:
                self._armed[kind] = False
                signal = AnomalySignal(
                    facts=GovernanceFacts(kind=kind, observation_count=len(times)),
                    evidence=self._evidence,
                    identity=self._identity,
                )
                self._signals.append(signal)
        if signal is not None and self._telemetry is not None:
            self._telemetry.record_governance(signal.facts)
        return signal

    def snapshot(self) -> tuple[AnomalySignal, ...]:
        """Return immutable signals; retention is bounded independently of telemetry."""
        with self._lock:
            return tuple(self._signals)
