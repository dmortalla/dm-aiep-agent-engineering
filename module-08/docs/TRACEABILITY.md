# Module 8 - Traceability

## Status

VERIFIED FOR INDEPENDENT ACCEPTANCE - 23/23 source requirements and 10/10
engineering requirements supported within the local reviewer scope. No
live-provider, deployment or unconditional production-readiness claim is made.

Every frozen requirement maps to implementation stories and expected verification/reviewer evidence.

The matrix below preserves the approved story allocation. The completed audit
following it records actual implementation and verification rather than relying
on the planning allocation as proof.

| Requirement | Stories | Expected Verification / Reviewer Evidence |
|---|---|---|
| REQ-OBJ-001 | S8,S9,S10 | End-to-end reviewer workflow |
| REQ-MCP-001 | S3,S4,S9,S10 | MCP discovery and topology evidence |
| REQ-MCP-002 | S3,S4,S9,S10 | Client/server execution evidence |
| REQ-MCP-003 | S8,S9,S10 | Runnable traditional-vs-MCP comparison |
| REQ-INFRA-001 | S3,S9,S10 | Exposed capability inventory |
| REQ-INFRA-002 | S3,S4,S9,S10 | Context exchange evidence |
| REQ-INFRA-003 | S4,S9,S10 | Streamable HTTP execution evidence |
| REQ-INFRA-004 | S3,S4,S9,S10 | Discovered capability evidence |
| REQ-ENT-001 | S2,S3,S9,S10 | Database results and execution evidence |
| REQ-ENT-002 | S2,S3,S8,S9,S10 | Sanitized API request/response evidence |
| REQ-ENT-003 | S2,S3,S9,S10 | Internal-system result evidence |
| REQ-INT-001 | S8,S9,S10 | Guided architecture explanation |
| REQ-INT-002 | S6,S7,S8,S9,S10 | OpenAI/ADK shared-capability demonstration |
| REQ-INT-003 | S4,S8,S9,S10 | Distributed-boundary evidence |
| REQ-INT-004 | S8,S9,S10 | Implemented-standards evidence/explanation |
| REQ-TECH-001 | S3,S4,S10 | Genuine MCP SDK execution evidence |
| REQ-TECH-002 | S6,S9,S10 | Genuine OpenAI SDK integration evidence |
| REQ-TECH-003 | S7,S9,S10 | Genuine Google ADK integration evidence |
| REQ-LAB-001 | S3,S4,S9,S10 | Runnable MCP server demonstration |
| REQ-LAB-002 | S6,S7,S8,S9,S10 | Agents-to-enterprise-tools demonstration |
| REQ-LAB-003 | S8,S9,S10 | Runnable interoperable workflow |
| REQ-DEL-001 | S3,S4,S8,S9,S10 | Working MCP-powered system |
| REQ-DEL-002 | S2,S3,S6,S7,S8,S9,S10 | Working enterprise integration system |
| ENG-001 | S1,S9,S10 | Self-explanatory Streamlit console |
| ENG-002 | S1,S2,S3,S4,S5,S6,S7,S8,S10 | Boundary validation evidence |
| ENG-003 | S1,S5,S6,S7,S8,S10 | Denied self-authority evidence |
| ENG-004 | S3,S4,S5,S6,S7,S9,S10 | Discovery/authorization decision evidence |
| ENG-005 | S1,S2,S4,S5,S6,S7,S8,S10 | Bounded-execution evidence |
| ENG-006 | S1,S6,S7,S8,S9,S10 | Zero-paid-call deterministic path |
| ENG-007 | S1,S2,S3,S4,S5,S6,S7,S8,S9,S10 | Visible evidence classification |
| ENG-008 | S2,S3,S4,S5,S6,S7,S8,S9,S10 | Security/failure-path verification |
| ENG-009 | S1,S2,S3,S4,S5,S6,S7,S8,S9,S10 | Static review and failure-path tests |
| ENG-010 | S1,S10 | Isolation verification |

## Completed implementation audit

Paths below are module-relative. Test names identify maintainable verification;
`tests/test_reviewer.py::test_real_reviewer_console` additionally executes and
renders both scenarios through real local services. All rows are verified in
that bounded scope; conceptual requirements use appropriately classified
explanations, not fabricated runtime implementations.

| Requirement | Actual implementation / explanation | Verification / reviewer evidence |
|---|---|---|
| REQ-OBJ-001 | `workflow.py`, `reviewer.py`, `console.py` under `src/mcp_enterprise_integration/` | `test_workflow.py::test_shared_plane_workflow`; complete console result |
| REQ-MCP-001 | `mcp_server.py`, `mcp_client.py`; console topology guide | `test_mcp_client.py::test_client_initializes_real_mcp_session`; negotiated metadata |
| REQ-MCP-002 | Official SDK client/server | `test_mcp_client.py`; real Streamable HTTP discovery/invocation |
| REQ-MCP-003 | `reviewer.py` direct lookup comparison; README explanation | `test_workflow.py::test_direct_versus_mcp_comparison`; console comparison result |
| REQ-INFRA-001 | Three `server.tool()` registrations | `test_mcp_server.py::test_mcp_discovers_three_enterprise_tools`; inventory |
| REQ-INFRA-002 | Typed workflow request/result exchange | `test_workflow.py::test_shared_plane_workflow`; displayed policy request |
| REQ-INFRA-003 | MCP Streamable HTTP app and consumers | `test_mcp_client.py`; three displayed transport records |
| REQ-INFRA-004 | Genuine `list_tools` discovery | `test_mcp_server.py::test_mcp_discovery_exposes_typed_contracts`; console inventory |
| REQ-ENT-001 | `database.py` parameterized SQLite queries | `test_database.py`, MCP client database test; actual customer table |
| REQ-ENT-002 | `enterprise_api.py` bounded local HTTP request | `test_enterprise_api.py`, SDK API tests; actual account table |
| REQ-ENT-003 | `internal_system.py` callable policy evaluation | `test_internal_system.py`, SDK policy tests; actual decision and rule |
| REQ-INT-001 | Console guide, README, Story 8 conceptual explanation | Static review: OS building blocks grounded in actual capabilities, context and policy; no OS implementation claim |
| REQ-INT-002 | Independent OpenAI/ADK consumers of one MCP plane | `test_workflow.py::test_shared_plane_workflow`; three SDK stages |
| REQ-INT-003 | Independently addressed local MCP/HTTP services | Real client/SDK tests; console guide explains distributed loopback scope |
| REQ-INT-004 | Implemented MCP; complementary A2A distinction | README, console guide and Story 8; no A2A implementation claim |
| REQ-TECH-001 | Official MCP server, client, discovery and transport | `test_mcp_server.py`, `test_mcp_client.py`; actual protocol metadata |
| REQ-TECH-002 | `openai_mcp.py` Agent and SDK MCP tool calls | `test_openai_mcp.py`; first/third workflow stages, no model runner |
| REQ-TECH-003 | `google_adk_mcp.py` Agent, McpToolset and tool execution | `test_google_adk_mcp.py`; second workflow stage, no model runner |
| REQ-LAB-001 | `create_enterprise_mcp_server` | Server/client tests and console-started genuine server |
| REQ-LAB-002 | SDK agents configured with shared MCP tools | Both SDK test files and reviewer enterprise results |
| REQ-LAB-003 | `EnterpriseWorkflow` | `test_workflow.py`, both reviewer scenarios |
| REQ-DEL-001 | Frozen architecture implemented as shared MCP capability plane | Architecture/ADR inspection plus real discovery and transport tests |
| REQ-DEL-002 | SQLite/API/internal policy integrated through both SDKs | Real workflow and console enterprise tables |
| ENG-001 | Thin `console.py`, application `reviewer.py`, README | `test_reviewer.py`; prior human Story 9 UI acceptance supplied for Story 10 |
| ENG-002 | Strict workflow envelopes, bounds, identity correlation and extra-field rejection | Domain/API/ADK tests and `test_workflow.py` corruption tests (mocked injection) |
| ENG-003 | `CapabilityPolicy`; original application role retained across stages | Unknown-role, forged-argument and workflow authority tests; empty-map regression |
| ENG-004 | Explicit discovery then independent allowlist check | MCP client and ADK denial-before-execution tests; console denial |
| ENG-005 | API size/time limits; SDK deadlines; 45s workflow; 60s reviewer; two demo slots | Bounds tests, `test_busy_console_rejects_without_startup`; source review of limits, not a load/SLA certification |
| ENG-006 | Neither SDK model runner used in the default path; Story 11 live mode is opt-in only | Workflow runner guards and reviewer no-key/external-connection guards; Story 11 ambient-key and offline live tests |
| ENG-007 | `ExecutionEvidence` taxonomy and checked execution flags | `test_evidence_contracts.py`; reviewer evidence assertions and visible classification |
| ENG-008 | Expected validation, denial, transport, cleanup and safe UI failure tests | Existing domain/backend/client/SDK/workflow/reviewer suites; nine empty-map cases |
| ENG-009 | Typed public interfaces, docstrings and chained failure boundaries | Source review plus Ruff/compileall and expected failure tests; no formal type-checker claim |
| ENG-010 | Standalone package, local project dependencies and tests | Story 10 tracked-source/import/dependency isolation inspection; no cross-module implementation imports |

The ordered Definition of Done and exact final native gate results are recorded
in [Story 10](stories/STORY-10-integrated-verification-release-evidence.md).

## Reviewer-Visible Working-Results Rule

Material capabilities are not accepted solely from architectural declarations, source presence, or automated tests.

Where a capability is material to the system's purpose or portfolio claims, its real execution result and appropriate supporting evidence must be available through the unified reviewer experience.

## Change Control

Any requirement or material architecture change requires explicit human approval before this matrix is revised to depend on that change.

## Story 11 additive extension - opt-in live provider / BYOK mode

No requirement definition changed. The optional live mode strengthens existing rows
without replacing their deterministic evidence. Tests are in `tests/test_live_provider.py`
and replace only the external model boundary (Agents SDK `ScriptedModel`, scripted ADK
`BaseLlm`); all such runs are classified `mocked`. No live-provider evidence exists in
the repository.

| Requirement | Additive implementation | Verification |
|---|---|---|
| REQ-TECH-002 | OpenAI Agents SDK `Runner` drives stage 1 with an optional genuine OpenAI model over the shared MCP plane | `test_scripted_providers_run_real_sdks_but_never_claim_live_evidence` |
| REQ-TECH-003 | Google ADK `Runner`/`McpToolset` drives stage 2 with an optional genuine Gemini model | Same test; `test_single_provider_selection_keeps_other_stage_deterministic` |
| REQ-LAB-002 / REQ-INT-002 | Live models connect to enterprise tools through MCP within application bounds | Scripted live-path workflow and console tests |
| ENG-002 / ENG-003 | Model output untrusted; cannot change role, identity, capability, arguments or decision | `test_provider_text_cannot_change_role_or_decision`, `test_model_cannot_bypass_capability_policy_or_argument_binding` |
| ENG-004 | Discovery, exposure authorization and per-call authorization are separate | `test_unknown_role_is_denied_before_any_model_request`; tool-exposure assertion |
| ENG-005 | Call, tool, token, stage and run bounds; no retries; one live run per process | `test_openai_call_and_tool_bounds_are_enforced`, `test_adk_call_bound_and_missing_tool_use_fail_safely`, `test_stage_deadline_is_enforced`, factory retry assertions |
| ENG-006 | Deterministic default unchanged; ambient keys never trigger live execution | `test_ambient_credentials_never_trigger_live_execution`, `test_console_defaults_to_deterministic_mode_with_attribution` |
| ENG-007 | `live-provider` only for genuine, completed, validated execution; injected doubles `mocked` | `test_live_classification_requires_genuine_completed_validated_execution`, `test_reviewer_live_run_with_injected_doubles_is_mocked` |
| ENG-008 | Consent, missing-key, redaction and failure paths | Consent, missing-key, redaction and console refusal tests |
| ENG-001 | Self-explanatory opt-in console mode with risk, bounds and limits | `test_live_mode_explains_risk_and_masks_key_inputs`, `test_live_console_runs_injected_doubles_as_mocked_and_clears_keys` |
