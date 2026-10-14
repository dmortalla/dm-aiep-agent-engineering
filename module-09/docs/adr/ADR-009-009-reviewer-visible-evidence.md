# ADR-009-009: Reviewer-Visible Evidence Is Architectural

## Status

Accepted (human-approved, 2026-10-14)

## Context

Reviewers must be able to see that capabilities actually work and how strong the proof is. Mixing
design intent, deterministic demos, and live calls would overstate claims.

## Decision

Every material capability must ultimately produce observable proof through the presentation layer.
Evidence is classified as `design_documentation`, `automated_test`, `deterministic_demo`,
`live_integration`, or `deployment_release`. `EvidenceRecord` validators stop weaker evidence from
claiming a stronger class.

## Consequences

- Story 9.1 evidence is `design_documentation` only. It proves design intent, not working behavior.
- The UI labels every result with its evidence class and execution mode.
- The UI includes concise guidance explaining how to use and test each workflow and what the
  results demonstrate.
