# ADR-001: FastAPI Is the Production Service Boundary

## Status

Accepted

## Context

Module 10 must deploy an AI application through FastAPI and demonstrate a production-ready backend with typed contracts, asynchronous behavior, health reporting, security controls, and automated verification.

## Decision

FastAPI is the production HTTP service boundary. Application and domain logic remain independent from FastAPI so they can be tested and reused without an HTTP runtime.

## Rationale

FastAPI directly satisfies the authoritative course requirement while providing typed request validation, asynchronous endpoints, OpenAPI contracts, dependency injection, and strong automated-test support.

## Consequences

- HTTP-specific concerns remain in the API layer.
- Domain and application behavior must not depend on FastAPI request objects.
- Health, readiness, inference, and job interfaces can be independently acceptance-tested.
- Streamlit acts as a client rather than becoming the production service boundary.
