"""Application-owned evaluation targets: the reference scenario runner.

The reference target composes the real accepted Story 2 authorization/safety
pipeline, the real Story 3 ``ReliabilityController`` with deterministic
scripted target adapters, an injected deterministic clock and sleeper, and a
real Story 4 ``TelemetryPipeline`` with a capturing sink. Observed facts carry
no timing values, so repeated runs over a scenario are deterministic.

The degraded demo variant is a test/demo boundary constructible only through an
explicit constructor argument; it is never selectable from environment
variables, settings or dataset content and records its own target identity.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from .authorization import AuthorizationDecision, AuthorizationPolicy, ToolPermission
from .domain import (
    BudgetState,
    Decision,
    EvidenceClass,
    UntrustedContent,
    WorkflowIdentity,
    WorkflowState,
)
from .evaluation_contracts import BudgetOutcome, ObservedFacts
from .evaluation_dataset import Scenario, ScenarioSpec
from .reliability import (
    AttemptResult,
    Failure,
    Principal,
    RecoveryResult,
    ReliabilityController,
    ReliabilityPolicy,
    Target,
)
from .safety import SafetyPipeline
from .safety_types import SafetyCheckResult, SafetyProvider, SafetyStage
from .telemetry import (
    CostBasis,
    TelemetryLimits,
    TelemetryPipeline,
    _code,
    from_recovery,
)

REFERENCE_TARGET_ID: Final = "reference_default"
DEGRADED_TARGET_ID: Final = "degraded_demo"
TARGET_VERSION: Final = 1
RESERVED_POLICY_TIMEOUT_SECONDS: Final = 0.5
MAX_EXECUTIONS_PER_SCENARIO: Final = 2
MAX_CAPTURED_RECORDS: Final = 256
MAX_SCENARIO_POLICY_CAPACITY: Final = 16


@dataclass(frozen=True)
class ScenarioCorrelation:
    """Deterministic workflow identity granted to one scenario run.

    Attributes:
        workflow_id: The per-scenario workflow identity used by Story 3.
        trace_id: The per-scenario trace identity used by Stories 3 and 4.
        action_id: The Story 3 idempotency key shared by replay executions.
    """

    workflow_id: UUID
    trace_id: UUID
    action_id: UUID


class _Effects:
    """Side-effect invocation counter shared by one scenario's adapters."""

    invocations: int = 0
    unresolved: bool = False


class _CapturingSink:
    """Capturing ``NeutralSink`` for local evidence; never interprets records."""

    def __init__(self) -> None:
        self._records: list[str] = []

    @property
    def records(self) -> tuple[str, ...]:
        """Return captured minimized records as an immutable snapshot."""
        return tuple(self._records)

    async def send(self, record: str) -> None:
        """Capture one record; replies are never produced.

        Args:
            record: Minimized JSON record from the telemetry pipeline.
        """
        self._records.append(record)


class _DeterministicSafetyProvider(SafetyProvider):
    """Always-allow deterministic provider keeping the composition app-owned."""

    name = "deterministic_provider"
    evidence_class = EvidenceClass.DETERMINISTIC_FIXTURE

    def check(self, text: str, stage: SafetyStage) -> SafetyCheckResult:
        """Return a deterministic allow result without rendering the text.

        Args:
            text: Untrusted text (unused; no content is echoed).
            stage: Assessment boundary the pipeline asks this provider for.

        Returns:
            A deterministic allow check result.
        """
        return SafetyCheckResult(
            check=self.name,
            decision=Decision.ALLOW,
            reason="deterministic_provider_permitted",
            evidence_class=self.evidence_class,
        )


class _ScriptAdapter:
    """Deterministic scripted Story 3 target adapter with effect counting.

    Attributes:
        tool_name: Bound trusted tool identity.
        failures: Ordered Story 3 failure script; an exhausted script succeeds.
    """

    def __init__(
        self, tool_name: str, failures: tuple[Failure, ...], effects: _Effects
    ) -> None:
        self.tool_name = tool_name
        self._failures = failures
        self._cursor = [0]
        self._effects = effects

    async def invoke(self, action_key: UUID, content: UntrustedContent) -> AttemptResult:
        """Invoke one scripted adapter attempt and count the side effect.

        Args:
            action_key: Story 3 idempotency key (never rendered or logged).
            content: Untrusted request content (never rendered or logged).

        Returns:
            The scripted attempt result; unknown failure steps are not scripted.

        Raises:
            asyncio.CancelledError: Propagates when the controller cancels the
                unresolved scripted operation; task ownership stays with Story 3.
        """
        self._effects.invocations += 1
        index = self._cursor[0]
        self._cursor[0] = index + 1
        if index >= len(self._failures):
            return AttemptResult(
                output=UntrustedContent(
                    value=f"{self.tool_name}: effect recorded",
                    source="tool",
                ),
            )
        step = self._failures[index]
        if step is Failure.TIMEOUT:
            self._effects.unresolved = True
            # Deterministically unresolved from the controller's view: the
            # controller waits with its own injected-scenario timeout and
            # keeps ownership of this task without recording success.
            await asyncio.Event().wait()
        return AttemptResult(failure=step, repeat_safe=True)


@dataclass(frozen=True)
class ReferenceTarget:
    """The reference Story 2-4 composed evaluation target.

    Attributes:
        target_id: Stable target identity recorded with every run result.
        target_version: Target semantic version.
        correlations: Deterministic per-scenario workflow identities.
        degraded: Demo-only degraded behavior, bound at explicit construction.
    """

    target_id: str
    target_version: int
    correlations: Mapping[str, ScenarioCorrelation]
    degraded: bool = False

    @staticmethod
    def build(
        correlations: Mapping[str, ScenarioCorrelation],
        *,
        degraded: bool = False,
    ) -> "ReferenceTarget":
        """Construct the reference or the confined degraded demo target.

        Args:
            correlations: Deterministic scenario workflow identities.
            degraded: True constructs the explicit demo-only degraded variant.

        Returns:
            An immutable bound target; degraded behavior is only reachable
            through the explicit constructor argument.
        """
        return ReferenceTarget(
            target_id=DEGRADED_TARGET_ID if degraded else REFERENCE_TARGET_ID,
            target_version=TARGET_VERSION,
            correlations=dict(correlations),
            degraded=degraded,
        )

    async def run(self, scenario: Scenario) -> ObservedFacts:
        """Execute one scenario through the real Story 2-4 components.

        Args:
            scenario: A validated dataset scenario.

        Returns:
            Bounded deterministic observed facts without timing values.

        Raises:
            KeyError: When no correlation exists for the scenario; the engine
                treats that as a target-boundary error, never as a verdict.
        """
        correlation = self.correlations[scenario.scenario_id]
        spec = scenario.spec
        evidence = scenario.scenario_evidence()
        clock = _DeterministicClock()
        effects = _Effects()
        reducer, policy = self._authorization(scenario, correlation)
        controller = self._controller(scenario, policy, clock)
        adapters = self._adapters(scenario, effects)
        targets = self._targets(spec, policy, correlation, reducer, adapters)
        pipeline, sink = self._pipeline()
        content = UntrustedContent(value=spec.content, source="user")
        conflict = _conflicting_content(spec)
        executions = []
        total = MAX_EXECUTIONS_PER_SCENARIO if (
            spec.duplicate_replay or spec.conflicting_replay
        ) else 1
        for execution in range(total):
            requested = (
                conflict if execution == 1 and spec.conflicting_replay else content
            )
            result = await controller.execute(
                principal=Principal(principal_id=spec.principal_id),
                state=self._state(scenario, correlation, evidence),
                content=requested,
                targets=targets,
            )
            executions.append(result)
            await self._emit_recovery(pipeline, result, scenario)
        canaries = self._canary_scan(scenario, sink.records)
        return self._observed(
            scenario, tuple(executions), reducer, effects, canaries
        )

    def _authorization(
        self, scenario: Scenario, correlation: ScenarioCorrelation
    ) -> tuple[AuthorizationDecision, AuthorizationPolicy]:
        """Issue application-owned authorization for the scenario tools.

        Args:
            scenario: The validated scenario.
            correlation: Deterministic workflow identity for records.

        Returns:
            The primary application-issued decision and the immutable policy.
        """
        spec = scenario.spec
        tools = [ToolPermission(tool_name=spec.tool_name, privileged=True)]
        if spec.fallback_tool_name is not None:
            tools.append(ToolPermission(tool_name=spec.fallback_tool_name, privileged=False))
        allowed = ()
        if spec.allowlisted:
            allowed = (spec.tool_name,)
            if spec.fallback_tool_name is not None:
                allowed = (spec.tool_name, spec.fallback_tool_name)
        policy = AuthorizationPolicy(
            policy_id="evaluation_allowlist",
            tools=tools,
            grants={spec.principal_id: allowed},
        )
        decision = policy.authorize(
            principal_id=spec.principal_id,
            tool_name=spec.tool_name,
            identity=_identity(correlation),
        )
        return decision, policy

    def _adapters(
        self, scenario: Scenario, effects: _Effects
    ) -> tuple[_ScriptAdapter, _ScriptAdapter | None]:
        """Build deterministic scripted adapters bound to the shared counter."""
        spec = scenario.spec
        primary = _ScriptAdapter(spec.tool_name, spec.primary_failures, effects)
        fallback = (
            _ScriptAdapter(spec.fallback_tool_name, spec.fallback_failures, effects)
            if spec.fallback_tool_name is not None
            else None
        )
        return primary, fallback

    def _targets(
        self,
        spec: ScenarioSpec,
        policy: AuthorizationPolicy,
        correlation: ScenarioCorrelation,
        decision: AuthorizationDecision,
        adapters: tuple[_ScriptAdapter, _ScriptAdapter | None],
    ) -> tuple[Target, ...]:
        """Bind trusted primary and optional fallback targets for the scenario.

        Args:
            spec: The validated scenario specification.
            policy: The authorization policy that issued the decisions.
            correlation: Deterministic workflow identity.
            decision: The primary application-issued decision.
            adapters: Scripted primary and optional fallback adapters.

        Returns:
            The ordered target plan for the real story 3 controller.
        """
        primary_adapter, fallback_adapter = adapters
        targets = [Target(
            tool_name=spec.tool_name,
            decision=decision,
            invoke=primary_adapter.invoke,
            reservation_usd=spec.reservation_usd,
        )]
        if spec.fallback_tool_name is not None and fallback_adapter is not None:
            targets.append(Target(
                tool_name=spec.fallback_tool_name,
                decision=policy.authorize(
                    principal_id=spec.principal_id,
                    tool_name=spec.fallback_tool_name,
                    identity=_identity(correlation),
                ),
                invoke=fallback_adapter.invoke,
                reservation_usd=spec.reservation_usd,
            ))
        return tuple(targets)

    def _controller(
        self, scenario: Scenario, policy: AuthorizationPolicy, clock: "_DeterministicClock"
    ) -> ReliabilityController:
        """Bind the real story 3 controller with deterministic scenario bounds.

        Args:
            scenario: The validated scenario.
            policy: Application-owned authorization boundary.
            clock: Deterministic monotonic clock with its advancing sleeper.

        Returns:
            The configured reliability controller.
        """
        spec = scenario.spec
        reliability_policy = ReliabilityPolicy(
            max_attempts=spec.max_attempts,
            attempts_per_target=spec.attempts_per_target,
            max_fallbacks=spec.max_fallbacks,
            timeout_seconds=RESERVED_POLICY_TIMEOUT_SECONDS,
            deadline_seconds=RESERVED_POLICY_TIMEOUT_SECONDS * 2,
            backoff_seconds=0.0,
            capacity=MAX_SCENARIO_POLICY_CAPACITY,
            retry_on=frozenset({Failure.TRANSIENT}),
            fallback_on=frozenset({Failure.TRANSIENT}),
        )
        if self.degraded:
            reliability_policy = reliability_policy.model_copy(update={
                "max_attempts": 1,
                "attempts_per_target": 1,
            })
        return ReliabilityController(
            policy=reliability_policy,
            authorization=policy,
            safety=self._safety(),
            clock=clock.now,
            sleeper=clock.advance,
        )

    def _safety(self) -> SafetyPipeline:
        """Build a real safety pipeline with a deterministic provider."""
        return SafetyPipeline(providers=(_DeterministicSafetyProvider(),))

    def _pipeline(self) -> tuple[TelemetryPipeline, _CapturingSink]:
        """Create a real story 4 telemetry pipeline with a capturing sink.

        Returns:
            The bounded real pipeline and its capturing sink.
        """
        sink = _CapturingSink()
        pipeline = TelemetryPipeline(
            limits=TelemetryLimits(max_events=MAX_CAPTURED_RECORDS),
            exporter=sink,
        )
        return pipeline, sink

    async def _emit_recovery(
        self, pipeline: TelemetryPipeline, result: RecoveryResult, scenario: Scenario
    ) -> None:
        """Emit one correlated story 3 recovery observation through story 4.

        Args:
            pipeline: The scenario-bounded real telemetry pipeline.
            result: The real controller recovery result for this execution.
            scenario: The validated scenario carrying the canary condition.
        """
        observation = from_recovery(
            result,
            cost_basis=CostBasis.FIXTURE,
            usage_available=True,
        )
        metadata: object = None
        if scenario.spec.canary_enabled:
            metadata = {"debug": scenario.canary_id()}
        await pipeline.emit(observation, metadata=metadata)

    def _canary_scan(
        self, scenario: Scenario, records: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Scan captured local records for scenario canary identifiers.

        Args:
            scenario: The validated scenario whose synthetic canary applies.
            records: Minimized captured story 4 records.

        Returns:
            Every committed canary identifier observed in any captured record.
        """
        if not scenario.spec.canary_enabled:
            return ()
        canary = scenario.canary_id()
        return (canary,) if any(canary in record for record in records) else ()

    def _state(
        self,
        scenario: Scenario,
        correlation: ScenarioCorrelation,
        evidence: EvidenceClass,
    ) -> WorkflowState:
        """Create the initial trusted workflow state for one execution.

        Args:
            scenario: The validated scenario.
            correlation: Deterministic scenario workflow identity.
            evidence: Derived scenario evidence class.

        Returns:
            The fresh initial state with the deterministic story 3 key.
        """
        return WorkflowState(
            identity=WorkflowIdentity(
                workflow_id=correlation.workflow_id,
                trace_id=correlation.trace_id,
            ),
            idempotency_key=correlation.action_id,
            operation="evaluation_action",
            evidence_class=evidence,
            budget=BudgetState(
                cost_limit_usd=scenario.spec.budget_limit_usd,
                cost_used_usd=0.0,
            ),
        )

    def _observed(
        self,
        scenario: Scenario,
        results: tuple[RecoveryResult, ...],
        decision: AuthorizationDecision,
        effects: _Effects,
        canaries: tuple[str, ...],
    ) -> ObservedFacts:
        """Project bounded observed facts aggregated over finished executions.

        Args:
            scenario: The validated dataset scenario.
            results: Finished controller recovery results.
            decision: The primary application-issued authorization decision.
            effects: Shared deterministic effect counter.
            canaries: Canary identifiers observed in captured records.

        Returns:
            Bounded fixed-vocabulary observed facts; no exception or raw text
            ever enters the projection beyond the fixed codes.
        """
        last = results[-1]
        budget_exhausted = any(
            result.classification == "budget_exhausted" for result in results
        )
        safety = last.state.safety.decision if last.state.safety else None
        return ObservedFacts(
            classification=_code(last.classification),
            attempts=max(result.attempts for result in results),
            fallbacks=max(result.fallbacks for result in results),
            replayed=any(result.replayed for result in results),
            effect_count=effects.invocations,
            authorization=decision.decision,
            safety=safety,
            budget_used_usd=last.state.budget.cost_used_usd,
            budget_limit_usd=scenario.spec.budget_limit_usd,
            budget_outcome=(
                BudgetOutcome.BUDGET_EXHAUSTED
                if budget_exhausted
                else BudgetOutcome.WITHIN_BUDGET
            ),
            canaries_observed=canaries,
        )


class _DeterministicClock:
    """Injected deterministic monotonic clock and cooperative sleeper."""

    def __init__(self) -> None:
        self._now: float = 0.0

    def now(self) -> float:
        """Return the current deterministic time in seconds."""
        return self._now

    async def advance(self, seconds: float) -> None:
        """Advance the deterministic clock by the requested period.

        Args:
            seconds: Deterministic wait period in seconds.
        """
        self._now += seconds


def _identity(correlation: ScenarioCorrelation) -> WorkflowIdentity:
    """Build the story 1 workflow identity for authorization records."""
    return WorkflowIdentity(
        workflow_id=correlation.workflow_id,
        trace_id=correlation.trace_id,
    )


def _conflicting_content(spec: ScenarioSpec) -> UntrustedContent:
    """Derive the deterministic different-content request for conflict replays.

    Two untrusted requests share one story 3 idempotency key while carrying
    different untrusted content; the accepted controller denies the second.
    """
    return UntrustedContent(
        value=spec.content.rstrip(" ,.") + " with revised ledger amount 2.",
        source="user",
    )


__all__ = [
    "DEGRADED_TARGET_ID",
    "REFERENCE_TARGET_ID",
    "TARGET_VERSION",
    "ReferenceTarget",
    "ScenarioCorrelation",
]
