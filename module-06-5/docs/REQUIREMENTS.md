# Module 6.5 - Requirements

## Status

APPROVED - Human-approved requirements baseline, 2026-10-10.

These requirements are derived from AUTHORITATIVE_SOURCE.md.
The authoritative source remains controlling if any derived requirement conflicts with it.
No requirement in this document is frozen until human approval.

## Objective

REQ-OBJ-001: The module shall produce an agent-engineering system that demonstrates end-to-end operational control and governance from task decomposition through safe execution, state recovery, human oversight, and cost governance.

## Task Planning and Decomposition

REQ-PLAN-001: The runtime shall decompose a high-level goal into executable subtasks.
REQ-PLAN-002: The runtime shall represent dependencies among subtasks.
REQ-PLAN-003: The runtime shall support priority-aware task execution.

## Prompt, Context, and Memory Orchestration

REQ-CTX-001: The runtime shall support dynamic prompt construction.
REQ-CTX-002: The runtime shall enforce or account for context-window budgets.
REQ-CTX-003: The runtime shall route information between short-term and long-term memory mechanisms.

## Context Packing and Compression

REQ-COMP-001: The runtime shall construct context with explicit token-efficiency considerations.
REQ-COMP-002: The runtime shall support summarization-based context compression.
REQ-COMP-003: The runtime shall support a sliding-window context strategy.

## Tool Routing and Permissions

REQ-TOOL-001: The runtime shall support dynamic tool selection.
REQ-TOOL-002: The runtime shall maintain a capability registry for available tools.
REQ-TOOL-003: Tool access shall be constrained by explicit permission scope.
REQ-TOOL-004: Tool execution shall support a sandboxed execution boundary.

## Execution Control

REQ-EXEC-001: Retry behavior shall support exponential backoff.
REQ-EXEC-002: External or failure-prone operations shall support circuit-breaker behavior where applicable.
REQ-EXEC-003: The runtime shall support graceful degradation when a preferred execution path is unavailable.
REQ-EXEC-004: The runtime shall enforce explicit hard-stop conditions.

## Checkpointing, Resume, and Recovery

REQ-REC-001: Execution state shall be persistable.
REQ-REC-002: The runtime shall support state snapshots or checkpoints.
REQ-REC-003: Interrupted execution shall support crash recovery and resume.
REQ-REC-004: Resume behavior shall support idempotent re-entry.

## Human Approval and Escalation

REQ-HITL-001: Human-approval routing shall support confidence-based thresholds.
REQ-HITL-002: Human approval shall support asynchronous interaction rather than requiring only synchronous blocking input.
REQ-HITL-003: Human overrides and approval decisions shall produce an auditable trail.

## MCP Integration

REQ-MCP-001: The module shall demonstrate MCP-based registration of external or enterprise capabilities.
REQ-MCP-002: The MCP integration shall demonstrate service or capability discovery.
REQ-MCP-003: MCP capability exchange shall be constrained by explicit security boundaries.

## Observability

REQ-OBS-001: Runtime execution shall emit structured span or equivalent structured trace information.
REQ-OBS-002: The module shall expose distributed-tracing integration hooks.
REQ-OBS-003: Observability design shall support anomaly-detection pipeline integration.

## Evaluation and Regression

REQ-EVAL-001: The runtime shall support inline behavioral assertions or invariant checks.
REQ-EVAL-002: The module shall provide a golden-set evaluation harness.
REQ-EVAL-003: The module shall provide automated regression checks for agent behavior.

## Cost and Latency

REQ-COST-001: Execution shall support per-step token budgeting.
REQ-COST-002: The system shall define and measure latency against explicit SLOs.
REQ-COST-003: The module shall expose cost attribution through a dashboard or equivalent reviewer-visible presentation.
REQ-COST-004: The system shall support spend-alert thresholds.

## Safety and Guardrails

REQ-SAFE-001: The system shall support output filtering.
REQ-SAFE-002: The system shall support action blocklists.
REQ-SAFE-003: The runtime shall enforce execution scope.
REQ-SAFE-004: The runtime shall provide an explicit off-switch or kill-switch protocol.

## Named Technology Coverage

REQ-TECH-001: LangGraph shall have an explicit, source-faithful role in the module.
REQ-TECH-002: Mem0 shall have an explicit, source-faithful role in the module.
REQ-TECH-003: MCP SDK shall have an explicit, source-faithful role in the module.
REQ-TECH-004: LangSmith shall have an explicit, source-faithful role in the module.
REQ-TECH-005: LangFuse shall have an explicit, source-faithful role in the module.
REQ-TECH-006: Guardrails AI shall have an explicit, source-faithful role in the module.
REQ-TECH-007: Helicone shall have an explicit, source-faithful role in the module.
REQ-TECH-008: OpenAI SDK shall have an explicit, source-faithful role in the module.
REQ-TECH-009: Anthropic SDK shall have an explicit, source-faithful role in the module.

Named technology coverage does not by itself require every technology to participate in the critical runtime path. Architecture must determine the smallest faithful role for each tool without silently omitting it.

## Hands-On Lab Coverage

REQ-LAB-001: The module shall provide a task-planning agent demonstrating decomposition and dependency tracking.
REQ-LAB-002: The module shall provide a context-compression pipeline demonstrating token-budget enforcement.
REQ-LAB-003: The module shall provide a tool-permission registry demonstrating sandboxed execution.
REQ-LAB-004: The module shall provide a checkpointed agent demonstrating crash recovery and resume.
REQ-LAB-005: The module shall provide a human-approval gate demonstrating asynchronous escalation.
REQ-LAB-006: The module shall provide observability hooks demonstrating trace capture, structured logging, and a cost dashboard.

## Deliverable Coverage

REQ-DEL-001: The completed module shall include a harness-engineered agent runtime with full lifecycle control.
REQ-DEL-002: The completed module shall include a checkpointing and recovery system.
REQ-DEL-003: The completed module shall include a human-in-the-loop approval workflow.
REQ-DEL-004: The completed module shall include an observability and cost-governance dashboard.
REQ-DEL-005: The completed module shall include a regression test harness for agent behavior.

## Additive Engineering Requirements

ENG-001: The completed module shall provide an appropriate runnable and self-explanatory reviewer interface without replacing the source-required architecture.
ENG-002: External, model, tool, MCP, memory, retrieved, and agent output shall be treated as untrusted until validated.
ENG-003: Model or agent output shall not directly grant privileged application authority.
ENG-004: Retries, loops, external calls, resource use, latency, and cost exposure shall be bounded where applicable.
ENG-005: Normal deterministic tests and demonstrations shall not require paid external execution.
ENG-006: Evidence shall distinguish deterministic, mocked, adapter, local-integration, live-provider, and deployment evidence.
ENG-007: Expected security, recovery, authority, and failure paths shall be tested where applicable.

ENG-008: The completed module shall provide production-grade dual-mode provider operation. Deterministic, credential-free operation remains the default reviewer mode. Live OpenAI or Anthropic provider execution shall be an opt-in capability, activatable only through explicitly validated application configuration, restricted to a documented provider and model allowlist, with credentials supplied through trusted server-side, environment, or secret-store mechanisms and never accepted as public browser input; credentials grant connectivity only and never authority. Live execution shall remain bounded by retries, token/output limits, latency deadlines, and cost exposure. Evidence classes shall remain explicitly distinct, and provider-level production readiness may be claimed only when the live path is implemented, securely configured, explicitly human-authorized for execution, exercised, and independently evidenced as live-provider (and where applicable deployment) evidence.

## Freeze rule

This requirements baseline was explicitly human-approved on 2026-10-10.
Future changes to this approved baseline require explicit review and approval before architecture or implementation relies on them.
The 69 approved baseline requirements above are preserved exactly as approved and have not been weakened, omitted, renumbered, or reinterpreted. ENG-008 was added on 2026-10-23 as an additive engineering requirement (like ENG-001 through ENG-007, additive repository engineering governance and not a source-derived requirement) under the human-authorized production-grade dual-mode corrective contract repair; repository governance already required production-grade engineering unless a module is explicitly declared DEMO-ONLY, and Module 6.5 has never been declared DEMO-ONLY.
