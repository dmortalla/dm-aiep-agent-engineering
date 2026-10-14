# ADR-007-009 - State, idempotency, and recovery model

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Begin with bounded in-process workflow state plus an explicit idempotency abstraction and deterministic recovery records. Do not introduce distributed persistence until a demonstrated requirement demands it.

## Rationale

This is the smallest architecture satisfying the source while preserving a clean persistence boundary.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

