# ADR-007-004 - Retry, fallback, timeout, and idempotency strategy

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Implement an application-owned resilience controller with explicit retryability classification, bounded retries, bounded timeouts, fallback policy, idempotency keys, budget accounting, and observable recovery state.

## Rationale

Reliability remains testable and vendor-independent, and fallback cannot bypass safety or authority.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

