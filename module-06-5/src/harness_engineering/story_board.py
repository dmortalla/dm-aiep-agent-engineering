"""Deterministic composed story-board demonstration over accepted module services.

``python -m harness_engineering.story_board --directory <fresh directory>``.
Four governed segments run under disjoint trusted workflow identities and compose accepted
planning, scheduling, context, memory, capability, authorization, execution,
provider, orchestration, evaluation, cost, MCP, approval-lifecycle, and recovery
services in a fixed reproducible order. Everything is local and credential-free;
the MCP, SQLite approval, and SQLite effect paths are local-integration
evidence, not production, deployment, or remote protocol claims.
"""

import argparse
import hashlib
import json
import sqlite3
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from mcp import types
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.anomaly_signals import AnomalyDetector
from harness_engineering.approval_lifecycle import (
    ApprovalAction,
    ApprovalLifecycle,
    ApprovalLifecycleError,
    SuspendedWorkflow,
)
from harness_engineering.approval_persistence import ApprovalEventKind, SQLiteApprovalStore
from harness_engineering.approvals import (
    ActionBinding,
    ApprovalObservation,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalSafetyState,
    BindingStatus,
    HumanDecision,
    HumanDecisionKind,
    HumanIdentity,
)
from harness_engineering.capabilities import (
    CapabilityDefinition,
    CapabilityRegistry,
    CapabilitySelectionCriteria,
)
from harness_engineering.context import (
    ContextBudget,
    ContextCompressor,
    ContextItem,
    ContextManager,
)
from harness_engineering.cost_governance import (
    FixtureLedger,
    FixtureTariff,
    LedgerPolicy,
    ProviderAlias,
    TokenPolicy,
)
from harness_engineering.domain import EvidenceClass, RuntimeBudget, TrustLevel, WorkflowIdentity
from harness_engineering.effects import EffectDeclaration, EffectObservation, EffectSpec
from harness_engineering.errors import (
    AuthorityViolationError,
    BudgetExceededError,
    HarnessError,
)
from harness_engineering.evaluation import InlineInvariantMonitor
from harness_engineering.execution import BoundedToolExecutor, ExecutionContext, ExecutionLimits
from harness_engineering.governance_facts import GovernanceKind
from harness_engineering.latency import Measurement
from harness_engineering.lifecycle_controls import OffSwitch
from harness_engineering.mcp_discovery import MCPServiceMetadata
from harness_engineering.mcp_local import LocalMCPIntegration
from harness_engineering.memory import MemoryCandidate, MemoryDestination, MemoryRouter
from harness_engineering.observability import TelemetrySession
from harness_engineering.orchestration import (
    LifecycleInput,
    LifecyclePhase,
    LifecycleRuntime,
    PreferredPathUnavailable,
    RetryPolicy,
    StepResult,
    TransientStepError,
)
from harness_engineering.permissions import (
    ActionProposal,
    AuthorizationOutcome,
    AuthorizationPolicy,
    CapabilityAuthorizer,
    CapabilityPermissionPolicy,
    ExecutionScope,
    PermissionGrant,
    RiskLevel,
)
from harness_engineering.persistence import CheckpointIdentity, SQLiteCheckpointStore
from harness_engineering.planning import (
    ExecutableSubtask,
    ExecutionPlan,
    PlanningEngine,
    PriorityScheduler,
    SubtaskDefinition,
)
from harness_engineering.providers import OutputFilter, ProviderOutputRejected, ProviderRuntime
from harness_engineering.recovery import CheckpointedLifecycle
from harness_engineering.telemetry_projections import observe_step, observe_workflow
from harness_engineering.usage import UsageFacts, UsageState

_IDENTITY_CORE = WorkflowIdentity(
    workflow_id=UUID(int=0xA65001), thread_id=UUID(int=0xA65002)
)
_IDENTITY_MCP = WorkflowIdentity(
    workflow_id=UUID(int=0xA65003), thread_id=UUID(int=0xA65004)
)
_IDENTITY_APPROVAL = CheckpointIdentity(
    workflow_id=UUID(int=0xA65005), thread_id=UUID(int=0xA65006)
)
_IDENTITY_REDLINE = CheckpointIdentity(
    workflow_id=UUID(int=0xA65007), thread_id=UUID(int=0xA65008)
)
_IDENTITY_RECOVERY = CheckpointIdentity(
    workflow_id=UUID(int=0xA65009), thread_id=UUID(int=0xA6500A)
)
_SUMMARY = "The approved local ticket is open."
_MCP_SUMMARY = "Local fixture ticket is open."
_REMOTE_ERROR = -32603
_CHECK_IDS = (
    "deterministic-order",
    "dependency-scheduling",
    "context-construction",
    "context-compression",
    "memory-routing",
    "capability-selection",
    "authorization-outcomes",
    "governed-tool-execution",
    "retry-transient-classification",
    "fallback-graceful-degradation",
    "inline-invariant-monitor",
    "provider-attempt-ledger",
    "provider-output-filter",
    "ledger-timeout-settle",
    "ledger-reopen-state-and-hard-cap-denial",
    "anomaly-threshold-signals",
    "mcp-discovery-inert",
    "mcp-trusted-binding",
    "mcp-unbound-inert",
    "mcp-authorization-denial",
    "mcp-off-switch-redline",
    "mcp-transport-close",
    "approval-suspension",
    "approval-independent-decision",
    "approval-fresh-resume-completes",
    "approval-consumption-once",
    "approval-replay-rejected",
    "approval-out-of-band-consumption-redline",
    "recovery-committed-interruption",
    "recovery-fresh-no-replay",
    "recovery-repeated-fresh-idempotent",
)

_NONCLAIMS = (
    "All providers and MCP handlers are deterministic local fixtures; no live billing.",
    "No authentication, deployment, distributed transaction, or production-readiness evidence.",
    "MCP SDK memory transport only; no remote protocol or hostile-isolation guarantees.",
    "Effect verification uses a local SQLite file, not OS or power-loss durability evidence.",
    "Consumption is not atomic with external execution; no exactly-once execution claim.",
    "All generated or MCP data is data only and never grants authority or approves actions.",
)


class StoryBoardFailure(HarnessError):
    """Expected composed evidence was not demonstrated; never fabricate success."""


class LocalSentence(BaseModel):
    """Application-owned local tool data contract, never provider-selected output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sentence: str = Field(min_length=1, max_length=256)


class TicketQuery(BaseModel):
    """Application-owned MCP input contract, stronger than the advertised schema."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query: str = Field(min_length=1, max_length=64)


class ReviewNote(BaseModel):
    """Validated untrusted MCP result data, never permission or a next action."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    note: str = Field(min_length=1, max_length=256)


def _require(condition: bool, message: str) -> None:
    """Fail the story board with a fixed invariant name; nothing else is retained."""
    if not condition:
        raise StoryBoardFailure(f"Story board invariant failed: {message}.")


def _budget(**overrides: object) -> RuntimeBudget:
    """Return the frozen bound set; callers may tighten but never raise it."""
    base = {
        "workflow_deadline_seconds": 180.0,
        "latency_slo_p95_seconds": 5.0,
    } | {key: value for key, value in overrides.items()}
    return RuntimeBudget.model_validate(base)


def _approval_safety() -> ApprovalSafetyState:
    """Trusted current application safety facts, composed independently of history."""
    return ApprovalSafetyState.model_validate(
        {
            "action_blocklisted": False,
            "capability_blocklisted": False,
            "cancelled": False,
            "binding_status": BindingStatus.CURRENT,
            "authority_valid": True,
            "hard_budget_exhausted": False,
            "deadline_exhausted": False,
            "scope_authorized": True,
            "prior_denial": False,
        }
    )


def _declaration(
    task_id: str,
    actor: HumanIdentity,
    override: HumanIdentity,
    identity: CheckpointIdentity,
    *,
    confidence: float,
) -> ApprovalAction:
    """Trusted application declaration; never reconstructed from stored data."""
    return ApprovalAction(
        request=ApprovalRequest.model_validate(
            {
                "binding": ActionBinding(
                    workflow_id=identity.workflow_id,
                    thread_id=identity.thread_id,
                    pending_action_id=task_id,
                    action_version=1,
                ),
                "requester_id": "requester-1",
                "capability_id": "local",
                "action": "evaluate",
                "risk": RiskLevel.LOW,
                "consequential": False,
                "privileged_scope": False,
                "escalation_required": False,
                "escalation_reason": "",
            }
        ),
        observation=ApprovalObservation(confidence=confidence),
        policy=ApprovalPolicy(),
        approvers=(actor,),
        override_approvers=(override,),
        safety=lambda: _approval_safety(),
    )


class _LocalSource:
    """Synchronous local capability with independent trusted coordination only."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def handler(self, inputs: BaseModel, _context: ExecutionContext) -> LocalSentence:
        """Return deterministic local data after cooperative checkpointing."""
        self.calls.append("read")
        return LocalSentence(sentence=_SUMMARY)


class _Interrupted(RuntimeError):
    """Injected unexpected defect standing in for an interruption."""


class _LocalEffect:
    """Deterministic local effect stand-in with independently queryable commitment."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[str] = []
        self.verifications = 0
        self.now = [0.0]
        self.mode = "normal"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, value TEXT)"
            )

    def invoke(self, identity: object, timeout: float) -> StepResult:
        """Apply the external effect and optionally interrupt after the commit."""
        assert 0 < timeout <= 1
        self.now[0] += 0.1
        key = str(getattr(identity, "key", identity))
        self.calls.append(key)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO effects VALUES (?, ?)", (key, "verified result")
            )
        if self.mode == "after":
            raise _Interrupted("external commit happened, checkpoint did not")
        return StepResult(text="verified result")

    def verify(self, identity: object, _timeout: float) -> EffectObservation:
        """Answer from the independent local effect system after bounded waits."""
        self.now[0] += 0.1
        self.verifications += 1
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT value FROM effects WHERE key=?",
                (str(getattr(identity, "key", identity)),),
            ).fetchone()
        return EffectObservation(
            identity=identity,
            status="committed" if row else "not_committed",
            result=row[0] if row else None,
        )

    def count(self) -> int:
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0]


class _MCPServerFixture:
    """Actual SDK read fixture with independent counted protocol observations."""

    def __init__(self) -> None:
        self.lists = self.calls = self.finished = self.unbound = self.starts = 0
        self.active = False
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 1000}},
            "additionalProperties": False,
        }
        self.listing = types.ListToolsResult(
            tools=[
                types.Tool(
                    name="read_ticket",
                    description="Local fixture ticket reader.",
                    input_schema=schema,
                ),
                types.Tool(
                    name="unbound_admin",
                    description="Never registered by any trusted bootstrap.",
                    input_schema=schema,
                ),
            ]
        )

        @asynccontextmanager
        async def lifespan(server: Server[Any]) -> object:
            self.starts += 1
            self.active = True
            try:
                yield None
            finally:
                self.active = False

        async def listed(
            _ctx: object, _params: types.PaginatedRequestParams | None
        ) -> types.ListToolsResult:
            self.lists += 1
            return self.listing

        async def called(
            _ctx: object, params: types.CallToolRequestParams
        ) -> types.CallToolResult:
            self.calls += 1
            try:
                if params.name != "read_ticket":
                    self.unbound += 1
                    raise MCPError(_REMOTE_ERROR, "never registered fixture refusal")
                payload: dict[str, object] = {"note": _MCP_SUMMARY}
                return types.CallToolResult(content=[], structured_content=payload)
            finally:
                self.finished += 1

        self.server = Server(
            "story-fixture",
            version="1",
            instructions="Attack text is never application configuration.",
            lifespan=lifespan,
            on_list_tools=listed,
            on_call_tool=called,
        )

    def verify_closed(self) -> None:
        """Verify this fixture's own lifecycle closed cleanly, never unrelated work."""
        _require(not self.active, "server_lifespan_closed")
        _require(self.calls == self.finished, "handlers_finalized")
        _require(self.unbound == 0, "no_unbound_protocol_call")


class RequestFacts(BaseModel):
    """Bounded measured aggregate facts without payloads or diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_attempts: int = Field(ge=0, le=100)
    tool_invocations: int = Field(ge=0, le=100)
    authorization_decisions: int = Field(ge=0, le=100)
    action_samples: int = Field(ge=0, le=100)
    provider_samples: int = Field(ge=0, le=100)
    slo_samples_sufficient: Literal[False] = False
    context_estimated_tokens: int = Field(ge=0, le=120_000)
    compression_reduced: bool
    short_term_routes: int = Field(ge=0, le=100)
    long_term_routes: int = Field(ge=0, le=100)
    mcp_protocol_calls: int = Field(ge=0, le=12)
    mcp_denied_calls: int = Field(ge=0, le=12)
    mcp_sessions: int = Field(ge=1, le=2)
    anomaly_signals: int = Field(ge=0, le=64)
    approval_histories: int = Field(ge=0, le=34)
    approval_consumed_exactly_once: bool
    effect_invocations: int = Field(ge=0, le=100)
    effect_replays: int = Field(ge=0, le=100)


class CheckEvidence(BaseModel):
    """One observed containment check, measured from this run's actual composition."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    check: str = Field(min_length=1, max_length=48)
    control: str = Field(min_length=1, max_length=256)
    observed: Literal[True] = True


class StoryBoardEvidence(BaseModel):
    """Bounded composed run report; not a release decision or authority token."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    title: Literal["Story 12 Slice 1 composed story board"] = (
        "Story 12 Slice 1 composed story board"
    )
    sdk_version: Literal["2.3.0"]
    classification: tuple[Literal["deterministic_fixture"], Literal["local_integration"]] = (
        "deterministic_fixture",
        "local_integration",
    )
    identity: WorkflowIdentity
    checks: tuple[CheckEvidence, ...] = Field(min_length=31, max_length=31)
    facts: RequestFacts
    nonclaims: tuple[str, ...] = Field(default=_NONCLAIMS)

    @model_validator(mode="after")
    def verify_coverage(self) -> "StoryBoardEvidence":
        """Require the complete fixed measured check set in reproducible order."""
        if tuple(item.check for item in self.checks) != _CHECK_IDS or self.nonclaims != _NONCLAIMS:
            raise ValueError("Story board evidence is incomplete or inconsistent")
        return self


def story_board(directory: Path) -> StoryBoardEvidence:
    """Run the fixed four-segment composition and return bounded immutable evidence.

    Args:
        directory: New isolated artifact directory, retained for reviewer inspection.

    Returns:
        Bounded immutable report containing no executable authority.

    Raises:
        StoryBoardFailure: If any measured composition invariant fails.
        HarnessError: For accepted-boundary failures observed during the run.
        FileExistsError: The artifact directory already exists.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    sdk = version("mcp")
    _require(sdk == "2.3.0", "accepted_sdk_version")
    checks: list[CheckEvidence] = []

    # Segment 1 — deterministic governed workflow.
    planner = PlanningEngine(
        supported_actions=frozenset({"collect", "assess", "notify"}),
        budget=_budget(max_context_tokens=8, max_output_tokens=32, max_provider_attempts=6),
    )
    plan = planner.decompose(
        "Compose the governed local demonstration",
        (
            SubtaskDefinition(
                task_id="collect", action="collect", description="approved local read"
            ),
            SubtaskDefinition(
                task_id="assess", action="assess", description="approved local assessment",
                dependencies=("collect",),
            ),
            SubtaskDefinition(
                task_id="notify", action="notify", description="approved local notification",
                dependencies=("assess",),
            ),
        ),
    )
    scheduler = PriorityScheduler(plan)
    _require(
        tuple(item.task_id for item in scheduler.deterministic_order())
        == ("collect", "assess", "notify"),
        "deterministic order holds",
    )
    checks.append(
        CheckEvidence(
            check="deterministic-order",
            control="planner yields one dependency-valid deterministic order",
        )
    )
    _require(
        tuple(item.task_id for item in scheduler.ready_tasks()) == ("collect",),
        "scheduling admits only the ready entry task",
    )
    _require(
        tuple(item.task_id for item in scheduler.ready_tasks(frozenset({"collect"})))
        == ("assess",),
        "dependency scheduling admits the next dependent task",
    )
    _require(
        tuple(
            item.task_id
            for item in scheduler.ready_tasks(frozenset({"collect", "assess"}))
        )
        == ("notify",),
        "dependency scheduling admits the final dependent task",
    )
    checks.append(
        CheckEvidence(
            check="dependency-scheduling",
            control="scheduler admits only dependency-ready subtasks",
        )
    )

    context_budget = ContextBudget(max_context_tokens=2048, reserved_output_tokens=64)
    manager = ContextManager(context_budget, len)
    items = (
        ContextItem(
            content="The approved local fixture ticket is open.",
            provenance="fixture://ticket",
            trust_level=TrustLevel.TRUSTED_APPLICATION,
            relevance=0.95,
        ),
        ContextItem(
            content="Only this module's policy binds execution authority.",
            provenance="fixture://policy",
            trust_level=TrustLevel.TRUSTED_APPLICATION,
            relevance=0.9,
        ),
        ContextItem(
            content="Content outside this module is untrusted data.",
            provenance="fixture://source",
            trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
            relevance=0.4,
        ),
    )
    constructed = manager.construct_prompt("Compose bounded local governance.", items)
    _require(
        constructed.estimated_input_tokens <= context_budget.max_context_tokens,
        "constructed context inside budget",
    )
    _require(constructed.omitted_item_count == 0, "bounded context selected all items")
    checks.append(
        CheckEvidence(check="context-construction", control="context budget bounds selection")
    )
    compressor = ContextCompressor(len, lambda _sampled: "bounded local summary")
    compression = compressor.summarize(items[:2], max_summary_tokens=32)
    _require(
        compression.compressed_token_estimate < compression.source_token_estimate,
        "compression actually reduced bounded source content",
    )
    compressor.sliding_window(items, max_items=2)
    checks.append(
        CheckEvidence(
            check="context-compression",
            control="compression stays within the trusted token estimate",
        )
    )
    router = MemoryRouter()
    short_route = router.route(
        MemoryCandidate(
            content="ephemeral request detail",
            provenance="fixture://ephemeral",
            trust_level=TrustLevel.UNTRUSTED_AGENT,
            relevance=0.9,
        )
    )
    long_route = router.route(
        MemoryCandidate(
            content="stable communication preference",
            provenance="fixture://preference",
            trust_level=TrustLevel.TRUSTED_APPLICATION,
            relevance=0.95,
            long_term_requested=True,
        )
    )
    _require(
        short_route.destination is MemoryDestination.SHORT_TERM
        and long_route.destination is MemoryDestination.LONG_TERM_ELIGIBLE,
        "memory routing honors application destinations",
    )
    checks.append(
        CheckEvidence(
            check="memory-routing",
            control="memory routing grants no authority and honors policy destinations",
        )
    )

    registry = CapabilityRegistry()
    for definition in (
        CapabilityDefinition(
            capability_id="ticket.read",
            description="Read the approved local fixture ticket.",
            input_schema=LocalSentence,
            output_schema=LocalSentence,
            tags=("read",),
        ),
        CapabilityDefinition(
            capability_id="dispatch.note",
            description="Send one approved notification note.",
            input_schema=LocalSentence,
            output_schema=LocalSentence,
            tags=("write",),
        ),
        CapabilityDefinition(
            capability_id="secret.file",
            description="Never-granted local file read.",
            input_schema=LocalSentence,
            output_schema=LocalSentence,
            tags=("read",),
        ),
    ):
        registry.register(definition)
    selected = registry.select(CapabilitySelectionCriteria(required_tags=("read",)))
    _require(
        tuple(item.capability_id for item in selected) == ("secret.file", "ticket.read"),
        "selection returns classified metadata in lexical identity order",
    )
    checks.append(
        CheckEvidence(
            check="capability-selection",
            control="tag selection returns metadata candidates, never permissions",
        )
    )
    frozen_policy = AuthorizationPolicy(
        capabilities=(
            CapabilityPermissionPolicy(
                capability_id="ticket.read",
                action="read",
                scope=ExecutionScope(resources=("ticket",)),
                risk=RiskLevel.LOW,
                approval_required=False,
            ),
            CapabilityPermissionPolicy(
                capability_id="dispatch.note",
                action="read",
                scope=ExecutionScope(resources=("note",)),
                risk=RiskLevel.LOW,
                approval_required=True,
            ),
            CapabilityPermissionPolicy(
                capability_id="secret.file",
                action="read",
                scope=ExecutionScope(resources=("file",)),
                risk=RiskLevel.LOW,
                approval_required=False,
            ),
        )
    )
    scoped_grant = PermissionGrant(
        principal_id="reviewer-1",
        identity=_IDENTITY_CORE,
        capability_id="ticket.read",
        action="read",
        scope=ExecutionScope(resources=("ticket", "archive")),
    )
    granted_noreusable = PermissionGrant(
        principal_id="reviewer-1",
        identity=_IDENTITY_CORE,
        capability_id="dispatch.note",
        action="read",
        scope=ExecutionScope(resources=("note",)),
    )
    authorizer = CapabilityAuthorizer(
        registry, frozen_policy, "reviewer-1", _IDENTITY_CORE,
        grants=(scoped_grant, granted_noreusable),
    )
    proposal_read = ActionProposal(capability_id="ticket.read", action="read", resource_id="ticket")
    probes = (
        (proposal_read, AuthorizationOutcome.ALLOW),
        (
            ActionProposal(capability_id="ticket.read", action="read", resource_id="other"),
            AuthorizationOutcome.DENY,
        ),
        (
            ActionProposal(capability_id="dispatch.note", action="read", resource_id="note"),
            AuthorizationOutcome.APPROVAL_REQUIRED,
        ),
        (
            ActionProposal(capability_id="secret.file", action="read", resource_id="file"),
            AuthorizationOutcome.DENY,
        ),
    )
    decisions = tuple(authorizer.authorize(proposal) for proposal, _expected in probes)
    _require(
        tuple(item.outcome for item in decisions)
        == tuple(expected for _proposal, expected in probes),
        "authorization outcomes match the frozen policy",
    )
    _require(
        decisions[2].approval is not None
        and decisions[2].approval.proposal.resource_id == "note",
        "approval-required decision carries a pending non-authoritative payload",
    )
    checks.append(
        CheckEvidence(
            check="authorization-outcomes",
            control="authorization is independent of selection and denies by default",
        )
    )

    session = TelemetrySession(_IDENTITY_CORE, evidence=EvidenceClass.DETERMINISTIC)
    _require(session.evidence is EvidenceClass.DETERMINISTIC, "segment evidence is declared")
    anomalies = AnomalyDetector(evidence=session.evidence, telemetry=session)
    tokens = TokenPolicy(
        step_count=2,
        input_per_call=8,
        output_per_call=32,
        input_per_step=24,
        output_per_step=96,
        workflow_attempts=6,
    )
    ledger_policy = LedgerPolicy(
        workflow_id=_IDENTITY_CORE.workflow_id,
        thread_id=_IDENTITY_CORE.thread_id,
        cap_units=160,
        tariff=FixtureTariff(
            provider=ProviderAlias.FAKE,
            input_units_per_million=1_000_000,
            output_units_per_million=1_000_000,
        ),
        tokens=tokens,
        action_ids=("assess", "notify"),
    )
    budget = _budget(max_context_tokens=8, max_output_tokens=32, max_provider_attempts=6)
    ledger = FixtureLedger(
        directory / "cost.sqlite",
        ledger_policy,
        create=True,
        telemetry=session,
        anomalies=anomalies,
    )
    provider = ProviderRuntime(
        budget=budget,
        action_ids=("assess", "notify"),
        telemetry=session,
        ledger=ledger,
        anomalies=anomalies,
        output_filter=OutputFilter(blocked_terms=("classified",)),
    )
    source = _LocalSource()
    executor = BoundedToolExecutor(
        registry,
        authorizer,
        {"ticket.read": source.handler},
        {"ticket.read": ExecutionLimits(
            timeout_seconds=2.0,
            max_input_bytes=1024,
            max_output_bytes=1024,
            max_work_units=100,
        )},
        budget,
    )
    waits: list[float] = []
    collected: list[bool] = []

    def collect_step(task: ExecutableSubtask, request: LifecycleInput) -> StepResult:
        if not collected:
            collected.append(True)
            raise TransientStepError("Trusted retry-safe local read classification.")
        output = executor.execute(proposal_read, {"sentence": request.text or "collect"})
        return StepResult(text=output.sentence)

    def assess_step(_task: ExecutableSubtask, _request: LifecycleInput) -> StepResult:
        result = StepResult(text="")
        for _ in range(2):
            generated = provider.generate({"prompt": "x"}, action_id="assess")
            result = StepResult(text=generated.text)
        return result

    def notify_step(_task: ExecutableSubtask, _request: LifecycleInput) -> StepResult:
        raise PreferredPathUnavailable("The trusted primary delivery path is unavailable.")

    def dispatch(task: ExecutableSubtask, request: LifecycleInput) -> StepResult:
        if task.task_id == "collect":
            return collect_step(task, request)
        if task.task_id == "assess":
            return assess_step(task, request)
        return notify_step(task, request)

    def fallback(_task: ExecutableSubtask, _request: LifecycleInput) -> StepResult:
        output = executor.execute(proposal_read, {"sentence": "fallback notification"})
        generated = provider.generate({"prompt": "x"}, action_id="notify")
        return StepResult(text=f"fallback:{output.sentence}|{generated.text}")

    runtime = LifecycleRuntime(
        plan,
        observe_step(session, dispatch, step_ids=("collect", "assess", "notify")),
        retry_policy=RetryPolicy(max_retries=1, failure_threshold=3),
        wait=waits.append,
        fallback_step=fallback,
        clock=lambda: 0.0,
    )
    monitor = InlineInvariantMonitor(runtime.bounds())
    state = observe_workflow(
        session,
        lambda: runtime.run_observed(LifecycleInput(text="govern"), observer=monitor),
    )
    _require(state.phase is LifecyclePhase.COMPLETED, "governed workflow completes")
    _require(monitor.boundaries_checked >= 1, "inline monitor observes boundaries")
    checks.append(
        CheckEvidence(
            check="inline-invariant-monitor",
            control="resume-safe life invariants hold on every consumed attempt",
        )
    )
    _require(len(collected) == 1, "transient classification stopped the first collect attempt")
    _require(tuple(waits) == (0.1, 0.1), "retry and fallback used bounded backoff delays")
    checks.append(
        CheckEvidence(
            check="retry-transient-classification",
            control="adapter-classified transient failure retries once inside budget",
        )
    )
    _require(
        state.fallback_task_ids == ("notify",) and state.fallback_activation_attempts == (4,),
        "fallback activated once after the preferred path refused",
    )
    _require(
        state.completed_task_ids == ("collect", "assess", "notify"),
        "all governed subtasks completed",
    )
    checks.append(
        CheckEvidence(
            check="fallback-graceful-degradation",
            control="preferred-path refusal reroutes to the trusted single fallback",
        )
    )
    _require(len(source.calls) == 2, "each executor-reaching governed attempt reauthorized")
    checks.append(
        CheckEvidence(
            check="governed-tool-execution",
            control="every governed attempt that reaches the tool reauthorizes first",
        )
    )
    _require(provider.attempts == 3, "provider attempts consumed inside frozen limits")
    _require(len(provider.usage_receipts) == 3, "each attempt settled one bounded receipt")
    checks.append(
        CheckEvidence(
            check="provider-attempt-ledger",
            control="provider attempts and receipts stay inside the frozen budget",
        )
    )
    rejected = ProviderRuntime(
        budget=_budget(max_output_tokens=32, max_provider_attempts=3),
        action_ids=("probe",),
        output_filter=OutputFilter(blocked_terms=("deterministic",)),
    )
    refused: bool = False
    try:
        rejected.generate({"prompt": "x"}, action_id="probe")
    except ProviderOutputRejected:
        refused = True
    _require(refused and rejected.attempts == 1, "filtered output fails closed on one attempt")
    checks.append(
        CheckEvidence(
            check="provider-output-filter",
            control="filtered provider output never returns and consumes the attempt",
        )
    )

    uncertain = ledger.reserve(1)
    before_settle = ledger.snapshot()
    ledger.settle(uncertain, UsageFacts(state=UsageState.TIMEOUT))
    after_settle = ledger.snapshot()
    _require(
        after_settle.committed_units + after_settle.outstanding_units
        >= before_settle.committed_units + before_settle.outstanding_units,
        "uncertainty retains the conservative exposure bound",
    )
    checks.append(
        CheckEvidence(
            check="ledger-timeout-settle",
            control="uncertain fixture attempts keep their full conservative bound",
        )
    )
    reopened = FixtureLedger(directory / "cost.sqlite", ledger_policy)
    _require(reopened.snapshot() == after_settle, "reopen preserves journal state exactly")
    denied: bool = False
    try:
        reopened.reserve(2)
    except BudgetExceededError:
        denied = True
    _require(denied, "hard exposure cap denies further reservation")
    checks.append(
        CheckEvidence(
            check="ledger-reopen-state-and-hard-cap-denial",
            control="reopened ledger preserves state and denies beyond the hard cap",
        )
    )

    for kind, count in (
        (GovernanceKind.RETRY_BURST, 2),
        (GovernanceKind.DENIAL_BURST, 3),
        (GovernanceKind.PROVIDER_FAILURE_BURST, 3),
        (GovernanceKind.TOOL_FREQUENCY, 10),
    ):
        for _ in range(count):
            anomalies.observe(kind)
    signal_kinds = tuple(sorted({item.facts.kind for item in anomalies.snapshot()}))
    _require(
        signal_kinds == (
            "budget_spike",
            "denial_burst",
            "provider_failure_burst",
            "retry_burst",
            "tool_frequency",
        ),
        "governance event and ledger observations arm five bounded advisory rules",
    )
    _require(provider.advisory_failures == 0, "advisory observation never broke the source")
    checks.append(
        CheckEvidence(
            check="anomaly-threshold-signals",
            control="governance event observations arm bounded advisory signals",
        )
    )

    # Segment 2 — real SDK MCP integration over memory transport.
    fixture = _MCPServerFixture()
    with LocalMCPIntegration(fixture.server, io_timeout_seconds=2.0) as connection:
        snapshot = connection.discover()
        _require(len(snapshot.candidates) == 2, "discovery yields exactly two candidates")
        _require(
            not connection.capabilities.list_capabilities(),
            "discovery never registers application capabilities",
        )
        candidate = next(item for item in snapshot.candidates if item.remote_name == "read_ticket")
        unbound = next(item for item in snapshot.candidates if item.remote_name == "unbound_admin")
        _require(
            candidate.trust == "untrusted_mcp"
            and not candidate.grants_authority
            and not unbound.grants_authority,
            "candidates stay inert metadata",
        )
        _require(fixture.calls == 0, "discovery invokes no tool handler")
        checks.append(
            CheckEvidence(
                check="mcp-discovery-inert",
                control="discovery yields inert untrusted candidates without registration",
            )
        )
        app_definition = CapabilityDefinition(
            capability_id="ticket.read",
            description="Local fixture ticket read.",
            input_schema=TicketQuery,
            output_schema=ReviewNote,
        )
        handle = connection.register(
            candidate,
            expected_service=MCPServiceMetadata("story-fixture", "1"),
            expected_tool="read_ticket",
            capability=app_definition,
            limits=ExecutionLimits(
                timeout_seconds=2.0,
                max_input_bytes=1024,
                max_output_bytes=1024,
                max_work_units=100,
            ),
        )
        _require(
            tuple(item.capability_id for item in connection.capabilities.list_capabilities())
            == ("ticket.read",),
            "trusted bootstrap registered exactly the bound application capability",
        )
        checks.append(
            CheckEvidence(
                check="mcp-trusted-binding",
                control="trusted binding binds the original candidate to application contracts",
            )
        )
        switch = OffSwitch()
        current: list[CapabilityAuthorizer] = [
            CapabilityAuthorizer(
                connection.capabilities,
                AuthorizationPolicy(
                    capabilities=(
                        CapabilityPermissionPolicy(
                            capability_id="ticket.read",
                            action="read",
                            scope=ExecutionScope(resources=("ticket",)),
                            risk=RiskLevel.LOW,
                            approval_required=False,
                        ),
                    )
                ),
                "reviewer-mcp",
                _IDENTITY_MCP,
                grants=(
                    PermissionGrant(
                        principal_id="reviewer-mcp",
                        identity=_IDENTITY_MCP,
                        capability_id="ticket.read",
                        action="read",
                        scope=ExecutionScope(resources=("ticket", "other")),
                    ),
                ),
            )
        ]
        mcp_runtime = connection.create_runtime(
            current_authorizer=lambda: current[0],
            budget=_budget(workflow_deadline_seconds=10.0, max_tool_calls=2),
            off_switch=switch,
        )
        mcp_proposal = ActionProposal(
            capability_id="ticket.read", action="read", resource_id="ticket"
        )
        mcp_output = mcp_runtime.execute(handle, mcp_proposal, {"query": "status"})
        _require(
            isinstance(mcp_output, ReviewNote) and mcp_output.note == _MCP_SUMMARY,
            "validated untrusted result stayed inside the declared contract",
        )
        _require(fixture.calls == 1, "exactly one authorized protocol call")
        checks.append(
            CheckEvidence(
                check="mcp-unbound-inert",
                control="the unbound candidate never enters the runtime or protocol",
            )
        )
        current[0] = CapabilityAuthorizer(
            connection.capabilities,
            AuthorizationPolicy(
                capabilities=(
                    CapabilityPermissionPolicy(
                        capability_id="ticket.read",
                        action="read",
                        scope=ExecutionScope(resources=("ticket",)),
                        risk=RiskLevel.LOW,
                        approval_required=False,
                    ),
                )
            ),
            "reviewer-mcp",
            _IDENTITY_MCP,
            grants=(),
        )
        current_denied: bool = False
        try:
            mcp_runtime.execute(handle, mcp_proposal, {"query": "status"})
        except AuthorityViolationError:
            current_denied = True
        _require(
            current_denied and fixture.calls == 1,
            "current authorization denies without another protocol call",
        )
        checks.append(
            CheckEvidence(
                check="mcp-authorization-denial",
                control="current controls deny execution without invoking the untrusted tool",
            )
        )
        switch.activate()
        switch_denied: bool = False
        try:
            mcp_runtime.execute(handle, mcp_proposal, {"query": "status"})
        except AuthorityViolationError:
            switch_denied = True
        _require(
            switch_denied and fixture.calls == 1,
            "off-switch latches and denies without another protocol call",
        )
        checks.append(
            CheckEvidence(
                check="mcp-off-switch-redline",
                control="mid-session cancellation latches and rejects every later call",
            )
        )
    fixture.verify_closed()
    checks.append(
        CheckEvidence(
            check="mcp-transport-close",
            control="the SDK session and server lifecycle close cleanly after denial",
        )
    )

    # Segment 3 — durable human approval lifecycle.
    humans = (HumanIdentity(principal_id="approver"), HumanIdentity(principal_id="override-now"))
    names: list[str] = []
    elapsed = [0.0]
    approval_dir = directory / "approval"
    approval_dir.mkdir()
    first = _approval_lifecycle(approval_dir, _IDENTITY_APPROVAL, humans, names, elapsed)
    suspended = first.start(LifecycleInput(text="durable local approval request"))
    _require(
        isinstance(suspended, SuspendedWorkflow) and names == ["a"],
        "workflow suspends without waiting for a human",
    )
    _require(
        _checkpoint_load(approval_dir, _IDENTITY_APPROVAL).pending_work == ("b",),
        "checkpoint records the pending guarded action",
    )
    checks.append(
        CheckEvidence(
            check="approval-suspension",
            control="guarded work suspends durably without blocking on a human",
        )
    )
    elapsed[0] = 30.0
    store = SQLiteApprovalStore(approval_dir / "approvals.sqlite")
    fresh_humans = (
        HumanIdentity(principal_id="fresh-approver"),
        HumanIdentity(principal_id="fresh-override"),
    )
    fresh_actions = (
        _declaration("a", fresh_humans[0], fresh_humans[1], _IDENTITY_APPROVAL, confidence=1.0),
        _declaration("b", fresh_humans[0], fresh_humans[1], _IDENTITY_APPROVAL, confidence=0.5),
    )
    store.decide(
        suspended.binding,
        HumanDecision(
            binding=suspended.binding,
            kind=HumanDecisionKind.APPROVE,
            evidence="local review",
            override_reason="",
        ),
        evaluator=fresh_actions[1].evaluator(),
        actor=fresh_humans[0],
        safety=fresh_actions[1].safety(),
    )
    _require(
        store.load(suspended.binding).status is ApprovalEventKind.APPROVED,
        "independent store recorded the approved decision",
    )
    checks.append(
        CheckEvidence(
            check="approval-independent-decision",
            control="a separately constructed store records the current human decision",
        )
    )
    fresh = _approval_lifecycle(approval_dir, _IDENTITY_APPROVAL, fresh_humans, names, elapsed)
    outcome = fresh.resume(
        LifecycleInput(text="durable local approval request"), actor=fresh_humans[0]
    )
    _require(
        outcome.phase is LifecyclePhase.COMPLETED and names == ["a", "b"],
        "fresh bootstrap resumed and completed the guarded work",
    )
    _require(
        SQLiteCheckpointStore(approval_dir / "checkpoints.sqlite")
        .load(_IDENTITY_APPROVAL)
        .consumed_budget.elapsed_milliseconds
        >= 31_000,
        "workflow age includes the human waiting interval",
    )
    checks.append(
        CheckEvidence(
            check="approval-fresh-resume-completes",
            control="a fresh trusted bootstrap resumes after the recorded decision",
        )
    )
    history = store.load(suspended.binding)
    _require(
        history.status is ApprovalEventKind.CONSUMED and len(history.events) == 3,
        "approval consumed exactly once through the durable lifecycle",
    )
    checks.append(
        CheckEvidence(
            check="approval-consumption-once",
            control="the durable approval is consumed exactly once at execution",
        )
    )
    replay = _approval_lifecycle(approval_dir, _IDENTITY_APPROVAL, fresh_humans, names, elapsed)
    replay_denied: bool = False
    try:
        replay.resume(LifecycleInput(text="durable local approval request"), actor=fresh_humans[0])
    except ApprovalLifecycleError:
        replay_denied = True
    _require(replay_denied and names == ["a", "b"], "replay after consumption is rejected")
    checks.append(
        CheckEvidence(
            check="approval-replay-rejected",
            control="consumed approvals cannot authorize a second resume",
        )
    )
    redline_dir = directory / "approval-redline"
    redline_dir.mkdir()
    redline_names: list[str] = []
    redline_actions = (
        _declaration("a", humans[0], humans[1], _IDENTITY_REDLINE, confidence=1.0),
        _declaration("b", humans[0], humans[1], _IDENTITY_REDLINE, confidence=0.5),
    )
    first_redline = _approval_lifecycle(
        redline_dir, _IDENTITY_REDLINE, humans, redline_names, elapsed
    )
    first_redline.start(LifecycleInput(text="durable redline request"))
    redline_store = SQLiteApprovalStore(redline_dir / "approvals.sqlite")
    redline_store.decide(
        redline_actions[1].request.binding,
        HumanDecision(
            binding=redline_actions[1].request.binding,
            kind=HumanDecisionKind.APPROVE,
            evidence="local redline review",
            override_reason="",
        ),
        evaluator=redline_actions[1].evaluator(),
        actor=humans[0],
        safety=redline_actions[1].safety(),
    )
    redline_store.consume(
        redline_actions[1].request.binding,
        evaluator=redline_actions[1].evaluator(),
        actor=humans[0],
        safety=_approval_safety(),
    )
    out_of_band = _approval_lifecycle(
        redline_dir, _IDENTITY_REDLINE, humans, redline_names, elapsed
    )
    out_of_band_denied: bool = False
    try:
        out_of_band.resume(LifecycleInput(text="durable redline request"), actor=humans[0])
    except ApprovalLifecycleError:
        out_of_band_denied = True
    _require(
        out_of_band_denied and redline_names == ["a"],
        "out-of-band consumption never becomes a transferable execution token",
    )
    checks.append(
        CheckEvidence(
            check="approval-out-of-band-consumption-redline",
            control="direct store consumption cannot drive a lifecycle resume",
        )
    )

    # Segment 4 — recovery with exactly-once local effect construction.
    recovery_dir = directory / "recovery"
    recovery_dir.mkdir()
    effect = _LocalEffect(recovery_dir / "external.sqlite")
    effect_spec = EffectSpec(
        application="story-board-local-effect",
        work_id="step-0",
        operation="write-v1",
        input_digest=hashlib.sha256(b"fixed accepted value").hexdigest(),
    )
    plan_recovery = ExecutionPlan(
        goal="Checkpointed local effect evidence",
        budget=_budget(),
        tasks=(
            ExecutableSubtask(task_id="step-0", description="one committed local effect"),
        ),
    )
    recovery_request = LifecycleInput(text="untrusted request cannot select effects")

    def interrupting_runtime() -> CheckpointedLifecycle:
        return CheckpointedLifecycle(
            LifecycleRuntime(
                plan_recovery,
                lambda _task, _request: StepResult(text="pure result"),
                clock=lambda: effect.now[0],
                wait=lambda _seconds: None,
            ),
            SQLiteCheckpointStore(recovery_dir / "checkpoints.sqlite"),
            _IDENTITY_RECOVERY,
            effects=(
                EffectDeclaration(effect_spec, effect.invoke, effect.verify, allow_retry=True),
            ),
        )

    effect.mode = "after"
    interrupted = False
    try:
        interrupting_runtime().run(recovery_request)
    except _Interrupted:
        interrupted = True
    _require(interrupted and effect.count() == 1, "external commit happened before the stop")
    checks.append(
        CheckEvidence(
            check="recovery-committed-interruption",
            control="interruption after the external commit keeps the committed result",
        )
    )
    effect.mode = "normal"
    fresh_effect = _LocalEffect(recovery_dir / "external.sqlite")
    recovered = CheckpointedLifecycle(
        LifecycleRuntime(
            plan_recovery,
            lambda _task, _request: StepResult(text="pure result"),
            clock=lambda: fresh_effect.now[0],
            wait=lambda _seconds: None,
        ),
        SQLiteCheckpointStore(recovery_dir / "checkpoints.sqlite"),
        _IDENTITY_RECOVERY,
        effects=(
            EffectDeclaration(
                effect_spec, fresh_effect.invoke, fresh_effect.verify, allow_retry=True
            ),
        ),
    ).recover(recovery_request, restart_safe_work=frozenset())
    _require(
        recovered.phase is LifecyclePhase.COMPLETED
        and recovered.results[0].text == "verified result",
        "fresh recovery reconstructed the committed effect",
    )
    _require(fresh_effect.calls == [], "fresh recovery replays nothing")
    _require(effect.count() == 1, "the external effect system applied exactly one write")
    checks.append(
        CheckEvidence(
            check="recovery-fresh-no-replay",
            control="fresh recovery verifies the commit and replays nothing",
        )
    )
    repeated = _LocalEffect(recovery_dir / "external.sqlite")
    repeated_recovery = CheckpointedLifecycle(
        LifecycleRuntime(
            plan_recovery,
            lambda _task, _request: StepResult(text="pure result"),
            clock=lambda: repeated.now[0],
            wait=lambda _seconds: None,
        ),
        SQLiteCheckpointStore(recovery_dir / "checkpoints.sqlite"),
        _IDENTITY_RECOVERY,
        effects=(
            EffectDeclaration(
                effect_spec, repeated.invoke, repeated.verify, allow_retry=True
            ),
        ),
    ).recover(recovery_request, restart_safe_work=frozenset())
    _require(
        repeated_recovery.phase is LifecyclePhase.COMPLETED
        and repeated_recovery.results[0].text == "verified result",
        "repeated fresh recovery stays idempotent",
    )
    _require(
        len(repeated.calls) == 0,
        "repeated recovery replays zero external invocations",
    )
    _require(effect.count() == 1, "the external effect system still holds one write")
    checks.append(
        CheckEvidence(
            check="recovery-repeated-fresh-idempotent",
            control="repeated fresh recovery completes idempotently without effect replays",
        )
    )

    provider_reports = tuple(
        report
        for report in session.reports()
        if report.cohort.measurement is Measurement.PROVIDER
    )
    _require(
        len(provider_reports) == 1 and provider_reports[0].sample_count == 3,
        "provider latency measurement retained its cohort window",
    )
    _require(
        not provider_reports[0].sufficient_samples,
        "the sample window is insufficient for any latency SLO claim",
    )
    action_report = next(
        report
        for report in session.reports()
        if report.cohort.measurement is Measurement.ACTION
        and report.cohort.outcome.value == "returned"
    )
    ordered = {item.check: item for item in checks}
    _require(set(ordered) == set(_CHECK_IDS), "all measured checks are retained once")
    return StoryBoardEvidence(
        sdk_version=sdk,
        identity=_IDENTITY_CORE,
        checks=tuple(ordered[name] for name in _CHECK_IDS),
        facts=RequestFacts(
            provider_attempts=provider.attempts,
            tool_invocations=len(source.calls),
            authorization_decisions=len(decisions),
            action_samples=action_report.sample_count,
            provider_samples=provider_reports[0].sample_count,
            slo_samples_sufficient=False,
            context_estimated_tokens=constructed.estimated_input_tokens,
            compression_reduced=(
                compression.compressed_token_estimate < compression.source_token_estimate
            ),
            short_term_routes=1 * (short_route.destination is MemoryDestination.SHORT_TERM),
            long_term_routes=1 * (long_route.destination is MemoryDestination.LONG_TERM_ELIGIBLE),
            mcp_protocol_calls=fixture.calls,
            mcp_denied_calls=2,
            mcp_sessions=fixture.starts,
            anomaly_signals=len(anomalies.snapshot()),
            approval_histories=2,
            approval_consumed_exactly_once=True,
            effect_invocations=len(effect.calls),
            effect_replays=len(fresh_effect.calls) + len(repeated.calls),
        ),
        nonclaims=_NONCLAIMS,
    )


def _approval_lifecycle(
    directory: Path,
    identity: CheckpointIdentity,
    humans: tuple[HumanIdentity, HumanIdentity],
    names: list[str],
    elapsed: list[float],
    actions: tuple[ApprovalAction, ...] | None = None,
) -> ApprovalLifecycle:
    """Construct an entirely fresh trusted approval lifecycle bootstrap."""

    def execute(task: ExecutableSubtask, _data: LifecycleInput) -> StepResult:
        names.append(task.task_id)
        elapsed[0] += 1.0
        return StepResult(text=f"done:{task.task_id}")

    chosen = ExecutionPlan(
        goal="Checkpointed local HITL",
        budget=_budget(),
        tasks=(
            ExecutableSubtask(task_id="a", description="safe local prelude"),
            ExecutableSubtask(
                task_id="b", description="protected local result", dependencies=("a",)
            ),
        ),
    )
    return ApprovalLifecycle(
        chosen,
        execute,
        SQLiteCheckpointStore(directory / "checkpoints.sqlite"),
        SQLiteApprovalStore(directory / "approvals.sqlite"),
        identity,
        actions
        if actions is not None
        else (
            _declaration("a", humans[0], humans[1], identity, confidence=1.0),
            _declaration("b", humans[0], humans[1], identity, confidence=0.5),
        ),
        restart_safe_work=frozenset(task.task_id for task in chosen.tasks),
        elapsed_seconds=lambda: elapsed[0],
        clock=lambda: elapsed[0],
        cancellation=lambda: False,
        wait=lambda _seconds: None,
    )


def _checkpoint_load(directory: Path, identity: CheckpointIdentity):
    return SQLiteCheckpointStore(directory / "checkpoints.sqlite").load(identity)



def main() -> None:
    """Run one new local story board and print self-describing structured JSON."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the Story 12 Slice 1 composed story board. Use a fresh directory "
            "outside the repository; local fixture state is retained for review."
        )
    )
    parser.add_argument(
        "--directory", type=Path, required=True, help="Fresh artifact directory"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(json.loads(story_board(args.directory).model_dump_json()), indent=2))
    except (StoryBoardFailure, HarnessError) as exc:
        print(json.dumps({"failure": str(exc), "cause": repr(exc.__cause__)}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
