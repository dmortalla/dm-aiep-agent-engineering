# Story 6 Slice 4 — Integrated recovery lab and implementation evidence

## Scope and baseline

This slice composes the accepted Story 6 persistence, lifecycle recovery, and
committed-effect services. Accepted Slice 3 commit
`e7b1112bcef5c16925d3aad9ee347a3ff1bc61d3` was verified as an ancestor of HEAD.
There were no intervening Module 6.5 commits, no pre-existing tracked/untracked
module work, and no staged files. Protected Module 7/8, root, and scripts work
was preserved.

Only three files are added:

- `src/harness_engineering/recovery_lab.py`: module-local lab, fixed local
  application adapter, strict evidence contracts, and JSON CLI.
- `tests/test_recovery_lab.py`: 13 focused integrated cases.
- `docs/STORY_6_SLICE_4.md`: this implementation reconciliation.

Accepted Slice 1–3 source/tests, dependencies, frozen requirements, architecture,
ADRs, implementation plan, TRACEABILITY, and PROJECT_STATUS are unchanged.
The baseline traceability already adequately maps recovery source requirements;
this document adds implementation evidence without restructuring that baseline.

## Run and inspect

From `module-06-5`, using its Python 3.12 environment:

```powershell
$labDirectory = "E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-6-slice-4/run-$([guid]::NewGuid())"
.\.venv\Scripts\python.exe -m harness_engineering.recovery_lab --directory $labDirectory
```

No network, credentials, live provider, paid API, or manual database setup is
needed. The command creates a fresh directory and retains both SQLite files.
Existing directories are refused rather than cleaned, reused, or overwritten.
The library entry point is `run_recovery_lab(directory: Path) -> RecoveryLabEvidence`.
It returns strict immutable inert data suitable for a later presentation consumer.
The CLI prints that report as JSON; no Streamlit/UI framework is introduced.

Expected outcome: one local effect invocation and commit, zero replay, four local
verification calls, nine checkpoint snapshots, completed workflow, and three
fresh recoveries. Read `purpose`, `interruption_point`, `checkpoints`,
`recovery_passes`, `evidence_classes`, and `limitations` to interpret the result.

## Exact deterministic scenario

Trusted application bootstrap supplies explicit workflow/thread UUIDs, a three-step
accepted plan (`prepare` -> `deliver` -> `summarize`), and a fixed local delivery
specification. Fresh declarations independently derive the same SHA-256 effect
key from accepted namespace, operation, input digest, and workflow/thread identity.
Request text cannot choose the effect operation, key, permissions, or routing.

1. The real lifecycle completes pure `prepare` and persists checkpoint 1.
2. It durably reserves the first `deliver` attempt in checkpoint 2.
3. The fixed local adapter independently reopens the checkpoint store and observes
   that reservation before recording invocation. This proves ordering; history
   does not supply adapter permissions or nominate work.
4. The adapter commits the fixed result in the second SQLite file, closes its
   transaction/connection, and raises the dedicated `_InjectedInterruption`.
   The interruption is exactly after external local commit and before the effect
   callback returns or normal completion checkpointing occurs.
5. The lab constructs an entirely fresh application adapter, clock, plan,
   declaration, runtime, store, and coordinator over those two durable files.
6. The supported `CheckpointedLifecycle.recover` loads latest history, reconciles
   fresh trusted declarations/limits, independently verifies the local external
   effect, and reconstructs its validated result without invoking it again.
7. Only pure remaining `summarize` executes; the workflow completes.
8. Two further entirely fresh bootstraps recover the completed workflow. They
   verify commitment again and execute no effect or pure step.

The lab retains original object references solely to compare Python object
identity. Each reported `fresh_components` entry is derived from `is not`
comparisons against **every earlier bootstrap**, rather than a hard-coded claim.
No raw executable object or Python object ID is serialized into the report.
Distinct clock origins (0, 1000, 2000, 3000 seconds) demonstrate that restoration
consumes recorded time despite reconstruction of invocation-local objects.

## Durable artifacts and observed evidence

`checkpoints.sqlite` is owned by the accepted `SQLiteCheckpointStore`: workflow
binding, append-only history, database/schema version 1, explicit effect state
version 2. The lab adds no recovery store, migration, reset, or pruning behavior.

`local-effect.sqlite` is a deterministic stand-in for an external effect system:

- `effects` contains the stable key, exact inert identity, and fixed committed result.
- `invocations` records every adapter invocation and the already-visible reservation
  sequence/attempt count, independently of the effect commit.
- `verifications` records each query and its observation category.

The verifier validates the exact trusted identity and expected fixed result from
this second file; malformed/inconsistent external state yields `unknown` and the
accepted coordinator fails closed. A local absence is conclusive because this
fixture is synchronous, quiescent, and has no background worker that could commit
later. This property must not be generalized to eventual-consistency providers.

| Sequence | Boundary | Completed / pending | Recorded elapsed ms |
| --- | --- | --- | ---: |
| 1 | step_completed | prepare / deliver, summarize | 500 |
| 2 | attempt_reserved | prepare / deliver, summarize | 500 |
| 3 | attempt_reserved | Same prefix; recovery verification time charged | 625 |
| 4 | step_completed | prepare, deliver / summarize; verified effect claim recorded | 625 |
| 5 | step_completed | All three completed / none | 1125 |
| 6–7 | step_completed | First repeat: reverified, no work replayed | 1250 |
| 8–9 | step_completed | Second repeat: reverified, no work replayed | 1375 |

There is one `invocations` row pointing to reservation sequence 2, one `effects`
row, and four observations: `not_committed`, then three `committed` results.
Every final runtime reports three consumed attempts, with one attempt for each
step; the interrupted effect attempt is not reset or incremented on verified skip.
The first recovery executes only `summarize`; repeated recovery executes nothing.

Time values come from an explicitly labeled **injected deterministic monotonic
clock**, not measured wall-clock latency. The five-second trusted deadline remains
five seconds, with reported remaining time 3.875, 3.750, and 3.625 seconds after
successive recoveries. The 500 ms historical consumption remains consumed;
verification adds 125 ms per recovery. Time spent inside the interrupted call
and downtime are not recoverable with the accepted clock contract.
Tool/provider/token counters remain zero: this lifecycle does not meter those
resources, and verification does not invent accounting claims. The lab performs
no provider/tool execution, and trusted tool/provider limits are set to zero.

## Integrated failure evidence

`tests/test_recovery_lab.py` adds 13 cases across the complete lab composition:

- Entire happy path, durable audit/history inspection, fresh object comparisons,
  remaining safe work, repeated duplicate prevention, and result reconstruction.
- Equivalent structured evidence from two independent artifact directories,
  excluding their intentionally different filesystem locations.
- CLI output, strict JSON round trip, rejected extra authority fields, and rejected
  contradictory success evidence.
- Existing artifact preservation without automatic cleanup.
- Ambiguous/inconsistent external verification: no replay or remaining safe work.
- Corrupt latest checkpoint 2: checkpoint 1 still exists but is never substituted.
- Fresh trusted effect identity mismatch: refusal before verification/execution.
- Cancelled, circuit-open, and deadline-exhausted histories: non-resumable.
- A noncommitted interrupted action with no remaining retry authority: no replay,
  and its consumed attempt remains recorded.
- A committed interrupted action with no replay attempt remaining: verified
  reconstruction is allowed without invocation or new retry authority.
- Unexpected programming defects propagate rather than being hidden/retried.

The accepted Slice 1–3 suites additionally cover schema/version validation,
transactions, resource closure, malformed observations, forged results/claims,
tighter bounds, deadline/budget/cancellation preservation, backoff/circuit state,
public fresh-start authority boundaries, and further interruption/write windows.
Those tests and controls are preserved rather than copied into this suite.

## Story 6 requirement reconciliation

This is implementation-level evidence, not formal acceptance or release.

| Requirement | Accepted implementation and executable evidence | Determination |
| --- | --- | --- |
| REQ-REC-001 — Execution state is persistable | `persistence.py`, temporary SQLite round trips in `test_persistence.py`, and all nine lab snapshots independently read from disk | Satisfied for Story 6 implementation |
| REQ-REC-002 — Snapshots/checkpoints | `CheckpointedLifecycle` boundary writes, lifecycle observation, lab checkpoint 1 and pre-invocation reservation 2; `test_recovery.py` and complete-lab test | Satisfied |
| REQ-REC-003 — Interrupted execution recovery/resume | Accepted coordinator loads/reconciles latest history; fresh runtime/store/application objects restore completed work and run only remaining safe work; complete-lab and fail-closed integration tests | Satisfied with explicitly injected Python interruption evidence |
| REQ-REC-004 — Idempotent re-entry | Stable trusted identity, independent effect verification/reconstruction, retained attempts, zero invocation delta on three recoveries; `test_effect_recovery.py` plus integrated lab | Satisfied in the accepted local verification/adapter contract |
| REQ-DEL-002 — Checkpointing & recovery system | Accepted persistence/recovery/effect/lifecycle services plus runnable integrated lab and structured evidence | Implementation deliverable present |
| REQ-LAB-004 — Checkpointed agent with crash recovery/resume | Credential-free module CLI and library composition through real local LangGraph lifecycle and actual SQLite, with explicit interruption/reconstruction boundaries | Lab implementation present and demonstrated |

The authoritative source is `AUTHORITATIVE_SOURCE.md` (Checkpointing, Resume &
State Recovery, hands-on lab 4, and checkpointing & recovery deliverable).
Frozen `REQUIREMENTS.md`, `ARCHITECTURE.md` recovery model/invariant, and Story 6
of `IMPLEMENTATION_PLAN.md` establish the reconciliation above.

| Additive engineering requirement | Story 6 evidence and scope |
| --- | --- |
| ENG-001 | Runnable self-explanatory CLI/library report for this lab; the completed module's final Streamlit reviewer UI remains Story 11 work |
| ENG-002 | Accepted strict historical/observation validation, trusted identity/result reconciliation, inconsistent external-state and corrupt-history refusals |
| ENG-003 | Bootstrap fixes work/limits/callbacks; persisted/external claims and report fields cannot grant authority; strict output rejects authority extras |
| ENG-004 | Accepted finite attempts/backoff/circuit/deadline checks; fixed three steps and three recoveries, bounded SQLite lock waits, fixed synchronous local adapter |
| ENG-005 | All normal lab/test paths are local, deterministic, credential-free, and incur no paid API execution |
| ENG-006 | Report explicitly labels deterministic/local integration, injected clock/interruption, and limitations; no live/deployment claims |
| ENG-007 | Existing Story 6 failure/adversarial suites plus focused integrated fail-closed scenarios |

No unrelated future requirement is marked complete by this reconciliation.

## Authority, limitations, and readiness

Persisted data remains historical evidence. The lab calls the supported store-backed
coordinator; it does not supply fabricated restored progress or call private runtime
resume/execution seams. Trusted declarations are rebuilt independently, never
loaded from SQLite. Possession of an effect identity alone grants no execution.
Local adapter scope is fixed by bootstrap, with no external capability or secret.
No generated input can change work, permissions, limits, fallback, or approval.

Demonstrated: deterministic behavior, actual SQLite integration, application-owned
recovery, injected Python interruption, fresh-object reconstruction, independent
local effect verification, safe resume, consumed-state preservation, and duplicate
prevention in this specific deterministic adapter/lab.

Not demonstrated: OS process crash, host/power loss, distributed transaction,
universal exactly-once external delivery, cross-process lease, live provider
behavior, deployment durability, or production readiness. No process termination
or external provider is involved. SQLite files remain unauthenticated plaintext;
the accepted verifier/bootstrap and quiescent-observation obligations remain.
Synchronous callbacks must cooperate with timeouts; the lab does not preempt them.
No retention/HA/encryption/operational durability capability is added.

Readiness evaluation in repository order:

- Requirements: Story 6 implementation evidence reconciled above.
- Product Experience: runnable CLI with structured explanatory evidence; final UI deferred.
- Real Functionality: accepted real local lifecycle/SQLite; external effect is a local stand-in.
- Reliability: integrated recovery and fail-closed tests; no OS/power-loss evidence.
- Security: accepted authority boundaries preserved; no new privileged capability.
- Cost: deterministic local execution, no network/credentials/paid API path.
- Evidence: deterministic and local integration only, with explicit non-claims.
- Deployment: no deployment evidence or release claim.

Story 6's **implementation contract and exit criterion are satisfied** within the
accepted deterministic/local scope: the lab visibly demonstrates interruption,
persisted checkpoint, fresh restart/reconstruction, safe resume, and prevention of
duplicate committed effects. It is implementation-complete and ready for independent
acceptance and administrative closeout. This document does not formally accept,
release, or commit Story 6.

Remaining administrative work: independent patch/source-conformance review,
human acceptance decision, authorized staging/commit, and any later explicitly
authorized PROJECT_STATUS/repository closeout bookkeeping. Story 7 HITL, MCP,
provider adapters, observability/cost dashboards, Story 11 regression/final UI,
and module release/deployment remain separate future work.

## Quality gates

Use the module-local Python 3.12 environment, safe Ruff fixes only, and fail-fast:

```powershell
.\.venv\Scripts\ruff.exe check . --fix
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest --basetemp E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-6-slice-4/pytest-full-1
.\.venv\Scripts\python.exe -m compileall src tests
```

Use a fresh `--basetemp` for each subsequent run. Temporary SQLite files, JSON
captures, and review evidence belong under parent TECHADEMY/EVIDENCE, not in the
repository. The patch remains unstaged and uncommitted for independent review.

Final verification on 2026-10-13, using the module-local Python 3.12.14 environment:

- Safe `ruff check . --fix`: passed; `ruff check .`: passed.
- Focused integration suite: **13 passed**.
- Full suite: **616 passed** (603 accepted cases plus 13 new), in 149.55 seconds.
- `python -m compileall src tests`: passed.
- Final CLI execution: one invocation, one commit, zero replay, four verifications,
  sequences 1�9, and recovery elapsed readings 1125/1250/1375 ms.
- Captured reviewer JSON: parent
  `EVIDENCE/module-06-5-story-6-slice-4/lab-final.json`.
- Retained CLI databases: parent
  `EVIDENCE/module-06-5-story-6-slice-4/lab-final/checkpoints.sqlite` and
  `EVIDENCE/module-06-5-story-6-slice-4/lab-final/local-effect.sqlite`.
- Full test temporary artifacts: parent
  `EVIDENCE/module-06-5-story-6-slice-4/pytest-full-1`.

Initial repairs were safe import ordering and formatting of new files. No test,
accepted source, security control, requirement, or quality rule was weakened.
The final module status contains only these three new untracked files; the index
is empty and no commit was created. Protected background work remains present.
