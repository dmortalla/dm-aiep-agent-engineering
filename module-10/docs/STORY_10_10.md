# Story 10.10 — Production Operations (operational readiness)

## Baseline and scope

Starting HEAD: `e2a01a3405aabd7510fe8fa0c27756ee5f16bea4` (the published
Step 410/412 documentation commit; Story 10.9 M2/M3 accepted and closed).
This story implements the authoritative definition in `docs/STORIES.md`:
"Exercise reliability, security, deployment checklist, incident response,
rollback, SLA/SLO reasoning, and cost engineering" as one outcome-sized
GCN/GROPE chunk (S10.10-C01), guided by the Step 413 discovery report
(SHA-256 `766505278e9d7b5fdb54a8b2da2cf73018a3b89b4e3b3d682fd8226e07e28847`).
No architecture change, no new dependency, no cloud contract change, no
recovery-stage implementation (RE-002+ remain planned), and no cloud or Git
operation.

## Repository implementation

Added `src/module10_ai/operations.py`, `scripts/operations_check.py`,
`tests/test_operations.py`, `docs/OPERATIONS.md` and this record. Updated
README, TRACEABILITY and STORIES with accurate Story 10.10 rows.

`module10_ai.operations` validates five minimized evidence registers
fail-closed: the deployment-readiness checklist (eight accepted M2 gate
items `passed` plus three carried-open items `open`; a carried-open item
reading anything other than `open` is `contradictory`), evidence-based
incident diagnostics (five
fixed scenarios with per-scenario observation allowlists and fixed read-only
guidance; unknown scenarios are `unsupported`), the data-only rollback plan
(accepted promotion-contract triggers, post-rollback checks, execution
authority, `deployment_authorized=false`, and `provenance_precondition` exactly
`unresolved`), the labeled SLO register (measured requires a bounded
measurement and a real source; proposed/illustrative must not carry one), and
the configuration-bounded cost register (verified↔observed-configuration,
assumption↔operator-judgment; monetary amounts are rejected fields; optional
bounded budget threshold). Every register: exact allowlists, type-strict,
bounded (32 KiB evidence, bounded counts/windows/text), tz-aware timestamps
parsed and echoed canonically, fixed sanitized errors with finite status
tokens, deterministic output (no clock reads), and no network, subprocess,
cloud, credential, or privileged operation. The CLI (`operations_check.py`)
is a thin deterministic checker with exit 0/1/2 semantics; authoritative
logic stays in the library.

Authority boundary enforced and tested: a validated rollback plan is not
authorized, performed, or successful rollback. A plan claiming deployment
authority is rejected as `incompatible`; the execution authority must equal
the accepted `ci/promotion.json` value; the unresolved provenance binding is
carried as an explicit precondition that a plan cannot claim resolved.

## Verification record

Focused gates: `python -m ruff check .` all checks passed; full
`python -m pytest` **1189 passed, 1 pre-existing Starlette warning** (1155
accepted + 34 operations cases); `python -m compileall -q src tests
scripts ui` exit 0. New tests cover: consistent/failed/contradictory
checklists, incompatible identity fields, missing items, unknown fields,
malformed timestamps; all five incident scenarios plus unsupported scenarios
and contradictory observations; rollback-plan conformance, authority-claim
rejection, trigger/check drift, provenance-claim rejection, wrong authority;
SLO label discipline (measured without measurement or with source `none`,
proposed with a fabricated measurement — all contradictory); cost
verified/assumption separation, mismatched basis, monetary-claim rejection;
byte-identical determinism; bounded-evidence reader failures; and real-CLI
success/failure paths including missing files.

### Independent-review corrections (Step 414.1)

The independent reviewer reproduced and corrected three defects in the
Builder candidate; the corrected bytes are what this record describes.

1. **Uncaught `RecursionError` in the evidence reader.** `json.loads` faults
   with `RecursionError` on a deeply nested document, and the reader caught
   only `UnicodeError`/`ValueError`, so a 32,000-byte in-bound artifact
   escaped as an unhandled fault: the CLI printed a Python traceback instead
   of a machine-readable report and disclosed local interpreter paths. The
   reader now rejects deep nesting as `malformed` with a fixed message, and
   the CLI reports it as JSON.
2. **A carried-open checklist item could be dropped.** An open item reading
   `failed` was neither a gate failure nor an unsupported completion claim,
   so it was omitted from the report while the checklist still reported
   `ready`. Carried-open items must now read `open`; anything else is
   `contradictory`.
3. **The CLI collapsed every load failure to `missing`.** Malformed and
   oversized evidence files were reported with the `missing` status token
   while their messages described malformed or oversized evidence. The reader
   now raises a typed `EvidenceError` carrying a finite status token
   (`missing` or `malformed`), matching the accepted M3 status semantics.

Four regression tests were added for these paths (34 operations cases in
total). No test, requirement, gate or security control was weakened, and no
file outside the approved eight-file scope was modified.

Offline demonstration exercised the real CLI against valid readiness
evidence (`ready`, exit 0, 8 gates + 3 open items), invalid/missing evidence
(fixed errors, exit 1), malformed and oversized evidence files (reported
with the `malformed` status token, exit 1), a conforming rollback plan
requiring human
authorization (`validated`, exit 0, `deployment_authorized=false`), and an
authority-claiming plan (rejected, exit 1). Simulated checks are OFFLINE
DETERMINISTIC evidence, never live-cloud evidence.

## Requirements mapping and evidence classification

| Requirement | Implementation | Evidence and limit |
|---|---|---|
| C-015 | Codified deployment-readiness checklist + offline validator | Checklist consistency vs accepted point-in-time gates; exercised offline; live checklist run not performed |
| C-016 | Incident scenario register + fixed read-only guidance; reuses accepted verifier/KQL surface for live diagnostics | Offline classification exercised; no live incident drill performed |
| C-017 | Data-only rollback-plan validator bound to `ci/promotion.json`; execution operator-gated | Plan validation exercised; ACTUAL ROLLBACK EXECUTION NOT VERIFIED |
| C-018 | Labeled SLO register enforcing measured/proposed/illustrative discipline | Register mechanism exercised; no live SLO measurement exists |
| C-012 (share) | Configuration-bounded cost register with budget-threshold field | No dollar amount asserted; no billing review performed |
| C-013 (share) | Reliability posture carried in incident guidance (saturation/deadline/readiness) | Accepted failure-path tests remain the reliability evidence base |
| C-014 (share) | Operational security carried by checklist gates and unchanged verifier boundaries | No new security surface; no audit claim |
| E-007/E-008/E-009/E-010/E-011/E-012 | Deterministic fail-closed validators, fixed errors, native gates, cost bounded, typed interfaces, tested failures | Covered by the new suite and unchanged accepted behavior |

Preserved verified limitations: M2 point-in-time Azure acceptance 8/8;
tested-source/cloud-image provenance UNRESOLVED (carried in the checklist and
as a rollback-plan precondition); actual rollback execution NOT VERIFIED;
C-026/C-027 DEFERRED to Story 10.11; full Module 10 completion NOT
ESTABLISHED. Live operational exercises (incident drills against the deployed
app, rollback execution, live SLO attainment) require fresh explicit human
authorization and an existing cloud footprint; the M2 authorization was
consumed by its run.

## Ordered completion assessment

Requirements: operational-readiness registers implemented and exercised
offline; live exercises remain human-gated. Product experience: one
deterministic CLI with five registers and machine-readable outcomes. Real
functionality: real validators against the accepted contracts; no simulated
cloud claim. Reliability: fail-closed on missing/malformed/contradictory/
unsupported evidence; deterministic outputs. Security: no privileged
operation anywhere; evidence never selects behavior; rollback authority
untouched. Cost: zero new footprint; registers assert no dollar amount.
Evidence: OFFLINE DETERMINISTIC / LOCAL VALIDATION only. Deployment: no cloud
operation, no Git write, no rollback execution. Independent review and
human acceptance remain the next acceptance-loop steps; no production-grade
completion claim is made.
