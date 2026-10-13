# Story 5 Slice 2 — Bounded retries, backoff, and circuit breaker

This slice extends the accepted Slice 1 orchestration boundary without changing
the frozen architecture, dependencies, or Stories 1–4. It implements the
REQ-EXEC-001 and REQ-EXEC-002 retry/circuit portions of Story 5, with applicable
ENG-002 through ENG-007 controls. Policy evidence is deterministic; executable
LangGraph integration evidence is local integration. No paid calls are required.

## Application authority and retry eligibility

Trusted bootstrap binds a frozen, revalidated `RetryPolicy` and waiting function.
The plan's accepted retry budget remains an upper bound; the policy itself allows
only 0–2 retries. Defaults use min(2, plan budget). Two retries mean one initial
attempt plus two retry attempts: at most three attempts per action. The runtime
counts every actual step invocation, including failed invocations, and records
per-action and total attempts in immutable lifecycle state. Scheduling new work
resets only its per-action counter; retries never reset it. History revalidation
checks both counters against actual transitions and checks each action's bound.

Only `TransientStepError`, derived from the existing `ToolExecutionError`, is
retryable and circuit-qualifying. A trusted adapter must explicitly classify a
known transient failure as safe to retry, including any possible side effects.
Never infer this classification from generated output or wrap arbitrary defects.
Generic tool failures, authority denials, budget/time-limit failures, contract
errors, and malformed output stop immediately without retry or breaker increment.
Unexpected programming/framework defects propagate. Waiting-function defects also
propagate without another step invocation. The accepted tool executor is unchanged;
each tool attempt must independently authorize and consume its existing budgets.

Input and result contracts remain data-only and reject undeclared fields. Text
cannot choose retries, counters, breaker state, thresholds, resets, or graph nodes.
LangGraph Command objects remain rejected as malformed output. Model labels and
configuration validation do not establish provenance: bootstrap remains trusted
application code, never generated authority.

## Exponential backoff and waiting

For one-based retry number k:

`delay(k) = min(max_delay_seconds, initial_delay_seconds * 2**(k - 1))`

Default delays are 0.1 and 0.2 seconds. Both parameters must be positive finite
numbers no greater than 30 seconds, with initial delay no greater than the cap.
There is no jitter. Each action has at most two waits, totaling at most 60 seconds;
for N actions, scheduled backoff totals at most 60N seconds. This is a delay bound,
not a workflow deadline or a guarantee about operating-system scheduling.
Calculation never sleeps. A dedicated graph retry node calls the trusted waiting
function; normal execution defaults to `time.sleep`, while tests inject recorders
and perform no actual backoff sleeps. Calculated delays are recorded and validated
against application policy before waiting and before subsequent execution.

## Circuit behavior

The circuit belongs to one run and the one bound step executor. It starts CLOSED
with zero consecutive qualifying failures. Each explicit transient failure counts
once, whether or not a retry remains. It opens exactly at the configured threshold
(default 3; integer range 1–300) and latches at that threshold. Open state blocks
execution. A validated successful step resets consecutive failures while closed;
neither success nor failure can reset an open circuit. Non-qualifying failures
terminate without changing the qualifying counter. Circuit opening takes precedence
over retry exhaustion when both happen on the same attempt.

Terminal reasons distinguish ordinary step failure, exhausted retries, and circuit
opening. There is no half-open state, automatic reset, cooldown, persistence,
cross-run failure accumulation, or distributed circuit. Each public run starts
fresh; this is not recovery or resume. No untrusted breaker state is accepted by
the public run boundary. Internal state revalidation verifies phase/threshold,
bounded failure counters, failure history, and the circuit-open terminal outcome.

## Finite LangGraph execution

The real compiled topology adds only an application-owned retry path:
execute → retry → execute. Each retry consumes one of at most R retries per action,
with R ≤ 2. All original completion and safe-stop nodes remain terminal. No
framework retry policy or generated Command chooses transitions.

For N actions and R allowed retries per action, the maximum node executions are:

- N+1 scheduling nodes;
- N(R+1) execution nodes;
- NR retry nodes;
- one terminal node.

Total: `(2+2R)N+2`. The invocation recursion limit is `(2+2R)N+3`.
At N=100 and R=2, there are at most 300 step calls, 200 retry waits, and 602 node
executions; the limit is 603. Lifecycle history is bounded at 602 entries and delay
history at 200 entries. Tests execute this maximum through real LangGraph.
Authority or malformed-state failures cannot create an additional attempt.

## Verification and deferred scope

`tests/test_orchestration_controls.py` exercises retry success/exhaustion, exact
initial-plus-retry semantics, capped backoff, strict policy rejection, transient
classification, immediate security/validation stops, programming defects, closed
and latched-open circuit behavior, forged state and output, stable repeated runs,
independent tool authorization on retries, plan budget enforcement, and the maximum
finite graph case. All accepted Slice 1 tests remain unchanged.

REQ-EXEC-003, complete REQ-EXEC-004, and REQ-SAFE-004 are not claimed complete.
Graceful fallback, workflow deadlines, cancellation/off-switch, persistence,
checkpointing, recovery, idempotent re-entry, HITL, MCP, providers, Guardrails AI,
observability vendors, dashboards, evaluation frameworks, UI, and deployment remain
deferred. Trusted callbacks and waiting functions must terminate; graph bounds do
not preempt synchronous Python execution. Retry-safe side-effect classification
is the trusted adapter's obligation, not inferred or supplied by generated data.
There is no full Story 5, full harness, production completion, or release claim.
