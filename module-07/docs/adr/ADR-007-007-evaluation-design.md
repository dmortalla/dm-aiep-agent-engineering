# ADR-007-007 - Evaluation, regression, benchmarking, and improvement

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Use a deterministic evaluation engine and controlled benchmark fixtures as the default. Store comparable evaluation results and regression thresholds. Permit bounded live/model-backed evaluations only as explicitly labeled evidence.

## Rationale

This provides repeatable zero-cost CI while retaining real integration evidence.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

