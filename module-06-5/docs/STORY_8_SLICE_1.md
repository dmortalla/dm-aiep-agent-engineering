# Story 8 Slice 1 — Inert MCP discovery boundary

## Scope and traceability

This slice begins REQ-MCP-002, REQ-MCP-003, and REQ-TECH-003, with
ENG-002 through ENG-007 applying. It does not complete Story 8 or establish
REQ-MCP-001 executable registration evidence. Architecture and existing
capability, permission, execution, persistence, and approval implementations
are unchanged. No final reviewer UI or Story 9 work is included.

The accepted four-slice decomposition fits the frozen package responsibilities:

1. Typed inert metadata, bounded discovery translation, schema validation,
   duplicate rejection, discovery audit, and adversarial tests (this patch).
2. Trusted application registration/binding, current authorization, and bounded
   invocation through the accepted controls.
3. Deterministic actual-SDK local server/client integration.
4. Integrated adversarial lab and complete Story 8 exit evidence.

Slices 2–4 remain unimplemented. In particular, timeout, cancellation, revocation,
workflow budgets, remote error/result handling, and invocation tests belong to
the later integration; discovery tests do not substitute for that evidence.

## Baseline and isolation

Initial HEAD was `44571350bdd719afc9a95a68275e0dd4b86fefc7`, the accepted Story 7
closeout itself; ancestry passed and there were no intervening module commits.
Module 6.5 had no tracked/untracked changes and the index was empty. Foreign
root, Module 7, and Module 10 work was observed and left untouched.

Inspected source authority, frozen architecture/ADR, requirements, traceability,
implementation plan, repository SOP/status, and accepted capability registry,
permission authorizer/tests, executor, lifecycle/off-switch controls,
persistence contracts, configuration, and domain/errors. Selection, metadata,
policy/grants, and handler bindings are already separate; no accepted-code
defect requires an architecture or authority amendment for this slice.

## Installed SDK facts

The module environment is Python 3.12.14. MCP was initially absent. The existing
locked `mcp` extra was installed offline using
`uv sync --locked --offline --inexact --extra mcp`, preserving other installed
packages. MCP and mcp-types are 2.3.0; jsonschema is 4.26.0, an existing locked MCP
dependency. No dependency declarations, versions, or lockfile were changed.
An initial offline sync including the orchestration extra could not complete
because sqlite-vec was not cached; no dependency upgrade was attempted.

Installed API inspection verified `Implementation`, `Tool`, `ListToolsResult`,
and `ClientSession.list_tools(*, params=None)`. Tool fields are `input_schema`
and `output_schema`, serialized as `inputSchema` and `outputSchema`.
ListToolsResult supports pagination and additional result types; this slice
requires one complete page and rejects continuation or input-required results.
SDK models alone are permissive enough that explicit application validation
must precede SDK validation. No transport/session is created here.

## Contracts and translation

`translate_discovery(service_json, discovery_json)` accepts already-received
UTF-8 JSON bytes for advertised service implementation metadata and one complete
tools result. It validates bounded JSON and the supported application profile,
validates against actual MCP SDK models, then returns a frozen
`MCPDiscoverySnapshot` of frozen `MCPServiceMetadata` and
`MCPCapabilityCandidate` records, sorted by exact remote name.

Schema dictionaries become canonical JSON strings to avoid nested mutable
state. Advertised service names/versions identify only untrusted claims; they
are not authenticated identity. Remote names never become application registry
keys automatically. Candidates have no handlers, permission scope, approval,
budget, or executable methods. `grants_authority` is always false. The boundary
accepts no registry, authorizer, session, or callback. It cannot invoke tools,
change policy, issue grants, or mutate existing capability registration.

Even constructing, copying, forging, or persisting candidate metadata cannot
establish its provenance or make it authoritative. Future invocation must use
current application-owned bindings and controls, never a serialized candidate
as an authorization token. Inert descriptions/schema text may contain hostile
instructions; no instruction interpretation or next-action routing occurs.

## Validation and bounds

| Boundary | Hard limit/profile |
| --- | --- |
| Service JSON | 4,096 bytes; only name/version, each 1–128 characters |
| Discovery JSON | 65,536 bytes, one complete tools page |
| JSON structure | 16 container levels; 4,096 value nodes per payload |
| Candidate count | 100; empty discovery is valid |
| Tool name | Exact, 1–128 characters; ASCII letters/digits and `._:-`; no whitespace |
| Description | Optional; 1–2,000 characters when present; no control characters |
| Schema | 16,384 canonical JSON bytes per input/output schema |
| Object schema | Closed object, at most 32 declared properties; required names must exist and be unique |
| String/array schema | Explicit maxLength <= 4,096 / maxItems <= 100 |
| Audit | Three success events or two rejection events per operation |

Only the explicitly supported metadata keys are accepted. Unknown fields,
including annotations, task execution hints, resource/prompt metadata, and
authority-shaped fields, are rejected rather than silently interpreted.
Resources and prompts are not discovery inputs for this tools-only slice.

The deliberately restricted JSON Schema profile supports closed objects,
bounded arrays/strings, primitive numbers/integers/booleans/null, descriptive
text, required properties, enum and applicable size/numeric constraints.
Draft202012Validator.check_schema validates the schema itself. References,
remote resolution, regexes, formats, combinators, and unknown keywords are
unsupported and fail closed. Schema validity never grants authorization.
This is not support for every schema allowed by MCP or JSON Schema.

Duplicate JSON keys anywhere, duplicate remote tool names (identical or
conflicting), malformed schemas, and malformed SDK structures reject the whole
operation. No partial candidate snapshot escapes. Results from different
services are separate snapshots, not merged global identities.

Finite, locally defined failure codes become MCPDiscoveryError, a specific
ContractValidationError. Expected decoder/SDK/schema validation causes are
chained; callers must treat those diagnostic causes as untrusted and avoid
logging raw payload-bearing exceptions. Unexpected programming defects
propagate. There are no retries, pagination loops, polling, or external calls.
These are bounds on already-received metadata, not transport buffering or
end-to-end discovery time guarantees.

## Audit and evidence

Success emits received, validated, translated events; failure carries received
and rejected events. Events contain only local enum codes and a bounded count,
never descriptions, service names, schemas, credentials, handlers, runtime
objects, or remote error text. Audit is operation-local immutable data, not a
durable store or authorization decision. Callers own retention/aggregation;
this slice does not add an unbounded in-memory audit history.

Evidence is **deterministic_fixture plus adapter/SDK construction**. Tests create
real SDK objects, serialize their wire aliases, and translate with real SDK
validation. This is not local transport integration, live-provider evidence,
enterprise authentication, cryptographic identity, production MCP service
readiness, network isolation, OS sandboxing, deployment, or release evidence.

`tests/test_mcp_discovery.py` adds 75 cases covering actual SDK wire translation,
frozen/detached metadata, deterministic ordering, model/agent/persisted/discovered
names, unknown and registered-but-unallowlisted names, allowlisted names without
permission, rejection by the accepted application registry, forged authority
fields, malformed discovery/service/tool/schema/output-schema data, duplicate
and conflicting identities/keys, bounds, nested schemas, inert injection text,
sanitized bounded audit, and propagation of unexpected defects.

Final quality gates passed in order on the final source/test patch:

1. `.venv/Scripts/ruff.exe check .` — PASS.
2. `.venv/Scripts/python.exe -m pytest -q -x --basetemp
   E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-08-slice-01-final-20261014`
   — **1,038 passed in 402.57 seconds** (963 accepted + 75 new).
3. `.venv/Scripts/python.exe -m compileall src tests` — PASS.

The earlier in-progress elevated run was interrupted to include the final added
tests and formatting; it is not the final gate evidence.
An initial full test run encountered sandbox denial creating its EVIDENCE
basetemp (642 passed, 387 setup errors); no tests or source were modified to
compensate. The fail-fast sequence was rerun with access to a fresh dedicated
EVIDENCE directory.

The exact new test functions (75 parameter-expanded cases) are:

- `test_actual_sdk_wire_translation_and_immutable_snapshot`
- `test_schema_snapshot_is_detached_from_mutable_advertisement`
- `test_selected_or_trusted_looking_name_cannot_mint_authority`
- `test_authority_fields_and_unsupported_metadata_fail_closed`
- `test_malformed_tool_metadata_fails_closed`
- `test_malformed_discovery_payload_fails_closed`
- `test_service_metadata_is_not_an_identity_or_authority_claim`
- `test_malformed_or_unsupported_schemas_fail_closed`
- `test_duplicate_identity_rejects_entire_result`
- `test_all_bounds_and_empty_discovery`
- `test_hostile_text_is_inert_and_absent_from_audit`
- `test_unexpected_programming_defect_propagates`
- `test_output_schema_uses_same_fail_closed_profile`
- `test_supported_nested_schema_and_delimiters_inside_strings`
- `test_duplicate_nested_schema_key_is_rejected`

## Patch ownership and repository status

Exactly three files are added; no existing tracked file is modified by this slice:

- `src/harness_engineering/mcp_discovery.py`
- `tests/test_mcp_discovery.py`
- `docs/STORY_8_SLICE_1.md`

No staging or commit was performed. The index remains empty. HEAD remains the
accepted Story 7 commit. Final status contains this patch plus protected foreign
work, including additional Module 7/8 changes that appeared concurrently during
verification. None was modified, staged, or claimed by this slice:

```text
 M module-07/src/reliability_safety_observability/logging.py
 M module-08/docs/IMPLEMENTATION_PLAN.md
 M module-08/docs/TRACEABILITY.md
 M module-08/src/mcp_enterprise_integration/capability_policy.py
 M module-08/tests/test_capability_policy.py
 M module-10/README.md
 M module-10/docs/STORIES.md
 M module-10/docs/TRACEABILITY.md
?? .editorconfig
?? .gitattributes
?? module-06-5/docs/STORY_8_SLICE_1.md
?? module-06-5/src/harness_engineering/mcp_discovery.py
?? module-06-5/tests/test_mcp_discovery.py
?? module-07/docs/STORY-03-IMPLEMENTATION.md
?? module-07/docs/stories/STORY-03-reliability-recovery-boundary.md
?? module-07/src/reliability_safety_observability/reliability.py
?? module-07/tests/test_reliability.py
?? module-08/README.md
?? module-08/docs/stories/STORY-10-integrated-verification-release-evidence.md
?? module-10/.dockerignore
?? module-10/Dockerfile
?? module-10/docs/STORY_10_5.md
?? module-10/scripts/
?? module-10/tests/test_container.py
?? scripts/
```

## Completion boundary

Requirements: partial Story 8 only. Product experience: typed API/tests and this
reviewer document; UI deferred. Real functionality: actual SDK metadata
construction/validation, no protocol calls. Reliability/security: bounded,
atomic, inert discovery with fail-closed validation and adversarial evidence.
Cost: zero paid/external calls. Evidence: deterministic plus SDK construction.
Deployment: not evaluated or claimed. Production-grade Story 8/module completion
and release approval remain pending later slices and required reviews.
