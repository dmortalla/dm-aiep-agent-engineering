# ADR-007-006 - Telemetry schema, redaction, and provider failure

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Emit normalized application telemetry through a mandatory redaction boundary before vendor adapters. Observability export failures are locally observable and cannot alter authorization or corrupt core state.

## Rationale

This supports multi-vendor observability while minimizing leakage and provider coupling.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

