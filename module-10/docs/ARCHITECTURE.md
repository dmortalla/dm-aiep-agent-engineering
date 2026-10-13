# Module 10 Architecture

## Purpose

Module 10 implements a production-grade AI deployment system that demonstrates deployment, scaling, observability, reliability, security, cost control, and production operations.

The authoritative course source requires FastAPI, Docker, Azure Container Apps, Azure Monitor, asynchronous architectures, queue systems, caching, load balancing, performance optimisation, CI/CD, monitoring, cost optimisation, reliability engineering, security, deployment checklists, incident response, rollback strategies, and SLA considerations.

## Architecture Freeze

The approved Module 10 architecture is frozen before feature implementation. Structural changes require an explicit architecture decision rather than incidental refactoring.

## System Flow

`mermaid
flowchart TD
    U[User or Reviewer] --> S[Streamlit Presentation Layer]
    S --> A[FastAPI Service]
    A --> V[Validation and Security Controls]
    V --> C[Cache Contract]
    C --> E[AI Execution Service]
    E --> D[Deterministic Runtime]
    E -. explicit opt-in .-> L[Live AI Provider]
    E --> Q[Bounded Async Queue]
    Q --> W[Worker]
    A --> O[Observability]
    E --> O
    W --> O
    O --> M[Azure Monitor]
    P[CI/CD Pipeline] --> I[Docker Image]
    I --> ACA[Azure Container Apps]
    ACA --> A
`",
        ",
        

1. Module 10 is standalone and must not depend on or modify another module.
2. FastAPI is the production service boundary.
3. Streamlit is the unified reviewer-facing presentation and demonstration layer; authoritative business logic remains outside the UI.
4. Every material capability must produce reviewer-visible working results and appropriate execution evidence.
5. Deterministic no-key execution is the default reviewer path.
6. Optional live AI execution must be explicit opt-in and must not persist or expose user-supplied secrets.
7. Deterministic, local-runtime, and live-cloud evidence are classified separately and accurately.
8. External input and model output are untrusted until validated.
9. LLM output cannot directly authorize deployment, rollback, scaling, infrastructure mutation, or other privileged behavior.
10. Asynchronous work is bounded by explicit concurrency, queue, timeout, and retry controls.
11. Cache behavior is explicit, bounded, and independent from authoritative inference logic.
12. Docker is the production deployment unit and must run without embedded credentials.
13. Azure Container Apps is the production orchestration target.
14. Azure Monitor is the production monitoring target.
15. Production behavior includes health checks, structured failures, graceful degradation, and revision-aware rollback.
16. Observability must cover correlation identifiers, latency, failures, cache behavior, queue behavior, and AI execution timing without leaking secrets.
17. Security, reliability, interoperability, authorization, protocol, and business behavior are verified primarily by maintainable Python tests and reviewer-visible evidence.
18. Native quality gates run fail-fast: Ruff, pytest, compileall, then project-native integration and acceptance tests.
19. Safe deterministic repairs may be automated; unsafe fixes, weakened tests, and weakened quality rules are prohibited.
20. Cloud resources are created only when live-cloud evidence materially requires them and must have explicit cost boundaries and teardown procedures.
21. SLA and production-performance claims must be labeled measured, proposed, or illustrative according to the evidence available.
22. Public Python interfaces use type hints and appropriate Google-style docstrings.
23. Exception handling belongs at genuine failure boundaries and must preserve actionable context.

## Reviewer Experience

A reviewer must be able to exercise real system capabilities through Streamlit, observe actual backend results, distinguish deterministic evidence from live evidence, and understand the operational state without reading source code first.

## Production Evidence

The module is not complete merely because its architecture exists. The production-ready deployment and scalable backend deliverables require executable and observable evidence.
