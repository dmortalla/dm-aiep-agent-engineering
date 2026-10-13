# Story 5 Slice 1 — Typed lifecycle and finite LangGraph topology

This implementation follows the frozen architecture and does not complete Story 5.

`orchestration.py` uses LangGraph 1.2.14's real `StateGraph`, compiles it, and
invokes the compiled graph. The topology is START → schedule → execute → schedule,
ending through complete or safe_stop → END. No future lifecycle nodes are simulated.

Application bootstrap snapshots and validates an accepted `ExecutionPlan` and binds
a trusted terminating local executor. The accepted `PriorityScheduler` determines
dependency and priority order. Public invocation accepts only bounded text in
`LifecycleInput`, never graph state, routing strings, commands, graph configuration,
permissions, or approval claims. Bootstrap must never be constructed from generated
authority data. Tool adapters must independently invoke `BoundedToolExecutor`;
scheduling does not grant permission.

Immutable, revalidated state contains a finite phase enum, completed identifiers,
validated data-only results, a strict step counter, phase history, and an explicit
safe-stop reason. Legal transitions are application-owned. State validation checks
transition history, counters, results, and completion consistency; runtime checks
the exact scheduled prefix and plan bound. Every return to scheduling follows one
new completed task. There are at most N step invocations and 2N+2 graph node
executions, with a framework recursion limit of 2N+3. Terminal phases have no
outgoing transitions. Expected harness failures or malformed outputs stop without
retry; unexpected defects abort invocation. Generated result text cannot route,
and LangGraph `Command` output is rejected as invalid step data.

## Requirement and evidence scope

| Requirement | Slice evidence |
| --- | --- |
| REQ-TECH-001 | Real compiled LangGraph invocation and observed step progression |
| REQ-EXEC-004 | Foundation: explicit safe-stop, terminal outcomes, finite plan progression; broader hard-stop controls deferred |
| ENG-002, ENG-003 | Data-only input/output validation, adversarial authority fields, node-name text and Command rejection; tool authorization integration |
| ENG-004 | Plan bound, strict counters, bounded history, finite routing and recursion guard |
| ENG-005 | Credential-free local execution; no provider calls |
| ENG-006 | Policy tests are deterministic; real framework/tool integration is local integration |
| ENG-007 | Malformed state, illegal transitions, expected failure, denial, and unexpected-defect tests |

`tests/test_orchestration.py` exercises real compiled graphs, dependency ordering,
stable repeated results, 1/12/100-step bounds, safe-stop without later execution,
and independently authorized tool execution. Existing Stories 1–4 remain unchanged.

## Limitations and deferred work

Graph finiteness does not preempt a trusted synchronous executor that never returns.
Workflow deadlines, exponential backoff, circuit breakers, graceful fallback, and
application off-switch behavior remain later Story 5 slices. REQ-EXEC-001 through
REQ-EXEC-003 and REQ-SAFE-004 are not complete. There is no persistence, recovery,
HITL, MCP, provider integration, telemetry vendor integration, UI, or deployment
in this slice. Repeated runs start fresh and are not crash-resume or idempotency
evidence. No complete harness, production-grade module, or release claim is made.

LangGraph moved from the optional orchestration extra to core dependencies because
the executable lifecycle requires it. Offline lock reconciliation changed only
that dependency placement and metadata; locked package versions are unchanged.
The existing optional SQLite checkpoint dependency remains optional and unused.
