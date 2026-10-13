# ADR-002: Streamlit Is the Reviewer Presentation Layer

## Status

Accepted

## Context

Production-grade portfolio evidence must be directly usable and observable by instructors, recruiters, and reviewers.

## Decision

Use Streamlit as the unified presentation and demonstration layer while keeping authoritative business, security, queueing, caching, and deployment behavior outside the UI.

## Rationale

Streamlit provides a low-friction reviewer experience without requiring UI code to become an architectural authority.

## Consequences

- Reviewers can exercise real backend capabilities visually.
- The same application behavior remains available to non-Streamlit clients.
- UI state cannot grant deployment or infrastructure authority.
- Material capabilities must expose actual results rather than static claims.
