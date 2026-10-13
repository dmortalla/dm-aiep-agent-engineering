# ADR-004: Asynchronous Execution Is Explicitly Bounded

## Status

Accepted

## Context

The source requires asynchronous architectures and queue systems, but unbounded concurrency and retry behavior create reliability and cost risks.

## Decision

Use asynchronous service interfaces and bounded queued processing for suitable workloads. Concurrency, queue capacity, timeouts, retry counts, and job lifecycle states are explicit configuration and domain concepts.

## Rationale

Bounded asynchronous execution demonstrates scalable behavior while providing backpressure and predictable resource use.

## Consequences

- Queue saturation must produce a controlled response.
- Retries apply only to operations classified as safe and retryable.
- Retry loops are bounded.
- Timeout and cancellation behavior require tests.
- Queue and worker behavior require observability.
