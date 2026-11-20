# ADR-007-013 - Immutable evidence records and read-only reload

## Context

Story 10 requires reloadable accepted evidence; existing producers return bounded in-memory results but have no immutable reference/load authority.

## Decision

The application owns a narrow immutable evidence-record boundary. Producer-validated typed results are minimized before atomic recording. The boundary assigns a content-and-provenance digest reference and permits read-only integrity-checked loading. References confer retrieval only, never workflow or authorization.

Records bind producer/schema, derived evidence class, candidate/contract where applicable, and canonical minimized content digest. Duplicate identical records are idempotent; collision, corruption, missing/stale binding, unknown producer, and classification promotion fail closed. Changed evidence receives a new reference.

Eligible producers are the accepted evaluation engine/baseline loader, Story 8 lab, accepted security/telemetry/policy boundaries, and formal-gate executor. Story 10 only loads and verifies. Caller mappings, labels, credentials, adapters, and gate dictionaries are never authority. Only qualifying producer provenance may classify live evidence; absent live evidence remains open.

The gate record is external to candidate content: freeze candidate identity, run Ruff -> pytest -> compileall, atomically record, then reload and verify. Repairs retain failure evidence and require a full rerun. Reviewer mode uses an ignored configurable runtime-local store; production may use a durable environment-backed adapter. Both require safe paths, bounded retention, atomicity, and concurrency-safe idempotency.

## Consequences

In-process-only evidence is rejected because it cannot support reload-and-rederive verification. This adds no workflow engine, provider authority, generic database, or second Story 9 session authority.
