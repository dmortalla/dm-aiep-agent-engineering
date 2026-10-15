"""Bounded local resilience for cooperative async operations.

Policy, principals, targets and usage attestations are supplied by trusted
application adapters, never parsed from provider payloads. Operations must yield
and honor cancellation; arbitrary blocking Python callbacks are unsupported.
"""

import asyncio
import hashlib
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .authorization import AuthorizationPolicy
from .domain import (
    AuthorizationDecision,
    BudgetState,
    Decision,
    EvidenceClass,
    Identifier,
    ReliabilityResult,
    TerminalStatus,
    UntrustedContent,
    UsageRecord,
    WorkflowState,
)
from .errors import AuthorizationDeniedError
from .safety import SafetyPipeline


class Principal(BaseModel):
    """Application-resolved principal, separate from untrusted request content."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    principal_id: Identifier


class Failure(StrEnum):
    """Safe identifiers; provider exception messages never enter recovery state."""

    TRANSIENT = "transient"
    TERMINAL = "terminal"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    AUTHORIZATION = "authorization_denied"
    SAFETY = "safety_denied"


class ReliabilityPolicy(BaseModel):
    """Trusted finite limits. Attempts include the initial call, across all targets.

    Backoff is a constant number of seconds; no jitter or recursive recovery.
    Cost uses USD. Capacity refuses new keys forever once full; no eviction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    max_attempts: int = Field(default=3, ge=1, le=1000)
    attempts_per_target: int = Field(default=2, ge=1, le=1000)
    max_fallbacks: int = Field(default=1, ge=0, le=100)
    timeout_seconds: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    deadline_seconds: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    backoff_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    capacity: int = Field(default=256, ge=1, le=4096)
    retry_on: frozenset[Failure] = frozenset({Failure.TRANSIENT})
    fallback_on: frozenset[Failure] = frozenset({Failure.TRANSIENT})


class AttemptResult(BaseModel):
    """Trusted adapter attestation, not a provider-supplied policy instruction.

    repeat_safe certifies no effect occurred, or adapter-level deduplication of
    this exact action across all configured candidates. Defaults fail closed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    output: UntrustedContent | None = Field(default=None, repr=False)
    failure: Failure | None = None
    usage: UsageRecord = Field(default_factory=UsageRecord)
    repeat_safe: bool = False


@dataclass(frozen=True)
class Target:
    """Trusted capability binding with a maximum cost reservation per invocation.

    The async adapter receives the original action key and input. Unknown cost
    exposure is invalid. Failed/timeout calls without usage consume reservation.
    """

    tool_name: str
    decision: AuthorizationDecision
    invoke: Callable[[UUID, UntrustedContent], Awaitable[AttemptResult]]
    reservation_usd: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.reservation_usd) or self.reservation_usd < 0:
            raise ValueError("Target requires a finite nonnegative cost bound.")


class RecoveryResult(BaseModel):
    """Immutable, content-minimal local evidence; zero attempts are represented honestly."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    state: WorkflowState
    classification: str
    attempts: int
    fallbacks: int
    elapsed_seconds: float
    remaining_attempts: int
    remaining_seconds: float
    actual_cost_usd: float
    overage_usd: float = 0.0
    history: tuple[str, ...] = ()
    replayed: bool = False
    reliability: ReliabilityResult | None = None
    output: UntrustedContent | None = Field(default=None, repr=False)


@dataclass
class _Entry:
    fingerprint: str
    state: WorkflowState
    result: RecoveryResult | None = None


class ReliabilityController:
    """Single-event-loop, bounded in-process action protection and recovery.

    Entries are never evicted, including uncertain outcomes. A full controller
    refuses new work. Recreate only at a deliberate application retention boundary;
    protection does not survive restart. No external observation hook is introduced.
    """

    def __init__(
        self,
        *,
        policy: ReliabilityPolicy,
        authorization: AuthorizationPolicy,
        safety: SafetyPipeline,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Bind trusted policy, existing security boundaries and monotonic timing."""
        forbidden = {Failure.UNKNOWN, Failure.AUTHORIZATION, Failure.SAFETY}
        if (
            forbidden & (policy.retry_on | policy.fallback_on)
            or Failure.TERMINAL in policy.retry_on
        ):
            raise ValueError("Unknown failures cannot recover; terminal failures cannot retry.")
        self.policy = policy
        self.authorization = authorization
        self.safety = safety
        self.clock = clock
        self.sleeper = sleeper
        self._entries: dict[UUID, _Entry] = {}
        self._unresolved: set[asyncio.Task[AttemptResult]] = set()

    @property
    def retained_actions(self) -> int:
        """Return retained protection count, including pending and failed work."""
        return len(self._entries)

    def _admit(
        self,
        principal: Principal,
        target: Target,
        content: UntrustedContent,
        state: WorkflowState,
    ) -> WorkflowState:
        decision = self.authorization.enforce(
            target.decision,
            principal_id=principal.principal_id,
            tool_name=target.tool_name,
        )
        assessment = self.safety.assess_input(content, state.identity)
        self.authorization.enforce(
            target.decision,
            principal_id=principal.principal_id,
            tool_name=target.tool_name,
        )
        return state.validated_update(authorization=decision, safety=assessment.decision)

    async def execute(
        self,
        *,
        principal: Principal,
        state: WorkflowState,
        content: UntrustedContent,
        targets: tuple[Target, ...],
    ) -> RecoveryResult:
        """Execute one logical action or safely replay/refuse its existing record.

        Args:
            principal: Trusted application identity, never derived from content.
            state: Foundation state with stable key and initial budget.
            content: Untrusted effectful request; only its digest is retained.
            targets: Ordered trusted primary/fallback bindings; distinct tool names.

        Returns:
            Structured bounded outcome. Raw adapter exceptions are discarded.

        Raises:
            ValueError: If the trusted target plan or starting state is invalid.
        """
        if not targets or len({t.tool_name for t in targets}) != len(targets):
            raise ValueError("Provide a finite non-cycling target plan.")
        if len(targets) > self.policy.max_fallbacks + 1:
            raise ValueError("Target plan exceeds the fallback limit.")
        if state.evidence_class not in {
            EvidenceClass.DETERMINISTIC_FIXTURE,
            EvidenceClass.SIMULATED_FAILURE,
        }:
            raise ValueError("Story 3 requires local deterministic or simulated evidence.")
        if state.terminal_status is not None or state.retry_attempt or state.fallback_used:
            raise ValueError("Provide an initial workflow state.")
        start = self.clock()
        deadline = start + self.policy.deadline_seconds
        attempts = fallbacks = retries = 0
        history: list[str] = []
        cost = state.budget.cost_used_usd
        actual = state.usage.cost_usd
        tokens_in, tokens_out = state.usage.input_tokens, state.usage.output_tokens
        if actual > cost:
            raise ValueError("Initial usage cannot exceed accounted cost.")
        current = state

        def result(kind: str, output: UntrustedContent | None = None) -> RecoveryResult:
            elapsed = max(0.0, self.clock() - start)
            terminal = (
                TerminalStatus.SUCCEEDED
                if kind == "success"
                else TerminalStatus.DENIED
                if kind.endswith("denied")
                else TerminalStatus.FAILED
            )
            final = current.validated_update(
                terminal_status=terminal,
                retry_attempt=retries,
                fallback_used=bool(fallbacks),
                budget=BudgetState(
                    cost_limit_usd=state.budget.cost_limit_usd,
                    cost_used_usd=min(cost, state.budget.cost_limit_usd),
                ),
                usage=UsageRecord(
                    input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=actual
                ),
            )
            return RecoveryResult(
                state=final,
                classification=kind,
                attempts=attempts,
                fallbacks=fallbacks,
                elapsed_seconds=elapsed,
                remaining_attempts=self.policy.max_attempts - attempts,
                remaining_seconds=max(0.0, deadline - self.clock()),
                actual_cost_usd=actual,
                overage_usd=max(0.0, cost - state.budget.cost_limit_usd),
                output=output,
                history=tuple(history),
                reliability=ReliabilityResult(
                    attempts=attempts,
                    fallback_used=bool(fallbacks),
                    recovered=kind == "success" and attempts > 1,
                )
                if attempts
                else None,
            )

        try:
            current = self._admit(principal, targets[0], content, current)
        except AuthorizationDeniedError:
            return result("authorization_denied")
        if current.safety is None or current.safety.decision is Decision.DENY:
            return result("safety_denied")
        digest = hashlib.sha256(
            repr(
                (
                    principal.principal_id,
                    state.operation,
                    content.value,
                    content.source,
                    tuple(t.tool_name for t in targets),
                )
            ).encode()
        ).hexdigest()
        entry = self._entries.get(state.idempotency_key)
        if entry is not None:
            if entry.fingerprint != digest:
                return result("identity_denied")
            if entry.result is None:
                return result("pending")
            recorded = entry.result
            # Replay releases output only after current authority for the actual
            # successful fallback and output safety have both been checked.
            if recorded.output is not None:
                try:
                    replay_state = self._admit(
                        principal, targets[recorded.fallbacks], content, current
                    )
                except AuthorizationDeniedError:
                    return result("authorization_denied")
                if replay_state.safety is None or replay_state.safety.decision is Decision.DENY:
                    return result("safety_denied")
                if not self.safety.assess_output(recorded.output, state.identity).allowed:
                    return result("safety_denied")
                try:
                    self.authorization.enforce(
                        targets[recorded.fallbacks].decision,
                        principal_id=principal.principal_id,
                        tool_name=targets[recorded.fallbacks].tool_name,
                    )
                except AuthorizationDeniedError:
                    return result("authorization_denied")
            return recorded.model_copy(update={"replayed": True})
        if self._unresolved or any(e.result is None for e in self._entries.values()):
            return result("concurrency_exhausted")
        if len(self._entries) >= self.policy.capacity:
            return result("capacity_exhausted")
        entry = _Entry(digest, current)
        self._entries[state.idempotency_key] = entry
        try:
            outcome = None
            for index, target in enumerate(targets):
                if index:
                    fallbacks += 1
                for local_attempt in range(self.policy.attempts_per_target):
                    if attempts >= self.policy.max_attempts:
                        outcome = result("attempt_exhausted")
                        break
                    if self.clock() >= deadline:
                        outcome = result("time_exhausted")
                        break
                    try:
                        current = self._admit(principal, target, content, current)
                    except AuthorizationDeniedError:
                        outcome = result("authorization_denied")
                        break
                    if current.safety is None or current.safety.decision is Decision.DENY:
                        outcome = result("safety_denied")
                        break
                    if self.clock() >= deadline:
                        outcome = result("time_exhausted")
                        break
                    reservation = target.reservation_usd
                    if cost + reservation > state.budget.cost_limit_usd:
                        outcome = result("budget_exhausted")
                        break
                    cost += reservation  # Never refunded, even on cheap/failed calls.
                    attempts += 1
                    if local_attempt:
                        retries += 1

                    async def invoke(bound: Target = target) -> AttemptResult:
                        self.authorization.enforce(
                            bound.decision,
                            principal_id=principal.principal_id,
                            tool_name=bound.tool_name,
                        )
                        return await bound.invoke(state.idempotency_key, content)

                    task = asyncio.create_task(invoke())
                    done, _ = await asyncio.wait(
                        {task}, timeout=min(self.policy.timeout_seconds, deadline - self.clock())
                    )
                    if not done:
                        task.cancel()
                        self._unresolved.add(task)
                        task.add_done_callback(self._discard_late)
                        actual += reservation
                        history.append("timeout_unresolved")
                        outcome = result("timeout_unresolved")
                        break
                    try:
                        response = task.result()
                        if not isinstance(response, AttemptResult):
                            raise TypeError("Invalid adapter result")
                    except AuthorizationDeniedError:
                        outcome = result("authorization_denied")
                        break
                    except (Exception, asyncio.CancelledError):
                        # External operation boundary: never expose raw exceptions,
                        # nor infer no effect/zero usage from an unknown failure.
                        actual += reservation
                        history.append("unknown")
                        outcome = result("unknown")
                        break
                    history.append(response.failure.value if response.failure else "success")
                    actual += response.usage.cost_usd
                    tokens_in += response.usage.input_tokens
                    tokens_out += response.usage.output_tokens
                    cost += max(0.0, response.usage.cost_usd - reservation)
                    if (
                        tokens_in > 2_147_483_647
                        or tokens_out > 2_147_483_647
                        or not math.isfinite(actual)
                        or not math.isfinite(cost)
                    ):
                        tokens_in = min(tokens_in, 2_147_483_647)
                        tokens_out = min(tokens_out, 2_147_483_647)
                        actual = min(actual, 1.7976931348623157e308)
                        cost = min(cost, 1.7976931348623157e308)
                        outcome = result("accounting_exhausted")
                        break
                    if cost > state.budget.cost_limit_usd:
                        outcome = result("budget_exhausted")
                        break
                    if self.clock() >= deadline:
                        outcome = result("time_exhausted")
                        break
                    if response.failure is None:
                        if response.output is None:
                            outcome = result("malformed_result")
                        else:
                            assessment = self.safety.assess_output(response.output, state.identity)
                            current = current.validated_update(safety=assessment.decision)
                            if not assessment.allowed:
                                outcome = result("safety_denied")
                            elif self.clock() >= deadline:
                                outcome = result("time_exhausted")
                            else:
                                try:
                                    self.authorization.enforce(
                                        target.decision,
                                        principal_id=principal.principal_id,
                                        tool_name=target.tool_name,
                                    )
                                except AuthorizationDeniedError:
                                    outcome = result("authorization_denied")
                                else:
                                    outcome = result("success", response.output)
                        break
                    failure = response.failure
                    if failure in {Failure.AUTHORIZATION, Failure.SAFETY}:
                        outcome = result(failure.value)
                        break
                    if not response.repeat_safe:
                        outcome = result("effect_uncertain")
                        break
                    can_retry = (
                        failure in self.policy.retry_on
                        and local_attempt + 1 < self.policy.attempts_per_target
                    )
                    if can_retry:
                        wait = self.policy.backoff_seconds
                        if wait >= deadline - self.clock():
                            outcome = result("time_exhausted")
                            break
                        await self.sleeper(wait)
                        continue
                    if failure in self.policy.fallback_on and index + 1 < len(targets):
                        break
                    outcome = result(failure.value + "_exhausted")
                    break
                if outcome is not None:
                    break
            assert outcome is not None
            entry.result = outcome
            entry.state = outcome.state
            return outcome
        except BaseException:
            # Cancellation/host failure must retain protection and a safe terminal
            # record; do not erase the pending action and permit duplicate work.
            if "task" in locals() and not task.done():
                task.cancel()
                self._unresolved.add(task)
                task.add_done_callback(self._discard_late)
            entry.result = result("interrupted")
            raise

    def _discard_late(self, task: asyncio.Task[AttemptResult]) -> None:
        """Discard late output/errors without mutating the protected action result."""
        self._unresolved.discard(task)
        if not task.cancelled():
            task.exception()
