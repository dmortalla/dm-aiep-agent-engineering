# Story 5 Slice 3 — Fallback, workflow deadline, and application off-switch

This narrow slice implements REQ-EXEC-003, the workflow hard-stop portion of
REQ-EXEC-004, and the cancellation foundation of REQ-SAFE-004, preserving applicable
ENG-002 through ENG-007. It does not complete Story 5 or Module 6.5.

## Trusted authority and fallback contract

LifecycleRuntime binds the preferred StepExecutor and at most one fallback_step
at trusted application bootstrap. Both receive only ExecutableSubtask and
LifecycleInput and must return validated StepResult data. Bootstrap bindings and
policies must never be deserialized from generated content. Public input and
results still forbid undeclared fields; text and LangGraph Command cannot route,
select a binding, authorize execution, or change control state.

PreferredPathUnavailable is a trusted adapter's explicit, retry-safe unavailable
preferred-path classification, derived from TransientStepError. It is
circuit-qualifying. Adapters must establish that repeating or switching execution
is safe, including possible effects. This classification must not wrap arbitrary
programming defects, permission denials, malformed data, or safety failures.

Only this exception on the preferred binding selects the configured fallback,
and only with a closed circuit and remaining retry allowance. Absence of a
fallback safely stops with preferred_unavailable if neither circuit opening nor
attempt exhaustion has already terminated the action. A max_retries=0 policy
therefore disallows fallback execution. Ordinary transient failures retry the
preferred binding; generated text cannot request degradation.

Selection is recorded as paired fallback_task_ids and fallback_activation_attempts
in immutable LifecycleState. Revalidation checks uniqueness, task order, bootstrap
binding presence, actual retry transitions, activation attempt numbers, counters,
and existing circuit/backoff invariants. Selection latches for the current action:
subsequent attempts use the same fallback. The next action starts preferred.

Fallback shares the existing per-action retry budget, deterministic backoff,
workflow-local circuit, plan and tool budgets, and control checks. It grants no
extra attempts. A fallback switch uses the next accepted retry transition and its
backoff delay. A generic expected fallback failure or invalid result stops with
step_failure; explicit transient/unavailability failure retries only while budget
and circuit permit. Opening/exhaustion terminate with their existing reasons.
Unexpected fallback programming defects propagate. There is no fallback chain,
provider framework, implicit permission grant, or circuit reset.

Each preferred, fallback, and retry tool adapter must independently call the
accepted BoundedToolExecutor. Scheduling or choosing a fallback never grants
tool authority. Local integration tests observe authorization on both paths,
including fallback denial before a handler executes. Existing retry authorization
tests remain unchanged.

## Workflow deadline and off-switch

WorkflowPolicy is frozen, rejects extra fields, and revalidates bootstrap
instances. deadline_seconds is finite, strictly positive, and at most 180 seconds;
its default is 180.0. RuntimeBudget.workflow_deadline_seconds is the accepted
plan-level upper bound. When workflow_policy is omitted, the effective deadline
is the lesser of that accepted plan deadline and the architecture-level hard
ceiling of 180 seconds. An explicit trusted WorkflowPolicy may tighten or equal
the accepted deadline, but bootstrap rejects a policy that exceeds it; the policy
must also satisfy the 180-second ceiling. Generated data cannot influence this
reconciliation. This is separate from the p95 <=5s
deterministic/local latency SLO, which this slice does not measure or certify.

The clock is a trusted Callable[[], float], defaulting to time.monotonic.
checked_time validates finite numeric readings and rejects bools. RunControls
holds invocation-local start and last-read time, outside public input/result
contracts. Start is captured once per fresh run. Subsequent readings must not
regress. Invalid readings/accounting fail closed with ContractValidationError;
clock source defects propagate. Tests inject clocks and do not wait 180 seconds.

OffSwitch uses threading.Event and exposes only activate() and is_active().
Activation is one-way; LifecycleRuntime.cancel() activates its internal switch.
An optional trusted cancellation callable must return an exact bool. An observed
activation latches the internal switch, even if the external source subsequently
returns false. A cancelled runtime cannot be reused to clear cancellation.
Source exceptions abort invocation and propagate; malformed readings fail closed.
The internal active switch is consulted before the external source.

Both controls are checked:
- immediately before every preferred, fallback, or retry StepExecutor invocation;
- before backoff waiting begins and after it returns;
- at scheduling after every validated successful callback, including the final
  callback, before scheduling subsequent work or claiming completion.

Initial scheduling grants no capability and performs no callback; its following
execute node checks both controls before the first invocation. A stop at that
boundary records blocked_execution rather than falsely counting a callback.
Stop reasons are application-owned cancelled and deadline_exhausted. Safe-stop
retains completed work and validated results, but denies all subsequent execution.
Malformed internal control state cannot authorize another attempt.

These checks do not preempt synchronous callbacks or time.sleep already running.
A callback may return after the deadline or switch activation; validated results
are retained and the scheduling boundary records the hard stop. Waiting may
overshoot the deadline, but no later callback begins. Trusted callbacks, clock,
cancellation source, and waiting function must terminate. No action-timeout
machinery, background worker termination, or claimed 30-second callback preemption
is introduced. A read/check is cooperative, not an atomic fence against an
activation racing immediately after that read.

## Deterministic precedence

At a continuation boundary, cancellation takes precedence over deadline expiry;
both deny new work before preferred/fallback/retry execution or backoff waiting.

Returned callback failures first undergo the accepted classification:
1. Circuit opening takes precedence over retry exhaustion on the same qualifying
   failure, preserving Slice 2.
2. Retry exhaustion takes precedence over fallback eligibility.
3. With a closed circuit and allowance, unavailable preferred execution either
   selects the sole configured fallback or stops preferred_unavailable.
4. Before any allowed continuation begins, cancellation precedes deadline; either
   blocks that continuation and replaces its pending retry/fallback outcome.

Thus circuit-open never enables fallback; exhausted retries never enable fallback;
deadline and cancellation always block pending fallback and retries. Already
terminal callback failure reasons (including circuit-open) remain terminal rather
than being overwritten by a later control read. Unexpected defects abort and
propagate. Successful callback returns reach the control-checked scheduling
boundary. Tests cover simultaneous cancellation/deadline, deadline versus retry
and fallback, cancellation versus fallback, circuit versus fallback, exhaustion
versus fallback, and circuit-opening versus exhaustion.

## Real LangGraph topology and finite bound

The real compiled StateGraph remains START -> schedule -> execute, with
execute -> schedule on success or execute -> retry -> execute for a bounded
continuation. No new node is added. Fallback runs inside the existing execute node
through its trusted binding; local tests observe the actual callback and graph.
schedule and retry can now route directly to safe_stop. complete and safe_stop
remain terminal with edges to END. Generated node names or Command do not route.

For N actions and R retries (R <=2):
- scheduling nodes: at most N+1;
- execution nodes: at most N(R+1);
- retry nodes: at most NR;
- terminal nodes: one.

Total remains (2+2R)N+2, recursion_limit remains (2+2R)N+3.
At N=100, R=2: at most 300 callbacks, 200 waits, 602 nodes, recursion limit 603.
Hard stops shorten this execution. Lifecycle history is bounded to 602 entries,
backoff history to 200, and fallback selection to 100 unique tasks. The new maximum
fallback test executes every action as unavailable preferred, transient fallback,
then successful fallback through the real graph. The original maximum test runs
unchanged.

## Evidence and verification

Policy and failure injection tests are deterministic evidence. Compiled LangGraph
execution and independently authorized local tool execution are local integration
evidence. No paid calls, live provider, MCP, deployment, persistence, or recovery
evidence is claimed. Dependencies, architecture, ADRs, requirements, traceability,
PROJECT_STATUS, and accepted tests are unchanged.

tests/test_orchestration_fallback_stops.py covers fallback results/failures and
authority, finite shared budgets, deadline validation and clocks, cancellation
sources and latching, precedence, malformed internal state, tool authorization,
and the maximum fallback graph. All existing module tests are also required.
Strict verification uses Ruff, pytest, then compileall src tests, fail-fast.

## Deferred scope and completion limits

Action-timeout machinery, checkpoint persistence, SQLite recovery, crash resume,
idempotent re-entry, durable HITL, MCP, provider integrations, Guardrails AI,
observability vendors, cost dashboards, golden sets/evaluation frameworks, final
reviewer UI, deployment, and PROJECT_STATUS closeout remain deferred. No new
dependency, frozen architecture amendment, or change to another module is made.

Requirements: this slice's bounded controls are evidenced; full reconciliation
remains later work. Product Experience: final UI is deferred. Real Functionality:
local compiled lifecycle and accepted tool executor are exercised. Reliability:
finite fallback/retry, deadline, cancellation, and expected failures are tested,
with cooperative synchronous limits above. Security: application authority and
independent authorization remain enforced. Cost: tests require no paid operations.
Evidence: deterministic and local integration only. Deployment: not performed.
No full Story 5, completed harness, production-grade module, or release claim.
