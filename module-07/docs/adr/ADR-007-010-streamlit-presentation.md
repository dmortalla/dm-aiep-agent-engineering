# ADR-007-010 - Streamlit presentation architecture

## Status

APPROVED / FROZEN - Human-approved, 2026-10-11.

## Context

Module 7 requires a production-grade, source-faithful architecture satisfying the frozen requirements while preserving deterministic testing, explicit trust boundaries, bounded cost, and defensible evidence.

## Decision

Use Streamlit as the integrated reviewer console for workflow execution, failure scenarios, normalized observability, safety decisions, cost/latency, and evaluation evidence. Specialist vendor dashboards remain complementary.

## Rationale

Streamlit is sufficient, already established by project governance, and avoids recreating vendor dashboards.

## Consequences

- This decision is binding under the human-approved Module 7 architecture.
- Implementation must preserve the frozen Module 7 requirements.
- Evidence must match the actual execution mode and integration level.
- Consequential deviation after architecture freeze requires explicit justification and human approval.

