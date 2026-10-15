# Story 8 Slice 2 — Trusted binding and bounded callable invocation

## Scope and baseline

This slice implements application-owned registration/binding and invocation of
SDK-derived MCP candidate metadata through accepted local controls. It advances
REQ-MCP-001 through REQ-MCP-003 and REQ-TECH-003; ENG-002 through ENG-007 apply.
It does not complete those requirements' final protocol/integrated exit proof.
Slice 3 server/client transport and Slice 4 integrated lab remain unimplemented.
No final reviewer UI or Story 9–12 functionality is added.

Initial HEAD was `220870b23996922dbde9795044dfeff9a30ede65`, the accepted Slice 1
commit. Ancestry passed, there were no intervening Module 6.5 commits, Module 6.5
was clean, and the index was empty. Foreign root and Module 7/8 work was observed
and protected. No staging or commit is performed by this slice.

Inspection covered the authoritative source, frozen architecture/ADR,
requirements, traceability, implementation plan, repository SOP, accepted
Slice 1 implementation/tests/report, capability registry, authorizer, executor,
domain budgets/identity/errors, lifecycle/off-switch, and audit-related contracts.
No accepted implementation, architecture, requirement, dependency declaration,
lockfile, or canonical PROJECT_STATUS change is required.

Python is 3.12.14; the installed MCP SDK remains 2.3.0. The accepted discovery
translator continues to validate with actual SDK models. No dependency or
environment installation was needed for this slice.

## Trusted configuration and authority boundary

`MCPBindingRegistry.register(TrustedMCPBinding(...))` is a **trusted application
bootstrap operation**, just like installing accepted capability policies or
local tool handlers. Validation, object type, remote identity, and schema
validity cannot establish the caller's provenance. Never expose bootstrap or
runtime construction as a tool available to models, agents, or contextual data.
This is not protection against arbitrary hostile Python in the same process.

The bootstrap declaration supplies:

- Explicit expected advertised service name/version and remote tool name.
- The original inert candidate selected by the application.
- A separate application CapabilityDefinition, with application-declared
  Pydantic input/output classes and description.
- An actual callable adapter, a trusted current-candidate callback, and accepted
  ExecutionLimits.

Metadata never resolves a callable from a string or replaces an application
contract. Raw dictionaries and candidate-only registrations are rejected.
There is no binding deserializer, metadata loader, or automatic registration.
Schemas are revalidated by accepted contracts; constructed candidate metadata is
revalidated through the unchanged Slice 1 public translation boundary before
registration. Canonical schema snapshots must remain exact.

Expected service/tool comparisons detect configuration mismatch, not identity
authentication or authority. The callable and application contract originate
only from trusted configuration. Matching remote metadata, including an exact
trusted-looking name, cannot create that configuration or grant permission.

The fixture remote tool is `search`; the application capability is
`enterprise.read`. There is no implicit mapping between them. Only the explicit
application identity is registered in the accepted CapabilityRegistry.

Registration returns a fieldless MCPBindingHandle. Execution requires the
original object by identity, bound to the exact application capability. A new
handle, copied handle, other registration set's handle, serialized metadata,
candidate, audit record, or binding-shaped dictionary is not accepted. Possessing
the original handle still grants no permission: current authorization is always
required. Opaque handles are process-local configuration objects, not credentials.

## Binding integrity and freshness

Declarations and installed references are frozen. Registration rejects both
duplicate application identity (via the accepted registry) and duplicate remote
service/version/tool identity, including identical or conflicting rebinding.
Registration is bounded to 100 bindings. Validation precedes registry mutation;
expected validation/conflict failures do not leave partial registration.

The registry seals on successful creation of one workflow runtime. It cannot
then register replacements or create a fresh executor to reset that runtime's
budgets. Its accepted metadata registry remains available to trusted bootstrap;
adding inert metadata there cannot add a runtime handler or bypass the handle
and exact application-identity checks.

At invocation, the trusted current-candidate callback must still return the
original pinned candidate object. None, an equal reconstructed copy, changed
schema/service/tool metadata, or a newly discovered object fails closed. A new
discovery therefore requires a new explicit trusted binding decision; equality
does not silently refresh authority. This is in-process staleness detection,
not a TTL, network service attestation, or cryptographic freshness mechanism.
Re-entry/recovery must still obey the accepted Story 6/7 lifecycle and consumed
budgets; this slice supplies no recovery or remote-effect replay authority.

## Current authorization and execution controls

The bridge owns one persistent accepted BoundedToolExecutor. It does not implement
parallel permission rules, retry/fallback routing, timeout waiting, payload
validation, call accounting, or worker lifecycle.

A narrow CapabilityAuthorizer subtype delegates to the current **accepted**
CapabilityAuthorizer returned by trusted application bootstrap. The delegate
implements no permission policy. The resolver must return the correct current
registry/principal/workflow authority; contextual data cannot select or replace
that resolver. The fixture replaces immutable policy/grant snapshots without
rebuilding the executor, proving revocation after binding and prior success.

The accepted executor invokes authorization in its bounded worker. Immediately
before the protected adapter, the bridge checks the original candidate, resolves
current authorization again, and checks the accepted ExecutionContext deadline.
The second evaluation closes the stale-permission gap during freshness lookup.
The existing OffSwitch is checked before/after authority lookup and late output
is rejected if cancellation activates during the adapter. No approval token or
serialized AuthorizationDecision is accepted. APPROVAL_REQUIRED remains a denial;
the bridge does not consume or fabricate durable human approvals.

Accepted bounds remain authoritative:

- One executor worker slot, workflow call budget and workflow deadline.
- Per-action/capability timeout and cooperative ExecutionContext work checks.
- Input/output byte limits and strict application Pydantic validation.
- Failed calls consume accepted accounting; there is no automatic retry.

The bridge adds a nonwaiting invocation lock for correlation state, not a
separate call/deadline budget. A timed-out callback continues to occupy the
accepted worker slot until it exits. A stuck current-authority or freshness
callback has the same cooperative bounded-wait limitation. All bootstrap
callbacks must use bounded operations; this seam performs no protocol I/O.
Accepted call accounting charges entry into the adapter wrapper; a later
freshness/authorization denial can consume a call without invoking the protected
adapter. It must not be interpreted as an external effect count.

Cancellation and revocation checks are execution checkpoints, not an atomic
transaction with external effects. There is no forced callback termination or
linearizable cancellation/revocation guarantee across arbitrary Python/I/O.

## Validation, failure semantics, and audit

Application schemas remain authoritative even when advertised schemas accept a
wider input. Malformed input fails before the adapter. Output remains untrusted
until accepted output-byte and Pydantic checks succeed. Returned text is data;
it cannot select another action, change policy, or dispatch another capability.

Only known application boundary exceptions raised by the adapter that the
accepted executor would otherwise pass through are given sanitized top-level
messages, preserving their category and causal context. Other handler failures
follow accepted executor semantics: ToolExecutionError with the original cause,
not a fabricated remote/schema validation failure. Unexpected defects outside
the worker propagate unchanged. There is no blanket exception swallowing.
Diagnostic exception chains may contain untrusted sensitive text and must not
be logged indiscriminately; audit never copies exception text or payloads.

Audit is an immutable tuple snapshot of a thread-safe ring of the most recent
128 events. Records contain only a local operation UUID and a fixed event enum:
registered/requested/authorized/invoking/validated/denied/invalid/budget/timeout/failed.
No remote identity, description, schema, argument, output, secret, handler,
permission, or runtime object is embedded. Operation UUIDs are correlation only.
Registration validation failures are also captured. Retention/aggregation beyond
the ring is not supplied; it is not a durable audit store.

Pre-execution denials have no invoking event. If cancellation or an adapter
authority failure occurs after the callable starts, the terminal event is failed,
not denied, so audit cannot falsely claim non-execution. Invalid output, timeout,
or other post-invocation failure likewise does not prove absence of effects.
No result is accepted after a bounded-wait timeout. The audit cannot authorize
re-entry, replay, approval, or another invocation.

## Deterministic adversarial evidence

`tests/test_mcp_binding.py` adds 74 parameter-expanded cases, using the actual
accepted registry, authorizer, executor, budgets, context, and off-switch.
The unchanged 75 Slice 1 tests remain part of regression coverage.

Coverage includes original-handle enforcement, candidate-only denial, distinct
identities, model/agent/persisted/forged data, duplicate/conflicting bindings,
service/tool/version/schema mismatch, immutable/sealed bindings, registration
bounds, strict application input/output, advertised-schema weakening attempts,
current scope/permission/allowlist/blocklist/approval checks, revocation during
freshness lookup, off-switch before/during invocation, stale/equal-copy metadata,
budget/deadline/timeouts and retained busy worker, work/payload limits, remote
error sanitization and causal context, expected worker defect semantics,
propagating bridge defects, inert hostile result text, sanitized bounded audit,
and inability of audit or serialized metadata to recreate callable authority.

## Evidence classification and nonclaims

Evidence is **deterministic_fixture + local_integration** of actual accepted
application components over a deterministic callable seam. Fixtures also reuse
the actual SDK discovery validation established in Slice 1. There is no MCP
ClientSession, server, protocol invocation, transport, live service, network call,
credential, provider, paid service, or external infrastructure in this slice.

No claims are made for enterprise authentication, cryptographic service identity,
production deployment/readiness, OS sandboxing, forced synchronous callback
termination, exactly-once execution, atomic external effects, crash-safe remote
effects, final Story 8 completion, final reviewer UI, or later-story features.

## Files and quality gates

Exactly three additive files belong to this slice:

- `src/harness_engineering/mcp_binding.py`
- `tests/test_mcp_binding.py`
- `docs/STORY_8_SLICE_2.md`

Ruff and the targeted 149-case MCP test run passed. Final full fail-fast gates
passed in order on the final source/test patch:

1. `.venv/Scripts/ruff.exe check .` — PASS.
2. `.venv/Scripts/python.exe -m pytest -q -x --basetemp
   E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-08-slice-02-final-20261014`
   — **1,112 passed in 347.76 seconds** (1,038 accepted + 74 new).
3. `.venv/Scripts/python.exe -m compileall src tests` — PASS.

The full run used access to the designated external EVIDENCE directory rather
than changing source/tests to accommodate sandbox temporary-directory restrictions.
No unsafe fixes were used. The report was updated afterward with these results;
source and tests were unchanged after the final gates began.

## Final isolation and repository status

At final verification HEAD was `06f1c8e34fcc8f7958e7e7e69057aaec731a2957`.
The accepted Slice 1 baseline remained an ancestor (exit 0); the module-filtered
commit log since that baseline was empty. Concurrent foreign commits were
therefore acceptable continuation state. No tracked Module 6.5 files changed,
the index was empty, and the only new Module 6.5 files were the three listed
above. `git diff --check -- module-06-5` reported no tracked whitespace issues.
No staging or commit was performed.

Final `git status --short` snapshot:

```text
?? .editorconfig
?? .gitattributes
?? module-06-5/docs/STORY_8_SLICE_2.md
?? module-06-5/src/harness_engineering/mcp_binding.py
?? module-06-5/tests/test_mcp_binding.py
?? module-07/docs/stories/STORY-04-neutral-telemetry-observability-boundary.md
?? scripts/
```

Root, Module 7, and Module 8 foreign state evolved during the run as other work
was committed. None was modified, staged, reverted, or claimed by this slice.

## Completion evaluation

Requirements: bounded Slice 2 implementation only. Product experience: typed API,
tests, and this review document; UI deferred. Real functionality: local accepted
component integration, without MCP protocol. Reliability/security: current
authority, pinned bindings, accepted bounds, and adversarial evidence. Cost: no
paid/external calls. Evidence: deterministic plus local application integration.
Deployment/release: not evaluated or claimed. Stop for independent review before
Slice 3. No accepted-code, architecture, dependency, or isolation conflict was
found that requires an amendment.
