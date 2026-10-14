# Module 7 - Architecture Inputs

## Status

PREPARATION - Architecture inputs derived from the approved requirements baseline.

This document identifies architectural concerns, invariants, evidence needs, and decisions that must be resolved during architecture design.

It does not select or approve an architecture.

## Authority

The approved Module 7 REQUIREMENTS.md is the controlling module contract.

The authoritative course screenshot remains controlling for course scope.

Repository governance remains controlling for applicable engineering process and production-grade standards.

## Architectural Objective

Design a standalone Module 7 system whose observability platform and evaluation pipeline collectively demonstrate safe, reliable, and monitorable AI engineering.

The architecture must integrate the source topics, required labs, meaningful use of all four course-indicated tools, and the two required deliverables into a coherent system rather than a collection of disconnected demonstrations.

## Hard Architectural Invariants

The architecture must preserve:

1. Standalone Module 7 isolation.
2. Source-faithful coverage of all 27 directly source-derived requirements.
3. Meaningful use of LangSmith, Langfuse, Helicone, and Guardrails AI.
4. An observability platform as a required deliverable.
5. An evaluation pipeline as a required deliverable.
6. Retry, fallback, idempotency, and resilience behavior.
7. Prompt-injection defence, tool permission control, guardrails, and moderation.
8. Workflow tracing, logging, latency monitoring, cost analytics, and debugging.
9. Automated evaluations, regression testing, benchmarking, and continuous improvement.
10. Failure-recovery simulation.
11. Explicit separation between validation and authorization.
12. Least-privilege tool authority independent of model output.
13. Telemetry redaction and secret exclusion.
14. Bounded external calls, retries, evaluations, and repair attempts.
15. Credential-free deterministic ordinary CI wherever practical.
16. Evidence distinction between deterministic, simulated, and live behavior.
17. Streamlit as the default guided reviewer UI unless a materially better alternative is justified.
18. Fail-fast Ruff, pytest, compileall quality gates.
19. Evidence-backed Definition of Done.

## Required System Capabilities

### Reliability Plane

The architecture must provide explicit components or boundaries for:

- retry policy
- retryability classification
- fallback policy
- idempotency
- timeout control
- failure recovery
- bounded execution
- safe degradation

### Safety and Authority Plane

The architecture must provide explicit components or boundaries for:

- prompt-injection detection or containment
- input validation
- output validation
- moderation
- tool permission policy
- authorization enforcement
- least privilege
- credential isolation
- telemetry redaction

Guardrails and validation must not themselves grant privileged authority.

### Observability Plane

The architecture must support:

- workflow traces
- structured logs
- latency measurements
- token or usage measurements where applicable
- cost analytics
- failure diagnostics
- retry/fallback visibility
- safety-decision visibility
- debugging evidence

Observability-provider failure must not become an authorization bypass or corrupt core workflow state.

### Evaluation Plane

The architecture must support:

- deterministic evaluations
- automated evaluation pipelines
- regression evaluation
- benchmark datasets or fixtures
- repeatable benchmark execution
- result comparison
- continuous-improvement evidence
- optional bounded live/model-backed evaluation where justified

### Presentation Plane

The reviewer-facing UI must make the required functionality inspectable and exercisable.

At minimum, architecture should support presentation of:

- workflow execution
- traces and operational evidence
- latency
- cost/usage
- retries and fallback
- failure recovery
- safety and permission decisions
- evaluation results
- regression results
- benchmark results

Vendor dashboards may remain specialist observability surfaces. The Streamlit application need not recreate every vendor dashboard.

## Course Tool Integration Questions

### LangSmith

Architecture must decide:

- which tracing and/or evaluation responsibility LangSmith owns
- whether its role is primary, secondary, or evidence-specific
- how ordinary CI remains credential-free
- what bounded live evidence is required

### Langfuse

Architecture must decide:

- whether Langfuse is the primary observability/evaluation backbone or a complementary integration
- whether cloud or self-hosted behavior is needed
- how OpenTelemetry-based instrumentation fits the internal telemetry contract
- what bounded live evidence is required

### Helicone

Architecture must decide:

- whether Helicone sits on a live model request path or behind an adapter
- how gateway-level observability contributes unique evidence
- how fallback behavior is demonstrated without coupling core correctness to vendor availability
- what bounded live evidence is required

### Guardrails AI

Architecture must decide:

- which validators satisfy deterministic local safety requirements
- which validators require external/model-backed execution
- how Guardrails integrates without becoming the authorization layer
- how moderation is satisfied
- how dependency resolution explicitly excludes compromised guardrails-ai 0.10.1

## Internal Abstraction Decisions

Architecture must decide whether explicit internal interfaces are required for:

- model/provider invocation
- observability emission
- evaluation execution
- guardrail execution
- moderation
- authorization
- resilience policy
- cost accounting
- workflow execution

Abstractions should exist only where they protect a genuine boundary, enable deterministic testing, prevent vendor lock-in at a consequential boundary, or support multiple concrete implementations.

Premature abstraction is not a goal.

## Data and State Decisions

Architecture must define:

- workflow state
- trace identifiers
- evaluation identifiers
- benchmark fixture structure
- idempotency keys
- failure/recovery state
- safety-decision records
- authorization-decision records
- cost/usage records
- redaction boundaries
- persistence requirements
- retention assumptions if persistence exists

## Trust Boundaries

Architecture must explicitly classify at least:

- user input
- model output
- retrieved/external content if used
- vendor telemetry responses
- tool arguments
- tool results
- evaluation data
- secrets and credentials
- configuration

Untrusted data must not be allowed to redefine trusted policy or authority.

## Failure Boundaries

Architecture must define behavior for at least:

- model/provider timeout
- retryable provider failure
- non-retryable provider failure
- observability-provider failure
- evaluation-provider failure
- guardrail failure
- moderation failure
- authorization denial
- duplicate/replayed operation
- malformed telemetry
- budget exhaustion
- invalid configuration

## Cost Boundaries

Architecture must identify:

- potentially billable operations
- per-run bounds
- retry amplification risks
- evaluation amplification risks
- optional live-test cost boundaries
- zero-cost deterministic substitutes used in ordinary CI

## Evidence Architecture

Architecture must make it possible to distinguish:

- deterministic fixture evidence
- simulated failure evidence
- mocked provider-contract evidence
- live vendor integration evidence
- live model-backed evidence

No evidence class may be silently promoted into a stronger claim.

## Required Labs as Architecture Scenarios

### Lab 1 - Observability Dashboard

Architecture must allow a reviewer to execute or inspect a workflow and observe operational telemetry through the observability deliverable.

### Lab 2 - Automated Evaluation Pipeline

Architecture must allow repeatable evaluation against controlled data and expose regression and benchmark results.

### Lab 3 - Failure Recovery

Architecture must allow deterministic or controlled injection of failures so retry, fallback, idempotency, recovery, and observability behavior can be verified.

## Architecture Decision Register

The architecture phase must resolve at least these decisions:

ADR-007-001: Primary observability and evaluation topology.
ADR-007-002: Meaningful responsibility split across LangSmith, Langfuse, and Helicone.
ADR-007-003: Guardrails AI integration and moderation strategy.
ADR-007-004: Reliability strategy for retry, fallback, timeout, and idempotency.
ADR-007-005: Tool permission and authorization boundary.
ADR-007-006: Telemetry schema, redaction, and provider-failure behavior.
ADR-007-007: Evaluation, regression, benchmarking, and continuous-improvement design.
ADR-007-008: Deterministic CI versus bounded live-integration evidence.
ADR-007-009: State/persistence and failure-recovery model.
ADR-007-010: Streamlit presentation architecture.
ADR-007-011: Dependency and supply-chain strategy.
ADR-007-012: Cost and resource governance.

Additional ADRs may be created only when a consequential decision cannot be adequately represented by these decisions.

## Explicitly Unresolved

This preparation document does not decide:

- the primary observability backend
- the primary evaluation backend
- whether Langfuse is cloud or self-hosted
- whether Helicone is inline or adapter-isolated
- the model provider
- the retry implementation library
- the moderation implementation
- persistence technology
- deployment topology
- exact dependency pins except established security exclusions

## Architecture Entry Criteria

Architecture design may begin when:

- the requirements baseline is human-approved and frozen
- all 27 source-derived requirements remain present
- technology research exists
- architecture concerns and unresolved decisions are explicitly identified
- implementation has not begun

All entry criteria are expected to be satisfied at this checkpoint.
