# ADR-009-005: Real Streaming Requires a Real WebSocket Boundary

## Status

Accepted (human-approved, 2026-10-14)

## Context

The source names streaming responses, WebSockets, real-time conversations, and low-latency
pipelines. Polling or simulated streams inside the UI would not satisfy that honestly.

## Decision

Real-time streaming goes over a genuine WebSocket boundary using a typed, versioned event protocol,
not unstructured strings. The protocol accommodates at least `session_started`,
`transcript_partial`, `transcript_final`, `response_delta`, `response_complete`, `audio_ready`,
`metric`, `error`, and `session_complete`. Exact details may evolve without weakening this.

## Consequences

- Story 9.1 defines the event models in `contracts/streaming.py` as a discriminated union with a
  strict parser that rejects unknown or malformed events.
- Events carry a session ID and a sequence number.
- Errors cross the boundary only as `SafeError` payloads.
- The server framework is chosen in Story 9.7.
