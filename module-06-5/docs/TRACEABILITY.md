# Module 6.5 - Source Traceability

## Status

APPROVED - Human-approved requirements baseline, 2026-10-10.

| Source area | Derived requirements |
| --- | --- |
| Objective | REQ-OBJ-001 |
| Task Planning & Decomposition | REQ-PLAN-001 through REQ-PLAN-003 |
| Prompt, Context & Memory Orchestration | REQ-CTX-001 through REQ-CTX-003 |
| Context Packing & Context Compression | REQ-COMP-001 through REQ-COMP-003 |
| Tool Routing & Tool Permissions | REQ-TOOL-001 through REQ-TOOL-004 |
| Execution Loops, Retries, Fallbacks & Stop Conditions | REQ-EXEC-001 through REQ-EXEC-004 |
| Checkpointing, Resume & State Recovery | REQ-REC-001 through REQ-REC-004 |
| Human Approval Gates & Escalation Rules | REQ-HITL-001 through REQ-HITL-003 |
| MCP-Based Integration with External Systems | REQ-MCP-001 through REQ-MCP-003 |
| Observability Hooks, Trace Capture & Logging | REQ-OBS-001 through REQ-OBS-003 |
| Evaluation Hooks, Test Cases & Regression Checks | REQ-EVAL-001 through REQ-EVAL-003 |
| Cost & Latency Management | REQ-COST-001 through REQ-COST-004 |
| Safety Controls & Guardrails | REQ-SAFE-001 through REQ-SAFE-004 |
| Named tools | REQ-TECH-001 through REQ-TECH-009 |
| Hands-On Labs | REQ-LAB-001 through REQ-LAB-006 |
| Deliverables | REQ-DEL-001 through REQ-DEL-005 |
| Repository engineering governance | ENG-001 through ENG-007 |

## Classification

REQ-* identifiers are derived from the authoritative course source.
ENG-* identifiers are additive engineering requirements derived from repository governance and are not represented as course-source requirements.

## Traceability rule

Every source-derived requirement must remain traceable to AUTHORITATIVE_SOURCE.md.
Every additive requirement must remain visibly classified as additive.
Future implementation stories and tests must reference applicable requirement identifiers.

## Story 10 implementation evidence — independently accepted

Story 10 implementation criteria are verified by Slices 1–4 and were
independently accepted; the accepted Story 11 baseline records the Story 10
acceptance (`096c96db4c181680d9d22bf52326ae9cc62e9f5c`, no intervening Story
11 commits before `fa7d248`). Approved requirement wording and source mappings
above remain unchanged. Module-wide release reconciliation is Story 12.

Paths below are relative to `module-06-5`. Full chronology, invocation, limitations
and gate evidence: `docs/STORY_10_SLICE_4.md`. Candidate gates: Ruff PASS,
300 focused tests PASS, 1,644 full-suite tests PASS, compileall PASS.

| Requirement | Implementation evidence | Verification / reviewer evidence |
| --- | --- | --- |
| REQ-OBS-001 | `src/harness_engineering/observability.py`, `telemetry_projections.py` | `tests/test_observability.py`, `tests/test_observability_lab.py`; CLI nested spans/structured logs |
| REQ-OBS-002 | `observability.py`, `providers.py`, `observability_adapters.py` | Strict inert traceparent, app/provider-worker correlation and SDK tests in `test_observability.py` / `test_observability_adapters.py` |
| REQ-OBS-003 | `anomaly_signals.py`, `governance_facts.py` | Six bounded advisory categories; `test_anomaly_signals.py`, `test_observability_lab.py`; explicitly labeled fixture signals |
| REQ-COST-001 | `cost_governance.py`, `providers.py`, `usage.py` | Per-step cumulative allocations/receipts; `test_cost_governance.py`, `test_usage_governance.py`; per-step dashboard |
| REQ-COST-002 | `latency.py`, `observability.py` | `test_latency.py`, `test_observability_lab.py`; one-sample insufficiency and explicit twenty-workflow CLI cohort against unchanged p95 <=5s target |
| REQ-COST-003 | `observability_report.py`, `observability_presentation.py` | Runnable `observability_lab.py`; per-step fixture committed/outstanding exposure, caps and usage availability; `test_observability_lab.py` |
| REQ-COST-004 | `cost_governance.py`, `governance_facts.py` | Durable 80%/100% warnings including outstanding exposure; `test_cost_governance.py`, `test_observability_lab.py`; dashboard threshold states |
| REQ-TECH-004 | `observability_adapters.py`, `_offline_observability_worker.py` | Genuine LangSmith SDK over offline transport; isolated payload/privacy/failure/zero-attempt probes in `test_observability_adapters.py` / `observability_sdk_probe.py` |
| REQ-TECH-005 | Same optional adapter/worker boundary | Genuine Langfuse/OTel offline seam; supported fresh-process lifecycle, zero-attempt and N2 regression probes |
| REQ-TECH-007 | `helicone_boundary.py` | `test_helicone_boundary.py`; strict disabled offline header/configuration contract only, no provider rerouting |
| REQ-LAB-006 | `observability_lab.py` | `python -m harness_engineering.observability_lab --directory <new-path>`; real local traces/logs/cost presentation; `test_observability_lab.py` |
| REQ-DEL-004 | `observability_presentation.py`, `observability_report.py` | Story 10 CLI text/JSON observability and cost dashboard; accepted combined Streamlit presentation recorded in the Story 11 section below |
| ENG-002 through ENG-007 | Existing application authority plus strict projection/report contracts and resource bounds | Focused Story 10 and full regression suites; privacy/provenance, no authority feedback, zero network attempts, failure/recovery/budget/evidence tests |

All monetary values are deterministic fixtures, not current provider prices or
verified billing. Optional genuine SDK-over-offline-boundary evidence is not
hosted/live-provider/deployment evidence. No live provider, hosted telemetry or
Helicone routing is authorized or exercised by this implementation.

## Story 11 implementation evidence — independently accepted

Story 11 closeout: Slices 1–2 were independently accepted and committed
(`fa7d24872826ffa835d24976a4c92d1f84fdc709`, `9853ac6afc24ddba82363a195149e3a3138c194d`);
Slice 3 closeout/traceability reconciliation is recorded in
`docs/STORY_11_SLICE_3.md`. Story 12 Slice 1 was independently accepted and
committed at `1666e99`; module-wide release reconciliation is the current
Slice 2 candidate and module release remains subject to independent review.
Evidence is `deterministic` and `local_integration` only; no live-provider,
hosted-service, deployment, genuine-identity, verified-billing or
production-latency claim is made.

| Requirement | Implementation evidence | Verification / reviewer evidence |
| --- | --- | --- |
| REQ-EVAL-001 | `src/harness_engineering/evaluation.py` `InlineInvariantMonitor` (7 invariants, fail-closed abort) | Embed in every lifecycle probe; `tests/test_evaluation.py` acceptance/violation cases |
| REQ-EVAL-002 | Strict versioned loader + `evaluation_golden_set.json` (16 bounded cases); trusted registry `evaluation_probes.py` | Loader bounds/recursion fail-closed tests (`tests/test_evaluation.py`); CLI smokes exit 0/1 (accepted record) |
| REQ-EVAL-003 | `src/harness_engineering/evaluation_lab.py` `run_regression`: exact comparison, per-field drift, exit codes 0/1/2 | `tests/test_evaluation_lab.py`; accepted drift/report CLI smokes |
| REQ-DEL-005 | Same regression harness driven by accepted Story 2–10 services/labs | Same tests; reviewer REGRESSION demonstration renders the report (`tests/test_reviewer_ui.py`) |
| REQ-COST-002 (regression reporting) | `evaluation_lab.py` twenty-workflow cohort vs frozen p95 ≤ 5 s SLO | Accepted Slice 1 record; retained workflow sample metric |
| ENG-001 | `streamlit_app.py`, `.streamlit/config.toml`, `src/harness_engineering/reviewer_service.py` (six labs + MCP + regression demonstrations, guided action/expectation/safety/evidence/limitations) | `tests/test_reviewer_ui.py` real Streamlit `AppTest` over the real entry point; cold headless smoke 8/8 demos; accepted full suite 1,751 passing |
| ENG-006 | Reviewer `DemoView.evidence` typed `EvidenceClass`; report evidence restricted to `deterministic`/`local_integration`; UI evidence-boundaries disclosure | `tests/test_reviewer_ui.py` evidence assertions; accepted slice non-claims records |
| ENG-007 | Probe ERROR verdicts, fail-closed loader/CLI, sanitized UI defect boundaries, denial/off-switch/hard-stop presentations | Failure-path coverage in `test_evaluation.py`, `test_evaluation_lab.py`, `test_reviewer_ui.py`; accepted suites |

ENG-006/ENG-007 are standing governance requirements and remain active for
Story 12. Story 11 scope is closed; Module 6.5 module-wide release evidence is
not claimed.

## Story 12 Slice 1 — composed integration evidence — independently accepted

Story 12 Slice 1 (`1666e99`, "feat(module-06-5): add end-to-end harness story
board") was independently accepted and committed on 2026-10-22. It executes the
accepted Story 2–11 services in one deterministic, credential-free composed run
(`src/harness_engineering/story_board.py`) across four disjoint identity
segments: the governed core workflow (planning, scheduling, context budget and
compression, memory routing, capability selection versus independent
authorization, per-attempt reauthorized tool execution, provider retry-then-
fallback, ledger TIMEOUT settle, reopen equality and hard-cap denial, anomaly
arming); the in-process MCP SDK memory transport (discovery without implicit
trust, trusted binding, denial and off-switch redlines, clean close of the
server/session life); the durable approval lifecycle (confidence suspension, an
independently constructed store recording the human decision, exactly-once
consumption, replay refusal, and an out-of-band direct-consumption redline);
and recovery after commit (verified fresh recovery with zero effect replays,
idempotent on repeat).

Verification: `tests/test_story_board.py` (5 tests: measured facts,
reproducibility across fresh directories, fail-closed directory reuse,
evidence-model tamper rejection, sanitized CLI failure) plus the full module
suite (1,756 passing at the slice record date). `StoryBoardEvidence` enforces
exactly 31 `CheckEvidence` items in the fixed `_CHECK_IDS` order and fixed
non-claims, validated in order, so missing, extra or reordered measurements
cannot validate. The record is `docs/STORY_12_SLICE_1.md`.

Evidence-class terminology: the story board uses labels
`deterministic_fixture` and `local_integration` for its emitted evidence. These
map directly onto the approved classes `deterministic` (fixed local fixtures)
and `local-integration` (local SQLite persistence and the in-process MCP SDK
memory transport). No new, higher-assurance category is created or implied, and
no live-provider or deployment evidence exists in this module.

## Story 12 Slice 2 — module-wide release reconciliation

This section reconciles the complete accepted implementation against all 69
approved requirements without amending any approved requirement wording. Story
counts: 62 source-derived (`REQ-OBJ`, `REQ-PLAN`, `REQ-CTX`, `REQ-COMP`,
`REQ-TOOL`, `REQ-EXEC`, `REQ-REC`, `REQ-HITL`, `REQ-MCP`, `REQ-OBS`,
`REQ-EVAL`, `REQ-COST`, `REQ-SAFE`, `REQ-TECH`, `REQ-LAB`, `REQ-DEL`) plus 7
additive (`ENG-001` through `ENG-007`). Requirements accepted in the Story 10
and Story 11 sections above (REQ-OBS-001..003, REQ-COST-001..004,
REQ-TECH-004/005/007, REQ-LAB-006, REQ-DEL-004/005, ENG-001..007) are closed by
those tables; the matrix below closes the remainder. Paths are relative to
`module-06-5`.

| Requirement | Implementation evidence | Verification / reviewer evidence |
| --- | --- | --- |
| REQ-OBJ-001 | Composed governed runtime: `orchestration.py` lifecycle over the accepted planning/context/tool/provider/persistence services; `story_board.py` closes the end-to-end path | `test_orchestration_integrated.py`, `test_story_board.py`; accepted `STORY_12_SLICE_1.md` (31 in-order checks) |
| REQ-PLAN-001..003, REQ-LAB-001 | `planning.py` (`PlanningEngine` decomposition, dependency graph, `PriorityScheduler`); `planning_lab.py` (`run_planning_lab()` service) | `test_planning_engine.py` (including the `run_planning_lab()` service run), `test_planning_scheduler.py`, `test_planning.py`; Streamlit reviewer demonstration 1; story board segment 1 deterministic order/dependency checks |
| REQ-CTX-001..003, REQ-COMP-001..003, REQ-TECH-002, REQ-LAB-002 | `context.py` (construction, budget, summarization compression, sliding window), `memory.py` (short-term state, long-term routing criteria, Mem0 adapter boundary) | `test_context.py`, `test_context_compression.py`, `test_memory.py`, `test_context_lab.py`; story board context/compression/routing facts |
| REQ-TOOL-001..004, REQ-SAFE-002, REQ-SAFE-003, REQ-LAB-003 | `capabilities.py` (registry selection), `permissions.py` (scope policy, approval-required metadata, blocklists), `execution.py` (application-level bounded executor), `permission_lab.py` | `test_capabilities.py`, `test_permissions.py`, `test_execution.py`, `test_permission_lab.py`; story board governed-tool-authorization check (selection never grants authority) |
| REQ-EXEC-001..004, REQ-SAFE-004, REQ-TECH-001 | `orchestration.py` (LangGraph-based finite lifecycle, bounded retry with exponential backoff, circuit-breaker, fallback, hard stops, deadlines, off-switch checks), `lifecycle_controls.py` (`OffSwitch`, `RunControls`) | `test_orchestration.py`, `test_orchestration_controls.py`, `test_orchestration_fallback_stops.py`; story board retry/fallback/off-switch redlines |
| REQ-REC-001..004, REQ-DEL-002, REQ-LAB-004 | `persistence.py`, `recovery.py`, `effects.py` (committed-effect tracking, no-replay recovery, idempotent re-entry), `recovery_lab.py` | `test_persistence.py`, `test_recovery.py`, `test_effect_recovery.py`, `test_recovery_lab.py`; story board segment 4 `effect_replays=0` and idempotent repeat |
| REQ-HITL-001..003, REQ-DEL-003, REQ-LAB-005 | `approvals.py` (confidence thresholds, exact-action binding), `approval_persistence.py` (durable store), `approval_lifecycle.py` (asynchronous suspend/resume), `approval_lab.py` | `test_approvals.py`, `test_approval_persistence.py`, `test_approval_lifecycle.py`, `test_approval_lab.py`; story board segment 3 suspension, independent decision, consumption-once, replay redline |
| REQ-MCP-001..003, REQ-TECH-003 | `mcp_discovery.py`, `mcp_binding.py`, `mcp_local.py`, `mcp_lab.py` | `test_mcp_discovery.py`, `test_mcp_binding.py`, `test_mcp_local.py`, `test_mcp_lab.py`; story board segment 2 inert-discovery/trusted-binding/denial checks |
| REQ-SAFE-001 | `providers.py` (`OutputFilter`, `ProviderOutputRejected`), `guardrails_adapter.py` (additive) | `test_providers.py`, `test_guardrails_adapter.py`; story board filtered-output check |
| REQ-TECH-006 | `guardrails_adapter.py` (Guardrails AI schema validation; locked extra; never inference or authority) | `test_guardrails_adapter.py` real `guardrails` lifecycle tests; additive validation only, no hosted service |
| REQ-TECH-008, REQ-TECH-009 | `vendor_providers.py` (`OpenAIProvider`, `AnthropicProvider` optional adapters behind the provider-neutral `providers.py` contracts) | `test_vendor_providers.py` credential-free adapter tests; adapters only, never exercised as live providers |
| REQ-DEL-001 | The accepted runtime composition of Stories 2–11 (parallel services, each with its own tests) integrated by `story_board.py` | `test_story_board.py` composed evidence; individual service suites cited in the rows above |
| ENG-002..ENG-005 | Untrusted-data validation with no model/agent authority feedback across the capabilities, permissions, execution, MCP, provider, guardrail, ledger, telemetry and golden-set boundaries; bounded retries, loops, calls, resources, latency and cost in the same accepted implementations; credential-free deterministic reviewer path | Failure/adversarial/zero-external-attempt coverage in the cited per-service suites plus `test_story_board.py` redlines; full module regression suites |

### 69/69 closure ledger

Every approved requirement identifier is closed by exactly one of: the Story 10
table (REQ-OBS-001..003, REQ-COST-001..004, REQ-TECH-004, REQ-TECH-005,
REQ-TECH-007, REQ-LAB-006, REQ-DEL-004), the Story 11 table (REQ-EVAL-001..003,
REQ-DEL-005, ENG-001), the ENG-002..ENG-007 line in the Story 10 table, or the
Story 12 Slice 2 matrix above. Individually enumerated: REQ-OBJ-001;
REQ-PLAN-001, REQ-PLAN-002, REQ-PLAN-003; REQ-CTX-001, REQ-CTX-002,
REQ-CTX-003; REQ-COMP-001, REQ-COMP-002, REQ-COMP-003; REQ-TOOL-001,
REQ-TOOL-002, REQ-TOOL-003, REQ-TOOL-004; REQ-EXEC-001, REQ-EXEC-002,
REQ-EXEC-003, REQ-EXEC-004; REQ-REC-001, REQ-REC-002, REQ-REC-003, REQ-REC-004;
REQ-HITL-001, REQ-HITL-002, REQ-HITL-003; REQ-MCP-001, REQ-MCP-002, REQ-MCP-003;
REQ-SAFE-001, REQ-SAFE-002, REQ-SAFE-003, REQ-SAFE-004; REQ-TECH-001,
REQ-TECH-002, REQ-TECH-003, REQ-TECH-006, REQ-TECH-008, REQ-TECH-009;
REQ-LAB-001, REQ-LAB-002, REQ-LAB-003, REQ-LAB-004, REQ-LAB-005; REQ-DEL-001,
REQ-DEL-002, REQ-DEL-003. Count: 62 source-derived + 7 additive (ENG-001,
ENG-002, ENG-003, ENG-004, ENG-005, ENG-006, ENG-007) = 69 of 69.
`tests/test_release_reconciliation.py` verifies this closure mechanically (all
69 identifiers present in this document).

### Labs (6 of 6) and deliverables (5 of 5)

All six labs are implemented, tested and reviewer-demonstrable. Four expose
direct CLI evidence surfaces (`python -m harness_engineering.permission_lab`,
`recovery_lab`, `approval_lab`, `observability_lab`, each with a real `main()`
entry point); planning and context expose deterministic service functions
(`run_planning_lab()`, `run_context_lab()`) and are reviewer-demonstrable
through the accepted Streamlit demonstrations ("1 · Task planning" and
"2 · Context compression" via `streamlit run streamlit_app.py`).

| Lab (requirement) | Reviewer surface / primary implementation | Tests | Evidence class | Non-claim / limitation |
| --- | --- | --- | --- | --- |
| REQ-LAB-001 planning | `run_planning_lab()` service in `planning_lab.py` over `planning.py`; Streamlit reviewer demonstration 1 | `test_planning_engine.py` (includes the `run_planning_lab()` service run), `test_planning_scheduler.py`, `test_planning.py` | deterministic | fixed local fixture goals only |
| REQ-LAB-002 context compression | `run_context_lab()` service in `context_lab.py` over `context.py`, `memory.py`; Streamlit reviewer demonstration 2 | `test_context_lab.py`, `test_context_compression.py`, `test_memory.py` | deterministic | token estimates are local heuristics, not model tokenizers |
| REQ-LAB-003 permissions/sandbox | `python -m harness_engineering.permission_lab`; `capabilities.py`, `permissions.py`, `execution.py` | `test_permission_lab.py`, `test_permissions.py`, `test_execution.py` | deterministic | application-level sandbox boundary, not OS/container isolation |
| REQ-LAB-004 recovery/resume | `python -m harness_engineering.recovery_lab`; `persistence.py`, `recovery.py`, `effects.py` | `test_recovery_lab.py`, `test_persistence.py`, `test_recovery.py`, `test_effect_recovery.py` | deterministic + local-integration (SQLite) | local trusted-filesystem evidence, not power-loss durability |
| REQ-LAB-005 HITL approval gate | `python -m harness_engineering.approval_lab`; `approvals.py`, `approval_persistence.py`, `approval_lifecycle.py` | `test_approval_lab.py`, `test_approval_lifecycle.py`, `test_approval_persistence.py` | deterministic + local-integration (SQLite) | human identities/decisions are simulated fixtures |
| REQ-LAB-006 observability/cost | `python -m harness_engineering.observability_lab`; `observability_lab.py` over `observability.py`, `telemetry_projections.py` | `test_observability_lab.py`, `test_observability.py`, `test_cost_governance.py`, `test_latency.py` | local-integration + deterministic | optional LangSmith/Langfuse projections are offline-boundary only (Story 10 rows) |

Deliverable reconciliation: REQ-DEL-001 (runtime with full lifecycle control) —
the Story 2–11 service composition, closed by `story_board.py`;
REQ-DEL-002 (checkpointing/recovery) — `persistence.py`/`recovery.py`/`effects.py`
with the Story 6 suites and story board segment 4; REQ-DEL-003 (HITL approval
workflow) — the approval family with the Story 7 suites and story board segment
3; REQ-DEL-004 (observability/cost dashboard) — Story 10 CLI presentation plus
the accepted combined Streamlit reviewer experience (Story 11 table);
REQ-DEL-005 (regression harness) — Story 11 table. Each is implemented and
verified evidence, not architectural mapping alone.

### Technologies (9 of 9)

| Technology | Actual role | Path type | Implementation evidence | Verification | Classification | Non-claim |
| --- | --- | --- | --- | --- | --- | --- |
| LangGraph | Core typed lifecycle orchestration (`StateGraph` compiled and invoked) | deterministic core (critical path) | `orchestration.py` | `test_orchestration.py`, `test_orchestration_controls.py`, integrated/story-board suites | deterministic | no LangGraph cloud/server/platform services are used |
| MCP SDK | Primary MCP integration boundary (in-process memory transport demonstrated end-to-end) | local integration (critical path) | `mcp_discovery.py`, `mcp_binding.py`, `mcp_local.py`, `story_board.py` segment 2 | MCP test suites; accepted story board | local-integration | no remote protocol, hosted MCP service or hostile-isolation claim |
| OpenAI SDK | Optional live-provider adapter behind provider-neutral contracts | optional adapter integration | `vendor_providers.py` `OpenAIProvider` | `test_vendor_providers.py` (credential-free) | adapter | no live OpenAI provider verification; not on the deterministic reviewer path |
| Anthropic SDK | Optional live-provider adapter behind provider-neutral contracts | optional adapter integration | `vendor_providers.py` `AnthropicProvider` | `test_vendor_providers.py` | adapter | no live Anthropic provider verification |
| Guardrails AI | Additive local schema validation of provider output | optional adapter integration | `guardrails_adapter.py` | `test_guardrails_adapter.py` | adapter (locked extra) | not the sole security boundary; no hosted service |
| Mem0 | Optional long-term semantic-memory adapter boundary; owns no recovery or authority | optional adapter integration | `memory.py` adapter seam | `test_memory.py` boundary tests | adapter | no live Mem0 service; never exercised as a hosted dependency |
| LangSmith | Optional observability projection over a controlled offline transport | optional adapter integration | `observability_adapters.py`, `_offline_observability_worker.py` | `test_observability_adapters.py`, fresh-process probes | adapter | no hosted LangSmith verification |
| Langfuse | Optional observability/OTel offline-boundary projection | optional adapter integration | same boundary | same tests; N2 fresh-process regression | adapter | no hosted Langfuse verification |
| Helicone | Strict disabled header/configuration boundary; no transport exists | optional boundary (disabled) | `helicone_boundary.py` | `test_helicone_boundary.py` | adapter (offline contract only) | no live Helicone routing or provider rerouting |

### Release non-claims (module-wide)

- No live OpenAI or Anthropic provider verification; vendor SDKs are optional
  adapters over provider-neutral contracts and are never exercised live.
- No paid inference is required for any normal reviewer/CLI path; the approval
  story board, all six labs and the reviewer interface run credential-free.
- No hosted LangSmith or Langfuse verification; both project over offline
  boundaries with zero external attempts.
- No live Helicone provider routing; only the strict disabled header contract.
- No live Mem0 service requirement; the adapter seam is optional and duty-free.
- No external production MCP service claim; MCP evidence is the in-process SDK
  memory transport plus local lab fixtures.
- No genuine production identity/authentication claim; approval identities are
  simulated fixtures and `HumanIdentity` data never enters evidence JSON.
- Fixture monetary values are not provider prices; no verified billing exists.
- Local deterministic latency cohorts are not production-latency certification;
  the frozen p95 ≤ 5 s SLO is a local workflow target, and the 180 s deadline
  remains a separate safety bound.
- The application-level sandbox is not OS/container isolation.
- Deployment evidence does not exist; engineering release for this module ends
  at independently reviewed engineering acceptance and is distinct from
  deployment verification, which has not occurred.

Module 6.5 engineering release is a Slice 2 candidate pending independent
review (`docs/STORY_12_SLICE_2.md`, `docs/RELEASE_READINESS.md`); deployment
verification and final module closeout are separate later gates.

## Release reconciliation status

Story 12 Slice 2 established this module-wide reconciliation mechanically
verified by `tests/test_release_reconciliation.py`: the 69-approved-requirement
ledger, six-lab and five-deliverable coverage, nine technology roles with
truthful classifications, preserved release non-claims, correct reference to
the accepted Story 12 Slice 1 commit `1666e99`, and a status-consistent README
and reviewer interface. Approved requirement wording and source mappings are
unchanged. Evidence remains `deterministic` and `local-integration` only.
Story 12 was closed and the module-wide reconciliation accepted (commit
`d4d2fd0`; reviewer-UI reconciliation `7ce1bd8`). On 2026-10-23 the corrective
additive ENG-008 restored the production-grade dual-mode invariant (ADR 002),
with completion tracked by Story 13 and the section above; no provider-level
production-readiness claim exists and live-provider evidence remains none.

## Corrective dual-mode contract (ENG-008) — adopted 2026-10-23, completion outstanding

Repository governance requires production-grade engineering unless a module is
explicitly declared DEMO-ONLY; Module 6.5 has never been declared DEMO-ONLY.
The contract-propagation gap (neutral statement): repository governance
requires production-grade engineering by default unless a module is explicitly
declared DEMO-ONLY, and Module 6.5 was never declared DEMO-ONLY, yet ADR 001
decision 11 and the Story 9/Story 12 acceptance contract described
OpenAI/Anthropic as optional adapters and accepted release reconciliation with
live-provider evidence = none, silently leaving the production-grade dual-mode
invariant unenforced at module level.

Corrective contract, additive to the unchanged 69-requirement baseline:

- **ENG-008** (wording in `docs/REQUIREMENTS.md`, decision in
  `docs/adr/002-production-grade-dual-mode-completion.md`): deterministic,
  credential-free operation remains the default reviewer mode; live OpenAI or
  Anthropic execution is opt-in and securely configurated only — explicit
  validated configuration, documented provider/model allowlist, credentials
  supplied through trusted server-side/environment/secret-store mechanisms and
  never public browser input, credentials granting connectivity only and never
  authority, bounded retries/token/output/latency/cost; evidence classes stay
  explicitly distinct; provider-level production readiness may be claimed only
  when the live path is implemented, securely configured, explicitly
  human-authorized for execution, exercised, and independently evidenced.

Implemented evidence already accepted (deterministic/adapter/local-integration
classes): `HarnessConfig` defaults with fail-closed mutual exclusion
(`config.py`, `test_config.py`); the live-adapter gate requiring explicit
`allow_live_providers` plus a finite `max_cost_usd` (`vendor_providers.py`);
credential-free adapter tests plus
`test_credentials_or_claimed_locality_do_not_authorize_live_provider` and
safe-missing-configuration tests (`test_vendor_providers.py`);
`EvidenceClass.LIVE_PROVIDER` distinct in `providers.py`/evidence contracts.

Story 13 Builder candidate (`docs/STORY_13.md`), verified at deterministic,
mocked, and adapter class only:

| ENG-008 clause | Implementation | Verification |
| --- | --- | --- |
| Deterministic default | `HarnessConfig()` with `live=None`; fake provider | `test_deterministic_mode_remains_default_and_credential_free` |
| Explicit opt-in, allowlist | `LiveProviderPolicy`, `SUPPORTED_LIVE_MODELS`, `_validate_binding` | activation, unknown-provider, disallowed-model, accepted-path tests |
| Trusted credentials, never browser input | `live_credentials.py` sources; explicit SDK `api_key` | missing-credential, secret-store, opacity, redaction, reviewer-widget tests |
| Connectivity only, never authority | Untrusted `ModelResult`; unchanged HITL/policy/off-switch | untrusted-output and HITL/policy/capability tests |
| Bounded retries/tokens/latency/cost | SDK `max_retries=0`; live ceilings; worst-case cost reservation | retry, latency, token/output, cost tests |
| Human authorization | Expiring `LiveExecutionAuthorization`, re-checked pre-dispatch | authorization scope/window/expiry/forgery tests |
| Distinct evidence classes | `live_readiness.py`; `evidence_class` capped at adapter | adapter/mocked-never-live test |

Outstanding (later human-authorized gate): live-path exercising with real
credentials under a separate human-authorized cost/credential/execution
boundary. No live-provider evidence exists yet; it requires that exercise and
an independent review. Until then, no provider-level production-readiness claim is made,
and adapter or mocked evidence must not be represented as live-provider
evidence.

`tests/test_dual_mode_contract.py` mechanically protects this contract:
the ENG-008 wording, ADR 002/ADR 001 addendum, Story 13/DoD entries,
release-readiness outstanding gate, unchanged evidence taxonomy, the
`HarnessConfig` structural defaults and validator, the adapter gate, and the
negation-bound discipline that release documents may not claim live-provider
evidence exists.
