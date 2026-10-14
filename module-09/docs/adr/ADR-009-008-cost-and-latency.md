# ADR-009-008: Cost and Latency Are Architectural Concerns

## Status

Accepted (human-approved, 2026-10-14)

## Context

Multimodal and voice workloads are expensive and latency-sensitive. Unbounded inputs, retries, or
histories create cost and denial-of-service exposure.

## Decision

Requests, input sizes, output tokens, timeouts, retries, conversation histories, and provider
activity are bounded by `ResourceBudget`, which cannot exceed fixed hard ceilings. Latency is
measured per stage: ingestion, STT, vision, document understanding, reasoning, first streamed
response, TTS, and end to end.

## Consequences

- Retries count against the per-session provider-call budget. There are no unbounded loops.
- Stage latency is emitted as typed `metric` events and shown to reviewers.
- Low-latency claims require measured evidence, not design intent.
