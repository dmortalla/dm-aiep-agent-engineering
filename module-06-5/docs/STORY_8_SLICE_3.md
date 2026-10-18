# Story 8 Slice 3 — Genuine local MCP SDK integration

## Scope and isolation

This additive slice advances REQ-MCP-001/002/003, REQ-TECH-003, and ENG-002 through
ENG-007 with a real SDK server/client/protocol path through accepted discovery,
trusted registration, authorization, and execution. It does not implement the
Slice 4 integrated adversarial lab, Story 8 closeout, Story 9, or reviewer UI.

Accepted baseline: `a9297817f45acd88308a145b6eb8da1645e49337`.
Starting HEAD: `50e811f6f0c852710eb5798c8817c00549acd2c6`.
Ancestry passed; the module-filtered commit log after the baseline was empty.
Module 6.5 was clean, the index empty, and root/Module 7 untracked concurrent
work was protected. No accepted source, tests, architecture, requirements,
dependency declarations, lockfile, or PROJECT_STATUS files are changed.

Inspection covered source authority, requirements, traceability, frozen
architecture/ADR, implementation plan, SOP, Slice 1/2 source/tests/reports,
capability registry, permissions, executor, domain budgets, errors, and off-switch.
No architecture, dependency, or accepted-implementation amendment was necessary.

## Actual installed SDK and selected transport

Python 3.12.14, MCP/mcp-types 2.3.0, and jsonschema 4.26.0 remain unchanged.
AnyIO is an existing locked SDK dependency; nothing was installed or upgraded.
Installed signatures/source and a bounded protocol probe verified:

- `Server(name, version=..., on_list_tools=..., on_call_tool=..., lifespan=...)`.
  SDK 2.3.0 uses constructor callbacks, not older `Server.list_tools` decorators.
- `Server.create_initialization_options()` and `Server.run(read, write, options)`.
- `create_client_server_memory_streams()` creates two bidirectional stream
  endpoints with capacity **one**, carrying genuine SDK SessionMessage/JSON-RPC
  requests/responses. This is SDK in-process memory transport, not HTTP or stdio.
- `ClientSession(..., read_timeout_seconds=...)`, `initialize()`, `list_tools()`,
  and `call_tool(name, arguments, read_timeout_seconds=..., ...)`.
- `CallToolResult` supports heterogeneous content, arbitrary structured content,
  `is_error`, result types, and metadata. These are not assumed interchangeable.
- `MCPError(code, message, data=None)` is the actual protocol exception API.
- SDK native output-schema validation remains enabled. Its possible programming
  or validation exceptions are not blanket-caught as remote failures.

The actual memory probe negotiated protocol **2025-11-25**, completed initialize,
tools/list and tools/call, then shut down. This deterministic local transport
needs no external service, network transport, credentials, subprocess, or model.
It supplies genuine SDK protocol evidence without production transport claims.

SDK-normalized listing models include `ttlMs=0` and `cacheScope=private`, even
when omitted on the negotiated wire. The adapter requires precisely these
defaults, then removes only these two verified envelope defaults before calling
unchanged Slice 1 translation. Other fields remain subject to Slice 1's strict
profile. Legacy protocol cache-hint normalization and SDK model normalization
are not represented as raw packet validation. Unsupported annotations are tested
using SDK-supported fields that actually survive protocol transmission.

## Application architecture and lifecycle

`LocalMCPIntegration` is a synchronous, single-use trusted-bootstrap context:

1. Start an AnyIO blocking portal with its own named asyncio thread.
2. In one owner task, open SDK memory streams, the SDK server task group, and
   the SDK ClientSession. Initialize using the actual protocol.
3. `discover()` performs one actual tools/list and passes SDK-normalized service
   and tool metadata through accepted `translate_discovery`. No pagination loop.
4. Trusted application code explicitly selects an original candidate and calls
   `register` with expected remote identity, independent CapabilityDefinition
   (application ID and Pydantic schemas), and accepted ExecutionLimits.
5. The adapter installs its explicit callable in an unchanged TrustedMCPBinding.
   Current-candidate lookup returns only the same pinned original object.
6. Trusted code creates the sole Slice 2 runtime with current accepted authorizer,
   workflow budget, and existing OffSwitch. This entry point rejects max_tool_calls
   above **12**; all actual call accounting remains in the accepted executor.
7. An accepted executor worker authorizes/validates, then submits one SDK call
   to the portal. The coroutine rechecks candidate freshness and its accepted
   ExecutionContext immediately before protocol invocation.
8. Validate the protocol result profile, snapshot bounded structured JSON, and
   let the accepted executor apply its authoritative output schema/byte bounds.
9. On context exit, invalidate all current candidates, close the client, cancel
   and join cooperative server tasks, close streams, and join the portal thread.

No public raw-call API or string-to-callable resolver is introduced. Registration
and runtime creation are trusted application operations, never agent tools or
metadata deserialization paths. Expected advertised service/tool names are
configuration checks, not authenticated identity. Server instructions, names,
schemas, annotations, results, and error text cannot supply permission.

The fixture remote name is `echo`; its application ID is `app.echo`. Another
discovered tool, `unbound`, never becomes executable automatically. Original
handles, current permission/scope/approval policy, off-switch, input/output
contracts, and budgets remain enforced by accepted code.

Bootstrap operations must be serialized by their trusted owner. Initial
discovery plus one explicit refresh are permitted; a third request fails closed.
Each attempt invalidates the previous candidate snapshot, including on failure.
This administrative setup bound is not a competing tool-call counter. There
are no automatic retries, multi-round input resolution, pagination, or polling.
The <=12 protected invocation budget belongs solely to the existing executor.
SDK cache population prevents hidden rediscovery on the tested invocation path.

Refresh, close, and foreign/copied candidates cannot reauthorize an old binding.
The connection cannot reenter/reconnect, and creating another protocol object
cannot reset or retarget the original runtime's spent budget. Creating a genuinely
new workflow is still a trusted application decision, subject to accepted
recovery/consumed-budget rules; this adapter supplies no recovery/replay authority.

## Deliberately narrow result profile

Accept only an actual complete CallToolResult with `is_error=False`, empty content,
no metadata/extra model fields, and a structured JSON **object**. Text/image/audio/
resource content, mixed content, absent/list structured data, input-required or
extension result types, and error results are unsupported and fail closed.
`allow_input_required`/`allow_claimed` return unusual shapes for rejection; they
do not authorize follow-up requests or dispatch another capability.

Structured data is bounded to 16 levels, 4,096 visited values, 4,096 entries per
container, 128-character keys, 16,384-character strings, and 65,536 serialized
bytes; only finite JSON values are accepted. A fresh JSON snapshot disconnects
mutable SDK data. Accepted executor byte limits and strict Pydantic contracts
then apply, often more tightly. The fixture advertises a 1,000-character input
but the application permits only 20; invalid inputs produce no protocol call.

These are application acceptance bounds **after SDK model construction**. They
are not byte-framing, pre-deserialization memory limits, or protection against
hostile Python fixtures. SDK normalization may discard unsupported wire fields;
discarded data cannot mint a binding or authority. Retained structured authority
fields are rejected by application extra-field validation. Hostile strings in
otherwise valid answer data stay inert and never cause a second tool call.

## Failure, timeout, cancellation, and cleanup semantics

Initialize, discovery, and each protocol call have a configurable finite I/O bound
in (0, 30] seconds (default 2). Bootstrap I/O has its own bounded lifecycle;
accepted workflow call/deadline budgets begin with accepted runtime creation
and are never recreated by discovery or transport activity. Accepted action and
workflow deadlines can reject before any protocol handler runs.

TimeoutError maps to ToolTimeoutError; MCPError/SDK validation/closed-stream
failures map to sanitized LocalMCPError with causal context. SDK read-timeout
races can therefore surface as LocalMCPError, still bounded and fail-closed.
Remote `is_error` content is rejected without copying it into an exception.
Diagnostic chains containing SDK errors are untrusted and must not be logged
indiscriminately. Unexpected defects follow accepted semantics, including worker
ToolExecutionError with its original cause; there is no blanket catch.

An executor timeout rejects output and may leave its worker/protocol request
active until the I/O bound or context cleanup. Closing the owner cancels SDK
tasks and cooperative async fixture handlers. Tests verify handler finally
execution, inactive server lifespan, no surviving portal thread, and bounded
join of cooperative executor workers after timeout. Caller exceptions preserve
identity while protocol resources are cleaned up.

There is no claim of native remote cancellation, forced synchronous termination,
atomic cancellation/revocation with external effects, exactly-once execution, or
crash-safe/atomic remote effects. Trusted fixture callbacks must cooperate;
arbitrary blocking Python or cancellation suppression can delay cleanup. That
accepted in-process limitation is not a production sandbox or shutdown guarantee.

## Audit, tests, evidence, and nonclaims

Discovery returns accepted bounded Slice 1 audit. Registration/invocation uses
the accepted 128-event sanitized ring and operation IDs, not a parallel telemetry
store. Initialization/protocol failures carry fixed application errors; no raw
payload/error text is copied to application audit or logging. Neither audit nor
correlation identifiers grant authority or recovery permission.

`tests/test_mcp_local.py` adds **30** actual-protocol cases: initialization,
discovery, authorized invocation, no implicit registration/execution, unbound
and remote-name denial, stricter application input/output schemas, current
permission/off-switch/stale-identity denials, malformed schema/duplicate/paginated/
oversized/annotation discovery, malformed result envelopes and unsupported result
profiles, hostile inert answer data, protocol errors and no retry, accepted call
budget retention across refresh/other protocol objects, max-12 enforcement,
foreign candidate rejection, protocol/executor timeouts, workflow deadline,
cooperative server/client/worker cleanup, and caller exception identity.

Evidence: **deterministic_fixture + genuine local_integration** over the installed
SDK memory transport. No live external service, enterprise authentication,
cryptographic identity, network/stdio transport readiness, deployment,
production readiness, OS sandboxing, live-provider spend, final Story 8 completion,
final reviewer UI, or Slice 4/later-story functionality is claimed.

## Files and verification

Only these files are added:

- `src/harness_engineering/mcp_local.py`
- `tests/test_mcp_local.py`
- `docs/STORY_8_SLICE_3.md`

Ruff and the targeted MCP suite passed: **179 tests in 2.40 seconds** (30 new +
149 accepted Slice 1/2 cases). Sandboxed Windows event-loop probes
stalled before execution and were stopped; the host probe and genuine SDK tests
completed normally with approved host access. No dependency/architecture workaround
or accepted-code change was made.

Final fail-fast gates passed on the final source/test patch:

1. `.venv/Scripts/ruff.exe check .` — PASS.
2. `.venv/Scripts/python.exe -m pytest -q -x --basetemp
   <LOCAL_EVIDENCE_DIR>/module-06-5-story-08-slice-03-final-20261015`
   — **1,142 passed in 494.07 seconds** (1,112 accepted + 30 new).
3. `.venv/Scripts/python.exe -m compileall src tests` — PASS.

No warnings or failures occurred in the final gates. Source/tests were unchanged
after those gates began; only this report was updated with their results.

At final verification, HEAD remained
`50e811f6f0c852710eb5798c8817c00549acd2c6`. Accepted Slice 2 ancestry passed
(exit 0), and the module-filtered commit log after that baseline remained empty.
The index was empty, there were no tracked Module 6.5 modifications, and exactly
the three intended Slice 3 files were untracked. No staging, commit, push,
history/tag change, or foreign mutation was performed.

Final `git status --short`:

```text
?? .editorconfig
?? .gitattributes
?? module-06-5/docs/STORY_8_SLICE_3.md
?? module-06-5/src/harness_engineering/mcp_local.py
?? module-06-5/tests/test_mcp_local.py
?? module-07/docs/stories/STORY-04-neutral-telemetry-observability-boundary.md
?? scripts/
```

The root and Module 7 entries are protected pre-existing concurrent state and
were untouched. `git diff --check -- module-06-5` reported no tracked whitespace
issues; newly added Python files passed Ruff.

Completion evaluation: requirements advanced for this slice; product experience
is API/tests/documentation, UI deferred; real functionality is actual SDK protocol;
reliability/security use accepted controls plus bounded profile validation;
cost is zero paid/external calls; evidence is local integration; deployment and
release are not evaluated or claimed. Stop before Slice 4 for independent review.
