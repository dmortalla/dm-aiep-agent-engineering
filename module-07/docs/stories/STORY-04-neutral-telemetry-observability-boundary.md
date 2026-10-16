# Story 4 - Neutral Telemetry, Structured Logging, Redaction, and Debugging Pipeline

## Status

CONTRACT AUTHORED - implementation not started by contract authoring.

Prerequisite: independently accepted Story 3 commit
`5cd857131559da4e71af3011e37be0e0f2f4337c`. Verify its ancestry and accepted
Module 7 content before implementation; unrelated descendant commits are allowed.

Contract-authoring baseline: branch `main`, HEAD equal to that accepted commit;
ancestor verification succeeded; Module 7 and the index were clean. Accepted
Stories 1-3 and frozen authorities had no differences from the accepted tree.
No Story 4 pipeline/export implementation existed: Story 1 supplied types/local
logging and Story 3 supplied recovery evidence without an observation hook.
Foreign dirty/untracked work was present and remains outside this contract.
Historical PLANNED/not-started wording in the frozen plan and earlier contract
status text is not a current implementation-status assertion or permission to
rewrite those authorities.

## Goal

Make workflow behavior observable through application-owned normalized telemetry,
structured correlated logs, redaction and debugging evidence without transferring
authority, leaking privileged data or making correctness depend on observation.

## Authoritative Scope

This contract operationalizes Story 4 in IMPLEMENTATION_PLAN.md under frozen
REQUIREMENTS.md, ARCHITECTURE.md and the three assigned ADRs. It does not amend
them. TRACEABILITY.md maps REQ-OBS-001 through REQ-OBS-005 individually to course
topics and governance through REQ-SEC-* and REQ-COST-* family mappings. Preserve
that grouped convention; do not manufacture IDs from historical range wording.
Earlier-story security, reliability, quality, isolation and evidence obligations
remain constraints rather than additional Story 4 assignments.

## Requirements

- REQ-OBS-001
- REQ-OBS-002
- REQ-OBS-003
- REQ-OBS-004
- REQ-OBS-005
- REQ-SEC-007
- REQ-SEC-008
- REQ-COST-002

## Assigned ADRs

- ADR-007-001: application-owned normalized telemetry before adaptation; Langfuse
  owns later operational integration and LangSmith later independent evaluation;
  neither is required for deterministic core correctness.
- ADR-007-006: mandatory pre-adapter redaction; export failures remain locally
  observable without changing authorization or corrupting core state.
- ADR-007-012: usage/cost evidence reflects the same bounded application budget
  across repeated work; ordinary deterministic CI incurs no billable calls.

## Frozen Architecture Constraints

Application code retains correctness, authorization, safety policy, resilience,
idempotency, budgets and recovery. The data path is application facts ->
minimization/redaction -> neutral telemetry port -> later vendor adapters.
Local logs and debug/evidence records must also be secret-safe. Vendor SDK types
or responses cannot become application-domain contracts. No vendor dependencies,
new control plane, distributed persistence or evaluation engine are needed here.

## Implementation Boundaries

Story 4 may add the smallest sufficient neutral emission/redaction/debugging
pipeline, deterministic local sink and fake-sink contract tests inside Module 7.
Compose with accepted interfaces; observe Stories 1-3 without rewriting their
accepted implementation or weakening their contracts/tests. Compatible new
telemetry-specific representations may carry missing observation metadata.
Do not silently change existing public schemas or logging behavior. A necessary
change to an accepted invariant must be identified and adjudicated before that
implementation proceeds; no such change is required by this contract.

### Neutral Telemetry Model

Use the accepted TelemetryRecord vocabulary and validation as the minimum:

| Concept | Required representation/meaning |
| --- | --- |
| Correlation | workflow_id and trace_id UUIDs from WorkflowIdentity; span_id UUID identifying an observation |
| Operation and outcome | bounded operation and status; distinguish successful, denied, failed, cancelled and replay/pending observations as applicable without inventing execution |
| Timing | finite nonnegative duration_ms; duration satisfies the architecture's start/end-or-duration alternative, so wall-clock timestamps are not mandatory |
| Reliability | retry_attempt, fallback_used and safe recovery/timeout/replay metadata from application results where applicable |
| Decisions | safety_decision and authorization_decision as observed outcomes; absent when no decision occurred |
| Usage/cost | accepted UsageRecord token counters and normalized cost_usd when known, with availability/provenance made explicit where defaults would otherwise mislead |
| Failure | optional bounded error_classification from application-owned classifications |
| Evidence | validated EvidenceClass reflecting actual execution, never inferred from credential presence |

Structured event type identifies what happened, using the accepted log event
concept; safe metadata can associate stage/component, recovery classification
and action identity without making a separate mandatory timestamp, run ID or
vendor span schema. WorkflowIdentity supplies run/workflow identity; the existing
idempotency key supplies logical action identity. Avoid redundant identity types.
Additional event metadata is validated and minimized before observation.

### Structured Logging

Preserve log_event's keyword interface, JSON record shape (event, workflow_id,
trace_id, fields), correlated UUID serialization and safe supported values.
Deterministic local emission must be inspectable without a vendor. Event labels
and diagnostic fields must not become an uncontrolled raw-text escape hatch.
Keep safe fields useful for debugging; do not replace every record with an empty
success marker merely to pass leakage tests.

Preserve recursive mappings/collections, SecretStr redaction, UUID handling,
recognized bearer sanitization, non-string-key handling and the unsupported-value
marker `[UNSUPPORTED_TYPE]`. Never invoke arbitrary object str/repr or serialize
an exception/SDK object to obtain telemetry. Preserve `[REDACTED]` and the accepted
credential-key classifier, including camel case, separator, plural and compound
variants covered by Story 1 regression tests. Safe non-secret fields must remain
available; do not broaden the classifier so usage counters such as input_tokens
or output_tokens are indiscriminately lost.

### Redaction and Data Minimization

REQ-SEC-007 and ADR-007-006 require minimization of prompt, response, metadata and
tool content before export; REQ-SEC-006 remains binding across logs, traces,
evaluation/evidence records and exposed errors. Default to normalized facts and
safe application codes rather than copying raw bodies. Safety-approved output is
not automatically telemetry-approved content.

Prevent credentials, API/access keys, bearer/access/refresh tokens, passwords,
authorization headers, cookies/session material, connection strings/DSNs,
private keys and equivalent privileged values from entering emitted logs,
telemetry or evidence, including nested values and secret-bearing exceptions.
This applies to event names, identifiers/operation labels derived from untrusted
input, metadata keys and values, and error/debug content as well as payloads.
Use safe application labels or omit unsafe content rather than assuming arbitrary
free text can always be made safe by a finite pattern classifier. Do not claim
universal secret detection. Retain the accepted classifier while preventing raw
untrusted payloads from bypassing it through the new pipeline.

Redaction precedes every telemetry/vendor boundary, including fake adapters used
to verify the contract. No unsafe-original fallback on redaction/serialization
failure, downstream-vendor-only sanitization or unsafe diagnostic exception chain
is permitted. Exposed diagnostics must not retain raw exceptions, traceback local
variables, prompts, response bodies, permission issuers or privileged state.
Internal causal context is retained only where it is safe; secret-bearing causes
must not leak through repr, context or chained errors.

### Trust and Authority

User, retrieved, model, agent, tool, validator, moderation and provider-error
content remains untrusted even after redaction or storage. Sanitization is not
authorization. Telemetry records and sink responses cannot grant permissions,
issue/replay authorization decisions, redefine policy, execute instructions,
choose retryability/fallback candidates, reset idempotency, increase budgets or
control privileged behavior. Decision telemetry is a projection of application
outcomes, never a decision that execution consumes as authority.

Preserve Story 2 allowlists and issued-decision enforcement, Guardrails as
safety-only, non-authoritative moderation, injection containment and fail-closed
safety-provider behavior. Provider/telemetry allow text cannot undo denial.
Preserve the existing Guardrails import confinement and dependency prohibition;
no Story 4 vendor/network import exception is introduced.

### Correlation and Continuity

Carry original workflow/trace identities and the same logical action key through
retry, fallback, timeout and recovery observations. Distinguish observation/span
identity from action identity: another event/span does not create another action.
No fresh key, new effect or renewed execution budget may result from emission.
Use application result identity, not user/vendor supplied authority-like metadata.

Completed replay retains the recorded original identity/usage and is visibly
replayed; it is not another invocation or cost charge. Pending and pre-execution
denial evidence must not fabricate attempts to satisfy ReliabilityResult's
at-least-one invariant. Different action observations must remain distinguishable.
Tests supply fixed identities and inspect relationships; random UUID defaults do
not need replacement with a new ID-generation architecture.

Trace/log debugging views must join on the same identities. Provide a compatible
correlation boundary for later evaluation evidence when supplied, without running
evaluators or claiming evaluation results here; do not fabricate missing scores,
trace links or evaluation identifiers.

### Latency, Usage, Cost and Debugging

Measure elapsed duration at the supported local boundary with documented scope;
use finite nonnegative milliseconds in TelemetryRecord. Story 3 elapsed_seconds
may be converted explicitly to milliseconds without changing deadline semantics.
Controlled clocks/known result durations make assertions deterministic. Distinguish
attempt and whole-execution timing where both are reported; do not sum overlapping
measurements or describe fixture durations as production latency.

Observe UsageRecord input/output tokens and cost_usd, BudgetState limits/used
cost, and relevant RecoveryResult actual_cost_usd, overage_usd, remaining bounds
and exhaustion facts without mutating them. Distinguish reservations/conservative
charges, actual supported usage and overage; budget saturation must not conceal
Story 3's separately recorded actual overrun. No new quota or pricing model is
mandated. Unknown/unavailable provider cost must remain explicitly unknown, not
silently asserted as a measured zero because UsageRecord defaults are zero.
A genuinely free fixture may report zero labeled deterministic usage. Validate
nonnegative finite cost/duration and bounded nonnegative counters. Observational
aggregation must avoid counting replayed historical usage as new consumption.
Telemetry neither reconciles spending authority nor reduces prior consumption,
resets limits, authorizes paid calls or invents provider invoices/prices.

Debug evidence correlates safe failure category, operation/stage/component,
retry/fallback/recovered state, timeout/pending/replay state and safe error code
or application-authored message with workflow/trace/action identity. Preserve
Story 3 safe classification/history and terminal outcomes. Unknown errors receive
safe classification rather than blindly copying their text. Useful local failure
reconstruction must not require exporting raw input/output or privileged policy.

### Telemetry Failure and Resource Bounds

REQ-ENG-006 and Story 3 isolation remain binding. A failing optional logging sink,
exporter, serializer or redactor cannot change the authoritative workflow result,
issue authority, bypass safety, corrupt recovery state, duplicate an effect or
renew resources. It may mark observation unavailable/failed. Do not hide failed
export as successful export.

ARCHITECTURE.md Provider Failure Semantics and ADR-007-006 explicitly require
local evidence of provider-export failure. Record a minimal secret-safe failure
status/code with correlation independently of the failing exporter. If that local
sink also fails, terminate observation in bounded handling; no recursive logging
or exporter retries through itself. The existing log_event failure isolation must
remain valid. Tests must inspect locally available failure evidence and a failing
primary-plus-local-sink case; no durable logging guarantee is implied.

Keep payload traversal/size, event retention/cardinality and observation attempts
bounded under SOP observability/resource rules. Handle malformed, deeply nested,
cyclic or oversized content by safe omission/truncation/refusal, never unsafe
serialization or unbounded recursion. Finite implementation limits and their
full/truncation behavior must be documented/tested; frozen authority specifies no
mandatory numeric payload/event cap. Streaming or bounded collection is sufficient;
no mandatory queue, retry service or persistent collector is introduced. Do not
retry export without an explicit finite bound or let observation extend execution
without a bound. Ordinary emission/tests make no intentional external vendor calls,
require no credentials and incur no billable operation.

## Required Tests

Use observable records/results, fake-sink captures and invocation/effect counters.
Assertions that constants or interfaces merely exist are insufficient.

1. Deterministic normalized trace/span and structured JSON log emission; required
   fields, validation, event type, status, evidence labels and preserved log shape.
2. Fixed workflow/trace/action correlations across logs/traces, retries, fallback,
   timeout/recovery and distinct actions; no new logical action from new spans.
   Replay/pending/denial stays honest about original identity and zero new work.
3. Finite nonnegative duration with explicit milliseconds, controlled measurement
   and seconds conversion; reject negative/non-finite timing, preserve deadlines.
4. Usage/token/cost and shared-budget projections; reservation versus actual and
   overage, exhaustion, explicitly unknown cost and genuine fixture zero; invalid
   values rejected and replay does not double charge observational aggregates.
5. Safe correlated failure/debug evidence including stage, classification,
   retry/fallback/recovery/timeout and safe error code; no raw exception leakage.
6. Credential families above absent from logs, pre-export captures and evidence;
   nested collections, SecretStr, accepted key variants and bearer text covered.
   Secret-bearing event/metadata/error content is omitted or sanitized safely;
   safe fields and usage counters remain useful. No unsafe exception context.
7. Unsupported objects/non-string keys retain accepted safe behavior; no arbitrary
   repr/str calls. Malformed/cyclic/deep/oversized data and collection capacity
   terminate under documented bounds without leaking an unsafe original.
8. Forged instructions/decisions from every applicable untrusted source and sink
   response cannot grant authority, widen permissions, bypass safety, change
   retry/fallback policy, idempotency, deadlines or budgets. Redaction grants none.
9. Export failure yields local redacted correlated failure evidence; failing log,
   export and local-failure sinks preserve authoritative results/decisions/state,
   invocation/effect counts and accounting. Attempts remain bounded/non-recursive.
10. Fake neutral provider/sink receives only minimized records: exercise success,
    failure and malformed/untrusted responses as mocked_provider_contract; no SDK
    type or vendor availability is required for core behavior.
11. Ordinary deterministic import/startup/emission needs no credentials and makes
    no intentional external vendor/billable call; credential presence does not
    activate live execution. Labels do not become live on a successful fake send.
12. Full unchanged Stories 1-3 regression: configuration, typed IDs/contracts,
    classifier/unsupported values, real local Guardrails contribution, allowlists,
    forged authority, injection, moderation/fail-closed safety, retry/fallback/
    timeout bounds, idempotency/effect protection, shared budgets, recovery and
    logging isolation. No weakening or reclassification for a green milestone.

## Requirement-to-Acceptance Coverage

| Assigned requirement | Contract behavior and verification |
| --- | --- |
| REQ-OBS-001 | Normalized trace/span model and action continuity; tests 1, 2, 10 |
| REQ-OBS-002 | Structured correlated secret-safe local logging; tests 1, 6, 7, 9, 12 |
| REQ-OBS-003 | Explicit finite duration measurement/conversion; tests 3, 9 |
| REQ-OBS-004 | Accurate available/unknown usage/cost without replay double counting; tests 4, 11 |
| REQ-OBS-005 | Correlated safe classification/recovery/debug pipeline and later evaluation join boundary; tests 2, 5, 9, 10 |
| REQ-SEC-007 | Minimized prompt/response/tool/metadata, mandatory pre-export redaction; tests 5-7, 10 |
| REQ-SEC-008 | Observation never becomes privileged authority/control path; tests 8, 9, 12 |
| REQ-COST-002 | Observable usage, actual/reserved cost, budget and exhaustion provenance; tests 4, 5 |

ADR-007-001 is exercised by the neutral model/port, independent core behavior and
tests 1, 2, 9, 10. ADR-007-006 is exercised by pre-export minimization, local failure
evidence and tests 5-10. ADR-007-012 is exercised by faithful budget/usage projection
and non-billable deterministic operation in tests 4, 8, 11, 12.

## Evidence Classification

Exact Story 4 assignment: **deterministic_fixture and mocked_provider_contract**.

Actual normalized local emission, redaction, correlation, timing and usage/debug
projection with controlled inputs proves deterministic_fixture behavior. Fake
sink/provider boundary exchanges prove mocked_provider_contract behavior; neither
proves a vendor SDK, hosted ingestion, dashboard, external trace or billing result.
Preserve Story 3 simulated_failure labels when observing those existing scenarios;
do not relabel their underlying evidence as Story 4 live or successful execution.
This does not expand the assigned Story 4 evidence classes or implement Story 8.

No live_vendor, live_model, hosted dashboard, external trace, provider-backed cost,
production monitoring, deployment or production-readiness claim follows here.
Reviewer evidence is reproducible tests and secret-safe local records/captures.
Later evaluation correlation is an interface capability, not completed evaluation.

## Quality Gates

Implementation acceptance requires the complete Module 7 fail-fast sequence:

1. Ruff
2. pytest
3. compileall over relevant source and test directories

Stop at the first failure. Preserve bounded repair and safe-only Ruff fixes;
never weaken tests/security/requirements. After repair rerun the failed gate and
the full sequence. Independent implementation review is mandatory before
acceptance and controlled commit. Contract authoring alone runs no implementation
gates and proves no implementation milestone. Temporary engineering evidence
belongs under parent TECHADEMY/EVIDENCE, outside the repository.

## Isolation

Only Module 7 belongs to this slice. No sibling implementation, tests, runtime
state or configuration may be copied, imported, modified or depended upon.
Foreign dirty state and unrelated descendant commits are not blockers. Stop for
conflicting concurrent Module 7 changes, history divergence invalidating accepted
lineage, a real dependency/isolation conflict or a genuine frozen-authority
contradiction. Preserve frozen requirements, traceability, architecture, ADRs and
accepted Stories 1-3. This task authors only this contract; no staging or commits.

## Non-Goals

The frozen plan reserves Langfuse integration/live verification for Story 5;
automated evaluation, regression, benchmarks and LangSmith for Story 6; Helicone
for Story 7; the failure-recovery simulation lab for Story 8; the guided Streamlit
console for Story 9; and integrated verification/live evidence/release closure for
Story 10. Story 4 still owns neutral retry/fallback/decision telemetry, debugging,
latency/usage records, pre-export redaction and telemetry-provider failure handling.
No vendor SDK/live call, new model execution, distributed storage, mandatory
wall-clock timestamps, pricing service or authority/architecture change is added.

## Definition of Done

- All eight assigned requirements and three assigned ADRs have traceable behavior
  and required verification within this neutral slice.
- Local logs, traces, timing, usage/cost and debugging correlate safely; export
  failures are locally observable with bounded isolation.
- Mandatory minimization/redaction occurs before export, and telemetry remains
  untrusted non-authoritative data throughout.
- Accepted Stories 1-3 and frozen authorities remain intact; all regressions and
  required success, negative, adversarial and failure tests pass.
- Evidence distinguishes deterministic_fixture and mocked_provider_contract and
  preserves any observed upstream classification without unsupported claims.
- Ruff -> full Module 7 pytest -> compileall pass; independent implementation
  review accepts the slice before lifecycle recording and controlled commit.

Story 5 remains blocked until Story 4 implementation is complete, independently
accepted and recorded through the required lifecycle/controlled commit process.
Authoring this document implements no Story 4 application behavior and does not
authorize beginning Story 5. No HITL required for contract authoring.
