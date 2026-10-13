# ADR-005: Caching Uses an Explicit Application Contract

## Status

Accepted

## Context

The source requires caching strategies and performance optimisation. Coupling inference directly to one cache technology would weaken portability and testability.

## Decision

Define caching behind an explicit application contract with bounded entries, TTL behavior, deterministic cache-key construction, and observable hit and miss behavior.

## Rationale

An explicit contract supports deterministic local testing and future distributed implementations without changing authoritative inference behavior.

## Consequences

- Cache behavior is independently testable.
- Cache keys must not expose secrets or sensitive raw values.
- TTL and invalidation semantics must be documented.
- Process-local caching must not be misrepresented as distributed production caching.
