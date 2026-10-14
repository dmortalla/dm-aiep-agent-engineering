# ADR-009-004: Deterministic and Live Modes Are First-Class Execution Modes

## Status

Accepted (human-approved, 2026-10-14)

## Context

Reviewers and CI must run every essential workflow reproducibly, with no API key and no cost.
Genuine provider integration is still valuable and must be demonstrable when someone opts in.

## Decision

`ExecutionMode.DETERMINISTIC` and `ExecutionMode.LIVE` both use the same application contracts and
ports. Deterministic is the default for reviewers and CI. Live requires explicit opt-in
(`SessionConfig.live_opt_in=True`) plus a user-supplied credential for an allowlisted provider.

## Consequences

- Credential presence alone never selects live mode or authorizes billable calls.
- Deterministic output is never presented as live evidence, and vice versa (ADR-009-009).
- Live-provider failure must not break the deterministic path.
- User-supplied credentials are ephemeral and never committed, logged, or persisted.
