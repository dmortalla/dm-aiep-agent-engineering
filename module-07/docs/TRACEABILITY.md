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

It does not freeze architecture. Architecture remains subject to research, design, ADRs, validation, and subsequent human approval.
