# Story 10 Slice 3: optional offline observability integrations

Candidate for independent adversarial review. Story 10 remains IN PROGRESS.
No independent acceptance, release closeout, dashboard or lab completion is claimed.

## Baseline, authority and isolation

Accepted Slice 2 commit: `61816fb5c08f943aa9dcf445e962adcc333e0582`.
Accepted pre-slice full suite: **1,541 passing tests**.
Before mutation, ancestry verification passed, there were no intervening commits,
Module 6.5 was clean including untracked implementation, and the entire index was
empty. After the usage interruption, these checks were repeated: only the three
expected new Slice 3 source files existed in Module 6.5, ancestry still passed,
no intervening commits existed, and nothing was staged. Existing work was preserved.

Read root policy/SOP and the authoritative source, requirements, traceability,
architecture, implementation plan, ADR 001, Story 10 authority policy, Slice 1/2
reports and accepted telemetry, latency, provider, governance and anomaly code/tests.
Architecture and authority policy remain unchanged. Root and Module 7 concurrent
changes are protected foreign work. No staging, commit or foreign-file edits occurred.

Added files relative to `module-06-5`:

- `src/harness_engineering/observability_adapters.py`
- `src/harness_engineering/_offline_observability_worker.py`
- `src/harness_engineering/helicone_boundary.py`
- `tests/test_observability_adapters.py`
- `tests/test_helicone_boundary.py`
- `docs/STORY_10_SLICE_3.md` (this report)

No accepted source file, dependency declaration, lockfile, provider transport,
cost authority, telemetry semantics or requirement status was changed.

## Requirements advanced, not closed

| Requirement | Slice 3 contribution and remaining limit |
|---|---|
| REQ-TECH-004 | Genuine LangSmith Client create/update/flush/close over an offline requests Session. No hosted evidence. |
| REQ-TECH-005 | Genuine Langfuse observations/end/flush/shutdown with a private OTel provider and controlled exporter. No hosted evidence. |
| REQ-TECH-007 | Typed disabled gateway/header evidence document only; no SDK or transport. |
| REQ-OBS-001/002 | Explicit sanitized event mapping and application identity/correlation preservation across SDK seams. |
| REQ-OBS-003 | Existing finite anomaly/governance facts can be projected; no return control loop. |
| REQ-COST-003/004 | Existing attributed exposure/warning facts reach optional projections; source accounting remains authoritative. Reviewer presentation remains deferred. |
| ENG-002/003 | Strict schema/provenance, no arbitrary metadata, external responses/context never become authority. |
| ENG-004/005 | Bounded queue/drain/process lifetime, no retries, credentials or live calls. |
| ENG-006/007 | Explicit offline evidence classifications and adversarial failure/isolation tests. |

These contributions do not close full acceptance criteria. Slice 4 reviewer-facing
Story 10 dashboard/lab and remaining presentation/acceptance work are deferred.

## Dependency and source inspection

Existing optional `observability` extra already declares LangSmith and Langfuse.
The lock contains **LangSmith 0.14.7** and **Langfuse 4.17.0**. LangSmith was
installed; Langfuse initially was not. Used the authorized existing mechanism:
`uv sync --frozen --inexact --extra observability`. It installed locked
Langfuse 4.17.0, backoff 2.2.1 and wrapt 2.5.0 without dependency-file changes.
The only installation warning was cross-volume hardlink fallback to copying.
Python 3.12.14 and OpenTelemetry SDK/API 1.45.1 were verified in this environment.

Inspected installed constructors, serialization/create/update paths, runtime
metadata insertion, sampling, transport injection, flush/close and Langfuse
resource/consumer/OTel lifecycle source before implementing. No automatic
decorator, global tracing provider installation or provider instrumentation is used.

Helicone shape/header names were verified against the official
[header directory](https://docs.helicone.ai/helicone-headers/header-directory).
Public documentation lookup was research, not a deterministic-test or hosted
integration call. No Helicone Python dependency was introduced.

## Projection and provenance boundary

`OfflineObservabilityAdapter` binds an exact application `TelemetrySession`,
snapshots workflow/thread identity and evidence, and requires explicit supported
`Vendor` and boolean activation. It defaults disabled and accepts no endpoint,
client, secret, callback, pricing policy or arbitrary metadata configuration.
Live/deployment evidence is rejected; deterministic, mocked, adapter and local
integration source evidence remains unchanged.

Enqueue strictly revalidates the accepted immutable `TelemetryEvent` contract,
requires matching workflow/thread/evidence, increasing sequence and membership
in the bound local sink snapshot. This rejects fabricated traces, unrelated
segments, replay, extra metadata/content and bypasses through unvalidated model
copies. Events must be submitted in sequence while still retained locally.
Evicted or reordered events are deliberately rejected, not reconstructed.

Only accepted event fields are mapped: bounded IDs, finite categories, elapsed
time/timing source, evidence and typed numeric governance facts. No workflow
state, prompts/outputs, tool/MCP/document contents, credentials, URLs, arbitrary
exception text/repr/tracebacks, free-form metadata or tariff structures cross
this boundary. Strict revalidation also applies to the worker's JSON input.

No usage/pricing interpretation is added; numeric cost/warning/anomaly projections
remain the existing Slice 2 contracts. SDK responses and generated IDs never
enter identity, permissions, routing, retries, HITL, off-switch, budget, checkpoint,
recovery or anomaly source state. The adapter has no ledger/provider/tool handles.

## Genuine SDK seams and correlation

LangSmith uses actual `Client.create_run`, `update_run`, `flush(timeout=0.1)` and
`close(timeout=0.1)` with an explicit dummy key, fixed `.invalid` URL, non-socket
requests Session, no automatic batching, full sampling, empty inputs/outputs and
`omit_traced_runtime_info=True`. The controlled Session admits only create/update
requests and captures bodies for direct seam tests. Runtime/environment metadata
is absent. Application event UUID identifies the projection run; application
trace hex becomes its UUID trace representation. Full application span/parent,
workflow/thread, sequence and evidence survive in the closed event metadata.

Each event is an independent projection run. It is not a reconstructed vendor
start/finish lifecycle. Fixed synthetic SDK timestamps are offline fixture data;
the event's accepted elapsed/timing fields remain the actual application facts.
No vendor timestamp is fed into latency reports or SLO cohorts.

Langfuse uses actual `Langfuse.start_observation`, observation `end`, `flush` and
`shutdown`, with explicit dummy keys, `.invalid` URL, HTTP MockTransport rejecting
every request, private OTel TracerProvider/empty Resource and controlled SpanExporter.
The application trace ID is explicit and application span ID is the remote parent;
Langfuse's child span is a projection detail. Closed event metadata preserves the
original application span and parent relationship, workflow/thread and evidence.
SDK wall-clock span times do not become application latency measurements.
No generation prompt/output/cost API or ambient application context is supplied.

Direct tests inspect genuine SDK-generated request bodies and exported OTel span
attributes. End-to-end adapter tests additionally exercise the isolated worker.
These are **genuine SDK-over-controlled-offline-boundary evidence**, not hosted
acceptance. Missing optional SDKs become a finite unavailable health category.
SDK seam tests skip if that optional extra is absent; the reported run has both
installed and does not rely on such skips.

## Resource and failure isolation

Enqueue invokes no exporter, SDK, subprocess or external callback. Pending capacity
is fixed at **64 events per adapter**, drop newest; the local sink's existing 512
record bound is unchanged. One sequence watermark replaces any replay registry.
Counters saturate at **1,000,000**; health fields and failure categories are closed
and bounded. No background worker exists in the workflow process.

Explicit reviewer `flush()` drains at most 64 events, no retry, through a single
nonblocking process-wide drain slot. A busy drain returns immediately and leaves
its queue pending. This operation is not installed in the correctness-critical
workflow path. A hard **10-second subprocess timeout** covers imports, construction,
serialization/export, flush, SDK consumer lifecycle and teardown; timeout kills
and reaps the subprocess through `subprocess.run`. At most one child is active
per application process. LangSmith emits at most 128 create/update requests;
Langfuse emits at most 64 spans and admits no scores/media/API requests.

The child receives only `SYSTEMROOT` where available and fixed offline settings.
It receives no inherited vendor/provider keys, proxy configuration, tracing
endpoints, releases or auto-enable flags. LangSmith profile lookup targets the
null device. A socket deny boundary is installed before SDK import in addition
to both controlled transports. Langfuse media consumers are disabled; its private
score/OTel consumers cannot outlive the isolated child budget.

Only `ok` or finite phase names return to the parent. Stderr is discarded and SDK
logging is disabled in the child. Construction/create/update/flush/close failures,
missing SDK/process, timeout and unexpected worker results are normalized without
retaining external exception diagnostics. Entire uncertain batches are counted
dropped, with no retry or assertion of hosted delivery. Close is immediate,
idempotent, stops admission and drops pending events. An already active drain
retains its ten-second bound. Explicit flush before close is optional.

Exporter health is advisory. It cannot reserve, settle, refund, reset attempts,
alter source warnings/anomalies, suppress persistence or trigger tool/provider
retries. Caller-owned source telemetry and workflow results remain untouched.

## Helicone offline boundary

`HeliconeOfflineConfig` is strict/frozen, defaults disabled, and cannot be enabled.
Only the exact documented `https://gateway.helicone.ai/v1` endpoint shape exists.
Its deterministic `describe(session)` output is an evidence document, not an
accepted provider request configuration. It contains fixed omission/retry/cache
headers plus application-derived thread/workflow/evidence properties. Boundary
evidence is deterministic; source fixture evidence is preserved separately.

There is no secret/key field or environment credential read, `Helicone-Auth`,
Authorization header, provider target, arbitrary header dictionary or networking
method. Extra credentials, arbitrary endpoints/URLs, budget/retry/permission/HITL/
off-switch/evidence overrides are rejected with secret-free validation messages.
Unvalidated model-copy activation is rejected again at serialization.

No live Helicone gateway binding exists. No provider endpoint was changed or
live-rerouted. No inference or provider credential traffic reaches Helicone.
Headers alone do not make future gateway behavior safe: retries, caching,
fallback, transformation and request handling require independent evaluation;
actual routing requires separate human authorization.

## Validation and security evidence

Strict fail-fast order: Ruff, focused tests, full module pytest, compileall.
Initial Ruff found one environment-variable casing rule; repaired manually using
the equivalent Windows case-insensitive uppercase spelling. No unsafe fixes used.
Initial focused suite passed 60 tests. Added genuine Langfuse failure-phase and
outstanding-exposure tests; reran Ruff and the entire focused gate.

- Ruff: **passed** (`ruff check .`).
- Focused Slice 3 tests: **66 passed**, 5.31 seconds; no warnings/skips reported.
- Full module pytest: **1,607 passed, 6 warnings in 541.13 seconds (9:01)**;
  accepted 1,541 baseline plus 66 new tests, no skips/failures.
- Compileall over `src` and `tests`: **passed**, exit 0, after full-suite success.

Tests cover independent vendor construction/create/update/flush/close failures;
genuine offline serialization; prompt/output/credential/exception sentinel exclusion;
application trace/provenance/evidence; hostile environment isolation; malformed,
unvalidated and foreign records; live evidence rejection; disabled/closed/busy
drains; full queue/drop-newest/replay/counter saturation; subprocess unavailability
and timeout; finite error normalization; and Helicone injection/activation attacks.
Outstanding fixture exposure, token allocations, warnings and nonempty anomaly
source snapshots remain identical across export failure for each vendor.

Temporary pytest storage is under parent `TECHADEMY/EVIDENCE`, outside this repo.
The full accepted 1,541-test baseline is retained; no existing test was weakened.
The six warnings are the existing Typer/Click stream and flag-parameter
deprecations from accepted guardrail adapter coverage; no Slice 3 test warning
was reported. A read-only Git inspection also reported the foreign Module 7
lockfile's existing LF-to-CRLF warning; no foreign line endings were changed.
Two Module 10 files acquired concurrent foreign changes during the full gate;
this work neither inspected their implementation nor modified them.

## Completion evaluation and non-claims

Requirements: Slice 3 advances the mapped contracts, not full Story 10 acceptance.
Product experience: explicit offline adapter/plan interfaces and this report are
reviewable; the Story 10 lab/dashboard is not yet complete. Real functionality:
genuine SDK serialization/export seams run offline. Reliability: bounded admission,
drain, loss and failure categories; full regression result recorded above.
Security: strict source membership/provenance, content exclusion and network denial.
Cost: no spending authority or price interpretation, existing accounting unchanged.
Evidence: deterministic application contracts and SDK-over-offline-boundary
integration evidence remain distinct from source-event evidence. Deployment: none.

No hosted LangSmith traffic occurred. No hosted Langfuse traffic occurred. No
Helicone inference traffic occurred. No live Helicone gateway binding or provider
rerouting exists. No live provider execution/spending or real monetary execution
occurred. No real credentials, real/current provider pricing, verified billing,
hosted delivery, deployment evidence or production observability is claimed.
Story 10 remains incomplete. Independent adversarial acceptance is not claimed.

## Final review boundary

Final accepted Slice 2 ancestry check passed; no intervening commits exist.
No accepted Module 6.5 tracked file changed. The six additions above are the
complete candidate. `git diff --cached --name-only` is empty: nothing is staged
and no commit was made. Foreign changes were not modified by this implementation;
their owners' concurrent work, including the two Module 10 edits, is preserved.
Candidate is ready for independent adversarial review, not release approval.

Complete final `git status --short`:

```text
 M module-07/pyproject.toml
 M module-07/tests/test_package_contract.py
 M module-07/uv.lock
 M module-10/src/module10_ai/azure_verification.py
 M module-10/tests/test_azure.py
?? .editorconfig
?? .gitattributes
?? module-06-5/docs/STORY_10_SLICE_3.md
?? module-06-5/src/harness_engineering/_offline_observability_worker.py
?? module-06-5/src/harness_engineering/helicone_boundary.py
?? module-06-5/src/harness_engineering/observability_adapters.py
?? module-06-5/tests/test_helicone_boundary.py
?? module-06-5/tests/test_observability_adapters.py
?? module-07/docs/STORY-05-IMPLEMENTATION.md
?? module-07/docs/stories/STORY-05-langfuse-integration-boundary.md
?? module-07/src/reliability_safety_observability/langfuse_adapter.py
?? module-07/src/reliability_safety_observability/langfuse_config.py
?? module-07/tests/test_langfuse_adapter.py
?? module-07/tests/test_langfuse_live.py
?? scripts/
```
