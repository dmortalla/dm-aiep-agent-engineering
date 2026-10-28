# Engineering SOP - Production Quality by Default

## Purpose

This document defines the repository-local engineering standard for dm-aiep-agent-engineering.

Unless a module is explicitly declared DEMO-ONLY through a human-approved decision, build toward production-grade quality and production readiness.
Production quality is opt-out, not opt-in.

## Source fidelity

Authoritative module source requirements define the minimum functional contract.
Engineering enhancements are additive only and must not omit, replace, weaken, reinterpret, or contradict authoritative requirements.
Genuine requirement, architecture, security, authority, material-cost, or release conflicts require human review.

## Standalone module isolation

Modules 6.5 through 10 are independently engineered units.
A module must not depend on another module source, tests, runtime state, prompts, fixtures, implementation, or module-local configuration unless authoritative source explicitly requires it and the human approves the relationship.

## Architecture-first lifecycle

1. Capture authoritative source evidence.
2. Freeze traceable requirements.
3. Research relevant dependency and compatibility constraints.
4. Establish architecture, trust boundaries, authority boundaries, and evidence classes.
5. Record consequential decisions in ADRs.
6. Obtain human architecture approval.
7. Freeze architecture.
8. Implement small vertical stories.
9. Independently review meaningful milestones.
10. Run fail-fast quality gates.
11. Exercise applicable failure, adversarial, security, recovery, and cost paths.
12. Reconcile implementation against requirements.
13. Complete the production-grade Definition-of-Done review.
14. Obtain required human approvals.
15. Publish only claims supported by evidence.

## Product experience

Every completed module must provide an appropriate runnable demonstration or operational interface.
Human-facing interfaces must explain the capability, action, expected result, result meaning, and demonstrated engineering capability.
Presentation must not substitute for sound domain architecture.

## Real functionality and evidence classification

Prefer genuine integrations where practical, valuable, secure, fiscally responsible, and source-faithful.
Mocks, fixtures, simulators, and injected doubles remain appropriate for deterministic CI, failure injection, adversarial testing, zero-key startup, and cost containment.

Evidence must distinguish deterministic fixture, mocked, adapter or SDK-construction, local integration, live external-service, and deployment evidence.
Claims must not exceed the strongest evidence actually obtained.

Every production-grade TAIE module that supports provider-backed AI must provide deterministic/no-key reviewer operation AND secure explicit opt-in BYOK/live operation. Server-side credentials may supplement BYOK but may not replace it.
A bring-your-own-key credential must be session-scoped and never persisted, logged, serialized, or exposed, and it grants connectivity only, never authority; live execution stays explicitly opted in, allowlisted, bounded, and separately classified as evidence.

## Reliability

Where relevant, integrate bounded execution, deadlines, retries, backoff, fallback, recovery, checkpointing, idempotency, concurrency limits, resource limits, and explicit stop conditions.
Expected failure paths require automated verification.

## Security and authority

Treat external content, retrieved content, model output, agent output, tool output, MCP content, and memory as untrusted until validated.
LLM or agent output must never directly acquire privileged application authority.
Use least privilege, explicit capability boundaries, validation, redaction, secret protection, and human approval for consequential actions.
Prompt injection and forged authority are explicit adversarial concerns.

## Fiscal responsibility

Bound tokens, requests, retries, external calls, execution time, concurrency, and resource exposure where relevant.
Normal tests, imports, startup, and deterministic demonstrations must not silently incur external charges.
Credential presence alone is not authorization for billable execution.
Potentially billable verification must be explicit, bounded, attributable, and human-authorized when required.

## Observability

Observability must describe system behavior without becoming a correctness dependency.
Telemetry must respect redaction, bounded cardinality, retention, resource, and cost constraints.
Observability failure must not silently alter workflow semantics.

## Python engineering standard

Use type hints for public interfaces and Google-style docstrings where appropriate.
Place exception handling at genuine failure boundaries.
Avoid blanket exception swallowing.
Provide actionable errors, preserve causal context when appropriate, and test expected failures.

## Quality gates and self-repair

Use stronger repository-specific gates when defined.
Default Python sequence: Ruff, pytest, compileall.
Stop at the first failing gate.
Safe deterministic repair may be automated. Never automatically apply unsafe fixes.
Semantic repair must be bounded and preserve requirements, architecture, tests, security controls, and quality rules.
After repair, rerun the failed gate and then the full gate sequence.

## Evidence hygiene

Files that properly document the shipped project may live in the repository, including requirements, traceability, ADRs, architecture, verification records, and release documentation.
Temporary review captures, diagnostics, inventories, agent-review transcripts, comparison artifacts, and other engineering-process evidence that does not belong to the shipped project must be stored under the parent TECHADEMY/EVIDENCE directory.
Do not commit temporary evidence merely because it was useful during development.

## Production-Grade Definition of Done

Evaluate applicable gates in this order:

Requirements -> Product Experience -> Real Functionality -> Reliability -> Security -> Cost -> Evidence -> Deployment

A module may be functionally complete while still not production-grade.
Production-grade claims require evidence proportional to the claim.

## Human authority

Human approval is required for genuine decisions involving requirement interpretation or deviation, architecture approval or exceptions, meaningful security tradeoffs, expansion of privileged authority, material cost exposure, acceptance of consequential limitations, and governed release decisions.
Mechanical verification, deterministic bookkeeping, evidence gathering, and previously authorized implementation should not be unnecessarily blocked.

## Governing principle

Build the smallest system that completely satisfies its authoritative requirements while advancing it as far toward secure, reliable, fiscally responsible, observable, maintainable, and evidence-backed production quality as reasonably achievable.
