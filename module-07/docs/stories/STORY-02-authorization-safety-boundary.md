# Story 2 - Authorization, Prompt-Injection Containment, Guardrails, and Moderation

## Goal

Implement the application-owned safety and authority boundary before any privileged or live provider behavior exists.

## Authoritative Scope

- explicit allowlisted tool permissions
- application-owned authorization decisions
- prompt-injection containment
- deterministic input and output safety checks
- Guardrails AI adapter and supported validator integration
- moderation policy and evidence
- forged-authority and permission-bypass adversarial tests
- fail-closed safety-provider behavior

## Requirements

- REQ-SAFE-001
- REQ-SAFE-002
- REQ-SAFE-003
- REQ-SAFE-004
- REQ-TOOL-004
- REQ-SEC-001
- REQ-SEC-002
- REQ-SEC-003
- REQ-SEC-004
- REQ-SEC-005
- REQ-SEC-006
- REQ-SEC-009
- REQ-SEC-010
- REQ-ENG-007

Governance-family traceability is represented in TRACEABILITY.md through the approved REQ-SEC-* and REQ-ENG-* family mappings.

## Frozen Architecture Constraints

- Application code owns authorization, privileged authority, and tool-permission decisions.
- Guardrails performs safety validation; Guardrails validation does not grant authorization.
- External input, retrieved content, telemetry content, tool results, and model output remain untrusted until validated at the appropriate boundary.
- LLM, agent, retrieved, telemetry, or validator output cannot directly grant privileged authority or bypass application-owned authorization.
- Tool access uses explicit least-privilege allowlisting independent of model-generated instructions.
- Prompt-injection controls prevent untrusted content from redefining trusted system policy, authority boundaries, or privileged tool permissions.
- Credentials and secrets must not be exposed through source control, UI, telemetry, logs, traces, evaluation records, or errors.
- Dependency selection remains security-aware.
- guardrails-ai version 0.10.1 is prohibited.
- Story 2 establishes the authority boundary before later privileged or live-provider integration.

## Assigned ADRs

- ADR-007-003
- ADR-007-005
- ADR-007-011

These frozen ADRs govern Story 2 implementation and do not create new architectural authority.

## Implementation Boundaries

Story 2 may implement:

- application-owned authorization policy and decisions
- explicit tool-permission allowlists
- trusted-versus-untrusted input separation
- prompt-injection containment controls
- deterministic input/output safety checks
- moderation policy and deterministic moderation evidence
- a Guardrails adapter boundary and supported validator integration
- actual Guardrails usage evidence satisfying REQ-TOOL-004
- rejection of stale Guardrails Hub installation patterns in accordance with ADR-007-011
- fail-closed handling of safety-provider failures
- adversarial tests for forged authority, injection attempts, and permission bypass

Story 2 must not:

- allow model, agent, retrieved, telemetry, tool, or validator content to self-grant authority
- treat Guardrails or moderation results as authorization
- introduce privileged live-provider behavior before the authority boundary exists
- weaken or bypass the frozen Story 1 typed contracts and configuration boundaries
- modify or depend on sibling modules
- modify frozen Module 7 requirements, traceability, architecture, ADRs, or Story 1 authority
- resolve or install guardrails-ai 0.10.1
- make unsupported live-provider, live-model, or deployment claims

## Security Acceptance

Acceptance evidence must demonstrate at minimum:

- untrusted content cannot redefine trusted policy
- forged authorization objects cannot grant authority
- unauthorized tool requests are denied
- allowlisted authorized requests follow the application-owned authority decision
- safety validation remains separate from authorization
- prompt-injection attempts cannot widen permissions
- safety-provider failure is fail-closed
- sensitive values are not exposed by Story 2 behavior or evidence
- Guardrails dependency handling respects the prohibited-version requirement

## Mandatory Guardrails Execution

Story 2 must execute at least one supported guardrails-ai validator inside the application safety boundary and produce observable deterministic evidence of that validator's contribution to a safety decision.

Merely listing, installing, importing, configuring, or mocking Guardrails does not satisfy REQ-TOOL-004.

A mocked Guardrails adapter may provide mocked_provider_contract evidence, but mocked execution alone does not satisfy the meaningful-use requirement.

The required real guardrails-ai validator execution remains deterministic_fixture evidence. It does not constitute live-provider, live-model, network, deployment, or production evidence.

Guardrails validation remains a safety-validation input only and cannot grant authorization, widen tool permissions, or redefine application-owned policy.

## Required Tests

Story 2 tests must explicitly verify:

- application-owned allowlisted authorization permits only authorized tool access
- forged or model-generated authority cannot grant privileged access
- untrusted content cannot redefine trusted policy, authority boundaries, or tool permissions
- prompt-injection attempts cannot widen permissions
- Guardrails validation is exercised and remains separate from authorization
- supported Guardrails validator integration is exercised without stale Guardrails Hub installation patterns
- deterministic input safety checks accept permitted input and reject unsafe input according to the application-owned safety policy
- deterministic output safety checks accept permitted output and reject unsafe output according to the application-owned safety policy
- moderation behavior is exercised with both permitted and denied outcomes
- safety-provider failure fails closed
- secrets and credentials are not exposed through Story 2 behavior, errors, logs, telemetry, or evidence
- prohibited guardrails-ai version 0.10.1 cannot satisfy the dependency contract

## Evidence Classification

Default Story 2 evidence is deterministic_fixture plus mocked_provider_contract unless a later explicitly authorized test genuinely exercises a live integration.

Simulation, deterministic validation, adapter tests, and mocks must not be described as live-provider or live-model evidence.

## Quality Gates

Run fail-fast in this order:

1. Ruff
2. pytest
3. compileall

Ruff safe auto-fix may be used before the formal gate. Unsafe fixes and test weakening are prohibited.

## Isolation

Module 7 remains standalone. Story 2 must not import from, copy from, modify, or create runtime dependencies on sibling modules.

Concurrent Module 6.5 work is outside Story 2 scope and must remain untouched.

## Definition of Done

Story 2 is complete only when:

- all assigned Story 2 requirements are implemented or evidenced within the approved scope
- the application-owned authority boundary is explicit and tested
- prompt-injection containment and least-privilege permission controls are demonstrated
- Guardrails validation remains subordinate to application authorization
- deterministic safety and moderation behavior is tested
- fail-closed safety-provider behavior is tested
- adversarial forged-authority and permission-bypass tests pass
- dependency-security constraints are preserved
- Ruff, pytest, and compileall pass
- repository/module isolation is preserved
- evidence claims are accurately classified
- frozen authorities remain unchanged
- an independent reviewer accepts Story 2

Story 3 must not begin until Story 2 receives independent acceptance.

## Non-Goals

Story 2 does not implement the later reliability controller, vendor observability platforms, automated evaluation pipeline, Helicone integration, failure-recovery lab, Streamlit console, or release closure assigned to subsequent stories.