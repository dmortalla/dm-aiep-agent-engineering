# ADR-007-003 - Guardrails AI integration and moderation

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Place Guardrails AI behind the application safety boundary for input/output validation. Keep moderation policy application-owned and allow deterministic moderation checks plus approved Guardrails validators. Guardrail results never grant authorization.

## Rationale

This satisfies safety requirements while preserving the validation-versus-authorization boundary.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

