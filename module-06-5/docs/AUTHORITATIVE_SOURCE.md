# Module 6.5 - Harness Engineering

## Source authority

This document transcribes the authoritative Module 6.5 course source supplied by the human.

The supplied source image is the ultimate source of truth. This transcription exists for traceability and engineering use. If this transcription conflicts with the source image, the source image governs.

This document records source content only. Engineering interpretations, derived requirements, architecture decisions, and additive enhancements belong in separate documents.

## Duration

6 Hours

## Objective

Equip engineers with deep operational skills to build, control, and govern production AI agents end-to-end - from task decomposition through safe execution, state recovery, human oversight, and cost governance.

## Topics

### Task Planning & Decomposition

- Breaking high-level goals into executable subtasks
- Dependency graphs
- Priority queues

### Prompt, Context & Memory Orchestration

- Dynamic prompt construction
- Context-window budgeting
- Short-/long-term memory routing

### Context Packing & Context Compression

- Token-efficient context construction
- Summarization-based compression
- Sliding-window strategies

### Tool Routing & Tool Permissions

- Dynamic tool selection
- Capability registries
- Permission scoping
- Sandboxed execution

### Execution Loops, Retries, Fallbacks & Stop Conditions

- Exponential backoff
- Circuit breakers
- Graceful degradation
- Hard stop triggers

### Checkpointing, Resume & State Recovery

- Persistent execution state
- State snapshots
- Crash recovery
- Idempotent re-entry

### Human Approval Gates & Escalation Rules

- Confidence thresholds
- Asynchronous human-in-the-loop integration
- Override audit trails

### MCP-Based Integration with External Systems

- Enterprise-tool registration
- Service discovery
- Secure capability exchange

### Observability Hooks, Trace Capture & Logging

- Structured span logging
- Distributed tracing hooks
- Anomaly-detection pipelines

### Evaluation Hooks, Test Cases & Regression Checks

- Inline assertions
- Golden-set test harnesses
- Regression suites

### Cost & Latency Management

- Per-step token budgeting
- Latency SLOs
- Cost attribution dashboards
- Spend alerts

### Safety Controls & Guardrails

- Output filtering
- Action blocklists
- Scope enforcement
- Off-switch protocols

## Tools

- LangGraph
- Mem0
- MCP SDK
- LangSmith
- LangFuse
- Guardrails AI
- Helicone
- OpenAI SDK
- Anthropic SDK

## Hands-On Labs

1. Build a task-planning agent with decomposition and dependency tracking.
2. Implement a context-compression pipeline with token-budget enforcement.
3. Create a tool-permission registry with sandboxed execution.
4. Build a checkpointed agent with crash recovery and resume.
5. Implement a human-approval gate with asynchronous escalation.
6. Add observability hooks: trace capture, structured logging, and cost dashboard.

## Deliverables

- Harness-engineered agent runtime with full lifecycle control
- Checkpointing & recovery system
- Human-in-the-loop approval workflow
- Observability & cost governance dashboard
- Regression test harness for agent behaviour

## Source-faithfulness rule

All derived requirements and architecture must remain traceable to this source or be explicitly identified as additive engineering enhancements.

Source-required functionality may not be silently omitted, replaced, weakened, or reinterpreted by an enhancement.
