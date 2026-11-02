# Story 9 — Streamlit Observability and Evaluation Console

## Status and Authority

**Status:** PROPOSED — contract design awaiting independent review and human
acceptance. Implementation must not begin until that acceptance.

This contract is subordinate to the frozen Module 7 authorities:

- `docs/REQUIREMENTS.md`
- `docs/TRACEABILITY.md`
- `docs/ARCHITECTURE.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/adr/ADR-007-010-streamlit-presentation.md`

It implements the Story 9 assignment in the frozen implementation plan. It
does not amend any authority, reopen an accepted story, or create a release
claim.

## Purpose

Story 9 delivers the runnable, guided reviewer console for the two Module 7
deliverables:

1. an observability platform; and
2. an evaluation pipeline.

The console makes existing working Module 7 results inspectable and
reproducible. It presents deterministic workflow and failure-recovery evidence,
normalized telemetry, safety and authorization decisions, latency and cost
facts, benchmark and regression output, and accurately classified provider
evidence. It is a presentation and demonstration layer, never a new control
plane.

The default reviewer experience is credential-free, deterministic, local, and
network-free. A reviewer can obtain meaningful results without configuring a
vendor account or typing a secret into the UI.

## Requirement and ADR Coverage

| Authority | Story 9 responsibility |
| --- | --- |
| REQ-UI-001 | Runnable Streamlit reviewer presentation layer. |
| REQ-UI-002 | Each major workflow gives concise purpose, action, expected result, and proof guidance. |
| REQ-UI-003 | Uses Streamlit as the approved presentation technology. |
| REQ-UI-004 | Presents authoritative existing results without replacing underlying implementation. |
| REQ-LAB-001 | Presents normalized observability dashboard evidence. |
| REQ-LAB-002 | Presents deterministic evaluation, benchmark, regression, and improvement evidence. |
| REQ-LAB-003 | Drives and presents the accepted Story 8 S01–S20 failure-recovery lab surface. |
| REQ-DEL-001 | Surfaces observability-platform results coherently. |
| REQ-DEL-002 | Surfaces evaluation-pipeline results coherently. |
| ADR-007-010 | Implements the approved integrated Streamlit reviewer console; specialist vendor dashboards remain complementary. |

The contract depends on, but does not reimplement, the Stories 1–8 authority,
safety, reliability, telemetry, evaluation, and provider boundaries.

## Reviewer Journey

The console shall open on a short **Start here** view that states the current
execution mode and evidence classes, then offers these reviewer journeys:

| Journey | Reviewer action | Expected result | What it proves |
| --- | --- | --- | --- |
| Deterministic workflow | Select the fixed approved deterministic demonstration and run it. | An authoritative recovery result with correlation identifiers, decisions, attempts, timing, usage and evidence label. | The console is exercising existing application controls rather than displaying static prose. |
| Observability lab | Inspect the trace, structured-log summary, reliability and cost panels for that run. | Redacted normalized operational facts correlated by workflow/trace identity. | REQ-LAB-001 and the observability platform are reviewer-visible without exposing raw telemetry. |
| Evaluation lab | Run the deterministic benchmark against the committed baseline. | Benchmark verdict, canonical report digest, regression outcome/findings, and improvement comparison. | REQ-LAB-002 and evaluation pipeline operate without credentials or network. |
| Failure-recovery lab | Select one named Story 8 scenario, or run the complete fixed matrix. | The typed `LabScenarioResult` or `LabSummary`, including pass/fail, attempts, fallbacks, effects, budget, decisions and evidence class. | REQ-LAB-003 uses the accepted finite failure taxonomy and real underlying boundaries. |
| Provider evidence | Inspect provider status/evidence cards and optional verified live evidence only when already enabled. | Explicitly labeled unavailable, deterministic, mocked-provider-contract, or live evidence facts. | Provider results are evidence, never authority, and claims match their evidence. |

Every view above shall place its four-part guidance immediately beside or above
the related control: **demonstrates**, **do this**, **expect**, and **proves**.
Guidance must use plain language and must not hide a caveat needed to interpret
an evidence label.

## Scope

### In scope

- A Streamlit entry point and presentation-only helper modules under Module 7.
- Guided deterministic workflow, evaluation, and failure-lab controls.
- Read-only rendering of typed application results and sanitized provider
  evidence.
- Reviewer-visible summary cards, tables, charts and expandable JSON only for
  already minimized and safe primitive projections.
- A fixed evidence legend and per-result evidence label.
- Error states that preserve the existing fixed/sanitized application error
  classification and do not render exception text.
- Deterministic Streamlit tests and zero-network-default verification.

### Explicit non-goals

- No new retry, fallback, idempotency, budget, authorization, moderation,
  safety, provider, telemetry, evaluation, or redaction semantics.
- No generic agent, chat, raw prompt console, model selection, provider
  configuration form, credential field, API-key persistence, or arbitrary tool
  invocation.
- No direct vendor SDK use, direct HTTP client use, adapter-private access, or
  vendor-dashboard recreation in Streamlit.
- No baseline mutation, evaluation-policy mutation, workflow-state mutation
  outside the existing accepted public execution paths, or automatic
  improvement application.
- No live evidence requirement, deployment, release closure, Story 10
  reconciliation, or claim that a deterministic run proves a live provider.
- No dependency on or inspection of sibling academic module implementations.

## Presentation Boundary and Authoritative Interfaces

The UI shall call only public Module 7 application interfaces and shall map
their returned typed facts into display-only view models. It shall never
recompute an outcome, infer authority from a provider response, or synthesize a
success state because a button was clicked.

| UI concern | Required existing interface(s) | UI responsibility |
| --- | --- | --- |
| Runtime mode | `RuntimeSettings`, `ExecutionMode`, `EvidenceClass` | Display configuration-derived mode and evidence class; never edit settings or unwrap secrets. |
| Controlled deterministic workflow | `ReliabilityController.execute`, `AuthorizationPolicy`, `SafetyPipeline`, `WorkflowState`, `Target`, `RecoveryResult` through a Story 9 composition boundary | Invoke only a finite, fixed, authorized demonstration plan and render its returned `RecoveryResult`. |
| Safety and authority | `RecoveryResult.state.authorization`, `RecoveryResult.state.safety`, `SafetyAssessment`, `AuthorizationDecision` | Render decision/reason identifiers already produced by the boundary; never provide allow/deny controls. |
| Observability | `from_recovery`, `Observation`, `TelemetryPipeline.records`, `log_event` | Render only the neutral, redacted record projection and correlation identifiers. |
| Failure lab | `ScenarioKind`, `run_scenario`, `run_full_lab`, `run_lab`, `LabScenarioResult`, `LabSummary` | Expose only the accepted S01–S20 selector/full matrix; show typed result fields unchanged in meaning. |
| Evaluation | `load_benchmark_dataset`, `EvaluationEngine`, `BenchmarkRunner.run_full`, `ReferenceTarget.build`, `load_committed_baseline`, `BenchmarkOutput`, `improvement_cycle` | Run and render the deterministic committed benchmark and regression output. |
| Langfuse | `LangfuseSink.status`, `LiveVerificationResult`, `run_live_verification` | Display sanitized status or a separately requested, existing verifier result. |
| LangSmith | `LangSmithExportPlan`, `LiveVerificationResult`, `run_live_langsmith_verification` | Display sanitized plan/result facts or a separately requested existing verifier result. |
| Helicone | `HeliconeEvidenceSnapshot`, `HeliconeLiveVerificationResult`, `run_live_helicone_verification` | Display accepted evidence state/result facts or a separately requested existing verifier result. |

The exact Story 9 implementation may add a narrowly scoped presentation
adapter such as `console_presenter.py` or `streamlit_app.py`. That adapter may
construct a fixed demo plan and convert public typed models to safe display
models. It shall contain no policy decision, retry/fallback loop, provider
transport, redaction algorithm, evaluator, credential acquisition, or business
outcome computation. The fixed demo plan is a composition of existing public
interfaces, not a second workflow service.

The existing public API has no accepted general-purpose workflow-service facade.
Accordingly, Story 9 must not invent one. Its workflow control is a bounded,
documented deterministic demonstration plan and its failure controls are the
accepted Story 8 public lab functions.

## Console Information Architecture

The implementation shall provide a clear navigation mechanism, such as tabs or
pages, with these stable sections:

1. **Overview and evidence legend** — module purpose, running mode, evidence
   legend, reviewer journey, and no-key starting point.
2. **Workflow and observability** — deterministic workflow control; trace,
   structured-log, authorization, safety, retry/fallback/replay/recovery,
   latency, usage and cost facts.
3. **Evaluation and regression** — deterministic benchmark control; scenario
   results, verdict, report digest, baseline comparison, regression findings,
   and improvement-cycle facts.
4. **Failure-recovery lab** — S01–S20 control and full-matrix control;
   scenario/result/summary facts and evidence classifications.
5. **Provider evidence** — read-only provider cards and the optional live
   evidence action described below.

Each section shall render meaningful facts before and after an action. Before a
run, it must say that no result has been run rather than display a fabricated
pass. After a run, it must render returned identifiers/counts/classifications,
not a generic "completed" state.

## Deterministic and No-Key Behavior

Deterministic mode is the default and is first-class:

- It starts without vendor credentials and performs no live-provider transport
  activation, live model call, or non-loopback network operation.
- It permits accepted local/offline execution transitively reached through
  existing public application interfaces. This expressly includes Story 8's
  `LabRunner`, its accepted local `GuardrailsCredentialProvider`/Guardrails
  validation behavior, and accepted deterministic/offline adapter surfaces.
  Such local safety/validation behavior is neither a live provider activation
  nor a live-evidence claim.
- Story 9 presentation code itself must not directly import a provider SDK,
  construct a vendor/live client, access a private provider transport, execute
  network/provider work, bypass a public application interface, or recreate
  accepted safety/business behavior in Streamlit.
- It uses the committed benchmark dataset/baseline and reference target for
  evaluation, not an input supplied through the browser.
- It exposes only finite known workflow controls and `ScenarioKind` values.
- It labels deterministic benchmark and normalized telemetry evidence
  `deterministic_fixture`; Story 8 governed recovery results remain
  `simulated_failure`; accepted fake/offline adapter results remain
  `mocked_provider_contract` where that is their actual class.
- It retains no raw user prompt or provider payload in Streamlit session state,
  downloadable payloads, exception text, UI logs, or cache keys.

Ambient credentials, selecting a provider/model, a normal Streamlit rerun, and
ordinary rendering cannot activate live behavior or promote evidence. A
deterministic interaction must reject/disable a duplicate in-flight action;
completed deterministic actions may be deliberately run again only as a new
bounded reviewer action, never as an implicit rerun side effect. UI session
state is presentation state, not idempotency or business authority. A returned
result's own `replayed` fact must be rendered accurately when the application
says it is a replay.

## Optional Live-Provider Evidence

Live behavior is optional evidence generation, never a default reviewer path.
The sole UI-triggered outbound live action permitted by Story 9 is a separately
and explicitly confirmed **Generate bounded live evidence** action which calls
one existing public Story 5/6/7 verifier. It is permitted only when all of
these are true:

1. `RuntimeSettings` is already valid for explicit live mode and integrations;
2. the provider-specific existing settings are valid and supplied outside the
   UI through the accepted explicit BYOK/configuration secret path. Server-side
   credentials may supplement that path but may not replace an available BYOK
   path;
3. the reviewer performs a separate confirmation action for that one verifier;
4. the existing verifier's own opt-in, endpoint qualification, call/cost/deadline
   bounds, provenance qualification and close behavior are used unchanged; and
5. the returned evidence is rendered with exactly its returned evidence class
   and verifier outcome.

The UI must have no credential-entry, credential-display, or
credential-persistence path, and no text fields for endpoints, headers,
prompts, budgets, provider routing, or opt-in environment values. The reviewer
uses the existing externally supplied BYOK/configuration path, which is the
only allowed credential handoff for Story 9. A credential never enters logs,
session state, cache keys, telemetry, errors, downloadable data, or display
output. Presence of a credential never enables a live action by itself and
never grants workflow/tool authority. If any required gate is false, the UI
shall render a fixed, actionable **live evidence unavailable** status without
leaking why a credential is missing.

No outbound work may occur on application startup, ordinary Streamlit reruns,
rendering, deterministic/no-key controls, disabled or unavailable live
controls, credential detection, or provider/model selection. An enabled live
control still performs no outbound work until its separate confirmation action
succeeds. The UI must not create another provider transport or live verifier,
infer authorization from credential presence, mint live evidence, or bypass the
existing verifier's allowlists, bounds, retries/timeouts, cost/latency controls,
provenance, redaction, or cleanup behavior.

Successful live verification may support a `live_vendor` claim only for that
specific returned verification result. It does not upgrade deterministic
workflow, benchmark, lab, safety, authorization, or provider-absence results.
`live_model` may be shown only when an existing public result carries that
class. Story 9 creates no new evidence class.

## Evidence Display Contract

Every result card/table row shall display a human-readable evidence badge and
the exact machine label. The fixed legend is:

| Evidence class | Meaning in the console | Claim boundary |
| --- | --- | --- |
| `deterministic_fixture` | Local deterministic application or benchmark evidence. | Does not prove live vendor/model behavior. |
| `simulated_failure` | Story 8 controlled failure/recovery evidence. | Does not prove a live incident or provider outcome. |
| `mocked_provider_contract` | Accepted fake, seam, offline-refusal, or adapter-contract evidence. | Does not prove provider ingestion or production behavior. |
| `live_vendor` | A qualified existing provider verification result. | Proves only the exact verified provider interaction. |
| `live_model` | A qualified existing model-backed result. | Proves only the exact verified model interaction. |

Unknown, missing, malformed, contradictory, failed, unavailable, or unresolved
provider evidence must be displayed as such. It must not become a green
operational, cost, fallback, safety, or authorization state.

## Required Working Results

### Observability platform and Lab 1

The workflow/observability view shall visibly render, from an authoritative
returned workflow and telemetry result:

- workflow, trace, span and idempotency correlation identifiers;
- terminal classification and evidence class;
- structured-log/telemetry event summary using redacted/minimized records;
- attempt count, retry history, fallback count/used state, recovered/replayed
  facts and remaining attempt/time facts where available;
- authorization and safety decision/reason identifiers;
- duration/latency, usage basis, normalized cost, actual cost, overage and
  budget usage/limit facts where available; and
- provider delivery/lifecycle status as evidence-only, never a workflow truth.

Charts may aggregate only numeric typed facts already in the returned models.
They must label units, distinguish unknown from zero, and not estimate cost or
latency from absent values.

### Evaluation pipeline and Lab 2

The evaluation view shall run the existing deterministic benchmark against the
committed dataset and baseline and render:

- benchmark verdict, dataset/version/digest, canonical report digest and
  declared scenario subset/full-run status;
- evaluation scenario and evaluator outcomes from the returned artifact;
- regression outcome, threshold findings and affected scenario/metric facts;
- benchmark result summaries and class labels; and
- a reviewer-selected `improvement_cycle(before, after)` only when two genuine
  `RunResult` values from accepted public benchmark execution exist, clearly
  marked as evidence/proposal context rather than an automatic code or policy
  change.

`BenchmarkOutput` is not an improvement cycle. After each completed
deterministic benchmark, the UI may retain its genuine `run.result` as one of
at most two bounded, safe display references: **before** and **after**. The UI
must make their provenance (benchmark run and selection order) visible, invoke
`improvement_cycle` only with those two valid returned `RunResult` objects, and
show a fixed guided unavailable state until both exist. Missing, invalid, or
incompatible comparison inputs fail closed; the UI must not fabricate a
comparison. One benchmark remains the maximum per interaction, and retaining
comparison state does not create a baseline writer or a new evaluation service.

The UI shall not write a baseline or invoke `candidate_baseline`; it shall not
transform a failing regression into a pass.

### Failure-recovery lab and Lab 3

The lab view shall offer only:

- a selector containing exactly `ScenarioKind.S01` through `ScenarioKind.S20`;
- **Run selected scenario**, which calls `run_scenario` once; and
- **Run complete matrix**, which calls `run_lab` once.

It shall render `LabScenarioResult` and `LabSummary` fields including scenario
ID, expected/observed disposition, attempts, fallbacks, effect count, budget
before/after, authority/safety outcome, telemetry state, reason codes,
evidence class, pass/fail and deterministic summary digest. It must preserve
the Story 8 distinction between a single scenario and the complete fixed matrix
and must not allow a free-form or arbitrary script/policy/scenario builder.

## Safety, Trust, Redaction, and Failure UX

- Browser values, Streamlit query parameters, uploaded values, session state,
  provider responses and any strings attached to exceptions are untrusted.
  They must never be used as policy, authority, evaluation, evidence, provider
  configuration or rendering instructions.
- No raw prompt, model output, secret-shaped text, provider response body,
  exception traceback, `SecretStr`, configuration object, raw telemetry record
  before minimization, or arbitrary metadata may be passed to Streamlit display
  functions or `st.session_state`.
- Render only allowlisted display projections of immutable typed public models.
  Reuse the Story 4 minimization/redaction output; Story 9 must not implement a
  second redactor or decide what sensitive data is safe.
- Injection/safety/authorization failures are ordinary reviewer-visible
  outcomes: show the fixed classification and safe decision/reason identifiers,
  explain that no authority was granted, and offer a deterministic next action.
  Do not show the rejected input.
- Provider/export failure is non-authoritative: show sanitized state and retain
  local deterministic results. Do not render transport exception messages or
  suggest that a provider failure changed core workflow state.
- Unexpected UI/application errors show a fixed safe message, an optional
  generated non-sensitive correlation ID if already available, and a retry
  instruction. Detailed diagnostics stay in existing structured logging after
  its redaction boundary; no traceback is rendered in the browser.

## Resource, Accessibility, and Usability Bounds

- A single Streamlit interaction starts at most one deterministic workflow,
  one selected Story 8 scenario, one complete Story 8 matrix, or one benchmark.
  The UI must disable/reject a concurrent, duplicate, or replayed UI action
  while one is running. A rerun cannot silently repeat a live/provider or other
  consequential action. Existing application idempotency/replay behavior,
  rather than UI session state, remains authoritative.
- It must not create unbounded threads/tasks, run a provider verifier on page
  load, poll vendors, retain a session-wide unbounded result history, or cache
  live results as if they were current. Session state retains at most the most
  recent result per section and contains only safe display projections.
- The lab retains its accepted bounds: fixed S01–S20 taxonomy; selected run or
  one complete matrix; no user-editable policies/scripts.
- Benchmark and live verifier bounds remain those enforced by their public
  application interfaces; the UI must not widen them.
- Controls are keyboard reachable, have visible labels, and pair charts with a
  table/text alternative. Status never relies on color alone. Evidence class,
  mode, disabled reason, units, empty state and failure state use text.
- The opening page and every major action include concise self-guidance; no
  reviewer must read repository source to understand a result.

## Implementation Shape (Post-Acceptance)

Story 9 may add only the smallest sufficient presentation files, for example:

- a Streamlit entry module;
- a typed, presentation-only projection/composition module; and
- a dedicated Story 9 test file or files.

Adding the constrained `streamlit` runtime dependency during implementation is
permitted only if its version is pinned compatibly with Python 3.12 and the
existing dependency strategy. It is not a license to add a provider SDK,
database, queue, web framework, secret manager, or another application layer.
The contract does not select an exact version; that is a routine dependency
compatibility decision verified during implementation, not an architecture
change.

The implementation must leave package startup deterministic: importing the
core package must not import Streamlit, construct a provider client, read a
secret, or make a network call. The Streamlit entry point may be launched
explicitly only.

## Exact Proposed Test Inventory

Implementation shall add **24 numbered tests** in Story 9-owned test files.
They are maintainable Python tests around public presentation helpers and
Streamlit's supported testing API where available; no custom source-string
meta-verifier substitutes for behavioral evidence.

1. App entry renders a title, purpose, deterministic/no-key notice and evidence legend.
2. Every major journey renders all four guidance parts: demonstrates, action,
   expected result and proof.
3. Core package import remains Streamlit-free; Story 9 presentation code does
   not directly import provider SDKs or construct vendor/live clients, while
   accepted local Story 8 Guardrails execution remains available through its
   public surface.
4. Default console startup works with no credentials and makes zero outbound
   calls; accepted local/offline safety and adapter behavior remains permitted.
5. Deterministic workflow control invokes the public fixed composition once and
   renders returned correlation IDs/classification rather than a synthetic pass;
   concurrent/duplicate/rerun actions cannot cause a duplicate authoritative
   execution or side effect.
6. Workflow trace/log view renders only safe normalized fields from a real
   returned `Observation`/pipeline record.
7. Retry, fallback, recovery and replay facts render exactly as the returned
   `RecoveryResult`; unknown remains unknown.
8. Authorization and safety cards render returned decisions but expose no
   control that can grant, alter or override them.
9. Latency, usage, normalized cost, actual cost, overage and budget display
   correct units and preserve absent/unknown versus zero.
10. Secret-shaped, prompt-shaped and provider-response-shaped canaries are
    absent from every rendered display projection and session state.
11. Rejected prompt-injection/safety outcomes display a safe classification and
    do not render rejected content or widen authority.
12. Telemetry/provider failure displays a sanitized non-authoritative status
    while preserving the local workflow result.
13. Deterministic benchmark control calls the public dataset/engine/runner
    composition and renders its real verdict/report digest.
14. Evaluation table renders authoritative scenario/evaluator outcomes and
    evidence classes without fabrication.
15. Regression display renders pass and failure findings/threshold facts; a
    regression failure is never changed to pass by presentation logic.
16. Improvement-cycle display accepts only two genuine bounded `RunResult`
    inputs retained from distinct accepted benchmark executions, identifies
    before/after provenance, fails closed with guidance when either is absent or
    invalid, and exposes no baseline-writing or policy/code-change control.
17. Lab selector contains exactly the 20 accepted `ScenarioKind` values and
    selected-run invokes `run_scenario` once.
18. Full lab action invokes `run_lab` once and renders the returned summary
    digest/counts/invariant failures and individual result facts.
19. Lab evidence badges preserve `simulated_failure`, deterministic fixture,
    and mocked-provider-contract classifications without live promotion.
20. Empty, invalid/unavailable and unexpected-error states use fixed safe UX;
    no traceback or raw exception/provider text reaches the view.
21. Startup, rendering, ordinary reruns, deterministic controls, disabled or
    unavailable live controls, credential detection, and provider/model
    selection produce zero outbound calls; ambient credentials alone do not
    enable a verifier.
22. Only a separately confirmed, fully gated live action calls the existing
    selected public verifier with its existing bounds/opt-in and renders the
    exact returned evidence class; this test uses a deterministic fake/seam,
    never a live call. An enabled control before confirmation still produces
    zero outbound calls.
23. Accessibility/usability test: keyboard-labelled controls, non-color-only
    statuses, units and table alternatives are present for reviewer workflows.
24. Subprocess zero-network proof with ambient credential-shaped environment
    variables and a socket guard: default UI import/startup plus deterministic
    workflow, benchmark and lab actions make zero non-loopback connections and
    leave no worker/session leak.

The formal Story 9 gate remains Ruff, full Module 7 pytest, then compileall.
Focused Story 9 tests may run during repair, but cannot replace the full
module gate at story completion. Optional live tests remain marked and skipped
unless explicitly enabled; their passing never retroactively reclassifies
ordinary deterministic evidence.

## Structural Anti-Evasion Acceptance

The test suite must prove behaviorally that presentation code cannot become a
shadow implementation:

- mocked public interfaces shall establish that the UI forwards a fixed control
  to the public application boundary and renders its returned result, rather
  than locally deriving a verdict/decision/cost/retry outcome;
- adversarial returned values shall remain displayed as safe, bounded,
  allowlisted projections or be refused, with no raw rendering;
- no UI test fixture may patch the application to return an invented success
  and then treat the visual pass state as proof of a workflow;
- dependency/import tests shall confirm Streamlit is not pulled into core
  package startup; Story 9 presentation code does not import provider SDKs or
  live transports directly; and deterministic mode does not activate live
  provider SDK/client paths while preserving accepted transitive local
  Guardrails/adapter execution reached through public interfaces;
- code review shall reject any Story 9 module that imports vendor SDKs,
  direct HTTP libraries, private adapter members, or writes an authorization,
  retry, fallback, redaction, evaluator, provider transport or baseline writer.

These checks intentionally focus on real boundary behavior and dependency
confinement rather than brittle source-string scoring.

## Acceptance Criteria

1. A reviewer can launch Streamlit locally with no credentials and follow the
   guided paths to real deterministic workflow, observability, evaluation and
   failure-lab results.
2. Each major action provides all four guidance elements and visible working
   evidence, satisfying REQ-UI-001 and REQ-UI-002.
3. The console uses Streamlit and remains a presentation layer, satisfying
   REQ-UI-003, REQ-UI-004 and ADR-007-010.
4. The observability platform view exposes normalized trace/log, reliability,
   safety/authority, latency and cost evidence, satisfying REQ-LAB-001 and
   REQ-DEL-001.
5. The evaluation view exposes benchmark, regression and improvement evidence,
   satisfying REQ-LAB-002 and REQ-DEL-002.
6. The failure view exposes exactly Story 8's accepted public S01–S20 surface
   and results, satisfying REQ-LAB-003.
7. Every evidence display follows the fixed evidence legend; deterministic,
   simulated, mocked, live-vendor and live-model claims are never conflated.
8. No secret, raw sensitive/untrusted material, provider exception body or
   credential is entered, retained or displayed; UI controls cannot grant
   authority or alter policy.
9. Default startup and deterministic actions are credential-free and
   zero-network while permitting accepted local/offline execution reached
   through public interfaces. Optional BYOK/live verification uses only a
   separately confirmed, fully gated existing secure opt-in verifier and its
   returned evidence class.
10. All 24 Story 9 tests and formal quality gates pass without modifying
    frozen authorities or accepted Stories 1–8 behavior.

## Evidence Classification

Story 9's own UI rendering tests are `deterministic_fixture`. The console
preserves, but does not mint, the evidence class carried by application
results. Story 9 may present `simulated_failure`, `mocked_provider_contract`,
`live_vendor`, and `live_model` only when those classes are present in the
underlying accepted result and the legend/claim boundary above is followed.

## Definition of Done

- This contract receives independent review and human acceptance before code.
- Implementation adds the minimum Streamlit presentation surface and the 24
  tests described above, without modifying frozen authorities or reimplementing
  Stories 1–8 logic.
- Deterministic/no-key reviewer journeys visibly work and quality gates pass.
- Any optional live path is disabled by default, securely bounded by existing
  verifiers, and accurately labelled.
- Independent review verifies requirements, ADR-007-010, authority separation,
  redaction, zero-network defaults, evidence labels and reviewer usability.

## Story 10 Handoff and Non-overlap

Story 9 hands Story 10 the runnable console, deterministic evidence outputs,
test inventory/results and any separately generated provider-verification
records. Story 10 remains solely responsible for integrated release closure:
full requirement/ADR/evidence reconciliation, final adversarial verification,
bounded live evidence required for live claims, dependency audit, UI claim
audit, release readiness and publication decisions.

Story 9 neither accepts itself nor declares the module release-ready.

## Open Human Decisions

No architecture conflict or implementation-blocking human-only decision is
present. The frozen architecture, ADR-007-010, existing public results and
evidence model determine this presentation contract. A future desire to add a
new generic workflow service, change provider activation, accept credentials
through the browser, add a dashboard backend, or expand live claims would be a
new human-approved architecture decision, not a Story 9 implementation choice.
