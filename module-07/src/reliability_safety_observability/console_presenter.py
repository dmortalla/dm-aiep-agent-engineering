"""Presentation-only composition for the Module 7 reviewer console.

This module deliberately has no Streamlit or provider-SDK dependency.  It
assembles fixed, accepted public application interfaces and projects their
typed results into bounded primitive records suitable for a browser view.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from .config import RuntimeSettings
from .domain import EvidenceClass, ExecutionMode

if TYPE_CHECKING:
    from .evaluation_benchmark import BenchmarkOutput
    from .failure_lab import LabScenarioResult, LabSummary
    from .reliability import RecoveryResult
    from .telemetry import Observation

_SAFE_ERROR = "The requested result is unavailable. Review the guidance and try again."
_MAX_HISTORY: Final = 2
_MAX_LIVE_LEDGER: Final = 8
_LIVE_PROVIDERS: Final = frozenset({"Langfuse", "LangSmith", "Helicone"})


class BenchmarkInFlightError(RuntimeError):
    """Raised when a duplicate benchmark action is refused before execution."""


@dataclass(frozen=True, slots=True)
class WorkflowEvidence:
    """Safe projection of one fixed deterministic workflow execution."""

    recovery: RecoveryResult
    observation: Observation
    records: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class BenchmarkReceipt:
    """Opaque provenance token for one boundary-owned benchmark result.

    ``owner`` names the issuing session boundary; authority comes only from
    that boundary's private registry, never from the receipt's fields.
    """

    token: str
    ordinal: int
    report_digest: str
    owner: str


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    """Safe projection plus a boundary-owned receipt for one benchmark run."""

    output: BenchmarkOutput
    receipt: BenchmarkReceipt


@dataclass(frozen=True, slots=True)
class LiveAuthorizationReceipt:
    """Opaque presentation reference to one boundary-recorded confirmation.

    Holding, restoring, copying, or reconstructing this value confers no
    authority: the issuing boundary's private ledger decides validity.
    """

    token: str
    provider: str


class LiveReceiptState(StrEnum):
    """Authoritative lifecycle of one issued live confirmation."""

    ISSUED = "issued"
    CONSUMED = "consumed"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class LiveGrant:
    """One consumed authorization bound to the exact confirmed configuration.

    The verifier is invoked with these resolved settings, so the executed
    action is the confirmed action rather than a later configuration re-read.
    """

    provider: str
    runtime: RuntimeSettings
    settings: object


@dataclass(slots=True)
class _LiveRecord:
    """Private boundary record for the one outstanding confirmation.

    The token and provider are recorded independently of the issued object,
    so mutating a held reference cannot rebind what the boundary recorded.
    """

    receipt: LiveAuthorizationReceipt
    token: str
    provider: str
    runtime: RuntimeSettings
    settings: object
    state: LiveReceiptState


LiveConfigResolver = Callable[[str], object]


def resolve_provider_settings(provider: str) -> object:
    """Resolve the existing server-side settings for one provider verifier."""
    if provider == "Langfuse":
        from .langfuse_config import LangfuseSettings

        return LangfuseSettings()
    if provider == "LangSmith":
        from .langsmith_config import LangSmithSettings

        return LangSmithSettings()
    if provider == "Helicone":
        from .helicone_config import HeliconeSettings

        return HeliconeSettings()
    raise ValueError("The selected provider verifier is unavailable.")


def safe_error(_: Exception | None = None) -> str:
    """Return the fixed browser-safe error text without retaining exception data."""
    return _SAFE_ERROR


def evidence_badge(value: EvidenceClass | str | None) -> str:
    """Return an exact evidence label, refusing unknown values as unresolved."""
    try:
        return EvidenceClass(value).value if value is not None else "unresolved"
    except ValueError:
        return "unresolved"


def recovery_projection(result: RecoveryResult) -> dict[str, object]:
    """Project allowlisted workflow facts without output or input content."""
    state = result.state
    return {
        "workflow_id": str(state.identity.workflow_id),
        "trace_id": str(state.identity.trace_id),
        "action_id": str(state.idempotency_key),
        "terminal_status": state.terminal_status.value if state.terminal_status else "unknown",
        "classification": result.classification,
        "evidence_class": evidence_badge(state.evidence_class),
        "attempts": result.attempts,
        "fallbacks": result.fallbacks,
        "replayed": result.replayed,
        "recovered": result.reliability.recovered if result.reliability else None,
        "remaining_attempts": result.remaining_attempts,
        "elapsed_seconds": result.elapsed_seconds,
        "actual_cost_usd": result.actual_cost_usd,
        "overage_usd": result.overage_usd,
        "budget_used_usd": state.budget.cost_used_usd,
        "budget_limit_usd": state.budget.cost_limit_usd,
        "authorization": state.authorization.decision.value if state.authorization else "unknown",
        "authorization_reason": state.authorization.reason if state.authorization else "unknown",
        "safety": state.safety.decision.value if state.safety else "unknown",
        "safety_reason": state.safety.reason if state.safety else "unknown",
        "history": list(result.history),
    }


def observation_projection(
    observation: Observation, records: tuple[str, ...]
) -> tuple[dict[str, object], ...]:
    """Decode only the already-redacted telemetry pipeline records."""
    _ = observation
    projected: list[dict[str, object]] = []
    for record in records:
        try:
            parsed = json.loads(record)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            fields = parsed.get("fields")
            if isinstance(fields, dict):
                row = {
                    "workflow_id": str(observation.telemetry.workflow_id),
                    "trace_id": str(observation.telemetry.trace_id),
                    "span_id": str(observation.telemetry.span_id),
                }
                row.update(
                    {
                        key: fields[key]
                        for key in (
                            "action_id",
                            "status",
                            "duration_ms",
                            "attempts",
                            "fallbacks",
                            "recovered",
                            "replayed",
                            "authorization_decision",
                            "safety_decision",
                            "evidence_class",
                            "source_evidence",
                            "actual_cost_usd",
                            "overage_usd",
                            "budget",
                            "usage",
                        )
                        if key in fields
                    }
                )
                projected.append(row)
    return tuple(projected[:1])


class ConsoleBoundary:
    """Bounded composition boundary owned by exactly one reviewer session.

    Streamlit session state is untrusted presentation state.  This boundary is
    the only authority for benchmark provenance, comparison ownership, and the
    live-confirmation lifecycle.  Each instance has an opaque owner identity
    and private bounded registries, so receipts issued by one session's
    boundary are never authority in another.  Benchmark provenance is
    established by object identity and digest; a type-valid ``RunResult`` or a
    copied receipt is never improvement authority.

    ``session_anchor`` is the server-side per-session object the boundary was
    created for.  It is held by identity so a boundary substituted into a
    different session is recognized as foreign and replaced, never adopted.
    """

    def __init__(
        self,
        settings: RuntimeSettings | None = None,
        *,
        live_config_resolver: LiveConfigResolver | None = None,
        session_anchor: object | None = None,
    ) -> None:
        self._settings = settings or RuntimeSettings()
        self._session_anchor = session_anchor
        self._owner = secrets.token_hex(16)
        self._runs: OrderedDict[str, tuple[object, str, int, BenchmarkReceipt]] = OrderedDict()
        self._ordinal = 0
        self._benchmark_lock = Lock()
        self._benchmark_execution_lock = Lock()
        self._live_lock = Lock()
        self._resolve_live_config = live_config_resolver or resolve_provider_settings
        self._live_current: _LiveRecord | None = None
        self._live_ledger: OrderedDict[str, LiveReceiptState] = OrderedDict()

    @property
    def owner(self) -> str:
        """Return this session boundary's opaque, non-authoritative identity."""
        return self._owner

    def owned_by(self, session_anchor: object) -> bool:
        """Return whether this boundary was created for exactly this server session."""
        return self._session_anchor is not None and self._session_anchor is session_anchor

    @property
    def mode(self) -> str:
        """Return the configured mode without exposing settings or secrets."""
        return self._settings.mode.value

    @property
    def live_available(self) -> bool:
        """Return whether runtime configuration has opted into live mode."""
        return (
            self._settings.mode is ExecutionMode.LIVE and self._settings.live_integrations_enabled
        )

    def issue_live_confirmation(self, provider: str) -> LiveAuthorizationReceipt | None:
        """Record one fresh confirmation bound to the provider and its configuration.

        This is the human acknowledgement only, not provider authority: the
        existing verifier retains all runtime, credential, and transport gates.
        Any previously issued confirmation is superseded.  The returned value is
        a reference; validity lives only in this boundary's private ledger.
        """
        if provider not in _LIVE_PROVIDERS or not self.live_available:
            return None
        try:
            settings = self._resolve_live_config(provider)
        except Exception:  # Unresolvable configuration fails closed.
            return None
        with self._live_lock:
            self._retire_current(LiveReceiptState.SUPERSEDED)
            receipt = LiveAuthorizationReceipt(token=secrets.token_urlsafe(32), provider=provider)
            self._live_current = _LiveRecord(
                receipt=receipt,
                token=receipt.token,
                provider=provider,
                runtime=self._settings,
                settings=settings,
                state=LiveReceiptState.ISSUED,
            )
            self._record(receipt.token, LiveReceiptState.ISSUED)
            return receipt

    def invalidate_live_confirmation(self) -> None:
        """Invalidate any outstanding confirmation when the requested action changes."""
        with self._live_lock:
            self._retire_current(LiveReceiptState.INVALIDATED)

    def live_receipt_state(self, receipt: object) -> LiveReceiptState | None:
        """Return the authoritative ledger state for a presented reference, if known."""
        if not isinstance(receipt, LiveAuthorizationReceipt) or not isinstance(receipt.token, str):
            return None
        with self._live_lock:
            return self._live_ledger.get(receipt.token)

    def live_confirmation_is_current(self, receipt: object, provider: str) -> bool:
        """Return whether this exact receipt is the current unconsumed confirmation.

        A request for a different provider or a changed configuration
        invalidates the outstanding confirmation, so changing away and back
        never resurrects it.
        """
        current_settings = self._current_settings(provider)
        with self._live_lock:
            return self._validate(receipt, provider, current_settings)

    def consume_live_confirmation(self, receipt: object, provider: str) -> LiveGrant | None:
        """Atomically consume one exact current receipt before any verifier can run.

        Returns the grant bound to the confirmed configuration, or ``None``.
        Consumption is final: success, handled failure, reruns, and restored
        references never make it valid again.
        """
        current_settings = self._current_settings(provider)
        with self._live_lock:
            record = self._live_current
            if record is None or not self._validate(receipt, provider, current_settings):
                return None
            self._retire_current(LiveReceiptState.CONSUMED)
            return LiveGrant(provider=provider, runtime=record.runtime, settings=record.settings)

    def update_runtime_settings(self, settings: RuntimeSettings) -> None:
        """Apply server-resolved settings and invalidate any outstanding receipt.

        Runtime configuration is not browser input.  This narrow refresh seam
        makes configuration replacement fail closed and keeps the authority
        boundary testable without exposing a presentation control.
        """
        with self._live_lock:
            self._settings = settings
            self._retire_current(LiveReceiptState.INVALIDATED)

    def _current_settings(self, provider: str) -> object | None:
        """Re-resolve provider configuration only while a confirmation is outstanding."""
        if self._live_current is None or provider not in _LIVE_PROVIDERS:
            return None
        try:
            return self._resolve_live_config(provider)
        except Exception:  # Unresolvable configuration fails closed.
            return None

    def _validate(self, receipt: object, provider: str, current_settings: object | None) -> bool:
        """Check lifecycle, provider, configuration binding, and exact identity.

        Caller holds ``_live_lock``.  A binding mismatch is a change of the
        requested action and invalidates the outstanding confirmation.
        """
        record = self._live_current
        if record is None or record.state is not LiveReceiptState.ISSUED:
            return False
        if (
            record.provider != provider
            or record.runtime is not self._settings
            or not self.live_available
            or current_settings is None
            or current_settings != record.settings
        ):
            self._retire_current(LiveReceiptState.INVALIDATED)
            return False
        return (
            receipt is record.receipt
            and isinstance(receipt, LiveAuthorizationReceipt)
            and isinstance(receipt.token, str)
            and secrets.compare_digest(receipt.token, record.token)
            and receipt.provider == record.provider
        )

    def _retire_current(self, state: LiveReceiptState) -> None:
        """Retire the outstanding confirmation permanently.  Caller holds the lock."""
        record = self._live_current
        if record is not None:
            record.state = state
            self._record(record.token, state)
        self._live_current = None

    def _record(self, token: str, state: LiveReceiptState) -> None:
        """Keep a bounded diagnostic ledger; only ``_live_current`` confers authority."""
        self._live_ledger[token] = state
        self._live_ledger.move_to_end(token)
        while len(self._live_ledger) > _MAX_LIVE_LEDGER:
            self._live_ledger.popitem(last=False)

    def run_workflow(self) -> WorkflowEvidence:
        """Run the one fixed, deterministic, locally guarded workflow."""
        from .authorization import AuthorizationPolicy, ToolPermission
        from .domain import UntrustedContent, WorkflowIdentity, WorkflowState
        from .guardrails_adapter import GuardrailsCredentialProvider
        from .reliability import AttemptResult, Principal, ReliabilityController, Target
        from .safety import SafetyPipeline
        from .telemetry import CostBasis, TelemetryPipeline, from_recovery

        provider = GuardrailsCredentialProvider()
        try:
            authorization = AuthorizationPolicy(
                policy_id="story9_fixed_demo",
                tools=[ToolPermission(tool_name="reviewer_demo")],
                grants={"reviewer": ["reviewer_demo"]},
            )
            safety = SafetyPipeline(providers=[provider])

            async def fixed_operation(_: UUID, __: UntrustedContent) -> AttemptResult:
                return AttemptResult(output=UntrustedContent(value="deterministic_demo_complete"))

            decision = authorization.authorize(principal_id="reviewer", tool_name="reviewer_demo")
            controller = ReliabilityController(
                policy=self._workflow_policy(), authorization=authorization, safety=safety
            )
            result = asyncio.run(
                controller.execute(
                    principal=Principal(principal_id="reviewer"),
                    state=WorkflowState(
                        identity=WorkflowIdentity(), operation="story9_reviewer_demo"
                    ),
                    content=UntrustedContent(value="run approved reviewer demonstration"),
                    targets=(Target("reviewer_demo", decision, fixed_operation, 0.0),),
                )
            )
            observation = from_recovery(result, cost_basis=CostBasis.FIXTURE)
            pipeline = TelemetryPipeline()
            asyncio.run(pipeline.emit(observation))
            return WorkflowEvidence(
                recovery=result,
                observation=observation,
                records=observation_projection(observation, pipeline.records),
            )
        finally:
            provider.close()

    @staticmethod
    def _workflow_policy() -> Any:
        """Return the existing bounded reliability policy for the fixed plan."""
        from .reliability import ReliabilityPolicy

        return ReliabilityPolicy(max_attempts=1, attempts_per_target=1, max_fallbacks=0)

    def run_benchmark(self) -> BenchmarkEvidence:
        """Run one benchmark or refuse a duplicate already in flight.

        The nonblocking action lock spans the consequential benchmark work,
        rather than merely receipt bookkeeping.  A refused caller never loads
        a dataset, constructs an evaluator, receives an ordinal, or creates a
        receipt.  The ``finally`` release also prevents handled or unexpected
        failures from wedging later legitimate actions.
        """
        if not self._benchmark_execution_lock.acquire(blocking=False):
            raise BenchmarkInFlightError("A benchmark is already in progress.")
        try:
            with self._benchmark_lock:
                ordinal = self._ordinal
            output = self._execute_benchmark(ordinal)
            receipt = BenchmarkReceipt(
                secrets.token_urlsafe(32), ordinal, output.report_digest, self._owner
            )
            with self._benchmark_lock:
                self._ordinal += 1
                self._runs[receipt.token] = (
                    output.run.result,
                    output.report_digest,
                    receipt.ordinal,
                    receipt,
                )
                while len(self._runs) > _MAX_HISTORY:
                    self._runs.popitem(last=False)
            return BenchmarkEvidence(output=output, receipt=receipt)
        finally:
            self._benchmark_execution_lock.release()

    def _execute_benchmark(self, ordinal: int) -> BenchmarkOutput:
        """Execute the accepted benchmark composition for one assigned ordinal."""
        from .evaluation_benchmark import BenchmarkRunner
        from .evaluation_dataset import load_benchmark_dataset
        from .evaluation_engine import EvaluationEngine
        from .evaluation_regression import load_committed_baseline
        from .evaluation_target import ReferenceTarget

        dataset = load_benchmark_dataset()
        return asyncio.run(
            BenchmarkRunner(EvaluationEngine()).run_full(
                dataset,
                target_factory=ReferenceTarget.build,
                target_id="reference_default",
                target_version=1,
                run_ordinal=ordinal,
                baseline=load_committed_baseline(dataset),
            )
        )

    def improvement(self, before: object, after: object) -> object | None:
        """Return an improvement cycle only for two exact receipts this session issued."""
        if not isinstance(before, BenchmarkReceipt) or not isinstance(after, BenchmarkReceipt):
            return None
        with self._benchmark_lock:
            before_entry = self._runs.get(before.token)
            after_entry = self._runs.get(after.token)
        if (
            not secrets.compare_digest(str(before.owner), self._owner)
            or not secrets.compare_digest(str(after.owner), self._owner)
            or before_entry is None
            or after_entry is None
            or before.token == after.token
            or before.ordinal >= after.ordinal
            or before_entry[1:3] != (before.report_digest, before.ordinal)
            or after_entry[1:3] != (after.report_digest, after.ordinal)
            or before_entry[3] is not before
            or after_entry[3] is not after
        ):
            return None
        from .evaluation_improvement import improvement_cycle

        return improvement_cycle(before_entry[0], after_entry[0])

    def comparison_receipts(self) -> tuple[BenchmarkReceipt, BenchmarkReceipt] | None:
        """Return the current two boundary-owned receipts in issuance order.

        A receipt that has been evicted never appears here, so presentation
        session state can only mirror the bounded current comparison window.
        """
        with self._benchmark_lock:
            if len(self._runs) != _MAX_HISTORY:
                return None
            values = tuple(self._runs.values())
        return values[0][3], values[1][3]

    def run_selected_lab(self, kind: str) -> LabScenarioResult:
        """Run exactly one accepted Story 8 scenario."""
        from .failure_lab import ScenarioKind, run_scenario

        return run_scenario(ScenarioKind(kind))

    def run_full_lab(self) -> tuple[tuple[LabScenarioResult, ...], LabSummary]:
        """Run the fixed accepted Story 8 matrix once."""
        from .failure_lab import run_lab

        return run_lab()


def lab_projection(result: LabScenarioResult) -> dict[str, object]:
    """Return a bounded primitive projection of a Story 8 scenario result."""
    return {
        "scenario_id": result.scenario_id,
        "kind": result.kind,
        "expected": result.expected_disposition,
        "observed": result.observed_disposition,
        "attempts": result.attempts,
        "fallbacks": result.fallbacks,
        "effects": result.effect_count,
        "budget_before_usd": result.budget_before_usd,
        "budget_after_usd": result.budget_after_usd,
        "authorization": result.authority_outcome,
        "safety": result.safety_outcome,
        "telemetry": result.telemetry_state,
        "evidence_class": evidence_badge(result.evidence_class),
        "passed": result.passed,
        "reason_codes": list(result.reason_codes),
    }
