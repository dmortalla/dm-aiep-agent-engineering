# ADR-007-002 - Responsibility split across course-indicated tools

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Langfuse owns primary operational tracing; LangSmith owns primary evaluation/regression evidence; Helicone owns gateway-level model observability/fallback evidence; Guardrails AI owns specialist safety validation. Application code owns authority, resilience, idempotency, budgets, and recovery.

## Rationale

Each required tool contributes unique verifiable behavior without outsourcing application authority.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

