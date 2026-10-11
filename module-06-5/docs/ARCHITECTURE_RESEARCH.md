# Module 6.5 Architecture Research

## Status

Research baseline only. This document does not approve or freeze the Module 6.5 architecture.

The approved requirements baseline contains 62 source-derived requirements and 7 additive engineering requirements, for 69 total requirements.

## Research Objective

Determine the smallest production-grade, source-faithful architecture that satisfies every Module 6.5 topic, lab, named technology, deliverable, and approved additive engineering requirement without forcing every named technology into the critical runtime path.

## Runtime Baseline

- Candidate Python baseline: Python 3.12.
- Local compatibility verification: PASS.
- uv resolved the combined candidate dependency graph with exit code 0.
- Combined resolution contained 141 packages.
- No dependencies were installed during compatibility verification.
- No project environment was created during compatibility verification.
- Repository state remained unchanged.

## Verified Candidate Python Integrations

| Source-named technology | Resolved integration | Candidate architectural role | Critical runtime candidate |
| --- | --- | --- | --- |
| LangGraph | langgraph 1.2.14 | Lifecycle orchestration, execution graph, checkpoint integration | Yes |
| Mem0 | mem0ai 2.2.1 | Long-term memory adapter and memory-routing demonstration | No |
| MCP SDK | mcp 2.3.0 | External capability registration, discovery, and secure exchange | Yes |
| LangSmith | langsmith 0.14.7 | Optional observability and trace adapter | No |
| Langfuse | langfuse 4.17.0 | Optional observability and cost-governance adapter | No |
| Guardrails AI | guardrails-ai 0.11.0 | Output validation and guardrail integration | No |
| Helicone | Gateway/integration role; no Python package required by this preflight | Optional provider gateway and cost/observability demonstration | No |
| OpenAI SDK | openai 2.54.0 | Optional model-provider adapter | No |
| Anthropic SDK | anthropic 1.13.0 | Optional model-provider adapter | No |

These classifications are architecture-research conclusions, not yet approved architecture decisions.

## Architecture Principles

1. Keep lifecycle control application-owned even when framework features implement parts of that lifecycle.
2. Use LangGraph as the leading orchestration candidate because the source requires lifecycle control, dependency-aware execution, checkpointing, resume, and bounded execution behavior.
3. Keep persistent execution checkpoints distinct from semantic long-term memory. LangGraph checkpoint state and Mem0 memory serve different responsibilities.
4. Place all tool and MCP invocation behind an application-owned capability and permission boundary.
5. Treat model, tool, MCP, memory, retrieved, and external outputs as untrusted until validated.
6. Never allow model or agent output to grant itself privileged authority.
7. Keep OpenAI and Anthropic behind provider-neutral application contracts so neither provider controls domain or orchestration logic.
8. Keep external observability providers optional. Core structured telemetry must remain testable without credentials or outbound telemetry.
9. Avoid requiring paid API calls for deterministic tests, regression tests, or the normal reviewer demo path.
10. Bound retries, loops, tool calls, context size, latency, and cost before privileged or external execution.
11. Make HITL decisions durable and auditable rather than transient UI state.
12. Preserve an application-owned off-switch independent of model behavior.

## State Separation

The architecture should distinguish at least four forms of state:

- execution state: current plan, step status, retry state, budgets, and stop conditions
- checkpoint state: durable snapshots required for crash recovery and idempotent resume
- memory state: short-term and long-term semantic context selected for future reasoning
- approval and audit state: human decisions, authority, overrides, trace identifiers, and consequential-action evidence

These state categories may share storage technology only if their contracts and authority boundaries remain explicit.

## Tool and MCP Boundary

Dynamic tool routing must not equal unrestricted tool access. Selection occurs only after capability discovery and before a separate permission decision. MCP capabilities are external and untrusted. Tool schemas, arguments, outputs, identities, scopes, and authorization state must be validated at the application boundary.

Sandboxing must constrain the effects available to tools rather than merely describing a tool as sandboxed.

## Observability Strategy

The core runtime should emit provider-neutral structured execution events and spans. LangSmith, Langfuse, and Helicone should be treated as distinct optional integrations unless architecture evidence demonstrates a source requirement for one to become mandatory.

This prevents observability availability, credentials, telemetry leakage, or vendor outages from becoming prerequisites for deterministic runtime operation.

Cost governance must remain application-visible even when an external observability provider enriches it.

## Provider Strategy

OpenAI and Anthropic are source-required named technologies but need not both be required for normal execution. Provider adapters should expose a narrow application-owned contract. Deterministic fake or local providers should support tests and the normal credential-free demonstration path.

Live provider execution, if enabled, must be explicit, bounded, credential-aware, and separately evidenced.

## Guardrail Strategy

Guardrails AI may provide validation capabilities, but application security cannot depend solely on model-output validation. Permission checks, capability scope, action blocklists, HITL authority, resource limits, and the off-switch remain deterministic application controls.

## Memory Strategy

Mem0 should be evaluated as a long-term semantic memory integration rather than as the owner of execution recovery. The runtime should retain explicit control over what information may enter memory, what may be retrieved, how retrieved content is labeled as untrusted, and how context budgets limit its use.

## Deterministic Test Strategy

The normal automated suite should require no paid model calls, external credentials, external MCP services, or hosted observability accounts. Test doubles and local adapters should cover orchestration, retries, stop conditions, checkpoint recovery, permission denials, HITL behavior, cost accounting, context limits, and regression behavior.

Optional live integration tests should be separately marked and must never be required to establish the deterministic quality baseline.

## Architecture Questions Requiring Resolution

The architecture proposal must resolve these questions before human approval:

1. What is the minimal LangGraph topology that demonstrates planning, execution, checkpointing, HITL interruption, recovery, and stop conditions without turning framework state into the entire domain model?
2. What persistence backend is appropriate for deterministic local checkpoint and approval demonstrations?
3. What exact sandbox boundary is practical on the target Windows development environment while remaining portable?
4. Which observability information remains application-owned, and which data may optionally be exported to LangSmith, Langfuse, or Helicone?
5. What local MCP server and capability set best demonstrates registration, discovery, secure exchange, permission denial, and successful authorized execution?
6. What confidence and consequence rules trigger asynchronous human approval?
7. What token, retry, latency, tool-call, and cost budgets should be proposed as deterministic defaults?
8. What anomaly signals can be demonstrated locally without requiring an external anomaly-detection service?
9. What reviewer workflow should the Streamlit UI expose so every major lifecycle control is directly demonstrable?

## Dependency Decision

The successful compatibility preflight proves that the eight candidate Python packages can resolve together under Python 3.12. It does not prove that all eight should become mandatory production dependencies.

The architecture should minimize mandatory dependencies and classify source-named technologies as core runtime, optional adapter, development/integration dependency, or externally demonstrated integration according to the smallest source-faithful design.

## Next Lifecycle Gate

Produce the concrete Module 6.5 architecture proposal and requirement-to-component mapping. The architecture remains unfrozen until explicit human approval.
