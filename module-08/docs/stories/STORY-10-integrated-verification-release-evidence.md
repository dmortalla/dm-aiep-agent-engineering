# Story 10 — Integrated verification, hardening and release evidence

## Status and baseline

Implemented for independent final acceptance; uncommitted. Audit date: 2026-10-14
(America/Chicago). Baseline HEAD at audit start:
`44571350bdd719afc9a95a68275e0dd4b86fefc7`.
`git merge-base --is-ancestor e16cb6ed122f3a2faa599eb1142e97b24e9dc2c5 HEAD`
returned 0. Module 8 began clean; unrelated changes were present and protected.
The source transcription, all frozen requirements, architecture, both ADRs,
implementation plan, existing story records, source, tests, configuration and
locked dependency environment were inspected. Historical story records remain
historical; this record and traceability describe the final state.

## Bounded changes

One defensible security defect was found: `CapabilityPolicy({})` restored the
default grants because the constructor used truthiness. Only `None` now selects
defaults; an explicit empty allowlist denies every role. Nine regression cases
cover all three default roles and all three discovered capabilities. Existing
default/custom policy tests retain their behavior. No architecture or authority
model changed, and no dependency, live mode, A2A or speculative feature was added.

Added the module README with setup, console instructions, expected real results,
SDK roles, comparison semantics, safety boundaries and limits. Updated the stale
implementation-plan status and completed actual evidence mappings for all 33
requirements in TRACEABILITY.md without changing requirement definitions.

## Ordered Definition of Done audit

| Gate | Assessment and evidence |
|---|---|
| Requirements | 23/23 source REQ and 10/10 ENG supported; individual evidence in TRACEABILITY.md. Transcribed screenshot topics, labs, objective, tools and both deliverables are covered. Original screenshot was not independently re-inspected; the supplied authoritative transcription governs this audit. |
| Product experience | Real self-explanatory Streamlit console; both scenarios exercised by AppTest. Prior human Story 9 review supplied by the user establishes visual acceptance; no new browser visual/accessibility certification. |
| Real functionality | Genuine MCP server/client and Streamable HTTP; discovery, context, SQLite, HTTP API, internal policy, both SDK tool integrations, direct comparison and heterogeneous workflow execute. Conceptual OS/distributed/emerging-standard coverage is grounded explanation. No model reasoning or A2A claim. |
| Reliability | API request/response limits, SDK deadlines, sequential three-stage workflow, 45s workflow and 60s reviewer deadlines, bounded startup/shutdown joins, two concurrent reviewer slots and safe errors. Existing expected-failure tests and database-file release test. No load, availability or hard real-time shutdown guarantee claimed. |
| Security | Application-owned capability policy; discovery gives no grants; denial precedes authorized remote invocation. Workflow rejects malformed, oversized, extra-field and identity-substituted context. Fixed UI identities are explicitly not authentication. Policy evaluation executes no proposed account change. UI errors redact internals with causal chaining. Empty-grant escalation repaired. Source inspection found no embedded credentials. |
| Cost | No key required and no OpenAI/Gemini model or paid provider calls. Reviewer tests remove keys, forbid model runners and reject external socket connections while real loopback services execute. Credential presence grants no execution authority. |
| Evidence | Deterministic contract/policy checks, mocked injected failures, adapter construction and genuine local-integration execution distinguished. UI preserves local classification and limits. No live-provider or deployment evidence. |
| Deployment | Not exercised or established. Local functional/engineering completion is ready for independent acceptance; human release closeout remains required. This does not certify an authenticated or remotely deployed production service. |

All requested functional Definition of Done items are supported within that scope,
including type hints/docstrings, failure handling, runnable UI, encoding, isolation,
traceability and known limitations. Deployment readiness remains explicitly
unverified rather than marked complete. Passing gates alone are not release approval.

## Security and operational limits

`CapabilityPolicy` is an application boundary, not network authentication. Raw
MCP server tools and low-level `invoke_tool` remain integration primitives;
authorized wrappers enforce consumer policy. The supported reviewer path uses
fixed application-owned identities and loopback. Models, requester fields and
MCP output cannot supply its role; returned policy decisions do not grant actual
privileges. Arbitrary remote callers, authenticated server-side authorization,
TLS, multi-host operations, persistence, cloud deployment and autonomous model
execution have not been established. These existing scope limits must remain
visible in any release description. No external service calls were added.

## Dependency, environment and presentation observations

The locked environment uses Google ADK 2.10.0. Module code imports the current
`McpToolset`, not deprecated `MCPToolset`. Installed
`google/adk/tools/mcp_tool/mcp_toolset.py` imports `MCPTool` at line 66 and constructs
it at line 533; `mcp_tool.py` emits the deprecation warning in its `MCPTool` wrapper.
Experimental warnings originate in ADK primitives as shown in pytest's warning
summary. No public deprecated module call needing migration was found. Dependency
internals were not patched, warnings were not suppressed, and the lock was not
changed merely to remove warnings. This is not a dependency vulnerability audit.

The reported exit-0 Windows `pytest-current` cleanup PermissionError is a known
environment/tooling observation. Database closure already has a passing file
release test; no new evidence identifies a Module 8 resource leak. No repeated
temporary-directory investigation or site-package modification was undertaken.
Final-run observation is recorded below with the gate results.

The module Streamlit configuration sets only `primaryColor`; it does not override
text or caption colors. Captions use supported Streamlit elements with inherited
theme styling, so no Module 8 text/background color conflict was identified by
inspection. Prior washed-out secondary text remains a non-blocking,
theme/browser/screenshot-dependent observation. No brittle CSS or forced theme
was introduced. AppTest verifies content/execution, not pixel contrast or WCAG
compliance; a formal contrast audit remains outside this evidence.

## Final verification

Final fail-fast sequence in the module's uv-managed Python 3.12.10 environment:

1. `uv run ruff check .`: passed, exit 0; no auto-fixes needed.
2. `uv run pytest`: **121 passed, 159 warnings in 76.26s**, exit 0.
3. `uv run python -m compileall -q src tests`: passed, exit 0.

The nine added parameterized empty-allowlist cases increase the accepted 112-test
suite to 121. No existing tests or quality controls were weakened. Both real
reviewer AppTest scenarios, SDK integrations, workflow and failure tests passed.
The final pytest run reproduced the known `pytest-current` atexit PermissionError
after success; it did not change exit status and is classified as tooling evidence.

An earlier sandboxed uv invocation could not persist its interpreter-cache file.
Compileall was rerun successfully with normal cache access, then the entire
Ruff → pytest → compileall sequence above passed with that same access. No
application repair, warning suppression or dependency change was needed.

Small native-Python/Git checks verified all **45** tracked/nonignored Module 8
text files decode as UTF-8 without BOM, all Python parses, no cross-module source
or dependency references were found, and completed audit rows cover exactly the
23 REQ and 10 ENG identifiers once each. Project dependencies are standalone;
no workspace/path dependency on another module is configured. `git diff --check
-- module-08` passed. These static checks supplement, not replace, runtime tests.

Exact Story 10 change set (module-relative):

- `README.md` (new).
- `docs/IMPLEMENTATION_PLAN.md` (status only).
- `docs/TRACEABILITY.md` (completion state and actual evidence mappings).
- `docs/stories/STORY-10-integrated-verification-release-evidence.md` (new).
- `src/mcp_enterprise_integration/capability_policy.py` (empty-grant repair).
- `tests/test_capability_policy.py` (nine regression cases).

Only these Module 8 files were edited by this story. No other module/protected
concurrent work was modified by this work; unrelated concurrent changes remain
present. HEAD remains `44571350bdd719afc9a95a68275e0dd4b86fefc7`, with the accepted
Story 9 commit still an ancestor. Nothing was staged, committed, tagged or pushed.

Ready for independent final acceptance and human release closeout of the local
academic module, subject to the explicit limitations above. No live-provider or
deployment evidence exists and no deployment approval is implied.

## Verified Deployment Closeout

Post-release deployment verification completed successfully in Streamlit Cloud.

Verified evidence:

- Full Streamlit Cloud reboot loaded the current Module 8 instrumentation.
- Manager review completed successfully.
- Reviewer-visible result: local enterprise execution completed and results validated.
- Discovered capabilities: 3.
- Workflow MCP stages: 3.
- Model calls: 0.
- Cloud dependencies were installed from module-08/uv.lock through uv-sync.
- GOOGLE_API_USE_CLIENT_CERTIFICATE=false disabled an unnecessary Google client-certificate credential probe for the credential-free loopback MCP deployment.
- The accepted repair removes the ambient-credential dependency rather than weakening the bounded discovery timeout.

Evidence classification: deployed reviewer demonstration and local enterprise integration evidence. This does not claim paid-provider inference, external enterprise production traffic, multi-host deployment, or cloud-managed MCP infrastructure.

The engineering release tag remains immutable; deployment-closeout documentation is post-release evidence and does not rewrite the accepted release.
