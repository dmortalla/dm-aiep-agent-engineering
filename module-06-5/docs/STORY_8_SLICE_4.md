# Story 8 Slice 4: integrated adversarial MCP lab and exit evidence

Status: implemented for independent review; Story 8 formal closeout and human
acceptance remain pending. Story 9 and the Story 11 reviewer UI are not begun.

## Scope and accepted baseline

Accepted Slice 3 is `cdc59f5279c8a8af1f2ac384253976b9618a29a8`.
Before mutation, it was an ancestor of HEAD
`529cc2293606eb70738581b909bca5737adcc110`; the module-filtered log after
that commit was empty, Module 6.5 was clean, and the index was empty.
Foreign untracked root/Module 7 work was present and protected.

This additive slice introduces exactly:

- `src/harness_engineering/mcp_lab.py`: runnable integration and typed evidence.
- `tests/test_mcp_lab.py`: 22 focused integration/report/failure-contract tests.
- `docs/STORY_8_SLICE_4.md`: this consolidated exit report.

Paths above are relative to Module 6.5. No accepted implementation, dependency,
architecture, requirement, traceability meaning, other module, or repository
PROJECT_STATUS is changed. No staging, commit, push, or history change is made.

Slice 1's `mcp_discovery.py` translates bounded SDK discovery into inert metadata.
Slice 2's `mcp_binding.py` owns trusted registration, opaque identity handles,
current authorization and accepted execution controls. Slice 3's `mcp_local.py`
owns the actual SDK connection, discovery freshness, sealed runtime lifecycle
and protocol result validation. Slice 4 calls these APIs directly and adds no
authorization algorithm, callable resolver, transport, or executor.

## Runnable reviewer evidence

From `module-06-5`, using its Python 3.12 virtual environment:

```powershell
.venv/Scripts/python.exe -m harness_engineering.mcp_lab
```

The command prints `MCPLabEvidence` JSON. Known harness failures print only
`{"passed": false, "error": "mcp_lab_failed"}` to stderr and exit 1.
Unexpected programming defects propagate; they cannot satisfy an expected
remote failure. No credentials, provider configuration, external services,
network connections or paid inference are involved.

Evidence contains ten ordered scenarios and 32 checks, each with a fixed check
identity, security/control explanation, expected and actual typed outcome,
pass flag, measured before/after tool-handler entry counts, output-validation
flag and causal-chain presence flag. Scenario evidence includes finite audit
event enums, discovery/session counters, trusted application capability name,
untrusted candidate classification, consumed calls and cleanup observations.
It is frozen, strict, bounded data suitable for the later UI. Deserializing
evidence grants no authority and does not authenticate its provenance.

Success requires exact expected outcomes and handler deltas. Unexpected
successful denial paths raise `MCPLabFailure`; no partial success report is
returned. Nested models revalidate, reject extra fields, contradictory totals,
missing/reordered scenarios, altered evidence classifications and omitted
nonclaims. Report-contract tests deliberately simulate a denial bypass and a
programming defect and verify fail-closed behavior and resource cleanup.

## Actual SDK path and successful integration

The pinned installed `mcp==2.3.0` SDK is exercised through accepted
`LocalMCPIntegration`: genuine `Server`, client/server memory streams,
`ClientSession`, initialization, `tools/list`, and `tools/call`. The fixture
registers the SDK server's actual `on_list_tools` and `on_call_tool` callbacks;
there is no fake client or session. A server lifespan counter measures entry
and exit. This is a local stand-in for an external ticket system, not an
enterprise deployment or authenticated enterprise service.

Two real tools are discovered. The application registry remains empty after
discovery. The original `read_ticket` candidate remains `untrusted_mcp` with
`grants_authority=False`. Trusted bootstrap explicitly pins its advertised
service/tool metadata and registers the distinct application ID `ticket.read`
with application-owned `TicketQuery`/`TicketSummary` contracts and execution
limits. A current application authorizer permits the read; the accepted runtime
checks authorization and budget, invokes SDK `tools/call`, accepts only its
supported bounded result profile, validates application output and emits
sanitized audit events. A prior successful result never becomes permission.

## Integrated scenarios and observed outcomes

| Scenario | Checks | Tool entries | Expected and observed control |
|---|---:|---:|---|
| Trust boundary | 6 | 0 | Hostile descriptions/instructions do not grant permission; unbound candidate, remote-name confusion, copied and persisted candidates are denied; forged proposal approval is rejected. |
| Current controls | 5 | 1 | Authorized read succeeds; current revocation, broader grant versus application scope, pending approval and off-switch prevent subsequent calls. |
| Application input | 3 | 0 | Malformed types and query beyond application's 64-character bound fail despite remote 1000-character schema; schema-valid UTF-8 input still exceeds the independent serialized-byte budget. |
| Stale discovery | 2 | 0 | Real refresh invalidates the original binding even with equal metadata; a third discovery is denied. |
| Malformed discovery | 2 | 0 | Unsupported SDK tool annotations fail accepted discovery validation; failed refresh also invalidates the old binding. |
| Untrusted results | 5 | 5 | Hostile schema-valid text remains inert data; forged approval field, malformed type and unsupported text content are rejected; hostile SDK error fails without leaking its text. |
| Spent budget | 6 | 1 | First read spends one-call budget; retry, refresh, attempted runtime reset, reconnect and a new genuine protocol object cannot reset or retarget the original runtime. |
| Workflow deadline | 1 | 0 | Actual elapsed workflow time prevents invocation. |
| Protocol timeout | 1 | 1 | SDK I/O bound rejects slow result; cooperative resources finalize and close. |
| Executor timeout | 1 | 1 | Accepted executor bound rejects slow result; cooperative resources finalize and close. |
| Total | 32 | 9 | All expected outcomes hold; zero unbound invocations. |

There are eleven established SDK sessions and thirteen actual discovery
requests. The additional session in the spent-budget scenario performs no
discovery or tool call: the spent original runtime remains spent. Fixture
handler-entry and finalizer counts match after cleanup; these are observations
of cooperative fixture lifecycle, not proof of exactly-once remote effects.

## Authority, bounds, lifecycle and errors

All policy, permissions, identity, scope, approval and budget are trusted
application bootstrap choices. Remote service/tool names are advertised
metadata, not authenticated application identity. Discovery candidate copying,
JSON persistence and agent-shaped approval data do not mint original handles.
Application contracts forbid extra fields and remain authoritative over weaker
remote schemas. Structurally valid hostile output is never executed or used to
select another action. Current authorization is resolved again for invocation
through the accepted bridge; accepted freshness/revocation checkpoints and
non-atomicity are unchanged.

The lab runs one instance per process, ten fixed sequential scenarios, and no
retry loop. Accepted MCP maximum remains twelve tool calls per runtime; the
spent-budget scenario intentionally lowers it to one. Normal scenario workflow
deadline is ten seconds with accepted default per-action limits; I/O is bounded
at two seconds. Timeout cases use 0.25-second protocol or executor limits and
finite cooperative three-second work. Deadline evidence uses actual elapsed
monotonic time, not a monkeypatched clock. Host scheduling must allow handler
entry before the timeout; failure to observe the expected entry fails the lab.
No claim of byte-identical wall-clock execution or hard OS scheduling is made.

Accepted discovery permits initial request plus one refresh, bounded profile
and result sizes, sealed runtime creation and single-use connection lifecycle.
The report caps ten scenarios, sixteen checks each, twelve calls per scenario,
and 128 binding audit events per scenario. Only the fixture's own observed
portal/worker thread objects are joined (two-second bound each); no unrelated
thread enumeration or termination occurs. Context managers close sessions and
streams and cancel/join cooperative work before success evidence is returned.

Failure classification uses accepted exception types and SDK numeric error
codes (`REQUEST_TIMEOUT` and the deliberate fixture error), never remote error
text. Unexpected causal chains re-raise. Top-level accepted errors are checked
for hostile marker leakage. Raw MCP descriptions, inputs, outputs, error
messages, exceptions/causes, UUIDs, handles and policy objects are excluded from
serialized evidence. Only finite audit kinds and causal-presence booleans are
projected. Error chains remain internal diagnostic context and are untrusted.

## Consolidated Story 8 requirement mapping

| Requirement | Accepted implementation and integrated evidence |
|---|---|
| REQ-MCP-001 | Slice 3 real SDK server/client integration plus Slice 2 explicit trusted binding. Lab SDK callback registration, discovered `read_ticket` to distinct `ticket.read` registration and authorized actual call; no implicit remote registration authority. |
| REQ-MCP-002 | Slice 1 bounded untrusted discovery translation; Slice 3 real SDK `tools/list`. Lab verifies empty application registry after discovery, inert candidates, refresh and malformed discovery rejection. |
| REQ-MCP-003 | Accepted registry, current permissions, scope/approval, input/output contracts, executor, budget/deadline/off-switch and lifecycle controls. All ten lab scenarios plus existing `test_mcp_discovery.py`, `test_mcp_binding.py`, `test_mcp_local.py` provide denial/security evidence. |
| REQ-TECH-003 | Installed pinned MCP SDK 2.3.0 has a direct registration, initialization, discovery and invocation role through genuine memory protocol. SDK API and profile constraints are recorded in Slice 3 and exercised here. |
| ENG-002 / ENG-003 | Untrusted candidates/results/errors, copied/persisted metadata and forged approvals never become privileged authority. Typed report is evidence data only. |
| ENG-004 / ENG-005 | Fixed bounded local scenarios, accepted call/deadline/payload limits and cooperative cleanup; no credentials or paid/external operation. |
| ENG-006 / ENG-007 | Explicit deterministic-fixture plus genuine local-integration classification; integrated failure paths, report contradiction checks, denial-bypass and programming-defect tests. |

The accepted requirements and traceability already identify these obligations;
this report supplies verified implementation/evidence detail without changing
their meaning. Accepted Slice 1/2/3 reports remain the detailed low-level
evidence and limitations, rather than duplicating their tests mechanically.

## Verification and captured evidence

Focused repair verification: Ruff passed, then all 22 new tests passed in
1.58 seconds. The initial focused failure was an incorrect test import path;
only that test import was repaired. No accepted behavior or gate was weakened.

Standalone CLI capture passed: ten scenarios, 32 checks, nine protocol handler
entries, zero unbound calls, all cooperative resources closed. Structured JSON
(24,940 bytes, pretty printed) is outside the repository at:

`<LOCAL_EVIDENCE_DIR>/module-06-5-story-08-slice-04-lab-20261015.json`

Final fail-fast sequence on 2026-10-15, from `module-06-5`:

1. `.venv/Scripts/ruff.exe check .` - PASS.
2. `.venv/Scripts/python.exe -m pytest -q --basetemp
   <LOCAL_EVIDENCE_DIR>/module-06-5-story-08-slice-04-final-20261015`
   - **1,164 passed in 347.44 seconds** (1,142 accepted + 22 new).
3. `.venv/Scripts/python.exe -m compileall src tests` - PASS.

No final-suite warnings or failures were reported. The genuine SDK lab and
tests ran with host Windows event loops because those loops stall in the
filesystem sandbox; evidence stayed in the designated external directory.
Source and test files remained unchanged after the final sequence began;
only this report was updated with measured results.

Final HEAD remained `529cc2293606eb70738581b909bca5737adcc110`.
Accepted Slice 3 ancestry passed (exit 0); no intervening commits touched
Module 6.5. The index and tracked Module 6.5 diff were empty. Exactly the
three Slice 4 paths listed above were new/untracked in Module 6.5.
`git diff --check -- module-06-5` passed for tracked content; the new Python
files passed Ruff. No files were staged or committed.

Protected foreign state at final verification included root `.editorconfig`,
`.gitattributes`, `scripts/`, Module 7 Story 4 documentation/telemetry/tests,
and concurrent tracked edits to Module 8's `google_adk_mcp.py` and its test.
Those paths were untouched by this work; their changing status was not treated
as a Module 6.5 isolation failure.

## Evidence limits and review disposition

Maximum classification: **deterministic_fixture + genuine local_integration**.
The final report repeats these twelve nonclaims:

1. SDK memory transport only; no HTTP/stdio production readiness.
2. No live-provider, deployment, or production-readiness evidence.
3. No enterprise authentication or cryptographically verified MCP identity.
4. No OS sandbox or protection against arbitrary hostile Python.
5. Timeout rejects results; it does not forcibly terminate synchronous work.
6. No native remote cancellation guarantee.
7. No exactly-once, atomic, or crash-safe remote effects.
8. Cancellation/revocation checkpoints are not atomic with external effects.
9. Application acceptance bounds apply after SDK model construction.
10. Structurally validated output is data, never permission or approval.
11. Story 9 and the final Story 11 UI are outside this lab.
12. Story 8 closeout requires independent review and human acceptance.

Completion evaluation: requirements have consolidated local evidence; product
experience is a runnable typed CLI for later UI rendering; real functionality
uses actual SDK protocol; reliability/security reuse accepted controls and
bounded cooperative lifecycle; cost is zero paid/provider/external calls;
evidence remains local; deployment and production readiness are not established.
With the final gates passing, Story 8 appears ready for independent closeout
review, not formally accepted or released. Stop here for that review.
