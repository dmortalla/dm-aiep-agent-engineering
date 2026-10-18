# Story 10 Slice 1: application-owned telemetry, correlation and latency

Implemented for independent review; Story 10 remains incomplete. Patch is
unstaged and uncommitted. No architecture, requirements, dependencies, lockfile,
root status, foreign module, provider endpoint or monetary policy is changed.

## Authority, baseline and scope

Story 9 closeout: `8d1deab98c599e94994b8fb0ab913e59bcc755e9`.
Human-approved Story 10 policy and initial HEAD:
`b0285bd8b7c913824dfe74b1b016976d76deb3bf`.
Accepted pre-Story-10 baseline: 1,344 tests.

Before mutation, policy ancestry passed (exit 0), the intervening Module 6.5
commit log was empty, the module had no tracked/untracked changes, and the
entire index was empty. Foreign root/Module 7/Module 9 work was protected.
No reset, revert, checkout, clean, stash, staging or commit was performed.

Re-read authoritative source, requirements, traceability, frozen architecture,
implementation plan, ADR 001, Story 10 authority policy, all three Story 9
slice reports, root PROJECT_STATUS, AGENTS/CLAUDE and engineering SOP. Inspected
accepted lifecycle, provider, approval, tool, persistence and regression seams.
No architecture amendment or new ADR is needed for this authorized foundation.

Exact files relative to `module-06-5`:

- Modified `src/harness_engineering/providers.py`.
- Added `src/harness_engineering/observability.py`.
- Added `src/harness_engineering/latency.py`.
- Added `src/harness_engineering/telemetry_projections.py`.
- Added `tests/test_observability.py`.
- Added `tests/test_latency.py`.
- Added `docs/STORY_10_SLICE_1.md` (this report).

## Requirements advanced, not closed

| Requirement | Slice 1 evidence and remaining scope |
|---|---|
| REQ-OBS-001 | Immutable structured start/finish spans for explicit workflow, step and provider observations, plus a local bounded operational ring. Full Story 10 lab/dashboard and broader projections remain deferred. |
| REQ-OBS-002 | Strict version-00 traceparent parsing/serialization hook, locally generated trace/span IDs, nested context and explicit provider-worker propagation. No distributed remote transport/exporter integration is claimed. |
| REQ-COST-002 | Monotonic/injected duration seams, distinct measurement cohorts and bounded nearest-rank p50/p95 reports against <=5-second deterministic/local workflow SLO. No representative performance evaluation or full Story 10 SLO evidence is claimed. |
| ENG-002/003 | Closed schemas, omission of content/errors, inert external trace hook, application-bound identities/evidence and no telemetry authority. |
| ENG-004/005 | Bounded records/rings/cohorts, no exporters/credentials/paid calls; accepted execution controls unchanged. |
| ENG-006/007 | Timing/evidence labels and explicit non-claims, hostile-input/failure tests and accepted-provider regression coverage. |

REQ-OBS-003, monetary governance, technology integrations, lab/dashboard and
Story 10 closeout are not claimed by this slice.

## Application boundary and safe projections

`TelemetrySession` is trusted bootstrap configuration associated with a snapshot
of accepted `WorkflowIdentity`, one generated segment, a generated root trace,
and an explicit accepted `EvidenceClass` enum. Neither a provider nor a model
response supplies classification. Sessions have no global identity registry.
Applications retain/dispose one session per owned workflow segment; this is not
a global service/session admission controller.

`TelemetryEvent` is frozen, strict, recursively revalidated, forbids extra
fields, and contains only schema version, generated UUID references, sequence,
finite measurement/kind/outcome/evidence/timing values, optional numeric step
ordinal, trace linkage and duration. Every call has a unique span; this span is
an observation reference, not the authoritative attempt counter. No action-ID
string is copied. The existing provider audit and counters remain authoritative.

`observe_workflow(session, operation)` wraps a trusted invocation such as
`lambda: runtime.run_observed(request, observer=critical_observer)`. The accepted
runtime still calls that observer directly. Its failures propagate unchanged,
outside accepted retry classification; no telemetry sink replaces it.
`observe_step` wraps an accepted `StepExecutor`, translating at most 100 bound
work references to numeric ordinals. Step returns are labeled RETURNED, leaving
actual output acceptance and lifecycle completion to the runtime. Retries and
fallbacks remain application runtime decisions.

`ProviderRuntime(telemetry=session)` measures its public caller boundary and
forwards to the original provider implementation. Validation, exact adapter
admission, filtering, Guardrails, live gates, endpoints, retries, attempt charging,
worker-slot behavior, deadlines, cancellation and error chains retain their
accepted semantics. Without a session the same execution path runs without
telemetry recording. No provider usage or monetary accounting is added.

Minimal credential-free use (the result remains untrusted data):

```python
from harness_engineering.domain import EvidenceClass, WorkflowIdentity
from harness_engineering.observability import TelemetrySession
from harness_engineering.providers import ProviderRuntime

telemetry = TelemetrySession(
    WorkflowIdentity(), evidence=EvidenceClass.DETERMINISTIC,
)
provider = ProviderRuntime(telemetry=telemetry)
result = provider.generate({"prompt": "Local fixture."})
safe_events = telemetry.sink.snapshot()
latency_reports = telemetry.reports()  # One sample cannot assess SLO compliance.
```

Tool data is tested through the accepted executor behind the generic action
boundary. There is no new tool-worker or MCP transport propagation in this
slice. Context/compression, MCP-specific, approval audit and recovery-store
event projections remain future work; existing contracts are not replaced.

## Privacy, context and resource bounds

Telemetry has no fields for prompts, model/tool/MCP/retrieved content, secrets,
credentials, authorization headers, URLs, exception messages/chains, object repr
or provider metadata. Safe projection is field omission, not a claim of semantic
secret detection. Unexpected operation defects are categorized DEFECT and
re-raised unchanged; the observation never serializes their diagnostics.

`TraceContext` supports only lower-case fixed-width nonzero trace/span IDs,
version 00 and flags 00/01. No baggage/tracestate is supported. External headers
can be validated as inert data, but sessions do not accept them as parents.
Even a separately bound external/other-workflow context cannot replace the
session root, identity, evidence or authority. Nested spans reuse only the
session's root. ContextVar tokens are reset in finally blocks.

Provider dispatch explicitly snapshots the current inert context into
`ProviderCallContext.trace_context` and binds/resets it inside the provider
worker. No prompt, tool argument, permission input or approval record is changed.
Different sessions isolate their trace roots; uninstrumented provider workers
bind None when no context exists. This is correlation, not authenticated origin
proof or protection against arbitrary trusted in-process Python mutation.

Bounds:

- Events are validated to <=4 KiB UTF-8 JSON; current closed field sizes fit
  comfortably below that maximum.
- One local sink retains at most 512 events and evicts the oldest, exposing an
  eviction counter. Rejected/foreign/replayed records are not retained.
- The sink binds workflow/thread/segment/root trace/evidence/timing and rejects
  attempted changes, including valid-looking higher evidence enums.
- Event sequence accepts at most 1,000,000; further records are rejected and
  counted as telemetry failures without changing workflow execution.
- Four finite measurement classes times nine outcomes give 36 possible cohorts
  per session, each retaining at most 1,000 samples. Empty cohorts are omitted
  from reports. No user/model/task IDs become metric labels or cohort keys.
- Durations are finite, nonnegative, at most 86,400 seconds; this observation
  ceiling does not expand the accepted 180-second execution deadline.
- No exporter queue, external sink, background exporter or telemetry retry exists.

## Failure semantics

Direct malformed sink input raises a fixed `TelemetryError` and cannot create
evidence. Best-effort observation boundaries count rejected events/timing,
classifier defects and local sink failures via `session.failures`; ring eviction
has its separate `sink.dropped` counter. Neither counter retains source payloads.
Failed timing produces no fabricated duration/completion sample.

Broad Exception catches are limited to the dedicated telemetry clock, local
sink emission, result-classification and timing/retention boundaries, where a
visible loss counter is the intended failure result. They never encompass the
measured operation. Operation exceptions are categorized by application types
and re-raised; unexpected operation defects propagate through finally unchanged.
No retry, budget change, approval, fallback or authority is granted by telemetry.
BaseException termination is not swallowed. As with accepted Python callbacks,
arbitrary blocking trusted instrumentation cannot be forcibly preempted.

Provider timeouts currently share the finite REJECTED latency cohort with other
budget/validation failures; the accepted provider audit still records TIMEOUT.
No classification is inferred from exception messages. Late worker completion
does not add a second caller sample or mutate the recorded completion event.

## Latency and SLO semantics

Session durations use `time.monotonic` by default, with an injected callable for
deterministic calculation tests. Injected timing is explicitly classified and
cannot receive an SLO compliance result. There are no wall-clock timestamps.
Nested workflow/action/provider boundaries are distinct; durations are not
summed as though independent. Provider latency includes caller validation,
dispatch/wait and acceptance, not merely vendor service time.

Workflow measurement covers one fresh submitted invocation through its observed
outcome. A genuine HITL suspension is SUSPENDED, never successful completion.
Resume callers must declare `resumed=True`; this records SEGMENT latency and
cannot assess end-to-end workflow SLO. Full suspended wall time and cross-process
duration aggregation are not implemented or silently excluded from a purported
end-to-end report. A new session generates a new segment/root; durable linking
across recovery remains deferred.

Reports identify measurement, outcome, evidence class and timing source, retained
sample count, evictions, p50, p95 and configured SLO. Sort retained values and use
nearest rank `x[ceil(p*n)-1]`. Empty cohorts have no percentiles. Nonempty small
cohorts can show percentiles, but fewer than 20 samples are insufficient for SLO
assessment. Only successful deterministic/local WORKFLOW cohorts with real
monotonic timing and >=20 retained samples receive a numerical `slo_met` value.
Other outcomes remain visible in separate cohorts; a successful cohort result
alone is not an overall availability or regression-run SLO conclusion.

The SLO may tighten but not exceed five seconds. The accepted 180-second hard
deadline is untouched. Injected-clock tests prove mechanics only. Representative
local regression measurements remain necessary for later performance evidence.

## Verification

Initial Ruff issues were import ordering, an unused import and line wrapping;
only safe import fixes/manual formatting were used. The first focused run found
one new test incorrectly assuming all lifecycle observers run before dispatch.
Accepted code actually reports after attempts, with pre-attempt reporting when
a before-step gate is bound. Repaired the fixture to test both behaviors; no
accepted implementation/test or requirement was weakened.

Final focused gate: Ruff PASS, then **233 passed in 12.33 seconds** across new
telemetry/latency tests and unchanged Story 9 provider/vendor tests (90 new cases
plus 143 accepted provider cases). No focused warnings were reported.

New coverage includes actual local LangGraph/SQLite HITL suspension, nested
workflow/action/provider linkage, tool output/failure omission, fixed trace
validation, forged evidence/identity rejection, hostile extra fields, secret
sentinels, ring/cohort bounds, concurrent sequence ordering, worker isolation,
late timeout completion, unchanged provider audit/limits, critical observer
failure, off-switch behavior under sink faults, clock failures, synthetic timing,
resume separation and percentile/SLO boundary cases. Tests forbid network sockets
and use no credentials, hosted observability or paid execution.

Final full-module fail-fast results on 2026-10-17, from `module-06-5`:

1. `.venv/Scripts/ruff.exe check .` - PASS.
2. Focused pytest command over `tests/test_observability.py`,
   `tests/test_latency.py`, `tests/test_providers.py` and
   `tests/test_vendor_providers.py` with `-q --tb=short` - **233 passed in
   12.33 seconds**, no warnings.
3. `.venv/Scripts/python.exe -B -m pytest -q --tb=short --basetemp
   E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-10-slice-01-full-20261017`
   - **1,434 passed, 6 warnings in 386.48 seconds** (1,344 accepted + 90 new).
4. `.venv/Scripts/python.exe -m compileall -q src tests` - PASS, exit 0.

The six full-suite warnings are the accepted Guardrails dependency's Typer/Click
deprecations: `get_binary_stream`, `get_text_stream`, and four warnings about
`is_flag`/`flag_value`. No dependency or accepted test was changed to hide them.
Tests used the host Windows runtime/event loops with sockets forbidden in the
new tests and accepted offline provider transports. No live operation was
authorized or performed. Source/tests were fixed before the final full gate;
only this report was completed afterward.

Temporary test artifacts are under parent `TECHADEMY/EVIDENCE`, outside this
repository. No separate temporary engineering capture is committed.

## Evidence, limitations and disposition

Evidence is deterministic/injected fault and calculation evidence plus genuine
local LangGraph, tool-executor and SQLite approval integration. Unchanged Story 9
SDK regression tests use genuine SDKs over mocked HTTP, not live providers.
Actual local monotonic durations in integration tests are not a representative
SLO performance campaign. Evidence is never escalated from provider/exporter claims.

No monetary tariffs/ledger, charging, estimates, spend warnings, hard monetary
admission, anomaly rules, LangSmith/Langfuse/Helicone adapter, gateway rerouting,
dashboard, hosted-service, live-provider, real billing, deployment, production
readiness or Story 10 completion is claimed. Existing provider recovery limits
and synchronous callback/preemption limitations remain unchanged.

Completion evaluation: requirements advanced for Slice 1 only; reviewer product
experience is the callable API and focused examples/tests, with lab/dashboard
deferred; real functionality is local observation of accepted boundaries;
reliability/security have bounded failure/adversarial evidence; cost remains zero
external spend and monetary governance is deferred; evidence classes are distinct;
deployment and production-grade completion are unestablished.

Final isolation recheck: HEAD remains
`b0285bd8b7c913824dfe74b1b016976d76deb3bf`; policy ancestry passes (exit 0),
no intervening module commit exists, entire index is empty and tracked-content
`git diff --check -- module-06-5` passes. Exactly the seven intended module
files listed above are modified/untracked. Foreign status below matches the
protected pre-existing work; it was not modified by this slice.

Slice 1 is ready for independent review with all required gates passing.
Story 10 Slice 2 and later work has not begun. No staging or commit is authorized.

Final `git status --short` (all changes unstaged):

```text
 M module-06-5/src/harness_engineering/providers.py
 M module-07/pyproject.toml
 M module-07/tests/test_package_contract.py
 M module-07/uv.lock
 M module-09/README.md
 M module-09/docs/ARCHITECTURE.md
 M module-09/docs/CONTRACTS.md
 M module-09/docs/EVIDENCE_POLICY.md
 M module-09/docs/PROJECT_STATUS.md
 M module-09/docs/REQUIREMENTS.md
 M module-09/docs/SECURITY_THREAT_MODEL.md
 M module-09/docs/STORIES.md
 M module-09/docs/TRACEABILITY.md
 M module-09/docs/governance/module-09-governance.json
 M module-09/pyproject.toml
 M module-09/src/multimodal_voice_platform/contracts/errors.py
 M module-09/src/multimodal_voice_platform/contracts/reasoning.py
 M module-09/src/multimodal_voice_platform/contracts/streaming.py
 M module-09/src/multimodal_voice_platform/crossmodal/observations.py
 M module-09/src/multimodal_voice_platform/crossmodal/records.py
 M module-09/src/multimodal_voice_platform/crossmodal/service.py
 M module-09/src/multimodal_voice_platform/interface/websocket.py
 M module-09/src/multimodal_voice_platform/speech/records.py
 M module-09/src/multimodal_voice_platform/speech/service.py
 M module-09/src/multimodal_voice_platform/streaming/coordinator.py
 M module-09/src/multimodal_voice_platform/understanding/records.py
 M module-09/src/multimodal_voice_platform/understanding/service.py
 M module-09/src/multimodal_voice_platform/voice/orchestrator.py
 M module-09/src/multimodal_voice_platform/voice/records.py
 M module-09/src/multimodal_voice_platform/voice/state.py
 M module-09/tests/test_deterministic_security.py
 M module-09/tests/test_governance.py
 M module-09/tests/test_websocket_gateway.py
 M module-09/uv.lock
?? .editorconfig
?? .gitattributes
?? module-06-5/docs/STORY_10_SLICE_1.md
?? module-06-5/src/harness_engineering/latency.py
?? module-06-5/src/harness_engineering/observability.py
?? module-06-5/src/harness_engineering/telemetry_projections.py
?? module-06-5/tests/test_latency.py
?? module-06-5/tests/test_observability.py
?? module-07/docs/STORY-05-IMPLEMENTATION.md
?? module-07/docs/stories/STORY-05-langfuse-integration-boundary.md
?? module-07/src/reliability_safety_observability/langfuse_adapter.py
?? module-07/src/reliability_safety_observability/langfuse_config.py
?? module-07/tests/test_langfuse_adapter.py
?? module-07/tests/test_langfuse_live.py
?? module-09/docs/LIVE_PROVIDERS.md
?? module-09/src/multimodal_voice_platform/adapters/openai/
?? module-09/src/multimodal_voice_platform/contracts/live.py
?? module-09/src/multimodal_voice_platform/live/
?? module-09/tests/live_builders.py
?? module-09/tests/test_live_adapters.py
?? module-09/tests/test_live_mode.py
?? scripts/
```
