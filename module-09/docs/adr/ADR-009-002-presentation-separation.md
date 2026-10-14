# ADR-009-002: Separate Presentation from Authoritative Application Logic

## Status

Accepted (human-approved, 2026-10-14)

## Context

Reviewers and recruiters need one place to see and try the system. Streamlit is a good
presentation tool but a poor home for business logic, streaming lifecycles, or security controls.

## Decision

Streamlit is the reviewer-facing presentation and demonstration layer only. Core behavior lives in
normal Python application/domain code in `multimodal_voice_platform`. An application interface
layer owns the service boundary and the genuine WebSocket streaming boundary.

## Consequences

- Streamlit calls the application interface. It never calls provider adapters directly.
- Core behavior is testable without Streamlit.
- The WebSocket gateway is a real server component, not a Streamlit simulation (ADR-009-005).
- Credentials entered in the UI pass to the core as ephemeral values and are never stored by the UI.
