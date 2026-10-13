# Story 5 Slice 4 — Integrated lifecycle evidence

## Scope

This slice adds tests/test_orchestration_integrated.py and this document only.
It supplies deterministic end-to-end evidence for the accepted Story 5 controls
through LifecycleRuntime.run() and real compiled LangGraph execution. Production
source, graph topology, dependencies, policy contracts, and Slices 1–3 tests are
unchanged. No complete Story 5, Module 6.5, production-readiness, or release claim
is made; independent review and later reconciliation remain required.

The scenarios evidence REQ-EXEC-001 through REQ-EXEC-004, REQ-SAFE-004, and
REQ-TECH-001, preserving applicable ENG-002 through ENG-007. They integrate accepted
controls rather than replace the lower-level Slice 1–3 regression coverage.

## Integrated scenario matrix

All test names below belong to tests/test_orchestration_integrated.py.

| Scenario | Exact test function | Integrated evidence |
| --- | --- | --- |
| A: Happy path and inert attack text | test_integrated_happy_path_preserves_priority_dependencies_and_data | Three actions execute in dependency/priority order; exact finite history, completed results, no retry/fallback selected by text, and identical results on repeated fresh invocation. |
| B/D/H: Retry recovery, graceful fallback, independent authorization | test_integrated_retry_then_fallback_reauthorizes_every_attempt | First action recovers after two transient failures; second action switches from unavailable preferred to bootstrap fallback. Five actual attempts are independently authorized. Cases deny the second attempt (retry) or fifth attempt (fallback), preventing denied handler execution and stopping without later work. |
| C: Circuit opening/exhaustion before fallback | test_integrated_failure_on_last_attempt_cannot_enable_fallback | Third attempt reports preferred unavailability. Threshold three opens the circuit, taking precedence over simultaneous exhaustion. Threshold four leaves circuit closed but exhausts attempts. Neither case invokes fallback or later actions. |
| E/F: Deadline/cancellation stops pending retry/fallback | test_integrated_controls_block_pending_authorized_continuation | One action completes; the next performs an authorized local read then requests trusted retry/fallback. Accepted plan deadline 10 seconds, cancellation, or both activate before continuation. No wait, later tool call, fallback, or third action begins. Cancellation wins over simultaneous expiry and remains latched across fresh runs on the same runtime. |
| E/F: Late successful callback and pending next action | test_integrated_late_success_retained_but_no_next_action_begins | First callback returns valid data after expiry or switch activation. Completed data is retained; scheduling records the hard stop and prevents the next action. |
| G: Forged public/request, callback, tool output, or Command | test_integrated_forged_authority_fails_closed_without_later_work | Extra authority fields fail input/result contracts; Command cannot route. Invalid callback/tool output produces immediate step_failure after one invocation, no retry/fallback, and unchanged closed circuit. Invalid public input invokes no callback or tool. |
| J: Unexpected callback/cancellation-source defect | test_integrated_programming_defect_propagates_after_completed_work | After an action completes, trusted callback or cancellation source raises RuntimeError. The exception propagates; no retry, fallback, fabricated terminal outcome, or later work follows. |
| I: Finite structural maximum | test_integrated_maximum_observes_602_real_nodes_and_603_recursion_limit | Every action uses unavailable preferred, transient fallback, then successful fallback. Actual framework node starts and exact sequence are observed: 602 nodes, 300 callbacks, 200 recorded waits, 100 completed actions, recursion limit 603. |

The eight test functions produce 21 cases: 1 happy path, 3 recovery/authorization,
2 circuit/exhaustion, 6 pending-continuation control combinations, 2 late-success
controls, 4 forged-authority origins, 2 defect boundaries, and 1 maximum.

These named pytest scenarios and expected outcomes can be reused as a reference
by Story 11. No golden-set loader, evaluation service, new production scenario
abstraction, reusable UI layer, or final reviewer UI is introduced. Accepted
module-local tool test fixtures are reused; no other module is imported.

## Real LangGraph evidence and finite bound

Every executable scenario invokes the public LifecycleRuntime.run() boundary.
No scenario substitutes a mocked graph, synthetic state machine, or direct call
to an internal node. Happy-path, recovery/fallback, and maximum tests explicitly
verify CompiledStateGraph. All runtime instances compile and invoke the accepted
real StateGraph.

The maximum test wraps the compiled graph's invoke method only to record the
application-supplied recursion limit and attach a test-only BaseCallbackHandler.
It delegates to the original real invoke with the same state and control
configuration, adding only its in-memory observer. Matching framework node names
and langgraph_node metadata identify node starts; exact counts and the full
sequence are asserted. Observer exceptions propagate (raise_error=True).
This uses an already-installed LangChain callback API, not a vendor integration,
production telemetry feature, replacement graph execution, or new dependency.

Accepted topology remains:

- START -> schedule.
- schedule -> execute, complete, or safe_stop.
- execute -> schedule after success, retry for allowed continuation, or safe_stop.
- retry -> execute or safe_stop.
- complete and safe_stop -> END.

One initial schedule plus one after each successful action yields at most N+1
scheduling nodes. Each action has at most R+1 execution nodes and R retry nodes.
There is one terminal node. Thus:

(N+1) + N(R+1) + NR + 1 = (2+2R)N + 2

The application recursion limit remains (2+2R)N + 3. Fallback selects a binding
inside execute and consumes an existing attempt; it introduces no new node.
Hard-stop routes terminate earlier. START/END sentinels are excluded from
application node counts.

At N=100, R=2, the observed counts are 101 schedule + 300 execute + 200 retry +
1 complete = 602 nodes, with recursion limit 603. Lifecycle history also contains
602 entries. Backoff has 200 entries; fallback records 100 tasks and exact
activation attempts 1,4,...,298. This test checks actual node starts in addition
to state history. No paid calls or real backoff sleeps occur.

RuntimeBudget.max_plan_steps still defaults to 12; its accepted range remains
1–100. Only structural stress explicitly configures 100 actions. Slice 4 changes
neither default nor maximum production contracts.

## Retry, fallback, circuit, and authority

Trusted application bootstrap owns plans, RetryPolicy, preferred/fallback
bindings, clocks, and cancellation sources. Ordinary TransientStepError retries
the same binding. PreferredPathUnavailable explicitly classifies a retry-safe
unavailable preferred path. Only that classification can select the sole
configured fallback; no generated text or undeclared field selects it.

The recovery scenario uses two retry attempts for its first action, recording
0.1 and 0.2 seconds of deterministic exponential backoff. Its second action uses
the next shared retry slot to invoke fallback, recording 0.1 seconds. Counts,
fallback task identity, activation attempt, validated results, and circuit reset
on success are asserted together.

Circuit opening precedes retry exhaustion on the same qualifying attempt.
Exhaustion precedes fallback eligibility. The circuit scenario deliberately
reports preferred unavailability on the last permitted attempt with configured
fallback present; neither circuit-open nor exhausted execution grants fallback
an additional attempt.

The local tool adapter invokes BoundedToolExecutor.execute independently on every
preferred, retry, and fallback attempt. Tests record actual authorization
decisions and handler invocation counts. Denial prevents the denied handler
from running and stops the lifecycle. Routing never substitutes for permission.
Tools here perform inert local read work; retry-safe classification follows
trusted application knowledge of that work, not tool-returned instructions.
There is no consequential external write or durable approval evidence.

Adversarial request, task-description, and tool-result text mentions node routing,
Command, permissions/approval, increased retries, counter reset, fallback,
deadline extension, clock reset, cancellation suppression, circuit reset, and
manufactured stop reasons. Validated text remains inert through actual local
tool and lifecycle paths. Authority-bearing extra request/callback/tool fields
fail closed; generated Command is rejected as result data. The unchanged
Slice 1–3 tests retain finer individual-field and malformed-state coverage.

This proves the normal untrusted data-contract boundary, not a sandbox against
malicious arbitrary Python inside trusted bootstrap callbacks.

## Deadline and off-switch hard stops

The pending-continuation scenario uses an accepted plan deadline of 10 seconds,
with no explicit WorkflowPolicy. This therefore exercises Slice 3's repaired
plan-to-policy reconciliation through real execution: omitted policy is bounded
by the accepted plan and the 180-second architectural ceiling. An injected
application monotonic clock reaches exactly 10 seconds after the second read.

Deadline-only cases record DEADLINE_EXHAUSTED. Cancellation-only cases record
CANCELLED. Both-active cases record CANCELLED, preserving cancellation precedence
at continuation boundaries. RETRY_PENDING -> SAFE_STOP occurs without a wait or
another callback, for both ordinary retry and selected fallback.

After cancellation is observed, repeating run() on the same runtime cannot clear
the latched switch or invoke new tools, even with hostile resume/reset text.
The separate late-success scenario records the valid result and completed action
before the scheduling boundary records the hard stop, proving no later action
starts. Existing Slice 3 tests retain final-callback and per-boundary coverage.

Already-terminal callback failures retain their accepted failure reason.
Unexpected callback and cancellation-source defects propagate rather than becoming
ordinary safe-stop results. This slice does not change precedence or error handling.

Checks are cooperative. They do not interrupt a synchronous callback or a wait
already running, undo effects performed before return, provide process/OS
isolation, or make an atomic guarantee against activation just after a read.
Trusted callbacks and sources must terminate. No action-timeout machinery,
threads/process termination, durable cancellation/resume, or new recovery
authority is added. The workflow safety deadline is separate from the p95 <=5s
latency SLO; this slice does not certify that performance target.

## Verification and evidence classification

Baseline: 418 tests passed before Slice 4 edits. The integrated module adds
21 deterministic cases. Quality gates are ruff check ., pytest, then
python -m compileall src tests using the existing Python 3.12 environment.
Accepted tests and configuration are unchanged.

Injected failures, recorded backoff, clocks, cancellation, and authority attacks
are deterministic policy evidence. Actual compiled LangGraph runs, observed
framework node starts, and BoundedToolExecutor authorization/handler execution
are local integration evidence. In-memory recorders and a test denial adapter
are test instrumentation, not live-service evidence. No credentials, paid
provider execution, external services, or network access are required.

## Limits and deferred scope

Story 5 acceptance/reconciliation and full Module 6.5 completion are not claimed.
Story 6 checkpointing, persistence, recovery, resume, idempotent re-entry;
Story 7 durable HITL; Story 8 MCP; Story 9 providers/Guardrails;
Story 10 vendor observability/cost dashboard; Story 11 golden-set framework/final
reviewer UI; Story 12 full harness integration/release; and deployment remain
deferred. Architecture, ADR, requirements, traceability, PROJECT_STATUS, dependency
files, accepted production source, and unrelated modules are unchanged.

Requirements: integrated scenarios evidence the named Story 5 contract, pending
independent review. Product Experience: final reviewer UI remains deferred.
Real Functionality: real graph and local tools execute. Reliability: control
interactions, failure paths, and finite maximum are exercised with cooperative
limits above. Security: data-only authority and separate tool authorization
remain enforced. Cost: no paid calls. Evidence: deterministic/local integration.
Deployment: not performed. This is evidence toward later reconciliation, not
production readiness or release approval.
