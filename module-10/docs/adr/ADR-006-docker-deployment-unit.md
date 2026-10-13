# ADR-006: Docker Is the Production Deployment Unit

## Status

Accepted

## Context

Module 10 explicitly requires Docker and Dockerization of AI workflows.

## Decision

Package the production FastAPI service as a hardened Docker image using deterministic dependency installation, non-root execution, runtime configuration injection, health support, and no embedded credentials.

## Rationale

A container provides a reproducible deployment artifact across local acceptance, CI/CD, and Azure Container Apps.

## Consequences

- Container builds become part of acceptance evidence.
- Secrets cannot be baked into images.
- Image contents and runtime permissions require security review.
- Local container acceptance precedes cloud deployment.
