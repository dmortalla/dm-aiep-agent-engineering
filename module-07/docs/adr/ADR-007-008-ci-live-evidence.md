# ADR-007-008 - Deterministic CI versus live integration evidence

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Ordinary CI is credential-free and deterministic. Live vendor/model tests are optional, bounded, separately configured, and required only when producing claims that depend on live behavior.

## Rationale

This protects reliability, cost, security, and evidence integrity.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

