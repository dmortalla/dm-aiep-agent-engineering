# Module 7 - Source Traceability

## Purpose

This document maps every source-derived Module 7 requirement to the authoritative course screenshot.

The screenshot remains controlling.

## Objective

| Requirement | Authoritative source |
| --- | --- |
| REQ-OBJ-001 | Module Objective: Prepare developers to engineer safe, reliable, and monitorable AI systems |

## Topics

| Requirement | Authoritative source |
| --- | --- |
| REQ-REL-001 | Topics: Retry strategies |
| REQ-REL-002 | Topics: Fallback mechanisms |
| REQ-REL-003 | Topics: Idempotency patterns |
| REQ-REL-004 | Topics: Resilience engineering |
| REQ-SAFE-001 | Topics: Prompt injection defence |
| REQ-SAFE-002 | Topics: Tool permission control |
| REQ-SAFE-003 | Topics: Guardrails |
| REQ-SAFE-004 | Topics: Moderation systems |
| REQ-OBS-001 | Topics: Workflow tracing |
| REQ-OBS-002 | Topics: Logging systems |
| REQ-OBS-003 | Topics: Latency monitoring |
| REQ-OBS-004 | Topics: Cost analytics |
| REQ-OBS-005 | Topics: Debugging pipelines |
| REQ-EVAL-001 | Topics: Automated evaluations |
| REQ-EVAL-002 | Topics: Regression testing |
| REQ-EVAL-003 | Topics: Benchmarking |
| REQ-EVAL-004 | Topics: Continuous improvement loops |

## Hands-on Labs

| Requirement | Authoritative source |
| --- | --- |
| REQ-LAB-001 | Hands-on Labs: Implement observability dashboards |
| REQ-LAB-002 | Hands-on Labs: Build automated evaluation pipelines |
| REQ-LAB-003 | Hands-on Labs: Simulate failure recovery workflows |

## Course-Indicated Tools

| Requirement | Authoritative source |
| --- | --- |
| REQ-TOOL-001 | Tools & Frameworks: LangSmith |
| REQ-TOOL-002 | Tools & Frameworks: LangFuse |
| REQ-TOOL-003 | Tools & Frameworks: Helicone |
| REQ-TOOL-004 | Tools & Frameworks: Guardrails AI |

## Deliverables

| Requirement | Authoritative source |
| --- | --- |
| REQ-DEL-001 | Deliverables: Observability platform |
| REQ-DEL-002 | Deliverables: Evaluation pipeline |

## Derived Source-Faithfulness Controls

REQ-SRC-001 through REQ-SRC-003 are governance controls derived from the requirement that the screenshot remain authoritative. They are not represented as additional course topics.

## Additive Repository Requirements

REQ-ISO-001 through REQ-ISO-002, REQ-UI-001 through REQ-UI-002, and REQ-ENG-001 through REQ-ENG-008 are additive repository engineering requirements. They are deliberately separated from the course-source mapping and must not be represented as course requirements.

## Architecture Status

No architecture decisions are frozen by this traceability baseline.

## Strengthened Acceptance and Governance Traceability

The following requirement families are intentionally additive and are not represented as direct course-screenshot requirements.

| Requirement family | Classification | Authority / rationale |
| --- | --- | --- |
| REQ-CLOSE-* | DERIVED | Connects the source objective, topics, labs, tools, and deliverables into an explicit completion contract |
| REQ-SRC-* | DERIVED | Preserves source authority, evidence fidelity, and distinction between live and simulated behavior |
| REQ-ISO-* | GOVERNANCE | Established standalone-module isolation policy |
| REQ-GOV-* | GOVERNANCE | Established repository engineering governance and architecture-freeze policy |
| REQ-UI-* | GOVERNANCE | Established runnable, guided presentation-layer Definition of Done |
| REQ-ENG-* | GOVERNANCE | Established production-grade reliability and failure-boundary standards |
| REQ-SEC-* | GOVERNANCE | Established security, prompt-injection, least-privilege, telemetry, and authority-boundary standards |
| REQ-COST-* | GOVERNANCE | Established bounded-cost and deterministic-CI standards |
| REQ-QUAL-* | GOVERNANCE | Established Python implementation and dependency-quality standards |
| REQ-QG-* | GOVERNANCE | Established fail-fast quality-gate and bounded self-repair standards |
| REQ-DOD-* | GOVERNANCE | Established evidence-backed completion and release standards |

These additive controls may strengthen how Module 7 is engineered and verified but shall not be described as additional requirements originating from the authoritative course screenshot.

## Completion Contract

Module 7 is not complete merely because each source item appears somewhere in the repository.

Completion requires verified implementation evidence showing that the observability platform and evaluation pipeline collectively demonstrate the source objective, all source topic families, all required labs, and meaningful use of all course-indicated tools.

## Architecture Status

Architecture remains UNFROZEN. No technology topology or implementation architecture is approved by this strengthened requirements baseline.

## Requirements Baseline Approval

**Status:** APPROVED

**Human approval date:** 2026-10-11

The human reviewer approved the strengthened Module 7 requirements baseline after validation confirmed that the previously identified weaknesses were corrected.

At approval:

- all 27 directly source-derived requirements were preserved and traced;
- objective-to-deliverable closure was encoded;
- source/live/simulated evidence distinctions were encoded;
- repository governance authority was encoded;
- module isolation and guided runnable UI requirements were encoded;
- reliability, security, authority, telemetry, and cost controls were encoded;
- Python engineering and dependency-quality standards were encoded;
- fail-fast quality gates and bounded self-repair were encoded;
- evidence-backed Definition of Done requirements were encoded.

This approval freezes the requirements baseline.

## Option 1 amendment reconciliation

The human-approved [ADR-007-013](adr/ADR-007-013-immutable-evidence-records.md)
and [architecture amendment](ARCHITECTURE.md#human-approved-option-1-amendment--immutable-evidence)
establish the following authority. All rows have lifecycle state: architecture
authority established; implementation repair pending; independent implementation
acceptance pending. Evidence below is REQUIRED FUTURE evidence, not accepted
evidence from the rejected candidate. Tests refer to the exact 20 conceptual
tests in the [Story 10 Revision 6 contract](stories/STORY-10-integrated-verification-release-readiness.md).

| Requirement | Applicable ADRs | Story | Conceptual tests | Required evidence |
| --- | --- | --- | --- | --- |
| REQ-EVD-001 | ADR-007-007, ADR-007-009, ADR-007-013 | 10 | 1, 7, 8, 10 | Producer-seam and fabricated-source rejection records |
| REQ-EVD-002 | ADR-007-006, ADR-007-013 | 10 | 1, 14 | Pre-recording minimization and all-output canary results |
| REQ-EVD-003 | ADR-007-009, ADR-007-013 | 10 | 1, 17 | Immutable envelope, trusted references, collision/rebinding probes |
| REQ-EVD-004 | ADR-007-007, ADR-007-009, ADR-007-013 | 10 | 1, 7, 17 | Reload/rederivation and corruption/staleness rejection results |
| REQ-EVD-005 | ADR-007-008, ADR-007-013 | 10 | 11, 12, 20 | Three-lane ledger and anti-promotion/open-live results |
| REQ-EVD-006 | ADR-007-008, ADR-007-013 | 10 | 17, 18 | Actual post-sequence gate record and synthetic repair attacks |
| REQ-EVD-007 | ADR-007-009, ADR-007-011, ADR-007-013 | 10 | 1, 13, 17, 18 | Atomicity/path/concurrency/retention and zero-network results |

These rows supplement REQ-OBJ-001, REQ-CLOSE-001..005, REQ-DOD-001..010
and REQ-QG-001..006 routing to Story 10. ADR-007-013 applies to their evidence
record/load and gate obligations alongside their existing applicable ADRs.
The reconciler MUST read frozen requirements, ADRs, story ownership and actual
test/evidence references independently; arbitrary rows cannot define truth.
Tests 2–3 require fabricated relationship/lab support rejection. Test 10 requires
policy outcome evidence from the accepted producer, including refusal paths.

It does not freeze architecture. Architecture remains subject to research, design, ADRs, validation, and subsequent human approval.
