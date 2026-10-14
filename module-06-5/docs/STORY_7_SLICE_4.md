# Story 7 Slice 4 — integrated application-owned HITL lab

This additive final implementation slice supplies deterministic, credential-free
programmatic lab evidence for REQ-HITL-001–003, REQ-LAB-005 and REQ-DEL-003.
It is ready for independent review once the verification below passes; it does
not declare Story 7 formally accepted or the module production-ready.

## Accepted baseline and scope

Accepted Slice 3 commit: `4206090ceac2938e1108effaf0b44507bbfb782c`.
Preflight HEAD: `01359b9b8a02f97bb08563ee5e74e1f26cadc5cc`.
The accepted commit was an ancestor, no later commit touched Module 6.5,
there were no tracked Module 6.5 modifications and the index was empty.
Concurrent root and other-module work was protected.

Only three files are added: `approval_lab.py`, `test_approval_lab.py`, and this
document. Accepted implementation, architecture, dependencies, requirements,
traceability, authority policy and project status remain untouched.

## Run and inspect

From the Module 6.5 directory:

```powershell
.venv\Scripts\python.exe -m harness_engineering.approval_lab --directory E:\ONEDRIVE-PERSONAL\TECHADEMY\EVIDENCE\approval-lab-fresh
```

Choose a new directory. The lab refuses existing directories, retains separate
checkpoint and approval SQLite files for each scenario and prints an immutable
JSON report. `run_scenario(directory, scenario)` runs one scenario;
`run_approval_lab(directory)` runs the finite 48-scenario matrix. No API keys,
network access, paid calls, polling or human-blocking transactions are needed.
The injected human wait advances a trusted workflow-age source by 30 seconds.

## Real integrated journey

The safe `prepare` prefix executes through the accepted compiled LangGraph.
At `protected`, the real policy evaluator requires approval, the accepted
checkpoint coordinator writes the durable prefix, and the real approval store
records PENDING. An inert `SuspendedWorkflow` returns without protected work.
The lab deletes the original lifecycle, runs collection and verifies its weak
reference is cleared. Fresh local handles are independently installed; a newly
constructed store and evaluator record the exact decision. A fresh lifecycle,
compiled graph, checkpoint store and approval store explicitly resume through
accepted reconciliation, current safety checks and one-time consumption.

Actual graph callbacks count execute-node entry (matching both node metadata
and callback name, avoiding inherited metadata false positives). Instrumentation
delegates to the original compiled graph invocation. The protected local adapter
reads the real approval store at entry: valid approved and overridden journeys
must observe CONSUMED before recording execution. Completion must be the actual
COMPLETED phase, with checkpoint work complete and PENDING → APPROVED/OVERRIDDEN
→ CONSUMED audit sequences 1, 2, 3. Framework checkpointer is absent.

Inspection transforms bounded accepted history and checkpoints into inert data:
exact workflow/thread/action/version, status, confidence, threshold, trigger
reasons, risk/escalation, checkpoint sequence, audit sequences/statuses,
completed/pending work, decision kind/evidence/override reason, and charged age.
No human handles, callbacks, route selectors or execution permits enter reports.
Authoritative history stays in the accepted store. Corrupt injected histories
have no invented final inspection; their report preserves the valid pre-attack
snapshot and rejection type.

## Journeys and adversarial coverage

* Ordinary approve: confidence 0.5 escalates; independent approval and fresh
  resume execute once after consumption.
* Deny: independent denial remains terminal after reconstruction. Later approve
  and override reject. Retry and fallback are configured (including trusted
  failure classifications if entry were possible), but denial prevents callback
  entry entirely. Recovery with a loosened confidence/risk policy also rejects.
* Override: a separately installed override handle accepts ordinary low
  confidence with durable rationale; ordinary approver override and blocklisted
  hard-invariant override reject. Resume rechecks installed authority.
* Threshold: below 0.80 requires approval; exactly 0.80 with no independent
  trigger executes without it; 0.99 still escalates independently for each of
  consequential action, privileged scope, configured risk and escalation.
* Authority: unauthorized, requester self, copied, deserialized, missing,
  model/agent/untrusted identity-shaped values reject. A new handle made from
  the actual persisted approving principal text cannot authorize resume.
* Binding/data: stale version, wrong workflow/thread/action, action A intent
  targeting B and forged approval-shaped dictionaries reject against real
  pending state. Binding mutations are decision attacks, not fabricated histories.
* Current controls: revoked approver, tightened threshold, cancellation source,
  explicitly latched off-switch, hard budget, total deadline including human
  wait, removed scope and action/capability blocklists reject before execution.
* Replay: repeated decision rejects; consumed approval cannot authorize fresh
  resume. Two actual concurrent fresh contenders are tested separately against
  the shared real stores; at most one may execute. A conflict may reject both;
  no concurrency availability guarantee is claimed.
* Untrusted continuation: Command-shaped dictionaries and actual framework
  Command objects (negative test only), and suspended objects reject as input.
  No native framework resume mechanism is invoked.
* Persisted callback, permission and route fields are injected into real local
  SQLite payloads; accepted schema validation rejects them, without dispatch.
* Crash: an injected safety-source interruption occurs at the next gate check
  after committed consumption and before protected adapter entry. Fresh resume
  rejects the consumed record. The lab also runs consumed/competing replay
  variants; they share this deliberate ambiguous-boundary construction.

All invalid paths retain zero protected executions. The report does not treat
expected rejection as an independently persisted rejection audit event: accepted
history records requests, decisions and consumption only. Unexpected defects
propagate; only expected HarnessError and the named interruption are caught.

## Evidence and limits

Classification: **deterministic_fixture + local_integration**. Real local
SQLite, accepted policy, checkpoint/recovery and genuine LangGraph orchestration
are exercised; task outputs, clocks, local identities and faults are fixtures.

No authentication/IdP, native LangGraph interrupt or Command-resume HITL,
framework checkpointer authority, exactly-once execution, atomic consumption
with external effects, forced synchronous callback termination, coherent external
database rewrite protection, live-provider evidence or deployment evidence is
claimed. Crash evidence is a Python interruption, not OS termination/power loss.
No Story 8 MCP, Story 9 provider/guardrail, Story 10 dashboard or Story 11 final
reviewer UI/regression implementation is included.

Requirements have integrated local evidence; product experience is a programmatic
lab and JSON CLI, with final reviewer UI deferred. Real functionality is local
integration; reliability and security include denial, replay, crash and contention
evidence within accepted limits. Cost is zero external calls with finite scenarios,
two tasks per scenario and bounded evidence/history. Evidence remains explicitly
classified. Deployment and production identity/durability remain unproven.

## Verification

The final fail-fast sequence passed: `.venv\Scripts\ruff.exe check .` reported
`All checks passed!`; `.venv\Scripts\python.exe -m pytest` reported **963 passed
in 348.68 seconds**; `.venv\Scripts\python.exe -m compileall src tests` exited 0.
Full-suite temporary state used the fresh parent evidence directory
`E:\ONEDRIVE-PERSONAL\TECHADEMY\EVIDENCE\s7s4-full-20261014a`.
The initial focused run passed 54 tests in 124.51 seconds; the full run also
validated the final refinements to persisted identity, off-switch and denial paths.
Only mechanical safe Ruff import repair and formatting were used; no unsafe fixes.

The accepted 909 tests are preserved; **54 tests are added**. They exercise the 48 scenarios plus
threshold/override details, immutable bounded authority-free serialization,
actual Command rejection, concurrent resume, directory isolation and unexpected
defect propagation. No accepted implementation or architecture defect has been
identified during lab integration. Changes remain unstaged and uncommitted.

Final HEAD: `e16cb6ed122f3a2faa599eb1142e97b24e9dc2c5`. Concurrent commits
advanced HEAD, but accepted Slice 3 ancestry still passed and no intervening
commit touched Module 6.5. Final tracked Module 6.5 diff and index were empty;
only the three Slice 4 files were untracked within the module. Protected concurrent
untracked paths were `.editorconfig`, `.gitattributes`, `scripts/`, and
`module-07/docs/stories/STORY-03-reliability-recovery-boundary.md`.
