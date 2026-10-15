# Story 3 - Reliability, Retry, Fallback, Timeout, Idempotency, and Budgets

## Status

CONTRACT AUTHORED - implementation not started by contract authoring.

Prerequisite: independently accepted Story 2 implementation recorded in commit
`01359b9b8a02f97bb08563ee5e74e1f26cadc5cc`. Verify its ancestry and Module 7
content before implementation; unrelated descendant commits do not invalidate it.

## Goal

Implement application-owned resilience without allowing recovery mechanisms to
bypass safety or authorization. Demonstrate retry, fallback, timeout, idempotency,
bounded workflow/recovery state, and shared execution/cost budgets together.

## Authoritative Scope

This contract operationalizes the Story 3 slice in IMPLEMENTATION_PLAN.md under
the frozen REQUIREMENTS.md, ARCHITECTURE.md and assigned ADRs. It does not amend
those authorities or create new course-source requirements. TRACEABILITY.md maps
REQ-REL-* individually to source topics and governance through grouped REQ-ENG-*,
REQ-COST-* and related families; those wildcard mappings remain applicable.

## Requirements

- REQ-REL-001
- REQ-REL-002
- REQ-REL-003
- REQ-REL-004
- REQ-ENG-001
- REQ-ENG-002
- REQ-ENG-003
- REQ-ENG-004
- REQ-ENG-005
- REQ-ENG-006
- REQ-COST-001
- REQ-COST-002

These are the exact Story 3 assignments. Story 1/2 security, configuration,
quality, isolation and evidence obligations remain constraints, not newly
assigned Story 3 source scope.

## Assigned ADRs

- ADR-007-004: application-owned resilience controller, classification, bounded
  retries/timeouts, fallback, idempotency, accounting and observable recovery.
- ADR-007-005: explicit application policy and allowlisted capabilities;
  external/model/guardrail/telemetry content cannot modify authority.
- ADR-007-009: bounded in-process workflow state, explicit application-owned
  idempotency abstraction and deterministic recovery records.
- ADR-007-012: explicit budgets for billable/model-backed execution; repeated
  execution consumes the same bounded budget; deterministic CI is non-billable.

## Frozen Architecture Constraints

- Application code owns correctness, authorization, resilience, idempotency,
  budgets and recovery. Vendor systems cannot supply privileged authority.
- Execution follows authorization and input safety; returned provider/tool data
  remains untrusted and must satisfy output safety before release.
- Retryability, attempt limits, backoff where appropriate, operation timeouts,
  fallback selection, idempotency checks and budget enforcement belong to the
  resilience boundary, not model instructions or a vendor gateway.
- Workflow/recovery state is bounded and in process. Distributed or durable
  persistence is not required or authorized by this story.
- Budgets bound execution and cost. Exhaustion stops affected work safely and
  produces observable evidence. Recovery does not reset an execution's budget.
- Observability failure cannot change authority, bypass safety or corrupt core
  state. Story 4 retains ownership of the telemetry pipeline.
- Ordinary execution evidence is credential-free and deterministic; controlled
  failure injection is confined to test boundaries in this story.

## Implementation Boundaries

Story 3 may add the smallest sufficient reliability policy, controller,
idempotency abstraction, bounded recovery records and tests within Module 7.
Trusted application policy may configure finite limits; frozen authority does
not prescribe numeric retry counts, delays, cache capacity or timeout values.
Document units, counting conventions, defaults and boundary behavior. Invalid
security/resource-critical policy must fail closed before work begins.

Preserve the accepted Story 1/2 interfaces and implementation behavior. Compose
with those interfaces; do not replace them or weaken their tests to fit execution.
Additional reliability-specific types may represent limits or outcomes absent
from the foundation without changing the accepted contracts' meaning.

### Retry

- Explicit application classification distinguishes retryable transient failures
  from terminal/non-retryable failures. Unknown failures must not automatically
  enter a retry loop. Exception text or provider payload cannot prescribe policy.
- Attempt counting must be explicit, including the initial invocation. Every
  primary/retry/fallback invocation counts against an overall execution bound;
  per-operation limits cannot multiply into an unbounded workflow.
- Retry only while the failure is eligible, repeat execution is idempotently
  safe, the attempt limit permits it and time/cost budgets can accommodate it.
  Authorization/safety denial and exhausted budgets are not transient failures.
- Backoff is finite and bounded; any configured exponential growth or jitter
  stays inside remaining time and execution limits. Tests control delays and any
  randomness to produce reproducible outcomes without real waiting.
- Success ends retries. Exhaustion produces an explicit failure or proceeds only
  to an independently eligible, bounded fallback. No recursive reset of limits.

### Fallback

- Fallback is an explicit trusted application policy decision for eligible
  operational failures, including retry exhaustion where policy permits it.
  A non-retryable failure is not automatically fallback-eligible.
- Candidates and invocation bounds are finite. No primary/fallback cycling or
  nested recovery may renew consumed limits or create a fallback loop.
- Each candidate must satisfy applicable application authorization, input/output
  safety, idempotency and remaining global budget/time constraints. A different
  tool requires its own valid allowlisted application decision; a primary tool's
  decision cannot authorize it.
- Denied authorization or safety is terminal for the affected request, not a
  route to a less restrictive fallback. No valid candidate or exhausted bounds
  yields an explicit safe terminal outcome, never silent success.
- Fallback use and whether recovery succeeded must be observable in results.

### Timeout

- Operations have a finite enforced timeout appropriate to their execution
  boundary. An overall finite execution-time bound includes attempts, backoff
  and fallbacks; a new attempt cannot extend that bound.
- Distinguish timeout from other operational failure. Timeout is retry/fallback
  eligible only under explicit policy and only if repeated execution is safe and
  all remaining bounds permit it. Time exhaustion stops further execution.
- Enforcement must bound waiting at the supported operation boundary; merely
  labelling an already completed slow call as timed out is insufficient. Use a
  timeout-aware/cooperative operation boundary or another justified bounded
  mechanism without prescribing a particular concurrency library.
- A timeout does not prove an effect did not occur. Do not launch overlapping or
  duplicate effectful work while an earlier outcome is unresolved. Late results
  cannot silently overwrite a terminal decision or authorize another attempt.
- Controlled clocks, sleepers and timeout-aware fakes may prove deterministic
  scheduling/accounting. Tests must also exercise the chosen timeout enforcement
  boundary; no slow wall-clock suite or claim of forcibly cancelling arbitrary
  uncooperative Python callbacks is required.

### Idempotency and Recovery State

- Use application-owned stable identity for the same logical request/action
  across retries, fallback and replay. Preserve the accepted idempotency key;
  generating a fresh key for each attempt defeats the required boundary.
- Scope identity to the relevant principal, operation and effectful request so a
  reused key cannot replay another principal's result or authorize a changed
  action. Incompatible identity reuse must fail safely rather than run as a
  duplicate or return an unrelated result.
- Within the supported in-process retention scope, a completed duplicate returns
  the recorded outcome without another effect or duplicate cost charge. Replay
  must still respect applicable authorization/safety before releasing a result.
  Correlation and usage evidence distinguish replay from a new execution.
- Pending duplicates must not independently execute the same effect. Failures
  before an effect may be retried when policy permits; completed or uncertain
  effects must not be repeated without an idempotently safe operation boundary.
  A failure/timeout after an effect cannot erase its protection.
- A plain result cache does not alone prove duplicate-side-effect prevention.
  Demonstrate the supported effect boundary with an observable side-effect
  counter, including failure/timeout paths, and state its guarantees honestly.
- Idempotency/recovery storage has finite capacity and documented retention/full
  behavior. Capacity handling must not discard protection for in-flight work or
  silently permit a protected replay to duplicate effects. Safe refusal of new
  work is acceptable; no particular eviction algorithm is mandated.
- Records expose attempts, fallback/recovery status, usage/budget, terminal
  outcome and evidence classification without retaining secrets unnecessarily.
  No cross-process, restart, distributed exactly-once or indefinite replay
  guarantee follows from bounded in-process storage.

### Budgets and Observable Results

- Trusted finite attempt/fallback limits and elapsed-time/deadline limits govern
  the whole logical execution. Per-attempt timeouts are capped by remaining
  time; retry waits consume time. No retry, fallback or replay renews resources.
- Use the accepted BudgetState cost limit/usage and UsageRecord normalized cost
  and token fields. No additional mandatory token quota, monetary pricing model
  or provider billing integration is introduced by this contract.
- Before potentially costly execution, require sufficient remaining budget for
  its application-established bound/reservation. Untrusted reported usage cannot
  increase limits, reduce prior consumption or authorize further calls. Unknown
  exposure cannot be treated as free merely to admit work.
- Account for actual supported usage, including failed attempts/fallbacks where
  resources were consumed; never reset cost on a change of candidate. Reconcile
  reservations without inventing negative, non-finite or over-limit BudgetState
  values. A zero-cost deterministic operation remains possible with zero budget.
- Exhaustion denies further work and yields an explicit bounded terminal result.
  It cannot be converted into success by ignoring an accounting error.
- Preserve WorkflowState identity, idempotency key, operation, decisions, retry
  count, fallback flag, budget, usage, terminal status and evidence class. Use
  validated transitions. Accepted ReliabilityResult.attempts is at least one;
  do not fabricate an attempt to represent a pre-execution denial or replay.
  Represent such outcomes through compatible workflow/recovery evidence.
- Expose sufficient local result/recovery evidence for REQ-COST-002 and later
  telemetry adaptation: attempts/retries, fallback, recovery, elapsed time,
  classification, usage/cost and remaining/exhausted limits. These are execution
  facts, not Story 4 tracing/export/dashboard implementation.
- Core results and authority must not depend on successful optional observation.
  Test that an unavailable/failing observation sink cannot alter them if such a
  hook is introduced; an observation hook is not mandatory for Story 3.

### Composition and Failure Classification

The combined retry + fallback + timeout + idempotency + budget path must preserve
one logical action identity and monotonically consumed execution resources.
Admission checks precede each invocation and are rechecked after waits and
candidate changes. Finite local limits must compose into a finite global bound.

Distinguish these behaviors with safe application-owned identifiers/results;
no new elaborate exception hierarchy is required:

| Outcome class | Required behavior |
| --- | --- |
| Retryable operational failure | Retry only within policy, safety, idempotency and remaining budgets |
| Terminal/non-retryable failure | No retry; fallback only if separately eligible |
| Timeout | Bound waiting; retain uncertain-effect protection; recover only if safe and permitted |
| Budget/time/attempt exhaustion | Stop work requiring the exhausted resource; no limit reset |
| Authorization/safety denial or safety-provider failure | Fail closed; no recovery into a policy bypass |
| Duplicate/in-progress replay | Reuse the protected outcome or return bounded pending/denied handling without duplicate work |
| Success/recovered success | End execution; release only safety-approved results with accurate accounting |

## Security Acceptance

- Allowlists and AuthorizationPolicy issuance/enforcement remain authoritative.
  Merely storing an AuthorizationDecision in WorkflowState is not proof of
  issuance. Forged, copied, model-generated or mismatched decisions cannot enter
  an effectful primary/retry/fallback path.
- Requester, retrieved, tool, model, telemetry, validator and moderation content
  cannot change principal identity, grants, retryability, fallback candidates,
  deadlines, budgets or idempotency policy. Preserve trusted/untrusted separation
  and prompt-injection containment.
- Guardrails/safety/moderation remain non-authoritative safety inputs; their
  allow results cannot grant tool permissions. Safety failure remains fail-closed.
  Recovery cannot add a second authorization path or skip output safety.
- Preserve secret-safe errors, logs, recovery records and evidence. Do not copy
  raw provider exception text/payloads into results or exception chains when they
  may contain secrets. Existing accepted configuration/redaction tests remain.
- Preserve the approved Guardrails import exception only in guardrails_adapter.py,
  the other vendor/network import prohibitions and excluded version 0.10.1.

## Required Tests

Use behavior assertions, controlled operation invocation/effect counters and
inspectable results, not just assertions that policy constants exist.

1. Retryable transient failure then success within limits; non-retryable and
   unknown failures do not retry; retry exhaustion terminates; finite backoff and
   configured limits are honored, including boundary values/invalid policy.
2. Permitted fallback succeeds and reports recovery; unavailable, ineligible or
   exhausted fallback terminates; candidate changes cannot widen tool permissions
   or reset attempts, deadlines or cost. No fallback cycles.
3. Enforced operation timeout; eligible timeout recovery within remaining limits;
   deadline exhaustion before/during retry waits and fallback; late/unresolved
   work does not produce duplicate effects or overwrite terminal outcomes.
4. Same-action retry/replay retains its key; completed replay returns the recorded
   outcome without duplicate effect/cost; pending duplicate cannot independently
   execute. Changed action/principal with a reused key fails safely. Exercise
   failures before and after an effect and bounded storage capacity behavior.
5. Attempt/fallback/time/cost exhaustion blocks additional invocation; failed
   attempts and fallbacks consume applicable shared resources; zero-cost fixtures
   work with zero cost budget; invalid/non-finite or contradictory accounting
   fails safely. Validate usage and remaining/exhausted evidence.
6. Combined transient failure, backoff, timeout, fallback and replay scenarios
   stay within global bounds and preserve one logical effect. A nested recovery
   path cannot cause retry amplification, budget renewal or duplicate action.
7. Primary/retry/fallback/replay reject forged/model-generated authority and
   unauthorized tools. Authorization denial, safety denial, moderation rejection
   and safety-provider failure never turn into success through recovery.
   Guardrails allow cannot authorize an otherwise denied operation.
8. Untrusted content cannot alter reliability/budget policy; unsafe recovered
   output is not released; secret-bearing failure messages do not appear in
   returned evidence, records, logs or exposed errors/exception context.
9. Recovery state remains bounded and consistent; optional observation failure,
   if a hook exists, cannot corrupt state or bypass authority/safety. Verify
   deterministic evidence labels and no vendor credential/network requirement.
10. Full accepted Story 1 and Story 2 regression suite remains valid, including
    real Guardrails execution, differential contribution, import confinement,
    network/telemetry containment, configuration and secret-safe behavior.

## Requirement-to-Acceptance Coverage

| Assigned requirement | Contract behavior and verification |
| --- | --- |
| REQ-REL-001 | Retry classification, bounds/backoff; tests 1, 3, 6 |
| REQ-REL-002 | Explicit safe bounded fallback; tests 2, 6, 7 |
| REQ-REL-003 | Stable action identity and duplicate-effect prevention; tests 4, 6 |
| REQ-REL-004 | Composed resilience and observable recovery; tests 1-9 |
| REQ-ENG-001 | Finite attempt/global bounds; tests 1, 5, 6 |
| REQ-ENG-002 | Enforced operation timeout and overall time bound; tests 3, 6 |
| REQ-ENG-003 | Retryable versus terminal classification; tests 1, 3, 7 |
| REQ-ENG-004 | Explicit observable fallback preserving decisions; tests 2, 7, 8 |
| REQ-ENG-005 | Idempotent retries/replay across failures; tests 4, 6 |
| REQ-ENG-006 | Observation-independent core state and authority; tests 9, 10; telemetry implementation remains Story 4 |
| REQ-COST-001 | Shared bounded execution/cost exposure and exhaustion; tests 5, 6 |
| REQ-COST-002 | Local usage/cost evidence compatible with accepted contracts; tests 5, 9; analytics presentation remains later scope |

## Evidence Classification

Assigned Story 3 evidence: **deterministic_fixture and simulated_failure**.

Actual local controller/idempotency/budget behavior with controlled inputs is
deterministic_fixture; intentionally injected transient/permanent/timeout/failure
scenarios are simulated_failure. Fakes enable deterministic execution but do not
establish live provider behavior. Any separate mocked provider contract remains
mocked_provider_contract and cannot substitute for exercising the real local
resilience implementation. Preserve the accepted evidence enum and label each
record according to what was actually exercised.

Ordinary tests require no credentials, external network or billable calls.
Do not infer live_vendor, live_model, deployment, production readiness or durable
recovery from deterministic or simulated results. Reviewer evidence consists of
reproducible tests and local result/recovery records, not a new UI or lab.

## Quality Gates

Implementation acceptance requires the complete Module 7 fail-fast sequence:

1. Ruff
2. pytest
3. compileall over relevant source and test directories

A failed earlier gate stops the sequence. Preserve bounded repair rules; no
unsafe automatic Ruff fixes, test weakening or reclassification of failures.
After repair rerun the failed gate and the full sequence. External-cache
compileall may preserve read-only verification; temporary evidence belongs in
the parent TECHADEMY/EVIDENCE directory. Contract authoring alone is not evidence
that Story 3 implementation gates passed.

## Isolation

Module 7 remains standalone. No sibling source, tests, prompts, runtime state or
module-local configuration may be imported, copied, modified or depended upon.
Protect concurrent foreign work. Verify accepted lineage and Module 7 status
before/after work; unrelated descendant commits/dirty files are not blockers.
Stop for an actual Module 7 conflict, invalidated lineage, dependency/isolation
conflict or genuine frozen-authority design conflict requiring human approval.

## Non-Goals

The frozen plan reserves the following for subsequent stories:

- Story 4: neutral telemetry/tracing/logging/redaction/debugging pipeline and
  telemetry-provider failure handling beyond preserving core invariants here.
- Story 5: Langfuse operational observability adapter and live verification.
- Story 6: automated evaluation, regression/benchmark pipeline and LangSmith.
- Story 7: Helicone gateway integration and live gateway evidence.
- Story 8: reviewer-facing failure-recovery simulation lab; Story 3 failure
  fixtures test the controller without implementing that lab.
- Story 9: guided Streamlit observability/evaluation console.
- Story 10: integrated verification, live evidence and release closure.

No vendor/model integration, new privileged live-provider execution, distributed
persistence or frozen-authority amendment is introduced by this story. Existing
local logging/results may support tests without moving later implementation here.

## Definition of Done

- All twelve assigned requirements and four ADRs have traceable behavior and
  verification within this bounded slice.
- Retry, fallback, timeout, idempotency, budgets and bounded recovery state work
  together; failures terminate without duplicate effects or policy/budget bypass.
- Accepted Story 1/2 interfaces, regressions, security and evidence boundaries
  remain intact, with no frozen-authority or sibling-module changes.
- Success, expected failure and adversarial tests pass; evidence accurately
  distinguishes deterministic_fixture and simulated_failure.
- Ruff, full Module 7 pytest and compileall pass in order.
- Independent implementation review accepts Story 3 against this contract and
  frozen authority. Authoring this document does not confer that acceptance.

Story 4 remains blocked until Story 3 receives independent implementation
acceptance and the required lifecycle acceptance record/controlled commit.
No Story 3 application implementation or Story 4 work is authorized by completion
of this contract-authoring task.
