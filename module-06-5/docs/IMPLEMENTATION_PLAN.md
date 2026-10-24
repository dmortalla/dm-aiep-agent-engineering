# Module 6.5 - Implementation Plan

## Status

APPROVED ARCHITECTURE IMPLEMENTATION PLAN

This plan decomposes the frozen Module 6.5 architecture into small implementation stories. It does not amend the approved requirements or architecture.

## Delivery Rules

- Preserve the frozen architecture and the 69-requirement baseline.
- Keep Module 6.5 standalone and do not modify other modules.
- Implement the smallest architecture-conformant slice for each story.
- Add tests with every behavioral story.
- Treat external, model, tool, MCP, memory, retrieved, and agent output as untrusted until validated.
- Never permit model or agent output to grant privileged authority.
- Keep retries, loops, calls, resources, latency, and cost bounded.
- Keep deterministic tests and the normal reviewer path credential-free and free of paid model execution.
- Run Ruff safe fixes when appropriate, then the fail-fast quality gate: Ruff, pytest, compileall.
- Never weaken tests, safety controls, or quality rules merely to obtain a green build.
- Record evidence according to the frozen evidence classes.

## Story 1 - Python Package and Typed Domain Contracts

Establish Python 3.12 packaging, dependency groups, source layout, typed workflow contracts, validated identifiers, trust classifications, budgets, execution status, errors, and deterministic configuration.

Primary requirements: REQ-OBJ-001, ENG-002, ENG-003, ENG-004, ENG-005, ENG-006, ENG-007.

Exit evidence: package imports cleanly; configuration is deterministic; invalid contracts fail closed; baseline quality gates pass.

## Story 2 - Planning, Dependencies, and Priority Scheduling

Implement executable task decomposition contracts, dependency validation, deterministic priority scheduling, cycle rejection, and bounded plan size.

Primary requirements: REQ-PLAN-001 through REQ-PLAN-003, REQ-LAB-001.

Exit evidence: deterministic planning lab demonstrates valid ordering, priority behavior, dependency blocking, cycle rejection, and plan bounds.

## Story 3 - Context Construction, Compression, and Memory Routing

Implement dynamic prompt construction, context-window budgeting, relevance selection, summarization compression, sliding-window behavior, provenance, short-term state, and deterministic long-term memory routing. Add the optional Mem0 adapter boundary without making it a correctness dependency.

Primary requirements: REQ-CTX-001 through REQ-CTX-003, REQ-COMP-001 through REQ-COMP-003, REQ-TECH-002, REQ-LAB-002.

Exit evidence: context lab proves budget enforcement, compression, provenance retention, sliding-window behavior, and bounded memory routing.

## Story 4 - Capability Registry, Permissions, and Sandboxed Tool Execution

Implement capability identity and schemas, dynamic selection, deterministic authorization, risk and scope policy, blocklists, approval metadata, timeouts, resource limits, and the application-level bounded tool executor.

Primary requirements: REQ-TOOL-001 through REQ-TOOL-004, REQ-SAFE-002, REQ-SAFE-003, REQ-LAB-003.

Exit evidence: permission lab proves allow, deny, scope enforcement, malformed input rejection, bounded execution, and no model self-authorization.

## Story 5 - LangGraph Lifecycle and Bounded Execution Controls

Implement the typed LangGraph lifecycle, finite routing, executable step progression, exponential backoff, circuit breaker behavior, graceful degradation, hard stop conditions, workflow deadlines, and application-owned off-switch checks.

Primary requirements: REQ-EXEC-001 through REQ-EXEC-004, REQ-SAFE-004, REQ-TECH-001.

Exit evidence: lifecycle tests prove finite transitions, bounded retries, circuit opening, fallback behavior, deadline termination, and off-switch enforcement.

## Story 6 - Checkpointing, Recovery, and Idempotent Re-entry

Implement application-owned persistence contracts, deterministic SQLite checkpoint storage, state-version validation, crash recovery, resume, committed-effect tracking, and idempotent re-entry.

Primary requirements: REQ-REC-001 through REQ-REC-004, REQ-DEL-002, REQ-LAB-004.

Exit evidence: recovery lab demonstrates crash, persisted checkpoint, restart, safe resume, and prevention of duplicate committed effects.

## Story 7 - Durable Human Approval and Asynchronous Escalation

Implement deterministic approval policy, confidence thresholds, durable pending approvals, asynchronous suspension and resume, exact-action binding, denial, override handling, and audit records.

Primary requirements: REQ-HITL-001 through REQ-HITL-003, REQ-DEL-003, REQ-LAB-005.

Exit evidence: HITL lab demonstrates suspend, inspect, approve or deny, resume, forged or stale approval rejection, and complete audit evidence.

## Story 8 - MCP Capability Boundary

Implement MCP registration, discovery, schema validation, allowlisting, permission evaluation, secure capability exchange, bounded invocation, output validation, and audit capture.

Primary requirements: REQ-MCP-001 through REQ-MCP-003, REQ-TECH-003.

Exit evidence: deterministic local MCP integration demonstrates discovery without implicit trust, authorized invocation, denial paths, malformed output handling, and bounded execution.

## Story 9 - Provider and Guardrail Adapters

Implement provider-neutral model contracts, deterministic fake provider behavior, optional OpenAI and Anthropic adapters, output filtering and validation, and optional Guardrails AI integration.

Primary requirements: REQ-SAFE-001, REQ-TECH-006, REQ-TECH-008, REQ-TECH-009, ENG-002, ENG-003, ENG-005.

Exit evidence: deterministic provider tests prove validated output, injection containment, malformed output rejection, credential-free operation, and inability of provider output to grant authority.

## Story 10 - Observability, Cost Governance, and Latency SLO

Implement provider-neutral structured events, correlation identifiers, distributed-tracing hooks, anomaly signals, token and cost attribution, spend alerts, hard cost budgets, latency measurement, and p50 and p95 reporting against the frozen p95 latency SLO. Add optional LangSmith, Langfuse, and Helicone integration boundaries.

Primary requirements: REQ-OBS-001 through REQ-OBS-003, REQ-COST-001 through REQ-COST-004, REQ-TECH-004, REQ-TECH-005, REQ-TECH-007, REQ-LAB-006, REQ-DEL-004.

Exit evidence: observability lab exposes traces, structured logs, anomaly signals, cost attribution, spend alerts, hard-budget enforcement, and measured latency evidence.

## Story 11 - Evaluation, Golden Sets, Regression, and Reviewer UI

Implement inline deterministic assertions, golden-set cases, regression comparisons, evidence classification, and the self-explanatory Streamlit reviewer interface covering all six labs and major safety, recovery, approval, cost, and regression behaviors.

Primary requirements: REQ-EVAL-001 through REQ-EVAL-003, REQ-DEL-005, ENG-001, ENG-006, ENG-007.

Exit evidence: reviewer UI is runnable and guided; regression harness is deterministic; expected failure paths are visible and tested.

## Story 12 - End-to-End Harness Integration and Release Evidence

Integrate the full harness lifecycle and verify every requirement, lab, deliverable, technology role, architecture invariant, security boundary, recovery path, approval boundary, budget, latency SLO, and reviewer workflow.

Primary requirements: all 69 approved requirements, REQ-DEL-001 through REQ-DEL-005.

Exit evidence: full fail-fast quality gate passes; requirement-to-test evidence is complete; deterministic end-to-end demo passes; source-faithfulness and architecture-conformance reviews pass; release evidence is captured without unsupported production claims.

## Story 13 - Secure Dual-Mode Provider Completion (additive, ENG-008)

Complete the already-supporting dual-mode machinery so that live OpenAI and
Anthropic provider execution is securely activatable without weakening the
deterministic/no-key default: provider/model allowlist enforcement in the
live-provider configuration seam, trusted server-side/environment/secret-store
credential mechanisms (never public browser BYOK input), bounded retries,
token/output limits, latency deadlines and cost exposure for the live path,
distinct live-provider evidence, and provider-neutral failure handling. No live
provider call is executed without a separate explicit human authorization that
supplies the credentials and approves the bounded run.

Primary requirements: ENG-008 (additive corrective, ADR 002), ENG-002 through
ENG-005 unchanged.

Exit evidence: deterministic default tests remain green and credential-free;
the live configuration seam fails closed without explicit
`allow_live_providers` plus allowlisted provider/model plus trusted-secret
mechanism plus finite cost budget; structural contract tests
(`tests/test_dual_mode_contract.py`) keep the invariant enforced; live-path
exercising happens only inside a later human-authorized execution gate with
its own recorded live-provider evidence.

## Definition of Done

- [ ] 69 of 69 approved requirements implemented and verified (the approved
      2026-10-10 baseline: 62 source-derived + ENG-001..ENG-007 additive;
      the corrective additive ENG-008 is item 13 below).
- [ ] 6 of 6 source labs runnable and evidenced.
- [ ] 5 of 5 source deliverables complete.
- [ ] 9 of 9 named technologies retain explicit source-faithful roles.
- [ ] Streamlit reviewer interface is runnable and self-explanatory.
- [ ] Security, authority, recovery, failure, budget, latency, and off-switch paths are tested.
- [ ] Deterministic reviewer path requires no paid model execution.
- [ ] Evidence classes are reported accurately.
- [ ] Ruff, pytest, and compileall pass in fail-fast order.
- [ ] Independent architecture-conformance and source-faithfulness review passes.
- [ ] PROJECT_STATUS and README accurately reflect verified implementation state.
- [ ] Repository contains no temporary evidence or unrelated module modifications.
- [ ] ENG-008 dual-mode completion implemented and verified, with live-path
      exercising only inside a later human-authorized execution gate.
