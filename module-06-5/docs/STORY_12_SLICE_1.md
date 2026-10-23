# Story 12 Slice 1: Composed story board (deterministic composed harness demonstration)

Adds `src/harness_engineering/story_board.py` and
`tests/test_story_board.py` — a bounded end-to-end composed demonstration that
executes the accepted Story 2–11 services and labs in one deterministic,
credential-free run and prints sanitized JSON evidence. This slice does not
implement Story 12 release reconciliation, does not update TRACEABILITY or
PROJECT_STATUS, does not touch the reviewer interface, and does not modify any
accepted implementation, dependency or lockfile file. Nothing is staged or
committed by this slice.

## Baseline and authority

Module 6.5 baseline: accepted Story 11 closeout at `3c4e410`
(`docs(module-06-5): close story 11 evaluation and reviewer UI`). HEAD is
`85dcd4d` (`fix(module-10): isolate RBAC reads from CLI defaults`), which
touches only module-10 and is foreign to this candidate. Verified before
mutation: `3c4e410` is an ancestor of HEAD; module-06-5 is clean against HEAD;
the Story 12 candidate files are new and no accepted module-06-5
implementation, test, dependency or lockfile file is modified. Foreign untracked
work (module-07 candidate files, root `.editorconfig`, `.gitattributes`,
`scripts/`) remains outside the candidate and was not modified or staged.

Read before mutation: AUTHORITATIVE_SOURCE (composed lifecycle, dedicated
services, labs, deliverables), REQUIREMENTS, frozen ARCHITECTURE (workflow
assembly, plan/adapt dimension, module lab narrative), ADR 001,
IMPLEMENTATION_PLAN Story 12 (module narrative composition; primary entry
`harness_engineering`), accepted STORY_11_SLICE_3 closeout, and the accepted
lab implementations this slice composes.

## What is composed

`story_board(directory)` runs four disjoint segments against one fresh
artifact directory (`mkdir(exist_ok=False)` fail-closed), each with its own
fixed `WorkflowIdentity`/`CheckpointIdentity` (series 0xA65001–0xA6500A), then
validates a strict `StoryBoardEvidence` model:

1. **Deterministic governed workflow (core identity)** — PlanningEngine
   decompose, PriorityScheduler deterministic order and dependency-ready
   admission, ContextManager construction/compression/memory routing,
   CapabilityRegistry selection vs independent CapabilityAuthorizer outcomes
   (allow, scope denial, approval-required with matching grant, no-grant
   denial), BoundedToolExecutor with per-attempt reauthorization, ProviderRuntime
   retry-of-one then trusted fallback, InlineInvariantMonitor lifecycle
   observation, and a governed FixtureLedger session that is exercised through
   an uncertain `TIMEOUT` settle, reopen (state equality proof) and a hard-cap
   denial at 200/160 units. The four advisory anomaly rules are armed with
   bounded explicit event observations and the ledger contributes its own
   budget-spike observation on its 25%-of-cap reservations.
2. **MCP SDK memory transport (MCP identity)** — a real in-process MCP SDK
   server fixture (`story-fixture`) exposes `read_ticket` and an inert
   unbound `unbound_admin` tool; `LocalMCPIntegration` discovery yields two
   untrusted candidates, registration binds the trusted candidate to the
   application contract, a reauthorization denial and a mid-session
   `OffSwitch.activate()` are denied redlines, the unbound candidate never
   reaches the protocol, and the SDK session and server lifespan close
   cleanly.
3. **Durable approval lifecycle (approval identity)** — a low-confidence
   guarded task suspends durably instead of blocking; an independently
   constructed `SQLiteApprovalStore` records a human approve decision as a
   separate identity; a fresh trusted bootstrap resumes to completion with the
   approval consumed exactly once at execution; replay resume is rejected; and
   a redline proves out-of-band direct store consumption cannot drive any
   lifecycle resume (fresh resume refused, zero executions).
4. **Recovery after commit (recovery identity)** — a local effect commits and
   then a boundary interruption stops the lifecycle; fresh recovery verifies
   the committed effect, replays nothing, and repeated fresh recovery completes
   idempotently.

`story_board_evidence` facts: `provider_attempts=3`,
`tool_invocations=2`, `authorization_decisions=4`, `action_samples=2`,
`provider_samples=3`, `slo_samples_sufficient=false`, `context_estimated_tokens`
bounded, `compression_reduced=true`, `short_term_routes=1`,
`long_term_routes=1`, `mcp_protocol_calls=1`, `mcp_denied_calls=2`,
`mcp_sessions=1`, `anomaly_signals=5`, `approval_histories=2`,
`approval_consumed_exactly_once=true`, `effect_invocations=1`,
`effect_replays=0`. `StoryBoardEvidence` enforces exactly 31 `CheckEvidence`
entries in the fixed `_CHECK_IDS` order (all `observed`), fixed
`classification` (`deterministic_fixture`, `local_integration`), fixed SDK
pin `2.3.0`, and fixed `_NONCLAIMS`; a model validator rejects any missing,
extra or reordered check, so trimmed or fabricated evidence cannot validate.
No `HumanIdentity` value is serialized (`StringIdentities` only). The CLI
(`python -m harness_engineering.story_board --directory <fresh>`) prints the
evidence as JSON on success, or exactly one sanitized line
`{"failure": ..., "cause": repr}` with exit 1 on any invariant failure; output
never includes records, decisions or secrets.

## Measured facts — truthfulness notes

- The ledger denial math is integral: three auto attempts ({assessment,
  assessment, fallback}) reserve 120 units, the manual `reserve(1)` probe
  reaches exactly the 160-unit cap, `settle TIMEOUT` keeps the conservative
  40-unit outstanding bound, reopen preserves that snapshot exactly, and the
  next reservation (200 units cumulative) is denied by `BudgetExceededError`.
- `anomaly_signals=5` includes the detector's own `budget_spike` signal from
  ledger reservations at 25% of the cap, alongside the four explicitly armed
  event rules (retry-burst, denial-burst, provider-failure-burst,
  tool-frequency).
- `source.calls` measures governed tool attempts that reached the executor:
  the preferred path attempt that was retried, plus the fallback attempt —
  every executor-reaching attempt reauthorizes first.
- Provider observations also contribute advisory events through the trusted
  telemetry path (one retry observation on the second assessment attempt);
  the explicit observations are the bounded arming fixtures.

## Non-claims

- All providers and MCP handlers are deterministic local fixtures; no live
  billing, hosting or network.
- No authentication, deployment, distributed transaction, or
  production-readiness evidence of any kind is produced by this slice.
- MCP evidence uses the in-process SDK memory transport only; no remote
  protocol, handshake or hostile-isolation guarantee is claimed.
- Effect verification uses a local SQLite file; no OS or power-loss durability
  evidence is claimed.
- Consumption is not atomic with external execution; no exactly-once execution
  claim is made.
- All generated or MCP data is data only and never grants authority or
  approves actions; human identity material never enters evidence JSON.
- This slice does not claim Story 12 completion, module release, deployment or
  production readiness, and does not update TRACEABILITY or PROJECT_STATUS.

## Gates (fail-fast order, this slice's venv)

1. `ruff check .` — PASS (all checks passed; the obsolete untracked
   `integration_lab.py` draft was removed so the module directory contains only
   the story board deliverable).
2. `python -m pytest` (module full suite) — 1,756 passed, 6 pre-existing
   third-party Typer/Click deprecation warnings
   (1,644 accepted Story 1–10 baseline + 86 Story 11 Slice 1 + 21 Story 11
   Slice 2 + 5 this slice).
3. `python -m compileall src/harness_engineering tests` — PASS.
4. Focused regression: `tests/test_story_board.py` green (5 tests: full
   composed run with measured facts, reproducibility across fresh directories,
   fail-closed directory reuse, evidence model tamper rejection, sanitized CLI
   failure exit).

## Integrity

`pyproject.toml`, `uv.lock`, all accepted module-06-5 implementation/test/doc
files, and all foreign module files are unchanged; only two new files
(`src/harness_engineering/story_board.py`, `tests/test_story_board.py`) and
this record exist for the slice. Nothing is staged or committed. Story 12
(release reconciliation, requirement-to-test closure, source-faithfulness and
architecture-conformance review) remains open, as does module completion.
