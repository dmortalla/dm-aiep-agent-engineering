# Story 9 Slice 2: optional OpenAI and Anthropic SDK adapters

Implemented for independent review. Story 9 is not closed; Guardrails AI remains
deferred. No UI, Story 10+ work, status update, staging or commit is included.

## Baseline, scope and requirements

Accepted Slice 1: `22fa61c0f5290075c698b6ac3b05597469f02e12`, 1,223 tests.
Initial HEAD: `fec6e016aa93cf693d2a8d2b38f1b10d59f46b4e`. Ancestry passed
(exit 0), no intervening commits touched Module 6.5, the module had no tracked
changes, and the index was empty. Foreign dirty/untracked work was protected.

Controlling source, requirements, traceability, frozen architecture, plan and
accepted Slice 1 report/source/tests were inspected before implementation.
The plan assigns Story 9 REQ-SAFE-001, REQ-TECH-006/008/009 and
ENG-002/003/005; ENG-004/006/007 also govern bounds, evidence and tests.
The frozen architecture already requires both optional vendor adapters behind
the neutral protocol. Guardrails AI is separable and additive, so remains for
a later Story 9 slice. No requirement or architecture meaning is changed.

| Requirement advanced | Slice 2 evidence |
|---|---|
| REQ-TECH-008 | Genuine installed OpenAI client construction, Responses request serialization, response parsing and SDK exceptions over in-memory HTTP. |
| REQ-TECH-009 | Genuine installed Anthropic client construction, Messages request serialization, response parsing and SDK exceptions over in-memory HTTP. |
| REQ-SAFE-001 | Both adapters feed accepted application text validation, byte bounds and OutputFilter; unsupported vendor output fails closed. |
| ENG-002 / ENG-003 | Vendor objects stay behind adapters. Results remain `untrusted_model`, never permission, routing, approval, capability or budget authority. |
| ENG-004 / ENG-005 | Accepted attempt/retry/deadline/off-switch controls remain authoritative; SDK retries disabled; fake remains default; deterministic evidence needs no real keys or network. |
| ENG-006 / ENG-007 | Explicit mocked-HTTP/SDK evidence classification and 84 new adversarial/failure tests. |

REQ-TECH-006 is deferred, not satisfied by native filtering. These are additive
implementation/evidence advances, not formal Story 9 or requirement closeout.

Exact files relative to Module 6.5:

- Modified `src/harness_engineering/providers.py`.
- Added `src/harness_engineering/vendor_providers.py`.
- Added `tests/test_vendor_providers.py`.
- Added `docs/STORY_9_SLICE_2.md`.

## SDK contracts actually verified

The existing optional `providers` extra was absent from the active environment.
`uv sync --frozen --extra providers --inexact` installed the already locked
packages while preserving existing packages. No dependency/lockfile changed.
Verified installed versions: OpenAI **2.54.0**, Anthropic **1.13.0**,
httpx **0.28.1**, httpx2 **2.13.1**, Python 3.12.

Installed signatures/source and offline requests established:

- `openai.OpenAI(http_client=..., max_retries=0, timeout=..., base_url=...)`;
  `responses.create(model=..., input=[user text], max_output_tokens=...,
  store=False, stream=False, tools=[], tool_choice="none", timeout=...)`.
  This installed SDK uses **httpx**, despite newer documentation also describing
  httpx2 paths. Its SDK `Response` is independently checked at the app boundary.
- `anthropic.Anthropic(http_client=..., max_retries=0, timeout=..., base_url=...)`;
  `messages.create(model=..., messages=[user text], max_tokens=...,
  stream=False, timeout=...)`. This SDK uses **httpx2** and returns SDK `Message`.
- Both expose `APIStatusError`, `APIConnectionError`, `APITimeoutError` and
  `APIResponseValidationError`; Anthropic also raises `CredentialsError` for
  missing profile configuration. Tests use genuine parsed SDK responses and
  genuine generated/constructed SDK errors, not fabricated SDK-shaped sessions.
- Both SDK constructors default to two retries. Explicit zero disables these;
  HTTP tests for 408/409/429/5xx and other statuses observe exactly one HTTP
  request per charged application attempt, with no hidden SDK retries.

Official cross-checks: [OpenAI Python SDK reference](https://developers.openai.com/api/reference/python)
and [Responses create reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
Installed source/signatures and observed offline behavior control version-specific
claims here; no model availability or live compatibility was inferred.

## Application-owned trust and execution boundary

`ModelProvider`, `ModelRequest`, `ModelResult` and `ProviderRuntime.generate`
retain their accepted semantics. Runtime binding now admits only exact
`OpenAIProvider`/`AnthropicProvider` types in addition to the exact fake. It does
not trust an arbitrary adapter's declared locality or authority. SDK imports
are lazy; default fake operation still works with optional SDKs unavailable.

Bootstrap chooses the model identifier; generated data cannot choose SDK
methods, endpoints, tools, callbacks, policies or model configuration. Each SDK
client is call-local and closed before returning application data. Clients,
raw responses, diagnostics, metadata, credential objects and usage objects
are never placed in application results or workflow/checkpoint state.

The provider context carries runtime-owned input/output limits, remaining
deadline and live permission. No invocation accepts overrides for these.
Existing workflow limits remain eight attempts, two retries per action,
12,000 input and 2,000 output limits, 30-second action timeout and 180-second
workflow deadline; tighter configured values remain authoritative. SDK calls
receive the actual remaining time, not a fresh action timeout. Their output
token parameter comes directly from the runtime's accepted output budget.
Input validation and attempt charging precede SDK invocation, and failures
consume attempts. No new retry classification, automatic retry, re-ask or
fallback is introduced. Known provider failures still stop the accepted graph
without granting routing authority; audit distinguishes expected failure from
an unexpected defect.

Accepted off-switch/deadline checkpoints run before invocation and after SDK
work/validation. The accepted runtime rejects late results and retains its
active worker slot until cooperative completion. SDK phase timeouts are not a
guarantee of native remote cancellation or forced termination. They cannot
widen the application's result-acceptance deadline.

Endpoints are fixed vendor HTTPS endpoints. Owned HTTP clients disable proxy
environment lookup and redirects. Offline construction requires an exact
httpx/httpx2 `MockTransport` and supplies fixed dummy credential configuration;
HTTP handlers never reach sockets. Tests replace the environment mapping
without reading/copying real values and redirect Anthropic's profile-location
hint to an empty directory under the fresh EVIDENCE basetemp. No real key is
required, read, copied into fixtures, validated against a service or transmitted.

Live transport binding defaults to denied. It requires trusted
`HarnessConfig(deterministic_mode=False, allow_live_providers=True)` with the
same runtime budget and an explicit finite positive monetary configuration.
Credential presence cannot satisfy this gate. Direct vendor invocation with a
default context also cannot use live transport. The SDK's environment-variable
OpenAI configuration mechanism remains supported only after these gates.
The human's key-reuse decision authorized keeping that mechanism, not any
live/paid execution; no live client with the real key was constructed here.

The monetary configuration is an opt-in precondition, **not** measured USD
accounting or proof that a provider's invoice fits that value. Pricing,
attribution, spend alerts and dollar consumption enforcement remain Story 10.
Any actual paid verification still requires separate explicit human approval.

## Response acceptance and failures

SDK model construction is not trusted validation. Exact SDK result types are
translated through a finite primitive profile: at most 4,096 visited values,
12 nesting levels, 256 members per container, 16,384 UTF-8 bytes per string
and 65,536 serialized bytes overall. Non-finite data and unknown top-level
fields are rejected. These are acceptance limits after SDK parsing; they do
not bound the SDK's initial HTTP buffering/model allocation.

OpenAI requires a completed response with no error/incomplete reason, empty
metadata, one completed assistant message and only plain output-text blocks.
Anthropic requires an assistant message ending naturally with only text blocks,
no container/diagnostics/stop details. Both require one to eight nonempty text
blocks and bounded valid primary input/output usage counts. Tool/function/action blocks, mixed tool
output, refusals, truncated/incomplete results, citations/annotations and other
unsupported profiles are rejected. Models emitting reasoning/thinking blocks
are outside this deliberately narrow profile. No output is truncated into
apparently valid success.

Accepted text becomes only `{"text": ...}` before existing runtime validation,
filtering and fresh `ModelResult` construction. Hostile instructions or
JSON-looking authority claims inside text remain inert text; they are not
interpreted. Byte-budget enforcement remains the accepted conservative local
estimate, separate from vendor usage. Reported usage is validated data, not
billing truth or permission to increase limits.

Expected timeout, transport/status, SDK validation/JSON-decode and missing
configuration errors map to specific fixed application exceptions. Raw SDK
errors may contain keys, HTTP objects, body text or profile paths, so the
public error is raised outside the SDK exception scope with only a fixed local
category as its cause. The raw SDK exception is not retained in the public
chain. Tests check formatted tracebacks, cause/context and sentinel exclusion.
No message parsing controls retry, authority or classification.

The installed OpenAI constructor can accept empty primary credentials when
an ancillary admin setting is present; the adapter therefore checks missing
primary configuration before request creation. Anthropic's missing config
may raise its credential-profile error during construction or otherwise a
generic header-construction TypeError; known absent configuration is checked
before calling Messages. Credential contents and service validity are not
inspected. Unexpected RuntimeError/TypeError/import defects remain defects and
propagate unchanged rather than being caught as generic provider failures.

The application logs no SDK request/response or credential. Its audit remains
finite enums and counters, never raw diagnostics. External SDK/debug logging
must not be treated as sanitized application evidence or enabled to capture
secret-bearing internals. No semantic redaction/safety completeness is claimed.

## Verification and disposition

Focused final verification: Ruff passed, then **143 provider tests passed in
13.07 seconds** (59 accepted + 84 new). Earlier runs exposed an isolated
fixture missing a profile-directory hint, a cold-import deadline assumption,
and the actual SDK missing-configuration behaviors above. Repairs preserved
all accepted security tests/controls; no SDK request or app validation boundary
was patched away to obtain success. Only selected failure-injection tests
replace SDK methods with explicit errors/no-request sentries.

Coverage includes translation/alignment, malformed/empty/unsupported content,
authority/tool-shaped output, hostile inert text, oversized/non-finite data,
SDK error/status sanitization, no hidden retries, missing SDK/configuration,
shared budgets/filtering, deadline propagation, before/during cancellation,
active-worker timeout behavior, cleanup and unchanged programming defects.
Socket connect/DNS paths are forbidden in the new tests.

Final full-module fail-fast results on 2026-10-16, from `module-06-5`:

1. `.venv/Scripts/ruff.exe check .` - PASS.
2. `.venv/Scripts/python.exe -m pytest -q --tb=short --basetemp
   <LOCAL_EVIDENCE_DIR>/module-06-5-story-09-slice-02-final-20261016`
   - **1,307 passed in 375.13 seconds** (1,223 accepted + 84 new).
3. `.venv/Scripts/python.exe -m compileall src tests` - PASS.

No final-suite failures or warnings were reported. Tests ran with host Windows
event loops because sandbox imports/SDK event-loop tests can stall; this did
not authorize network/vendor execution. Source and test files were unchanged
after final gates began; only this report was completed afterward.

Final HEAD: `1fab6821546722378af067f1dd8658bbf50f63a8`. Accepted Slice 1
ancestry passed (exit 0); the module-filtered intervening commit log and entire
index were empty. One tracked Module 6.5 source modification plus the three
new files listed above remained unstaged. `git diff --check -- module-06-5`
passed for tracked content and the new Python files passed Ruff. Dependency
files and accepted tests remain unchanged.

Concurrent root, Module 7 and Module 9 changes were foreign/protected and
untouched. HEAD and foreign dirty/untracked state advanced during this work;
no foreign content was staged, committed, reset, checked out or modified here.

Evidence: deterministic fixtures and injected faults, **genuine SDK construction
and serialization/parsing over mocked in-memory HTTP**. This is adapter/SDK
evidence, not genuine external-service or live-provider evidence. Accepted
local LangGraph integration remains green but is not vendor inference evidence.

No live/paid inference, real credential access after the HITL decision,
service-side key validation, secret creation/rotation/persistence, deployment,
production authentication, exactly-once effects, atomic cancellation/revocation,
crash-safe provider effects, OS isolation or forced termination is claimed.
SDK-side buffering and arbitrary synchronous callbacks remain outside app
memory/preemption guarantees. Durable provider recovery and complete Story 9
closeout remain deferred.

After independent acceptance, another Story 9 slice can implement additive
Guardrails AI validation without a new architecture decision. Guardrails must
never override application schemas or grant authority. A real live/spend test
would require a new explicit human authorization; none is necessary for the
next deterministic implementation slice. Stop for independent review.

Completion evaluation: requirements advanced for Slice 2 only; product
experience is the provider API/tests/report with UI deferred; real functionality
is genuine SDK serialization/parsing over offline transports; reliability and
security reuse accepted controls plus narrow vendor validation; cost is zero
paid inference with dollar governance deferred; evidence remains SDK/mocked,
not live-provider; deployment and production readiness are not established.
