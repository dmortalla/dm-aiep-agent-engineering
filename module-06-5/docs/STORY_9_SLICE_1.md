# Story 9 Slice 1: provider-neutral deterministic boundary

Implemented for independent review; not Story 9 closeout. No staging or commit.

## Baseline and scope decision

Accepted Story 8 implementation: `fe3e97cfe0fae88136850278619b759730c535a4`.
Accepted closeout: `6dad527033e09f5703c697454c71046b44d82f1d`.
Initial HEAD equals that closeout. Ancestor check passed (exit 0), the
module-filtered intervening log was empty, no tracked Module 6.5 changes
existed, and the index was empty. Accepted test baseline: 1,164.

Read controlling source, requirements/traceability, frozen architecture,
ADR 001, implementation plan, engineering SOP, current PROJECT_STATUS and
accepted configuration/domain, context, execution, lifecycle and recovery
contracts before implementation. Architecture/ADR establish a narrow provider
protocol and deterministic fake independently of optional vendor SDKs.
No accepted model-provider adapter exists yet. Existing `StepExecutor` is a
trusted application callback, `StepResult` is text data, and `RuntimeBudget`
already defines provider attempts and output/context limits. `OffSwitch` is
the accepted one-way cancellation source.

The smallest coherent first slice is therefore the provider-neutral protocol,
fake/default implementation and bounded application validation/filtering path.
Adding a live vendor at the same time would also require SDK normalization,
explicit spend authority and vendor-specific security/error work. Those are
separate independently reviewable slices. No architecture amendment or new
authority policy is needed for this deterministic first slice.

Exact new files, relative to Module 6.5:

- `src/harness_engineering/providers.py`
- `tests/test_providers.py`
- `docs/STORY_9_SLICE_1.md`

No accepted code, dependency groups/lockfile, requirements, architecture,
traceability meaning, root status document or other module is modified.
No UI, Story 10+ work, OpenAI/Anthropic implementation or Guardrails AI adapter
is included. Story 9 remains incremental and incomplete.

## Requirements and exit criteria derived before coding

The frozen implementation plan assigns Story 9 **REQ-SAFE-001,
REQ-TECH-006, REQ-TECH-008, REQ-TECH-009, ENG-002, ENG-003, ENG-005**.
Its exit evidence is validated deterministic output, injection containment,
malformed-output rejection, credential-free operation and inability of model
output to grant authority. ENG-004, ENG-006 and ENG-007 additionally govern
boundedness, evidence classification and expected failure testing.

| Requirement | Slice 1 evidence and exact remaining scope |
|---|---|
| REQ-SAFE-001: output filtering | Strict application text profile, forbidden extra fields, bounded UTF-8 output and optional trusted case-insensitive literal rejection policy. Partial Story 9 coverage; no semantic safety classifier or Guardrails AI evidence. |
| ENG-002: untrusted external/model data | Strict request/result contracts, explicit `untrusted_model` result trust, no raw response/metadata export, injected malformed/hostile response tests. Structural validity never makes text authoritative. |
| ENG-003: no model self-authorization | Result grants no authority; action/approval/permission/budget/tool/metadata fields are rejected. Hostile text cannot change fixed real LangGraph routes, cancellation or consumed budgets. |
| ENG-004: bounded operations | Shared workflow attempts, per-action repeat/retry caps, input/output bounds, single active provider worker, action/workflow deadlines, no implicit retry and accepted off-switch. |
| ENG-005: no paid deterministic execution | Default concrete fake, no credential/environment lookup, vendor imports or network calls. Only exact `FakeProvider` bindings accepted; a provider's claimed local/live metadata cannot authorize it. |
| ENG-006 / ENG-007 | Classified fake/injected/local lifecycle evidence and automated security/failure tests; no live or deployment claim. |
| REQ-TECH-006: Guardrails AI | Deferred. Later additive validation adapter must fail safely and never override application schemas or authority. No SDK integration claimed here. |
| REQ-TECH-008 / REQ-TECH-009: OpenAI / Anthropic SDKs | Deferred. Later optional adapters must conform to this application boundary, use actual installed SDK APIs, normalize expected errors safely and enforce explicit live/spend gates. No vendor SDK or API exercised here. |

Slice 1 exit criteria: independently runnable deterministic provider path,
strict application input/output contracts, meaningful filtering, no implicit
authority or spend, bounded calls/failures and real accepted lifecycle callback
integration, with complete module gates preserving the accepted baseline.

## Application boundary and authority semantics

`ModelProvider.generate(ModelRequest, ProviderCallContext) -> object` is the
narrow application-owned adapter seam. SDK clients/responses never appear in
its public request or result contract. Only the local fake is bindable in this
slice; adding a vendor requires explicit trusted integration code in a later
slice, not a string resolver, environment flag, deserialized object or
provider-controlled `is_live` assertion.

`ModelRequest` contains only bounded prompt text. Model selectors, tool calls,
approval, permissions, budget and routing overrides are not accepted input.
Bootstrap supplies finite application action IDs, immutable validated budget,
output-filter policy and the accepted OffSwitch. Neither serialized data nor
the result supplies those controls. Do not expose action IDs as generated
callable/route selection or recreate a runtime to restore consumed resources.

The adapter's untrusted response must be exactly a plain `{"text": str}`
dictionary. Unsupported SDK-like objects, structured/action/tool responses,
metadata, extra approval/permission/budget/cancellation fields, non-finite data,
bytes and malformed types fail closed. A fresh application `ModelResult`
contains text plus fixed `untrusted_model` classification; `grants_authority`
always returns False. JSON-looking instructions inside valid text are not
parsed, dispatched or interpreted. This is containment, not a claim that
prompt injection can always be detected.

Application `OutputFilter` optionally rejects text containing any configured
case-insensitive literal substring (at most 32 bounded terms). It rejects the
whole output, without echoing matches. Empty default policy accepts structurally
valid text. It is not a secret detector, semantic content-moderation model or
replacement for permissions, blocklists, HITL and execution scope. Guardrails
AI remains deferred and additive to this authoritative validation path.

## Bounds, failures and lifecycle

Construct one `ProviderRuntime` per application-owned workflow. The runtime
snapshots and revalidates `RuntimeBudget`, rejecting expansion beyond frozen
provider caps: eight attempts, two repeats/retries per action, 12,000 input and
2,000 output budget units, 30-second action timeout and 180-second workflow
deadline. Trusted configuration may tighten these limits. Deadline starts at
runtime construction, not the first call, and repeated calls cannot reset it.
Finite action IDs bind per-action attempt accounting; unknown IDs are rejected.

Each started invocation consumes one workflow and one action attempt, even on
timeout, malformed output or a defect. Input validation fails before adapter
invocation/charging. No automatic retry, fallback, re-ask or circuit retry
classification is added. Explicit repeated calls share the same counters and
have at most `1 + max_retries_per_action` entries. The accepted real lifecycle
stops on these expected validation/budget/authority failures without retry;
the provider does not emit `TransientStepError` or choose graph transitions.

UTF-8 byte length is the deterministic conservative resource estimate against
input/output budgets in this slice, with independent character caps. It is not
vendor tokenizer/usage evidence or billing accounting. Later SDK adapters must
also enforce their actual request output-token settings and validate usage.
No output can enlarge a configured limit. Invalid UTF-8 is rejected.

One worker slot bounds active provider execution. Calls use a bounded queue and
deadline; a timeout rejects output and marks the cooperative context cancelled.
The slot stays occupied until the callback finishes, preventing overlapping
retry work. Late results are discarded. Off-switch is checked before invocation
and after provider/validation work. It cannot be reset by model text. These
checkpoints are not atomic with arbitrary external effects.

Known `TimeoutError` is normalized to `ProviderTimeoutError` with a fixed safe
message and preserved internal cause. Malformed/filtered output raises
`ProviderOutputRejected`; attempts/size/concurrency use `BudgetExceededError`;
cancellation uses `AuthorityViolationError`. Unexpected programming exceptions
cross the thread queue and re-raise unchanged; the broad thread bridge catch
only transports the exception and does not swallow or classify it as an SDK
failure. Vendor-specific exceptions are not yet normalized because no vendor
adapter exists in this slice.

Audit is at most 128 fixed `ProviderEvent` enums for started attempts and their
observed outcomes. Request/result repr hides text; top-level diagnostics never
echo provider content or filter matches. Raw causal chains are internal,
untrusted diagnostics and must not be logged/rendered as sanitized evidence.
The implementation neither reads nor logs credentials; application filtering
does not guarantee redaction of arbitrary secret-like generated text.

## Runnable use and actual API evidence

From the Module 6.5 environment:

```python
from harness_engineering.providers import ProviderRuntime

runtime = ProviderRuntime()
result = runtime.generate({"prompt": "Summarize this local fixture."})
assert result.text == "Deterministic provider response."
assert result.trust == "untrusted_model"
assert not result.grants_authority
```

Accepted `LifecycleRuntime` is exercised through its real compiled LangGraph
`run(LifecycleInput)` path and trusted `(ExecutableSubtask, LifecycleInput) ->
StepResult` callback. Hostile output remains StepResult text while application
task IDs/order stay fixed; malformed provider output produces SAFE_STOP after
one attempt and no retry. Accepted lifecycle implementation is unchanged.

No OpenAI, Anthropic or Guardrails SDK constructor, transport, method, model,
credential or API is exercised. No SDK compatibility inference follows from
the provider-neutral protocol. The key-setup skill was read for applicability;
its API-work gate is not entered because no code here calls the OpenAI API.

## Verification and evidence classification

59 new focused tests passed in 1.49 seconds after Ruff passed. Initial focused
collection exposed a malformed test fixture: constructing a NaN RuntimeBudget
already failed its accepted validator. The fixture was corrected to create a
deliberately forged copied model, which runtime revalidation rejects. No
accepted validator, implementation or test was weakened.

Coverage includes malformed inputs; hostile/authority-shaped/unsupported and
oversized outputs; output filtering; UTF-8 byte budgets; shared workflow and
per-action budgets including failed calls; workflow deadline; cooperative
timeout/busy-slot behavior; before/during cancellation; sanitized timeout with
causal preservation; unknown adapter denial; frozen limit expansion rejection;
defect propagation; and real local lifecycle success/safe-stop paths.
A fresh subprocess removes all credential environment variables, forbids
OpenAI/Anthropic/Guardrails imports and blocks socket connections while proving
the default path remains usable. No installed optional SDK is required.

Evidence classes: deterministic fake provider, injected/mocked adversarial
responses and faults, plus genuine local integration of the accepted LangGraph
lifecycle. There is no vendor SDK-construction, provider-transport,
live-provider, deployment or production-readiness evidence.

Final full-module fail-fast gates on 2026-10-16, from `module-06-5`:

1. `.venv/Scripts/ruff.exe check .` - PASS.
2. `.venv/Scripts/python.exe -m pytest -q --basetemp
   <LOCAL_EVIDENCE_DIR>/module-06-5-story-09-slice-01-final-20261016`
   - **1,223 passed in 352.01 seconds** (1,164 accepted + 59 new).
3. `.venv/Scripts/python.exe -m compileall src tests` - PASS.

No final-suite failures or warnings were reported. Full tests used the host
Windows event loops because the accepted real-SDK tests stall in the sandbox;
this did not authorize any live/provider operation. Temporary pytest evidence
remained under the designated parent EVIDENCE directory. Source/tests did not
change after final gates began; only this report was completed afterward.

Final HEAD: `6dad527033e09f5703c697454c71046b44d82f1d`.
Accepted-closeout ancestry passed (exit 0); no intervening commits touched
Module 6.5. The index and tracked Module 6.5 diff were empty. Exactly the three
new files listed above remained untracked in Module 6.5. Tracked-content
`git diff --check -- module-06-5` passed and new Python files passed Ruff.

Foreign status remained protected and untouched: root `.editorconfig`,
`.gitattributes`, `scripts/`, Module 7's Story 5 document, and tracked Module 8
workflow/test edits. No staging, commit, push, reset, checkout, or history change
was performed.

## Limits and next slice

No forced synchronous termination, OS sandbox, native provider cancellation,
exactly-once provider execution, atomic revocation/effects, crash-safe provider
effects, authenticated production provider integration, vendor token accuracy,
semantic safety completeness, deployment or production readiness is claimed.
Arbitrary trusted Python callbacks may block indefinitely; a timed-out callback
holds the worker slot until cooperative completion. This is a bounded local
execution seam, not protection against hostile in-process Python.

Recovery serialization of provider counters is not wired in this first slice;
no provider runtime may be reconstructed from untrusted checkpoint/model data
to obtain authority or fresh accounting. Optional SDK/live integration and
actual SDK failure mapping remain work for later slices. Live spend remains
impossible through this slice's supported binding, regardless of API-key
presence or configured monetary budget.

Slice 2 can proceed after independent acceptance without a new architecture or
security-policy decision: implement one optional vendor SDK boundary against
this neutral contract with separately evidenced SDK behavior and explicit
live/spend gates. Adding the second vendor must preserve semantic alignment;
Guardrails remains additive. Any real paid call still requires explicit human
authorization and the applicable credential setup flow. No live inference is
needed merely to prove SDK contracts.

Completion evaluation: requirements advanced for Slice 1 only; product
experience is a runnable API and focused tests (UI remains Story 11); real
functionality is deterministic provider execution plus actual lifecycle
integration; reliability/security are bounded and fail closed as described;
cost is zero external/provider spend; evidence is accurately classified;
deployment and full Story 9 completion remain unclaimed. Stop for independent
review with the patch unstaged and uncommitted.
