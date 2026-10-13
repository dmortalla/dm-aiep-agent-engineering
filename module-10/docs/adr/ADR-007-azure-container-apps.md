# ADR-007: Azure Container Apps Is the Production Orchestration Target

## Status

Accepted

## Context

The authoritative source explicitly names Azure Container Apps and requires container orchestration, load balancing, scaling, and API deployment.

## Decision

Use Azure Container Apps as the production orchestration target for the Module 10 FastAPI container.

## Rationale

Azure Container Apps supplies managed ingress, revisions, replica scaling, and load distribution while avoiding unnecessary Kubernetes control-plane complexity and cost for this module.

## Consequences

- Live-cloud evidence must come from genuine Azure execution.
- Replica and scaling configuration must be observable.
- Revision behavior supports controlled deployment and rollback.
- Cloud resources require explicit cost boundaries and teardown procedures.
- Azure CLI availability is required before the live deployment story, not for local development.
