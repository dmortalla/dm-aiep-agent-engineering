# Story 6 Slice 3 — Committed effects and idempotent re-entry

This bounded slice extends accepted commits `bc19e0b` and `0ec88f1` toward
REQ-REC-001 through REQ-REC-004, REQ-DEL-002, REQ-LAB-004, and ENG-002 through
ENG-007. It does not close Story 6 or certify module production readiness.
Frozen requirements, architecture, ADRs, implementation plan, PROJECT_STATUS,
dependencies, and other modules are unchanged.

## Baseline and patch

Before mutation, accepted Slice 2 commit
`0ec88f160d09c01093f8e9009e2305d2c6870ff5` was verified as an ancestor of HEAD.
There were no intervening commits touching `module-06-5`, no tracked or untracked
module changes, and nothing staged. Existing changes under Module 7/8, root
configuration, and scripts were preserved.

The patch contains exactly these module files:

- `src/harness_engineering/effects.py` — trusted bootstrap declarations and
  verification observation contract.
- `src/harness_engineering/persistence.py` — inert effect identities, committed
  claims, and an explicit version 2 state contract in the accepted SQLite store.
- `src/harness_engineering/orchestration.py` — private reservation/execution seams
  and conservative pending-attempt reconstruction through existing backoff.
- `src/harness_engineering/recovery.py` — store-backed reconciliation,
  verification, reconstruction, ledger writes, and time preservation.
- `tests/test_effect_recovery.py` — deterministic and local integration evidence.
- `docs/STORY_6_SLICE_3.md` — this narrow implementation/evidence description.

## Contract and stable identity

`EffectSpec` is trusted bootstrap data: application namespace, work ID,
versioned operation name, and SHA-256 digest of the exact accepted effect inputs.
The application binds callbacks to those fixed inputs. Incoming request text is
not passed to the effect callback and cannot select the effect operation/key.
Changing the accepted inputs or operation requires distinct application-approved
work; recovery of existing history then fails its identity comparison.

The deterministic key is SHA-256 of canonical JSON containing a fixed identity
contract tag, those four spec fields, and the explicit workflow/thread UUIDs.
No randomness, result text, persisted nomination, or credential participates.
The full `EffectIdentity` records namespace, workflow/thread, work ID, and key.
Each work item has at most one declared logical effect. Identity references are
bounded to 128 characters; keys are exactly 64 lowercase hexadecimal characters.

`CommittedEffect` contains only an identity. It is an immutable, inert historical
claim, with no result, callback, permission, approval, secret, or routing authority.
At most 100 bindings/claims fit a checkpoint; duplicates and mismatched
workflow/binding identities are rejected. The existing 1 MiB payload, 100-work,
4096-character stored-result, attempt, counter, and sequence bounds remain.

## Trusted verification boundary

`EffectDeclaration` binds application-owned `invoke(identity, timeout)` and
`verify(identity, timeout)` callbacks, an explicit retry permission, and a timeout
of at most 30 seconds. Identity is data, not authorization. Adapters retain their
own permissions and must honor timeout and external idempotency contracts.
Declarations are validated and snapshotted at coordinator construction, never
restored from SQLite. Effect workflows reject fallback bindings in this slice.

Verification returns `EffectObservation`: exact identity, one of `committed`,
`not_committed`, or `unknown`, and a bounded optional reconstruction result.
Observations are recursively validated and compared with the trusted expected
identity. Malformed, foreign, unknown, unavailable, or late observations fail
closed. A committed observation without its required reconstruction result fails
closed. Results come from the verifier; historical effect result text is never
used without verification and equality reconciliation.

The adapter must provide a conclusive, quiescent `not_committed`: no earlier
invocation may still commit afterward. Absence from an eventually consistent
index or an invocation still in flight is `unknown`. This is an application
adapter obligation, not a capability SQLite can infer. A trustworthy verifier
must bind both commitment and result to the exact accepted operation and inputs.

## Ordering and crash windows

Before each effect attempt, the lifecycle emits its validated executing boundary.
The coordinator durably appends an `attempt_reserved` checkpoint counting the
upcoming attempt as consumed. Persistence failure aborts outside the step-error
handler. Cancellation/deadline are checked again after the write. A control stop
retains the reservation even when the callback was not invoked.

The effect handler verifies before invocation. An already committed effect yields
its verified result without invocation. Otherwise it invokes with the stable key,
checks timeout, verifies commitment/result, and only then completes the step.
Classified transient failures are retryable only with conclusive noncommitment,
the declaration's retry permission, and existing runtime retry/circuit limits.
Unexpected defects propagate without automatic retries or invented outcomes.

| Failure window | Durable evidence and restart behavior |
| --- | --- |
| Before reservation write | No effect callback ran; there may be no checkpoint to recover. |
| During reservation write | SQLite either retains the previous snapshot or appends the reservation. Invocation cannot proceed after write failure. |
| After reservation, before invocation | Attempt stays consumed; verification resolves commitment. A proven absence permits only a remaining authorized attempt. |
| During invocation | Reservation remains. Unknown or still-in-flight commitment blocks recovery. |
| After external commit, before completion write | Independent verification reconstructs the committed effect and prevents replay. |
| During completion write | Latest history may contain reservation or completion; either requires independent verification. |
| After completion write | Recovery verifies commitment and result again; no invocation follows. |
| During recovery verification/reconciliation write | A later recovery repeats verification. No effect is invoked unless all prior checks/writes succeeded. |

The external commit and SQLite checkpoint are separate operations. There is no
distributed transaction, atomic commit across systems, or exactly-once external
delivery claim. The target is verified idempotent recovery. External adapters
must implement their own atomic key deduplication and safe observations. No
cross-process execution lease or general distributed concurrency protocol is
implemented; applications must govern workflow ownership and adapter safety.

## Recovery and preserved limits

Recovery always loads the latest checkpoint through the existing store; corruption
never falls back. Version 2 declarations must exactly equal trusted expected
bindings. Historical work/order, attempts, sequence capacity, consumption,
cancellation, and deadline are checked before verification. Claims about
unattempted work cannot authorize a skip.

Every completed effect, and the first partially attempted effect, is verified.
Committed work is reconstructed without invocation, including when no replay
attempt remains. Persisted commitment contradicted by noncommitment fails closed.
A partially attempted, noncommitted action resumes only from an attempt reservation
or retry-pending boundary, with explicit retry permission and remaining attempt
and circuit capacity. Terminal failures cannot authorize a new attempt.
Cancellation and persisted circuit/deadline stops remain fail closed.

Consumed pending attempts are conservatively reconstructed as circuit-qualifying
failures, preserving total attempts and existing backoff. This may stop sooner
than the original execution but never grants more retries. Version 1's refusal
to resume partially attempted pure work remains. Repeated verification/recovery
cannot reset consumed attempts or obtain fresh retry authority.

Verifier calls are finite: one per relevant effect during reconciliation, at most
100, and at most two per live reserved attempt. They are synchronous local
callbacks with remaining-time limits and post-call timeout checks. Verification
time is added to historical elapsed time and checkpointed before another
verification or any re-entry, including expected verification failure. Unexpected
programming defects propagate; the earlier reservation remains. Checkpoint
sequence capacity is checked conservatively for verification and remaining work.

Tool/provider/token counters are checked against current trusted limits and
carried unchanged. This lifecycle meters attempts and elapsed time, not tool,
provider, token, or monetary usage; verification does not fabricate resource
charges. These callbacks are intended for bounded local verification. A future
metered/billable adapter requires independent accounting and authorization.

`LifecycleRuntime.run` and `run_observed` still start fresh and accept no restored
progress or effect-authority parameters. The supported recovery API remains
`CheckpointedLifecycle.recover(request, restart_safe_work=...)`; its inputs cannot
supply restored state. Effect configuration is trusted application constructor
bootstrap. Private seams remain Python module conventions, not process isolation.

## Persistence compatibility

SQLite tables, transactions, append-only sequencing, workflow/thread binding,
connection ownership, schema version, and database `user_version` remain version 1.
Legacy `Checkpoint` state version 1 still requires empty effect slots and retains
its exact validation semantics. `EffectCheckpoint` state version 2 requires
bindings, committed claims, boundary, and stop reason; missing/unsupported fields
or versions fail closed. The store explicitly dispatches the two contracts.

Pure coordinators continue writing version 1. Effect coordinators start new
workflows with version 2; legacy histories cannot silently acquire effect semantics.
No migration, reset, deletion, pruning, or framework checkpointer is added.
Approval slots stay empty; Story 7 approval authority remains deferred.

## Verification and evidence

Run from `module-06-5` with its Python 3.12 environment:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest --basetemp <LOCAL_EVIDENCE_DIR>/module-06-5-story-6-slice-3/pytest-full-1
.\.venv\Scripts\python.exe -m compileall src tests
```

The new test file adds 57 cases. It exercises stable/scoped identities, strict
inert contracts, actual committed claims, normal once-only invocation, reservations,
all relevant simulated interruption/write windows, fresh and repeated recovery,
verified noncommitment, remaining/exhausted attempts, conservative circuit/backoff,
terminal controls, malformed/foreign/unavailable observations, unsafe reconstruction,
forged identities/claims/results, cancellation, elapsed/timeout/tighter-limit
checks, carried counters, corrupt latest data, legacy compatibility, unexpected
defects, unsupported fallback, and public API authority boundaries.

Policy assertions are deterministic evidence. Actual temporary checkpoint SQLite
files and an independently queryable second SQLite file provide local integration
evidence with a deterministic stand-in for an external effect system. Interruption
is injected in-process; there is no OS crash, power-loss, live-provider, paid
execution, or deployment evidence. Temporary files reside under parent
`TECHADEMY/EVIDENCE`, outside the repository.

Final verification on 2026-10-13 used Python 3.12.14: Ruff passed; full pytest
passed **603 cases** (546 existing plus 57 new) in 94.37 seconds; compileall of
`src` and `tests` passed. The full test run used the `pytest-full-1` evidence
directory shown above. `git diff --check -- module-06-5` passed, and nothing was
staged or committed. All accepted Slice 1/2 tests remain green.

Initial verification repairs addressed a missing evidence parent directory, a
module-local test import, safe import ordering, and formatting. No tests, safety
controls, requirements, or quality rules were weakened.

## Limits, readiness, and Slice 4 deferrals

Synchronous callbacks must terminate and honor timeout; checking late results does
not preempt Python or undo effects. Historical recorded execution/verification time
is consumed, but downtime and time lost in a process interruption are not measurable
without a trusted cross-process clock. SQLite data is unauthenticated plaintext;
forged reductions in historical counters cannot be detected. Pure result/plan-ID
and fallback-history limitations from Slice 2 remain. The verifier and bootstrap
must bind fixed inputs, permissions, accurate results, and quiescent observations.
Finite sequence exhaustion fails closed. No retention/HA/encryption claim is made.

Requirements: bounded Slice 3 implementation toward recovery requirements.
Product Experience: runnable explanatory tests; final reviewer interface deferred.
Real Functionality: actual local SQLite, deterministic effect-system stand-in.
Reliability: verified replay prevention and fail-closed failure cases.
Security: exact trusted identity reconciliation; no persisted authority restoration.
Cost: no network/credentials/paid calls; finite attempts/calls/time/data.
Evidence: deterministic and local integration only. Deployment: none.

Slice 4 retains the final integrated recovery lab, integrated recovery evidence,
requirement/deliverable acceptance reconciliation, and Story 6 closeout. This patch
does not implement Story 7 HITL, MCP, provider adapters, observability/cost dashboards,
final reviewer UI, release/deployment, or unrelated refactoring. Independent review
and later module production-readiness evaluation remain necessary.
