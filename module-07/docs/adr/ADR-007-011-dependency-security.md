# ADR-007-011 - Dependency and supply-chain strategy

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Use minimal constrained dependencies, verify compatibility, prohibit guardrails-ai 0.10.1, and reject stale Guardrails Hub installation patterns. Dependency security is validated before release.

## Rationale

This incorporates current upstream security/distribution evidence and minimizes attack surface.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

