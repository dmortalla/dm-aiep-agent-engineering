# ADR 001 - Module 6.5 Architecture Baseline

## Status

Accepted and frozen on 2026-10-11.

## Decision Authority

The human reviewer conditionally selected Option 1 provided that the architecture satisfied all approved Module 6.5 requirements.

Final reconciliation verified 62 of 62 source-derived requirements and 7 of 7 additive engineering requirements, for 69 of 69 total approved requirements.

The conditional approval therefore became effective before this architecture freeze.

## Context

Module 6.5 requires a standalone harness-engineered agent runtime demonstrating lifecycle control, recovery, human oversight, MCP integration, observability, evaluation, cost governance, and safety.

The architecture must remain source-faithful while providing production-grade engineering boundaries and deterministic reviewer evidence.

## Decisions

1. Python 3.12 is the proposed implementation runtime.
2. LangGraph is the core orchestration framework.
3. Application-owned typed state and deterministic policy retain authority over lifecycle decisions.
4. MCP SDK provides the primary MCP integration boundary.
5. Tool discovery and tool selection remain separate from authorization.
6. Application-owned persistence contracts govern checkpointing, recovery, approvals, and audit state.
7. SQLite is the deterministic local persistence implementation candidate.
8. Recovery must support idempotent re-entry and must not replay committed effects.
9. Human approvals are durable, asynchronous, auditable, and bound to the exact pending action.
10. Streamlit is the default reviewer presentation layer and contains no authoritative domain policy.
11. OpenAI and Anthropic are optional live provider adapters behind provider-neutral application contracts.
12. Deterministic fake or local providers support normal tests and reviewer demonstrations without paid model execution.
13. Mem0 is an optional long-term semantic-memory adapter and does not own execution recovery or application authority.
14. LangSmith, Langfuse, and Helicone are optional observability integrations rather than runtime correctness dependencies.
15. Guardrails AI provides additive validation and is not the sole security boundary.
16. The sandbox is an application-level bounded execution boundary and must not be represented as operating-system isolation unless later implementation evidence proves that property.
17. External, model, tool, MCP, memory, retrieved, and agent output remains untrusted until validated.
18. Model or agent output cannot grant privileged application authority.
19. Retries, loops, tool calls, context, resources, latency, and cost are bounded.
20. Retry and fallback paths cannot bypass authorization, safety, approval, or budget controls.
21. The application owns an explicit off-switch independent of model behavior.
22. Deterministic and local workflow latency has a p95 SLO of no more than 5 seconds.
23. The 180-second workflow deadline remains a separate hard safety bound rather than a performance target.
24. Evidence must distinguish deterministic, mocked, adapter, local-integration, live-provider, and deployment evidence.
25. Module 6.5 remains standalone and does not depend on prior module implementations.

## Consequences

Implementation must conform to this frozen architecture unless a genuine design flaw or approved requirement change requires an explicit architecture amendment.

Optional integrations may be implemented without becoming prerequisites for deterministic runtime correctness.

Tests must provide defensible evidence for security, authority, recovery, failure, budget, latency, and lifecycle behavior.

## Verification Basis

- 69 of 69 approved requirements architecturally covered.
- 6 of 6 source labs mapped.
- 5 of 5 source deliverables mapped.
- 9 of 9 source-named technologies assigned explicit roles.
- Requirements baseline remained unchanged during architecture reconciliation.
- Implementation had not started when this architecture was frozen.
