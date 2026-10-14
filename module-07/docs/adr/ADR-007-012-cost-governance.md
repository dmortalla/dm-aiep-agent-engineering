# ADR-007-012 - Cost and resource governance

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Attach explicit budgets to billable/model-backed execution. Retries and evaluations consume the same bounded budget. Deterministic CI requires no billable calls; live evidence modes expose usage and cost.

## Rationale

This makes cost analytics operational rather than merely cosmetic and prevents retry/evaluation amplification.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

