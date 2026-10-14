# Module 7 - Requirements

## Status

APPROVED - Human-approved strengthened requirements baseline, 2026-10-11.

These requirements are derived from the authoritative Module 7 course screenshot, explicit human instructions for Module 7, and additive repository engineering governance.

The authoritative course source remains controlling for course scope.
Explicit human instructions may strengthen implementation and acceptance criteria but shall not weaken, omit, replace, or reinterpret the course source.
Repository governance remains normative for engineering execution.
No requirement in this document is frozen until human approval.

## Requirement Classification

Requirements are classified as:

- SOURCE: directly represents the authoritative Module 7 screenshot.
- DERIVED: necessary to preserve source faithfulness or connect the source objective, topics, labs, tools, and deliverables.
- GOVERNANCE: additive engineering requirements established by repository/project governance.

Additive requirements shall not be represented as requirements originating from the course screenshot.

## Source Authority

The user-supplied Module 7 course screenshot is the ultimate authoritative course source.

Technology research, previous-module engineering lessons, repository governance, production-grade practices, and later architecture decisions may inform implementation but shall not replace, weaken, omit, or reinterpret source requirements.

## Objective

REQ-OBJ-001 [SOURCE]: The module shall prepare developers to engineer safe, reliable, and monitorable AI systems.

## Reliability and Resilience

REQ-REL-001 [SOURCE]: The module shall demonstrate retry strategies.
REQ-REL-002 [SOURCE]: The module shall demonstrate fallback mechanisms.
REQ-REL-003 [SOURCE]: The module shall demonstrate idempotency patterns.
REQ-REL-004 [SOURCE]: The module shall demonstrate resilience engineering.

## Safety and Guardrails

REQ-SAFE-001 [SOURCE]: The module shall demonstrate prompt injection defence.
REQ-SAFE-002 [SOURCE]: The module shall demonstrate tool permission control.
REQ-SAFE-003 [SOURCE]: The module shall demonstrate guardrails.
REQ-SAFE-004 [SOURCE]: The module shall demonstrate moderation systems.

## Observability

REQ-OBS-001 [SOURCE]: The module shall demonstrate workflow tracing.
REQ-OBS-002 [SOURCE]: The module shall demonstrate logging systems.
REQ-OBS-003 [SOURCE]: The module shall demonstrate latency monitoring.
REQ-OBS-004 [SOURCE]: The module shall demonstrate cost analytics.
REQ-OBS-005 [SOURCE]: The module shall demonstrate debugging pipelines.

## Evaluation and Continuous Improvement

REQ-EVAL-001 [SOURCE]: The module shall demonstrate automated evaluations.
REQ-EVAL-002 [SOURCE]: The module shall demonstrate regression testing.
REQ-EVAL-003 [SOURCE]: The module shall demonstrate benchmarking.
REQ-EVAL-004 [SOURCE]: The module shall demonstrate continuous improvement loops.

## Hands-on Labs

REQ-LAB-001 [SOURCE]: The module shall implement observability dashboards.
REQ-LAB-002 [SOURCE]: The module shall build automated evaluation pipelines.
REQ-LAB-003 [SOURCE]: The module shall simulate failure recovery workflows.

## Course-Indicated Tools

REQ-TOOL-001 [SOURCE]: The module shall meaningfully use LangSmith.
REQ-TOOL-002 [SOURCE]: The module shall meaningfully use Langfuse.
REQ-TOOL-003 [SOURCE]: The module shall meaningfully use Helicone.
REQ-TOOL-004 [SOURCE]: The module shall meaningfully use Guardrails AI.

Meaningful use means that the technology contributes observable and verifiable evidence to one or more source requirements, labs, or deliverables. Merely listing, installing, importing, or mentioning a technology does not constitute meaningful use.

## Required Deliverables

REQ-DEL-001 [SOURCE]: The module shall deliver an observability platform.
REQ-DEL-002 [SOURCE]: The module shall deliver an evaluation pipeline.

## Objective-to-Deliverable Closure

REQ-CLOSE-001 [DERIVED]: The completed observability platform and evaluation pipeline shall collectively demonstrate achievement of the Module 7 objective.

REQ-CLOSE-002 [DERIVED]: Every source topic shall have traceable implementation and verification evidence contributing to one or both required deliverables.

REQ-CLOSE-003 [DERIVED]: Every required hands-on lab shall produce traceable evidence contributing to one or both required deliverables.

REQ-CLOSE-004 [DERIVED]: Every course-indicated tool shall have meaningful, traceable, and verifiable use contributing to one or more source requirements, labs, or deliverables.

REQ-CLOSE-005 [DERIVED]: Completion of isolated requirements without coherent integration into the required deliverables shall not constitute completion of Module 7.

## Source Faithfulness

REQ-SRC-001 [DERIVED]: All source-derived requirements shall remain traceable to the authoritative Module 7 screenshot.

REQ-SRC-002 [DERIVED]: Additive engineering shall not omit, replace, reinterpret, weaken, or conflict with source-derived requirements.

REQ-SRC-003 [DERIVED]: Evidence shall distinguish implemented and exercised behavior from simulated, mocked, proposed, or unverified behavior.

REQ-SRC-004 [DERIVED]: Simulated or mocked evidence shall not be used to claim successful live integration or production behavior.

## Module Isolation

REQ-ISO-001 [GOVERNANCE]: Module 7 shall remain standalone and shall not depend on another academic module's implementation.

REQ-ISO-002 [GOVERNANCE]: Module 7 may apply repository-level governance and engineering lessons without importing, modifying, or reusing another module's implementation.

## Normative Repository Governance

REQ-GOV-001 [GOVERNANCE]: Module 7 engineering shall comply with applicable repository-level AGENTS.md, CLAUDE.md, ENGINEERING_SOP.md, and approved architecture and ADRs.

REQ-GOV-002 [GOVERNANCE]: If module documentation conflicts with the authoritative course source, the authoritative source controls course scope.

REQ-GOV-003 [GOVERNANCE]: If implementation guidance conflicts with an approved architecture or ADR without identifying a genuine defect or changed requirement, the approved architecture shall control until explicitly revised.

REQ-GOV-004 [GOVERNANCE]: Consequential architecture changes after architecture freeze shall require explicit justification and human approval.

## Presentation Layer

REQ-UI-001 [GOVERNANCE]: The module shall provide a runnable presentation layer through which a reviewer can inspect and exercise the module's functionality.

REQ-UI-002 [GOVERNANCE]: The presentation layer shall provide concise built-in guidance explaining what each major workflow demonstrates, what action a reviewer should take, what result to expect, and what that result proves.

REQ-UI-003 [GOVERNANCE]: Streamlit shall be the default presentation technology unless architecture evidence demonstrates that another platform is materially more capable for Module 7.

REQ-UI-004 [GOVERNANCE]: The presentation layer shall expose operational evidence without becoming a substitute for the underlying production-grade implementation.

## Reliability Engineering

REQ-ENG-001 [GOVERNANCE]: Runtime retries shall be bounded by explicit attempt limits and shall not create unbounded execution loops.

REQ-ENG-002 [GOVERNANCE]: External operations shall use bounded timeouts appropriate to their failure boundary.

REQ-ENG-003 [GOVERNANCE]: Retry behavior shall distinguish retryable failures from non-retryable failures.

REQ-ENG-004 [GOVERNANCE]: Fallback behavior shall be explicit, observable, testable, and shall preserve applicable safety and authorization controls.

REQ-ENG-005 [GOVERNANCE]: Idempotent operations shall prevent duplicate side effects when the same logical operation is retried or replayed.

REQ-ENG-006 [GOVERNANCE]: Failure of an observability or telemetry provider shall not silently grant additional authority, bypass safety controls, or corrupt core workflow state.

REQ-ENG-007 [GOVERNANCE]: Expected failure paths and recovery behavior shall be tested.

## Security and Authority Boundaries

REQ-SEC-001 [GOVERNANCE]: External input, retrieved content, telemetry content, tool results, and model output shall be treated as untrusted until validated at the appropriate boundary.

REQ-SEC-002 [GOVERNANCE]: LLM, agent, retrieved, or telemetry content shall not directly grant privileged authority or bypass tool authorization.

REQ-SEC-003 [GOVERNANCE]: Tool access shall follow explicit least-privilege permission controls independent of model-generated instructions.

REQ-SEC-004 [GOVERNANCE]: Validation and guardrail decisions shall not be treated as authorization decisions.

REQ-SEC-005 [GOVERNANCE]: Prompt-injection controls shall prevent untrusted content from redefining trusted system policy, authority boundaries, or privileged tool permissions.

REQ-SEC-006 [GOVERNANCE]: Credentials and secrets shall not be committed to source control, exposed through the UI, or emitted into telemetry, logs, traces, evaluation records, or error messages.

REQ-SEC-007 [GOVERNANCE]: Telemetry shall apply data minimization and redaction appropriate to potentially sensitive prompt, response, metadata, and tool content.

REQ-SEC-008 [GOVERNANCE]: Observability infrastructure shall not become a privileged control path capable of bypassing application authorization boundaries.

REQ-SEC-009 [GOVERNANCE]: Dependency selection and installation shall include supply-chain and vulnerability awareness appropriate to production-grade engineering.

REQ-SEC-010 [GOVERNANCE]: Dependency resolution shall reject guardrails-ai version 0.10.1 because of the upstream security advisory identified during Module 7 technology research.

## Cost and Resource Governance

REQ-COST-001 [GOVERNANCE]: Model calls, external service calls, retries, evaluations, and other potentially billable operations shall be bounded.

REQ-COST-002 [GOVERNANCE]: The system shall expose sufficient usage information to support the source-required cost analytics capability.

REQ-COST-003 [GOVERNANCE]: The ordinary automated quality gate shall not require billable model or vendor calls where deterministic substitutes can validate the same engineering contract.

REQ-COST-004 [GOVERNANCE]: Live external evaluations or integration checks shall be explicitly identifiable and separable from ordinary deterministic tests.

## Implementation Quality

REQ-QUAL-001 [GOVERNANCE]: Public Python interfaces shall use type hints appropriate to their contracts.

REQ-QUAL-002 [GOVERNANCE]: Modules, classes, public functions, and public methods shall use Google-style docstrings where appropriate, including Args, Returns, and Raises sections when applicable.

REQ-QUAL-003 [GOVERNANCE]: Exception handling shall be intentional and located at real failure boundaries; blanket exception swallowing is prohibited.

REQ-QUAL-004 [GOVERNANCE]: Errors shall be specific and actionable, and exception chaining shall preserve useful context where appropriate.

REQ-QUAL-005 [GOVERNANCE]: Runtime configuration, credentials, and environment-specific values shall be separated from committed application logic.

REQ-QUAL-006 [GOVERNANCE]: Dependency versions shall be deliberately constrained and verified for compatibility before release.

## Quality Gates and Self-Healing

REQ-QG-001 [GOVERNANCE]: Formal Python quality gates shall run fail-fast in the established order: Ruff, pytest, then compileall over the relevant source and test directories.

REQ-QG-002 [GOVERNANCE]: Ruff safe auto-fixes may be applied before the formal quality gate when appropriate; unsafe fixes shall not be applied automatically.

REQ-QG-003 [GOVERNANCE]: Automated repair shall be bounded by a maximum attempt count and shall rerun the failed gate followed by the complete fail-fast gate sequence before success is declared.

REQ-QG-004 [GOVERNANCE]: Tests, security controls, validation rules, or quality standards shall not be weakened, deleted, bypassed, or reclassified merely to obtain a passing build.

REQ-QG-005 [GOVERNANCE]: A later passing gate shall not override an earlier failed gate in the same fail-fast sequence.

REQ-QG-006 [GOVERNANCE]: Failures requiring genuine design, requirements, authority, or risk decisions shall escalate to human review rather than being automatically repaired.

## Evidence and Definition of Done

REQ-DOD-001 [GOVERNANCE]: Every requirement shall have explicit traceability to implementation evidence, verification evidence, or both as appropriate.

REQ-DOD-002 [GOVERNANCE]: Every source-derived requirement shall have verification evidence before Module 7 can be declared complete.

REQ-DOD-003 [GOVERNANCE]: Requirements involving runtime behavior shall be exercised by automated tests, demonstrable execution evidence, or both as appropriate.

REQ-DOD-004 [GOVERNANCE]: Live integration claims shall require matching live integration evidence; deterministic mocks or simulations may validate contracts but shall be labeled accordingly.

REQ-DOD-005 [GOVERNANCE]: The required deliverables shall be runnable and reviewable through documented execution paths.

REQ-DOD-006 [GOVERNANCE]: The presentation layer shall be runnable and shall provide sufficient guidance for a reviewer to exercise the demonstrated workflows.

REQ-DOD-007 [GOVERNANCE]: All formal quality gates shall pass before release.

REQ-DOD-008 [GOVERNANCE]: Documentation shall accurately describe the implemented system and shall not claim unimplemented, unverified, or merely proposed capabilities.

REQ-DOD-009 [GOVERNANCE]: Final traceability shall distinguish source requirements, derived requirements, governance requirements, implementation evidence, test evidence, live evidence, and simulated evidence.

REQ-DOD-010 [GOVERNANCE]: Module completion shall require the two source-required deliverables to collectively demonstrate the source objective, topics, labs, and meaningful use of the indicated tools.

## Architecture Boundary

This strengthened requirements baseline intentionally does not select:

- a primary observability backend
- a primary evaluation backend
- provider topology
- telemetry storage topology
- model providers
- retry libraries
- moderation implementation
- deployment architecture
- exact dependency versions except explicit security exclusions

Those decisions belong to the architecture phase and require evidence-based justification.

