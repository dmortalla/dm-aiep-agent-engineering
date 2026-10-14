# Story 7 Slice 3 — Application-owned asynchronous approval lifecycle

## Authority and approved mechanism

The human explicitly approved Option 1 after the native LangGraph architecture
gate: durable asynchronous suspension/resume belongs to the application-owned
harness, using existing trusted persistence/recovery. LangGraph remains the real
orchestration engine. Native interrupt, Command resume, and a framework checkpointer
are not introduced or claimed. Later native HITL requires separate architecture
review demonstrating material benefit; this slice does not amend frozen documents.

Accepted Slice 2 baseline: `e17cac7f3b209565d68281f7b56c74c73ad70bd7`. Preflight HEAD:
`61479d709fdb7b86a0ec3f38b22e2de714dd5b93`. Ancestry passed; later commits did not
touch Module 6.5, there were no tracked Module 6.5 edits, and the index was empty.
Concurrent Module 7/8 and root work remains outside this patch.

## Patch and existing boundaries

- `approval_lifecycle.py`: current bootstrap declarations, inert suspension data,
  application-owned start/resume boundary, and cancellation recording.
- `orchestration.py`: a small optional trusted before-step callback. With the
  default None, accepted behavior/topology is unchanged. With a gate, the accepted
  observer saves a pre-attempt prefix, then the gate runs outside step failure and
  retry classification. Controls are rechecked before execution. Effect-session
  use with this gate fails explicitly, preserving existing reservation semantics.
- `test_approval_lifecycle.py`: focused policy, security, actual graph, and local
  SQLite evidence.
- This documentation artifact.

Accepted Story 7 policy/store implementation, Story 6 recovery code and schemas,
dependencies, frozen requirements/architecture/ADR/authority policy, PROJECT_STATUS,
and other modules are unchanged. The existing CheckpointedLifecycle remains the
sole caller of the protected reconciled runtime-resume seam.

## Bootstrap and suspension

`ApprovalLifecycle` requires an accepted plan/adapter, existing checkpoint store,
accepted approval store, explicit workflow/thread identity, and one immutable
`ApprovalAction` per task. Each action declares exact versioned metadata, bounded
confidence/evidence, current trusted policy, independent ordinary/override
allowlists, and a current safety callback. It also requires current cancellation,
execution clock, and an independent authoritative **total workflow-age source**.
No suspended/persisted record supplies any of these objects.

The workflow-age source must include human waiting and be reconstructed from
trusted application/job authority independent of the original runtime. It must
not restart at zero or be inferred solely from a deserialized checkpoint. The
service checks monotonicity and persisted consumption; the existing runtime guard
enforces the current accepted deadline. Tests use deterministic application-owned
clocks, not an identity/deadline infrastructure service.

The genuine compiled graph schedules the next action. Before consuming an attempt
or invoking an adapter, its existing observer stores a valid version 1 checkpoint
with completed prefix, pending work, attempts, budgets, and elapsed consumption.
The gate evaluates current policy/safety and creates or verifies an exact durable
approval. An approval requirement raises a private application control transfer;
the service returns `SuspendedWorkflow` containing only status, exact binding, and
checkpoint/approval sequence references. No human polling/backoff, transaction,
worker, callback, human handle, or runtime object is retained as a continuation.
The caller may discard the complete original object graph.

No approval requirement is treated as step failure, retry-safe failure, model
routing, or framework interruption. An already-approved history still cannot
execute through start without explicit resume. Denied and consumed history cannot
be bypassed by loosening confidence/risk policy.

## Independent decisions and fresh resume

Humans submit decisions independently through accepted SQLiteApprovalStore.decide
using a newly constructed current Slice 1 evaluator and original installed human
handle. No identity lookup/deserializer issues a handle from historical actor text.

Fresh `resume(LifecycleInput, actor=...)`:

Each service instance allows only one graph invocation. A suspended/used instance
cannot reuse its old frozen policy/allowlist bootstrap for resume; construct a
fresh service with current trusted inputs. Preflight rejection consumes no approval.

1. Validates inert input and reconciles the latest checkpoint against current
   identity, plan, retry/circuit bounds, budgets, deadline, and restart-safe facts.
2. Selects the first incomplete action from the trusted plan/reconciled history;
   it accepts no caller-supplied action selector or suspended token as authority.
3. Loads exact current approval; missing/PENDING/DENIED/CONSUMED/stale or mismatched
   state fails. Current metadata, observation, and exact callback inputs must match.
4. Rechecks current workflow age/off-switch, current hard safety/scope/budget facts,
   current ordinary/override authority, and current Slice 1 policy. Tightened
   thresholds or newly applicable approval triggers invalidate historical decisions;
   no old threshold selects current policy. Legitimately loosened policy is reevaluated.
5. Charges human waiting time to an appended accepted checkpoint, checks remaining
   checkpoint capacity, and calls accepted store.consume for atomic revalidation
   and at-most-once consumption.
6. Grants one private invocation-local entry for that exact binding, then invokes
   existing CheckpointedLifecycle.recover and the real compiled graph. At the
   action boundary, policy/safety/current actor are checked again before adapter
   entry. The private entry is cleared on every return or exception.

Approval input equality includes a SHA-256 digest of the exact accepted task and
LifecycleInput. It is embedded by the application in the bounded observation
evidence envelope, alongside source evidence. Changes to callback input, task
description/dependencies, version, or metadata invalidate old approval. The digest
is equality evidence, not a signature/authentication mechanism. Oversized envelopes
are rejected; evidence is not silently truncated.

Each later action gets its own policy evaluation/approval boundary. One approval
cannot authorize another task. A valid denial remains terminal after reconstruction;
revision or disguised task replacement cannot bypass the existing checkpoint plan
or accepted store denial. No retry/fallback attempt can reuse the consumed entry:
the gate runs before every attempt and rejects a second protected entry.

## Cancellation, budgets, and limits

Cancellation is one-way. Service.cancel latches the accepted runtime switch and,
for an existing inactive workflow, appends the existing cancelled checkpoint field.
During active execution the accepted writer first retains completed work; on return
or failure the service ensures latched cancellation is recorded. Current source
cancellation observed before resume is also recorded when history exists. A fresh
false source cannot clear a persisted cancellation. Persistence failure propagates;
the local switch remains active and no reset API exists.

Current hard resource/scope/authorization facts come from the required trusted
safety source, and adapters retain their independent permission/resource boundary.
The service does not add general provider/tool metering. Accepted persisted budget
bounds, retry/circuit limits, plan order, and deadline reconciliation remain intact.
Human waiting stays consumed; clocks/deadlines are not restored from approval text.
The gate adds bounded checkpoint writes, not graph nodes or wider recursion limits.
Capacity is checked for the added pre-attempt writes before consuming approval.
Audit reads retain the accepted 34-event bound. No human polling or resume loop exists.

## Consumption/execution crash boundary and limits

Consumption remains an at-most-once SQLite transition, **not atomic action execution**.
Crash after consumption but before adapter entry leaves CONSUMED with incomplete
work. A fresh runtime has no invocation-local entry and fails closed; it does not
replay even if the stored approval had been valid. Out-of-band store consumption
likewise grants no transferable execution token. Unexpected defects propagate.
The tests simulate crashes with injected exceptions, not operating-system process kills.

This integration deliberately uses the accepted version 1, explicitly restart-safe
work path. All plan work must be declared restart-safe. It does not adapt effect
sessions, weaken their attempt reservations, or infer external commitment. Existing
Story 6 effect-verification behavior is unchanged and remains separately tested.
No exactly-once, distributed recovery, OS isolation, human authentication, IdP,
cryptographic database authentication, or tamper-resistance claim is made. Coherent
external database rewriting remains outside the accepted local-store guarantee.
Cross-database checkpoint/approval writes are not a distributed transaction;
missing or inconsistent records fail closed without an automatic repair/replay.

## Evidence and remaining scope

Tests exercise real LangGraph nodes, actual temporary SQLite files, independent
decisions, garbage collection of the original runtime, fresh bootstrap handles,
policy/safety changes, cancellation/deadline/budget/scope, exact inputs/bindings,
denial/replay, malformed records, retry/fallback blocking, and consumption crash
ambiguity. Evidence classes are deterministic and local integration. No network,
credentials, external services, paid calls, or other-module imports are required.

Reviewer entry point: focused pytest file, then the full fail-fast sequence from
Module 6.5: Ruff check `.`, pytest, compileall `src tests`. Fresh temporary databases
are under parent TECHADEMY/EVIDENCE for the known Windows temp restriction.

Final verification on 2026-10-14, Python 3.12.14: Ruff passed; full pytest
**909 passed, 0 failed** (839 accepted cases plus 70 new cases), in 279.62 seconds;
compileall of `src` and `tests` passed. The final run used parent
`EVIDENCE/module-06-5-story-7-slice-3/pytest-full-2`. Safe repairs were import sorting,
formatting, docstring line lengths, explicit exception chaining, and correcting a
test observer to require both actual node name and matching metadata rather than
count inherited child-chain metadata. Its strict expected order was retained.
After repair and the final fresh-bootstrap safeguard, the full fail-fast sequence
was rerun. No unsafe fixes, weakened expectations/rules, or dependency changes.

Slice 4/final HITL lab and UI, native framework HITL, external effects in this
approval wrapper, authentication/identity infrastructure, general telemetry/cost,
Story 8 and later work, deployment, and Story 7 completion remain deferred.

Requirements: Slice 3 asynchronous integration toward REQ-HITL-001 through 003,
REQ-DEL-003, and REQ-LAB-005. Product Experience: runnable focused tests; final lab/UI
deferred. Real Functionality: real graph and SQLite through application-owned HITL.
Reliability: bounded re-entry, current guards, fail-closed crash/replay and defects.
Security: current authority, exact binding/input, inert history, denial and hard
stops. Cost: zero paid calls. Evidence: deterministic/local integration. Deployment:
none. No further frozen-policy/architecture conflict was discovered within the
explicitly approved Option 1 and restart-safe scope.
