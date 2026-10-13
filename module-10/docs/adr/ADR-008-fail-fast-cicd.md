# ADR-008: CI/CD Uses Fail-Fast Progressive Promotion

## Status

Accepted

## Context

The source requires CI/CD for AI and a scalable deployment pipeline. Production deployment must not bypass quality or security evidence.

## Decision

Use progressive fail-fast promotion: Ruff, pytest, compileall, security and container checks, build, integration and acceptance verification, deployment, then post-deployment health verification.

## Rationale

Fail-fast promotion prevents a later successful stage from masking an earlier failed quality gate and minimizes wasted compute.

## Consequences

- Failed gates stop promotion.
- Safe deterministic repairs may be attempted before rerunning the complete gate sequence.
- Unsafe fixes and weakening tests or quality rules are prohibited.
- Deployment evidence must identify the exact accepted revision.
