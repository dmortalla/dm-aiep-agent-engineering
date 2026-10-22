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
`docs/STORY_11_SLICE_3.md`. Story 12 and module release remain outstanding.
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
