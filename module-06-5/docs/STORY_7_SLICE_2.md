# Story 7 Slice 2 — Durable approval persistence

Authority: frozen Module 6.5 requirements/architecture and the human-approved
`STORY_7_AUTHORITY_POLICY.md`. Starting HEAD is accepted Slice 1 commit
`0c0e260d13737c92b5c7a090879dba7ef7cbe4bd`; ancestry passed with no intervening
Module 6.5 commits, tracked Module 6.5 edits, or staged content. Existing Module 7,
Module 8, and root background work is protected and outside this patch.

Only `src/harness_engineering/approval_persistence.py`,
`tests/test_approval_persistence.py`, and this document are added. Accepted source,
checkpoint schemas, dependency files, frozen documents, PROJECT_STATUS, and other
modules are unchanged. No migration or incompatible accepted-schema change is
required.

## Small application-owned store

`SQLiteApprovalStore` uses a **dedicated local approval database file**. It reuses
Story 6's persistence error hierarchy and conventions: immutable revalidated data,
versioned canonical JSON, parameterized values, bounded reads, one-second SQLite
lock wait, explicit transactions, and connection closure on every path. It does
not populate the checkpoint approval placeholders or adopt a checkpoint database.
Tests verify attempted adoption leaves an accepted checkpoint database unchanged.

SQLite application_id identifies this database format; user_version and event
schema/state versions are 1. These are format markers, not authentication. Empty
new databases are initialized; foreign, unsupported, missing, or altered schemas
fail rather than being migrated/reset. Metadata is checked on every operation.

Two tables hold one stable thread binding per workflow and append-only audit
events keyed by workflow, pending action, and consecutive sequence. The exact
workflow/thread/action/version binding is present in every payload and checked
against row data, expected caller identity, and the complete bounded history.
There is no public update/delete/import/reset-authority operation.

## Transitions and audit

| Operation | Required prior state | Durable event/result |
| --- | --- | --- |
| `request` | Absent or still pending with a strictly newer version | PENDING, including full request metadata, confidence/evidence, evaluated threshold and all approval reasons |
| `decide` | Exact current PENDING | APPROVED, DENIED, or OVERRIDDEN, including checked decision, approver audit identifier, binding, bounded evidence and explicit override reason |
| `consume` | Exact current APPROVED or OVERRIDDEN | CONSUMED, appended atomically once, retaining the decision and current policy assessment |
| `load` / `audit` | Exact current expected binding | Validated inert history or bounded ordered page; no authority is minted |

Duplicate requests/decisions, regressed/stale versions, conflicting decisions,
and repeat consumption fail closed. Pending revisions invalidate older bindings.
A decided logical action cannot be revised, reopened, or replaced through this
API. This conservative boundary also prevents a version bump from bypassing
denial or consumption; genuinely new application-approved work needs a new pending
action identity. Audit retains superseded pending revisions in sequence order.

DENIED explicitly terminalizes the action in the same append transaction as the
decision. It cannot be consumed, approved, overridden, resubmitted, or revised
after restart, even if a caller supplies `prior_denial=False`. History exposes
`prior_denial` for later integration with accepted Slice 1 semantics; no retry or
fallback operation exists here.

## Trust, current authority, and consumption

`decide` accepts human intent plus the current application-owned Slice 1 evaluator,
installed human handle, and current safety facts. It invokes `check_decision`
**inside BEGIN IMMEDIATE** and compares the resulting request metadata with the
durable pending request before appending. A raw dictionary, serialized assessment,
or assessment-shaped object cannot bypass validation through a save/import API.
The store does not choose approval/override authority itself.

`consume` reads authoritative consumption/denial state from this store under
BEGIN IMMEDIATE, then rechecks the historical intent against current Slice 1
policy, installed actor, exact metadata/binding, and hard safety facts. The current
actor must be authorized and match the recorded approving/overriding principal.
Revocation, mismatches, blocklists, cancellation, invalid binding/authority,
exhausted hard budgets/deadlines, scope denial, and prior denial all prevent the
append. Historical thresholds/reasons never select current policy. Override stays
explicit; ordinary approval cannot confer override authority.

No deserializer constructs HumanIdentity handles. Loaded approver identifiers are
audit text only. A matching copied/deserialized identity fails against the current
Slice 1 allowlist. Trusted application bootstrap must independently install a
current local handle; this is neither real human authentication nor evidence of
fresh human interaction after restart.

SQLite serializes the read/check/append/commit transition across competing local
connections. The successful call returns only after commit. A second consumer
sees CONSUMED and fails. Insert/commit failure rolls back and returns no successful
assessment. Unexpected Python defects propagate, with rollback/closure, rather
than becoming authorization success.

Consumption is an at-most-once **store transition**, not atomic execution of a
tool or external effect. Crash after consumption commit but before work begins
leaves consumption terminal; this slice supplies no automatic re-execution. It
also does not atomically couple a checkpoint, approval database, and external
effect. Later lifecycle/recovery design must handle that boundary explicitly.

## Corruption and bounds

Reads validate every event in the bounded action history before returning even a
one-event audit page. Unsupported versions, duplicate JSON keys, missing/defaulted
fields, extra/executable authority fields, malformed JSON, oversized payloads,
row/payload mismatch, inconsistent approval reasons, event/decision/override-kind
conflicts, self-approval claims, missing workflow binding, sequence gaps,
duplicate/conflicting decisions, and impossible consumption fail closed.
Altered table definitions are rejected without silently repairing them.

Limits: 32 pending revisions plus one decision and one consumption (34 events per
logical action); 65,536 serialized bytes per event; existing Slice 1 identifier,
version, and 2,000-character evidence bounds. Reads fetch at most 35 rows to detect
overflow, and oversized SQLite payloads are withheld before Python decoding.
Audit cursor and page size are strict bounded integers. Reads never enumerate
all workflows. Total workflow count/database size and retention remain operational
concerns; there is no cleanup/retention service in this slice.

Append-only semantics apply to application APIs. Format and consistency checks
cannot authenticate a database or detect every coordinated external rewrite,
valid-looking forged history, wholesale deletion, or truncation of a valid prefix.
No cryptographic tamper resistance, encryption, database authentication, OS
isolation, distributed/HA safety, or production database security is claimed.
Configured-risk reasons remain historical policy evidence; current evaluation
recomputes policy rather than trusting the old configured risk set. Keep credentials
and sensitive values out of plaintext audit evidence.

## Evidence and deferred scope

Focused tests provide deterministic authority/corruption evidence and local
integration evidence using actual temporary SQLite files, reopened stores,
competing local connections, and injected insert/commit failures. They need no
credentials, network, external services, paid calls, or other-module imports.
Quality gates run from Module 6.5: Ruff, pytest, then compileall of src/tests.
Temporary databases use fresh directories under parent TECHADEMY/EVIDENCE.

Verification on 2026-10-14 with Python 3.12.14: Ruff passed; focused persistence
tests **89 passed**; full pytest **839 passed, 0 failed** (750 accepted cases plus
89 new cases), in 203.77 seconds; compileall of `src` and `tests` passed. The full
run used parent `EVIDENCE/module-06-5-story-7-slice-2/pytest-full-1`. Safe repairs
were formatting and shortening two overlong docstring lines after the initial
Ruff failure. No unsafe fixes, weakened tests/rules, or environment/dependency
configuration changes were used. Accepted Story 6 and Slice 1 tests remain green.

Asynchronous workflow suspension/resume, LangGraph interruption, runtime/tool
execution integration, checkpoint approval embedding, durable rejection-event
logging, final HITL lab/UI, provider/identity services, deployment, and Slice 3
remain deferred. Rejection calls fail without appending, keeping history bounded.
Neither Story 7 completion nor production readiness is claimed.

Requirements: persistence foundation for REQ-HITL-001 through 003 and later
REQ-DEL-003/REQ-LAB-005. Product Experience: focused runnable tests; lab/UI deferred.
Real Functionality: local SQLite requests, decisions, audit, denial, consumption.
Reliability: restart, transactions, limits, and failure paths tested; workflow
integration deferred. Security: current Slice 1 authority plus inert history and
exact binding. Cost: no paid execution. Evidence: deterministic/local integration.
Deployment: none. No frozen-policy or architecture conflict was discovered.
