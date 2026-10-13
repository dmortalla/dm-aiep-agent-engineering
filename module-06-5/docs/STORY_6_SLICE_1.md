# Story 6 Slice 1 — Persistence contracts and local SQLite

This slice establishes persistence toward REQ-REC-001/002 and the later
REQ-REC-003/004, REQ-DEL-002, and REQ-LAB-004 recovery deliverables. It does
not complete Story 6 or certify production readiness. The approved architecture
and ADR 001 govern; the architecture's residual PROPOSED footer is superseded
by its approved status, accepted ADR, and the explicit Slice 1 instruction.

## Contracts and lookup

`src/harness_engineering/persistence.py` owns immutable, recursively revalidated
Pydantic contracts. Schema and state versions are application constants, both 1.
Every checkpoint field is required. Workflow/thread UUIDs have no generated
defaults. A workflow binds to one thread; a different thread fails closed.
Separate workflows remain separate even when sharing a database.

A checkpoint records ordered completed work and result text, ordered pending
work references, consumed budgets, retry attempts, cancellation data, and required
empty approval/committed-effect slots. Work references are unique across completed
and pending work, total at most 100. Retry references are unique and must refer
to recorded work. Attempts are 0–3, consumption counters 0–1,000,000, references
1–128 characters, and result text at most 4096 characters. These are storage
bounds, not authorization to spend or execute. Payloads are limited to 1 MiB.

Caller-assigned sequences are integers 1–1000. Save appends only a greater
sequence; duplicate saves, overwrites, and regression fail explicitly. Gaps are
allowed. Exact lookup selects the requested sequence; latest selects the greatest
sequence, independent of timestamps and insertion timing. A corrupt latest record
fails rather than silently falling back. Missing lookup raises
`CheckpointNotFoundError`; other expected failures raise `PersistenceError` with
causes preserved at validation and SQLite boundaries. There is no migration,
automatic reset, delete, pruning, or replacement operation.

JSON serialization sorts object keys with fixed separators, preserves array order,
and uses no arbitrary-code deserializer. Duplicate JSON keys, unknown fields,
missing fields, invalid scalar types, unsupported versions, conflicting work,
row/payload identity or sequence disagreement, missing bindings, and ambiguous
lookup are rejected. Strict JSON UUID parsing is deliberate; Python constructors
require UUID objects. Save revalidates even bypass-constructed/copied models.

## SQLite behavior

The store takes an application-selected local file Path. It opens one connection
per operation, enables foreign keys, and closes the connection on both success
and failure. Initialization and saves use explicit BEGIN IMMEDIATE transactions.
Identity binding and checkpoint insertion commit together or roll back together.
Reads use a transaction for a consistent binding/record view. Database user_version
is checked at initialization and each save/load. Lock wait is bounded to one second;
storage errors do not retry application execution. SQL values are parameterized.

The two tables store workflow/thread binding and workflow/sequence-keyed snapshots.
No LangGraph checkpointer, new dependency, lifecycle integration, or provider is
needed. SQLite transaction evidence does not establish process-crash durability,
distributed safety, encryption, database HA, or OS isolation. Retention and total
database size remain application operational concerns; this slice has no janitor.

## Authority boundary

Loaded data is structurally validated historical data, not authenticated truth or
usable runtime authority. No API converts it into execution state or performs
work. Result text and work IDs cannot select nodes, callbacks, tools, permissions,
or bootstrap configuration. Consumed-budget data contains no resource limits,
retry policy, deadline extension, or cancellation reset operation. Nonempty
approval/effect records are rejected rather than interpreting Story 7 semantics
or pretending to verify committed effects. Adding those records later requires
explicit contracts and application verification.

A local database writer can forge structurally valid data. Future recovery must
reconcile snapshots against trusted plans, policies, time/cancellation sources,
approval evidence, and effect records before any re-entry. This slice neither
authenticates snapshots nor makes its cancellation/result counters authoritative.
Store no credentials or sensitive text: payloads are plain local SQLite data.

## Evidence and reviewer entry point

Run from `module-06-5` using the Python 3.12 environment:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall src tests
```

`tests/test_persistence.py` is the runnable reviewer interface for this foundation.
Contract assertions provide deterministic evidence. Actual temporary SQLite files,
reopened stores, parameterized hostile text, failure-injected transactions, and
closed-connection assertions provide local-integration evidence. Normal tests need
no network, credentials, hosted services, or paid execution. When sandbox temp
creation fails, use a fresh `--basetemp` directory under parent TECHADEMY/EVIDENCE;
temporary databases and diagnostic captures do not belong in this repository.

Coverage includes round trips and canonical serialization; latest/exact/missing
lookup; versions and required fields; identity binding and record mismatch;
malformed/deep/oversized/duplicate-key JSON; extra authority fields and forged
models; hostile SQL-shaped data; sequence conflicts; ambiguity; rollback of both
binding and snapshot on injected failure; resource closure; invalid database
version/path; and invalid lookup sequences.

Verification on 2026-10-13: Ruff passed; pytest passed all 508 cases (439 existing
plus 69 Slice 1 cases); compileall of src and tests passed, using Python 3.12.14.
The successful full run used fresh temporary storage at parent
`EVIDENCE/module-06-5-story-6-slice-1/pytest-final-1`. Repairs were a safe import fix, formatting,
short explicit IDs for large test payloads on Windows, and using python -m pytest
with the policy-required evidence location after launcher/default-temp failures.
No test expectation, dependency, or quality rule was weakened.

## Deferred work and readiness evaluation

Lifecycle checkpoint integration, automatic graph snapshots, crash/restart
orchestration, resume, effect verification/replay prevention, idempotent re-entry,
LangGraph checkpointer integration, Story 7 HITL, MCP, provider adapters,
observability/cost, final Streamlit UI, Story 11/12, and deployment remain deferred.
PROJECT_STATUS, frozen requirements/architecture, dependencies, existing runtime,
and other modules are unchanged.

Requirements: Slice 1 foundation only. Product Experience: runnable tests explain
storage behavior; final UI deferred. Real Functionality: actual local SQLite.
Reliability: transactions, validation, conflicts, and resource failures tested;
crash recovery deferred. Security: data-only contracts, no authority restoration;
no authentication/encryption claim. Cost: no paid calls, bounded payload/work and
lock wait. Evidence: deterministic and local integration only. Deployment: none.
Independent review and later Story 6 recovery evidence remain required.
