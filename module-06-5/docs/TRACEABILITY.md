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

## Story 10 implementation evidence — pending independent acceptance

Story 10 implementation criteria are verified by Slices 1–4. This records
implementation evidence, not independent acceptance or module release. Approved
requirement wording and source mappings above remain unchanged. Final Streamlit
presentation/evaluation is Story 11; module-wide release reconciliation is Story 12.

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
| REQ-DEL-004 | `observability_presentation.py`, `observability_report.py` | Story 10 CLI text/JSON observability and cost dashboard; final combined Streamlit UI remains Story 11 |
| ENG-002 through ENG-007 | Existing application authority plus strict projection/report contracts and resource bounds | Focused Story 10 and full regression suites; privacy/provenance, no authority feedback, zero network attempts, failure/recovery/budget/evidence tests |

All monetary values are deterministic fixtures, not current provider prices or
verified billing. Optional genuine SDK-over-offline-boundary evidence is not
hosted/live-provider/deployment evidence. No live provider, hosted telemetry or
Helicone routing is authorized or exercised by this implementation.
