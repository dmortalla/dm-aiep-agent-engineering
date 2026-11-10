# Module 10 Requirements

## Authoritative Objective

Teach learners how to deploy, scale, and manage production-grade AI systems.

## Course Requirements

| ID | Requirement | Classification |
|---|---|---|
| C-001 | FastAPI for AI systems | course |
| C-002 | Docker | course |
| C-003 | API deployment | course |
| C-004 | Container orchestration | course |
| C-005 | Async architectures | course |
| C-006 | Queue systems | course |
| C-007 | Caching strategies | course |
| C-008 | Load balancing | course |
| C-009 | Performance optimisation | course |
| C-010 | CI/CD for AI | course |
| C-011 | Monitoring pipelines | course |
| C-012 | Cost optimisation | course |
| C-013 | Reliability engineering | course |
| C-014 | Security | course |
| C-015 | Deployment checklists | course |
| C-016 | Incident response | course |
| C-017 | Rollback strategies | course |
| C-018 | SLA considerations | course |
| C-019 | Lab: deploy AI application using FastAPI | course |
| C-020 | Lab: Dockerize AI workflows | course |
| C-021 | Lab: build scalable deployment pipeline | course |
| C-022 | Tool: FastAPI | course |
| C-023 | Tool: Docker | course |
| C-024 | Tool: Azure Container Apps | course |
| C-025 | Tool: Azure Monitor | course |
| C-026 | Deliverable: production-ready AI deployment | course |
| C-027 | Deliverable: scalable AI backend system | course |

## Approved Engineering Requirements

| ID | Requirement | Classification |
|---|---|---|
| E-001 | Module 10 remains standalone and isolation-preserving | approved architecture |
| E-002 | Streamlit provides the reviewer-facing presentation and demonstration layer | approved architecture |
| E-003 | Authoritative business logic remains outside Streamlit | approved architecture |
| E-004 | Material capabilities expose reviewer-visible working results | approved architecture |
| E-005 | Deterministic no-key operation is the default demonstration path | approved architecture |
| E-006 | Live AI mode is explicit opt-in with non-persistent secret handling | approved architecture |
| E-007 | Evidence classifications distinguish deterministic, local-runtime, and live-cloud results | approved architecture |
| E-008 | Untrusted input and AI output cannot directly control privileged behavior | approved architecture |
| E-009 | Native fail-fast quality gates precede custom verification | approved architecture |
| E-010 | Cloud usage has explicit cost boundaries and teardown procedures | approved architecture |
| E-011 | Public Python interfaces use type hints and appropriate Google-style docstrings | approved architecture |
| E-012 | Expected failure paths use intentional exception handling and tests | approved architecture |

## Recovery Authorization Requirements (Story 10.9, structural stage implemented)

| ID | Requirement | Classification |
|---|---|---|
| RE-001 | Story 10.9 recovery grants are structurally validated offline fail-closed with an exact 23-field signed Step 73 payload and a versioned RSA-PSS-SHA256 envelope whose signature shape is bounded but never authenticated by the validator | IMPLEMENTED — STRUCTURAL SCOPE ONLY (committed `src/module10_ai/recovery_authorization.py` + 64 focused tests in `tests/test_recovery_authorization.py`; structural tests only) |
| RE-002 | Cryptographic signature verification against the operator's protected public trust anchor is a separate stage and never claims issuance or authenticity beyond its verification result | planned architecture (stage R1) |
| RE-003 | Independent human approval binding (approval reference, version and digest) is a separate stage and never treats grant structure as approval | planned architecture (stage R2) |
| RE-004 | Durable single-use replay prevention is a separate fail-closed stage consumed only after the earlier gates pass | planned architecture (stage R3) |
| RE-005 | Recovery planning derives a concrete plan from a verified grant plus fresh read-only observations and yields no execution authority | planned architecture (stage R4) |
| RE-006 | Authorized recovery execution uses a fixed mutation command family under fresh explicit human authorization, bounded attempts, and telemetry | planned architecture (stage R5) |
| RE-007 | Independent outcome verification re-runs the accepted cloud snapshot/HTTPS/Monitor contracts and produces durable audit evidence with exclusive-create persistence | planned architecture (stage R5/R6) |
| RE-008 | Issuer signing identity stays non-exportable in protected Windows key storage; recovery execution identity is separate and least-privileged | approved architecture (protected trust boundary) |

RE-001 records the implemented structural stage only: structural validation is
not cryptographic authentication, human approval, replay protection, or
recovery authorization. RE-002 through RE-007 record authorized plan stages and
no row other than RE-001 is implemented; RE-008 is an approved
existing-trust-boundary architecture statement, not an implemented new service.
Operational activation of any remaining stage requires separate human
authorization and its own implementation evidence.
