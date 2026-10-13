# ADR-003: Deterministic Execution Is Default and Live AI Is Opt-In

## Status

Accepted

## Context

Reviewer workflows must remain reproducible and cost-efficient while still allowing genuine external AI integration where useful.

## Decision

Every essential reviewer workflow operates without an external API key. Live AI execution is an explicit opt-in capability using a provider boundary and ephemeral user-supplied credentials.

## Rationale

This preserves reproducibility, availability, security, and cost control while allowing genuine live-integration evidence.

## Consequences

- Deterministic execution cannot be represented as live-provider evidence.
- User-supplied credentials must not be committed, logged, or intentionally persisted.
- Live-provider failure must not break the deterministic reviewer path.
- Evidence must identify deterministic, local-runtime, and live execution accurately.
