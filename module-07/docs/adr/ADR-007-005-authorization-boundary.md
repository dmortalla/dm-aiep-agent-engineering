# ADR-007-005 - Tool permission and authorization boundary

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Use explicit application policy and allowlisted capabilities. Model output, guardrail output, telemetry, and external content cannot modify authority. Denials fail closed and are observable.

## Rationale

This directly protects against prompt injection and forged authority.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

