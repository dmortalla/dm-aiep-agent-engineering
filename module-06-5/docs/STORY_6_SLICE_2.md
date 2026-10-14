# Story 6 Slice 2 — Lifecycle checkpoints and crash/restart/resume

This slice connects the accepted Slice 1 checkpoint store to the accepted Story 5
lifecycle, toward REQ-REC-001 through REQ-REC-003, REQ-DEL-002, and REQ-LAB-004.
It does not complete Story 6, does not address REQ-REC-004 idempotent re-entry,
and makes no production-readiness claim. Independent review remains required.

## What changed

- `src/harness_engineering/recovery.py` (new): `CheckpointedLifecycle`,
  `reconcile`, and `RecoveryError`.
- `src/harness_engineering/orchestration.py`: public boundary observation
  (`run_observed`, `bounds`, `BoundarySnapshot`, `LifecycleBounds`), the inert
  `RestoredProgress` value, and a private resume seam. `run()` behaves as before
  and is still the public data boundary. Graph nodes, edges, routing, and the
  recursion limit are unchanged.
- `tests/test_recovery.py` (new) and this document.

The checkpoint schema, state version, SQLite store, dependencies, frozen
requirements, architecture, and PROJECT_STATUS are unchanged. No LangGraph
checkpointer is used; the application-owned store remains the only persistence.

## Checkpoint boundaries

The lifecycle reports a boundary only after its own state has passed full
plan and policy validation. One snapshot is appended per boundary, with
sequences 1, 2, 3, … continuing after recovery.

| Boundary | When | Why it is coherent |
| --- | --- | --- |
| Attempt consumed | End of the `execute` node, for every outcome that invoked a step: step completed, retry pending, or failure stop | The attempt counters, circuit, and result are final for that attempt. |
| Control stop | `safe_stop` node, for cancellation or deadline exhaustion | Records the cancellation flag and consumed time even when no attempt ran. |

Nothing is written while a step callback is running, during backoff waiting, or
before the first attempt finishes. A snapshot holds completed work IDs with
result text, remaining work IDs in trusted order, attempts consumed per started
action, consumed time, and the cancellation flag. It holds no functions,
exceptions, graph nodes, clients, policies, permissions, limits, or request text.
Approval and committed-effect slots stay empty.

## Trusted authority versus persisted history

| Concern | Authority | Persisted data is |
| --- | --- | --- |
| What work exists and its order | Current accepted plan in the fresh runtime | A claim that must match it exactly |
| Retry, circuit, fallback, topology | Fresh runtime bootstrap | Never consulted |
| Deadline and budgets | Current plan budget and workflow policy | Consumption to subtract, never a limit |
| Cancellation | Runtime off-switch and trusted source | A reason to refuse; never a reset |
| Which interrupted work may run again | `restart_safe_work` declared by the caller | Not consulted |

The runtime never receives persisted work IDs. Recovery passes it only a
completed-prefix length, results, and attempt counts; the runtime maps these
onto its own scheduling order, rebuilds the state, and revalidates it.

### Supported API and the restored-progress boundary

`LifecycleRuntime.run` and `LifecycleRuntime.run_observed` always start from
fresh state. Neither has a parameter for prior progress, and no public runtime
method accepts `RestoredProgress` or `LifecycleState`. `RestoredProgress` is an
inert value: constructing one, or calling `reconcile` directly, resumes nothing.

The only supported way to resume is `CheckpointedLifecycle.recover`. It takes a
request and the `restart_safe_work` declaration and nothing else; the completed
prefix is always derived inside that call from the latest checkpoint in the
bound store, reconciled against the bound runtime. It then calls the runtime's
private `_resume_reconciled` method, which still rebuilds and validates the
prefix against the trusted plan, order, and retry policy.

This is an API and module-convention boundary, not tamper-proofing. Python does
not prevent code in the same process from calling a private method, and code
that can do so is already trusted application code able to construct a runtime
with any plan. The boundary removes restored progress from the supported
surface so it cannot be supplied by ordinary callers or mistaken for input.
No token, secret, stack inspection, or global authorization state is used.

## Recovery reconciliation

`CheckpointedLifecycle.recover` loads the latest snapshot through the store
(which already rejects corruption, version and identity mismatch, and never
falls back to an older row) and then requires all of the following. Any
failure raises `RecoveryError` before any step runs.

1. The snapshot revalidates and its identity equals the trusted identity.
2. It is not cancelled. Slice 2 has no re-entry authorization for cancelled work.
3. Completed plus pending work equals the trusted plan's work, in order.
4. Every completed action records between one attempt and the smaller of the
   trusted per-action attempt limit and circuit threshold.
5. No incomplete work records attempts (see "Partially attempted actions").
6. The sequence is at least the number of recorded attempts.
7. Recorded tool calls and provider attempts do not exceed the plan budget;
   recorded context and output tokens do not exceed the per-call limit times
   the provider-attempt limit.
8. Recorded elapsed time is below the trusted deadline.
9. The first incomplete action is in the caller's `restart_safe_work`.
10. Enough sequence numbers remain for the worst case of the remaining work.

Completed work is restored from its validated result and is not executed again.
Execution then enters the unchanged graph at its normal scheduling node, so the
first thing that happens is the usual cancellation and deadline check.

## Deadline, retry, and budget handling

Elapsed time is rounded up to whole milliseconds when written. On recovery the
invocation clock is started that far in the past, so the remaining deadline is
the trusted deadline minus recorded consumption. A restart cannot obtain a
fresh deadline, and a tighter current deadline than recorded consumption fails
closed. Attempt history of completed actions is restored into total attempts,
backoff records, and transition history. Tool, provider, and token counters are
validated and carried unchanged into every later snapshot; the Story 5
lifecycle does not meter them, so a run that starts fresh records zero.

## Partially attempted actions

When the latest snapshot shows attempts consumed on incomplete work (a crash
during backoff or a later attempt, retries exhausted, an open circuit, or a
non-retryable step failure), recovery refuses and leaves the history untouched.
The version 1 snapshot cannot distinguish "retry pending" from "terminally
failed", and resuming inside an action would need a new graph entry point.
Refusing keeps consumed attempts consumed. Resuming such workflows is deferred.

## Interruption evidence classification

Interruption is simulated by an injected exception from a step callback or the
wait function. The exception propagates unchanged, exactly as in Story 5; no
retry, fallback, or fabricated outcome follows. Tests then discard the original
objects and build a new store, runtime, and coordinator over the same SQLite
file, with a different clock origin. This is deterministic and local-integration
evidence. It is not an operating-system process crash, power-loss, or
durability test, and no such claim is made.

## Limitations

- An attempt interrupted before it reaches a boundary is not recorded, so the
  resumed action starts with its full per-action attempts.
- Time between the interruption and recovery is not counted; only recorded
  execution time is. No trusted cross-process clock exists in the lifecycle.
- A forged snapshot with smaller counters than reality cannot be detected.
  It can never exceed what a fresh run under the same trusted limits allows.
- The plan is matched by work ID and order only; snapshots carry no plan digest.
- The request text is supplied again by the caller and is not compared.
- Fallback selection history of completed actions is not persisted or restored.
- A step result longer than 4096 characters cannot be stored; the run aborts
  with `PersistenceError` rather than truncating.
- Checkpoint write failure aborts the run and is never treated as a step failure.

## Deferred to Slice 3

Committed-effect records and contracts, effect identity and verification,
duplicate committed-effect prevention, idempotency keys and ledger semantics,
and idempotent re-entry across effectful or partially attempted boundaries.
`restart_safe_work` is a trusted declaration, not an effect record.

## Verification

Run from `module-06-5` with the Python 3.12 environment:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall src tests
```

`tests/test_recovery.py` adds 38 cases over the 508-case baseline. Temporary
databases belong under parent `TECHADEMY/EVIDENCE` via `--basetemp`, not here.
