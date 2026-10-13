# ADR-009: Production Operations Are First-Class Capabilities

## Status

Accepted

## Context

The source requires monitoring, cost optimisation, reliability engineering, security, deployment checklists, incident response, rollback strategies, and SLA considerations.

## Decision

Treat observability, Azure Monitor integration, rollback, incident response, service-level reasoning, security, and cost management as implemented production capabilities rather than documentation-only appendices.

## Rationale

The module objective is to deploy, scale, and manage production-grade AI systems. Operational management therefore belongs inside the architecture and acceptance criteria.

## Consequences

- Operational behavior requires tests or executable evidence where practical.
- Azure Monitor must receive genuine live-deployment telemetry before that integration is claimed complete.
- Rollback must be demonstrable rather than merely described.
- SLA, SLO, latency, reliability, and cost claims must be classified as measured, proposed, or illustrative according to actual evidence.
- Deployment and incident runbooks must correspond to implemented system behavior.
