# ADR-007-001 - Primary observability and evaluation topology

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Use an application-owned normalized telemetry and evaluation layer. Langfuse is the primary operational observability integration; LangSmith is the primary independent evaluation/regression integration. Neither is required for deterministic core correctness.

## Rationale

This assigns distinct meaningful responsibilities, limits vendor coupling, and directly supports both required deliverables.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

