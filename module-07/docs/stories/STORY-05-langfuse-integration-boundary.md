# Story 5 - Langfuse Operational Observability Integration

## Status

CONTRACT AUTHORED - implementation not started by contract authoring.

Amendment (human-approved Option A, after independent implementation
rejection): only the Langfuse public-key contract/authority conflict (review
B-2) is resolved, by the Langfuse Key Protocol Boundary under Redaction and Data
Minimization and test 7. This amendment requires independent re-acceptance and
does not accept the Story 5 implementation. Implementation blockers B-1 (ambient
Langfuse context exporting sensitive metadata after Story 4 redaction), B-3
(close reporting success while an SDK prompt-cache worker remains alive), B-4
(cancellation/readback timeouts permitting overlapping, untracked workers) and
B-5 (mocked transport producing live_vendor evidence) remain open for later
repair.

Prerequisite: independently accepted Story 4 commit
`ba0b3f2f4844df9972cf72839f0c041a5aaa5b92`. Verify its ancestry and accepted
Module 7 content before implementation; unrelated descendant commits are allowed.

Contract-authoring baseline: branch `main`, HEAD
`fe3e97cfe0fae88136850278619b759730c535a4`. The accepted Story 4 commit is an
ancestor; the only descendant commit touches no Module 7 path. Module 7 had no
tracked or untracked changes, the index was empty, and frozen authorities and
accepted Stories 1-4 had no differences from the accepted tree. No Langfuse
adapter, configuration, dependency or test existed: the only `langfuse` text in
Module 7 is the accepted Story 1 forbidden-import list, and the lockfile holds
no `langfuse` package. Foreign dirty/untracked work outside Module 7 was present
and remains outside this contract. Historical PLANNED/not-started wording in the
frozen plan and earlier contract status text is not a current implementation
status assertion or permission to rewrite those authorities.

## Goal

Connect the accepted application-owned neutral telemetry to Langfuse as the
primary operational observability integration, so Langfuse receives correlated,
minimized workflow traces, observations, latency, usage/cost and debugging
metadata, without Langfuse becoming authoritative for anything the application
owns and without core correctness depending on Langfuse.

## Authoritative Scope

This contract operationalizes Story 5 in IMPLEMENTATION_PLAN.md under frozen
REQUIREMENTS.md, ARCHITECTURE.md and the four assigned ADRs. It does not amend
them. TRACEABILITY.md maps REQ-TOOL-002 (Tools & Frameworks: LangFuse),
REQ-OBS-001/003/004/005, REQ-LAB-001 and REQ-DEL-001 individually to the course
source. Earlier-story security, reliability, cost, quality, dependency, isolation
and evidence obligations (including REQ-SEC-006 through REQ-SEC-009, REQ-ENG-006,
REQ-COST-001/003/004, REQ-QUAL-001 through REQ-QUAL-006, REQ-SRC-003/004,
REQ-DOD-004, ADR-007-011 and ADR-007-012) remain binding constraints rather than
additional Story 5 assignments.

Plan scope: Langfuse adapter; workflow traces and spans; latency evidence; usage
and cost evidence; debugging metadata after redaction; provider-unavailable
behavior; deterministic adapter contract tests; bounded optional live Langfuse
verification.

## Requirements

- REQ-TOOL-002
- REQ-OBS-001
- REQ-OBS-003
- REQ-OBS-004
- REQ-OBS-005
- REQ-LAB-001
- REQ-DEL-001

## Assigned ADRs

- ADR-007-001: application-owned normalized telemetry precedes adaptation;
  Langfuse is the primary operational observability integration and is not
  required for deterministic core correctness.
- ADR-007-002: Langfuse owns primary operational tracing; application code owns
  authority, resilience, idempotency, budgets and recovery.
- ADR-007-006: normalized telemetry crosses a mandatory redaction boundary before
  any vendor adapter; export failures are locally observable and cannot alter
  authorization or corrupt core state.
- ADR-007-008: ordinary CI is credential-free and deterministic; live vendor tests
  are optional, bounded, separately configured and required only for claims that
  depend on live behavior.

## Frozen Architecture Constraints

ARCHITECTURE.md assigns Langfuse: traces, spans/observations, latency,
usage/cost, workflow debugging and selected evaluation scores; core workflow
success does not depend on Langfuse availability. Execution Flow steps 7-8 place
redaction before Langfuse. Provider Failure Semantics for an observability
provider: core workflow may continue if policy permits, local telemetry records
the export failure, and no authority changes. Langfuse responses are untrusted
telemetry-provider responses. Live integrations require explicit enablement, not
credential presence. Dependencies stay minimal and constrained.

Selected evaluation scores are an architecture responsibility of Langfuse but are
not in Story 5's plan scope; automated evaluation belongs to Story 6. Story 5
carries the accepted optional evaluation join identifier only and must not
preclude later score export. It neither implements nor claims score export.

Cloud versus self-hosted Langfuse is not selected by frozen authority. This
contract keeps it a configuration value (explicit host) and selects neither.

## Implementation Boundaries

Story 5 may add, inside Module 7 only: one Langfuse adapter module that alone
imports the Langfuse SDK; Langfuse-specific typed settings in a new module; a
deterministic fake transport and contract tests; an opt-in live verification
test; the constrained dependency and lockfile update; and registration of a
live-test pytest marker. It composes with the accepted Story 4
`TelemetryPipeline`/`NeutralSink` seam and does not rewrite Stories 1-4.

Accepted source files (`config.py`, `domain.py`, `logging.py`, `telemetry.py`,
`reliability.py`, safety/authorization modules) and their public schemas remain
unchanged. `_is_sensitive_key`, `_redact`, `minimize`, `_project` and
`TelemetryLimits` are used as accepted; Story 5 must not weaken, broaden or
bypass them. The package `__init__` must not import the adapter.

Original pre-adjudicated accepted-test change: the Story 1 test
`test_story_one_source_has_no_network_client_imports` forbids `langfuse` imports
under `src`. Following the accepted Story 2 Guardrails precedent, permit the
`langfuse` root only in the single Langfuse adapter module, leaving every other
forbidden root and file unchanged, and add a confinement test proving no other
source file imports it. This strengthens confinement; it must not relax any other
assertion. Any further change to an accepted test or invariant must be identified
and adjudicated before that implementation proceeds.

Human-approved Round 3 import evolution: `httpx` is additionally permitted
only in `langfuse_adapter.py`, and only to implement, explicitly own and publicly
close the HTTP transport supplied to the supported public
`langfuse.api.LangfuseAPI` path. All other forbidden roots and files remain
unchanged. Behavioral lifecycle tests and AST confinement must prove this exact
boundary; it grants no general networking permission, redaction bypass, global
OTel mutation, evidence authority or lifecycle exception. The shutdown requirement
is unchanged.

### Adapter Boundary

The only data path is:

application facts -> Story 4 `Observation` -> `TelemetryPipeline.emit`
(validation, minimization, accepted redaction, size bound) -> one minimized JSON
record -> `LangfuseSink.send(record)` -> controlled mapping into an
application-owned, SDK-free export specification -> `LangfuseTransport` ->
Langfuse SDK.

1. `LangfuseSink` implements the accepted `NeutralSink` protocol and is attached
   as the pipeline `exporter`. Its only data ingress is the minimized JSON
   string. It exposes no method accepting `Observation`, `TelemetryRecord`,
   `RecoveryResult`, `WorkflowState`, policy objects, exceptions, raw strings or
   arbitrary mappings, so nothing can reach Langfuse without Story 4 redaction.
2. The adapter parses the record strictly: bounded byte size, JSON object with
   the accepted top-level shape (`event`, `workflow_id`, `trace_id`, `fields`),
   UUID-valid identifiers, fixed `Event`/`Component`/`Code` vocabulary, finite
   nonnegative numbers. A field-name allowlist defines what may be mapped;
   unknown fields are dropped, never forwarded. `[REDACTED]`, `[OMITTED]`,
   `[TRUNCATED]` and `[UNSUPPORTED_TYPE]` markers stay markers; no recovery of
   original values is attempted. Malformed input raises inside `send`, which the
   accepted pipeline records as `export_failed`; nothing is sent.
3. Mapping produces an immutable application-owned export specification built
   from primitives only. SDK types never appear in it, in `domain.py`,
   `telemetry.py`, configuration, or any public application contract.
4. `LangfuseTransport` is a narrow protocol accepting export specifications plus
   bounded flush/close lifecycle calls. Two implementations are required: an
   SDK-backed transport (the only SDK user) and a deterministic fake transport
   for tests. The SDK is imported lazily so importing the package or adapter
   module creates no client, thread, OpenTelemetry provider or network activity.
5. The SDK-backed transport constructs its client only from validated Story 5
   settings passed explicitly. It must not use SDK global/singleton client
   accessors, decorators, framework callbacks or auto-instrumentation, and
   ambient `LANGFUSE_*` environment variables must never activate export.
6. The adapter must not install or replace the global OpenTelemetry tracer
   provider, add processors to a provider it does not own, or capture spans from
   other libraries. Spans or telemetry produced by Guardrails AI or any other
   dependency must never reach Langfuse, because they bypass Story 4 redaction.
7. Vendor observation `input`/`output` content fields are never populated.

If the selected SDK cannot satisfy items 4-6 (isolated client, explicit
configuration, no global provider takeover, bounded flush/close), stop and
escalate as a dependency/isolation conflict rather than weakening the boundary.

### Correlation Mapping

| Neutral record element | Langfuse projection |
| --- | --- |
| `trace_id` | One Langfuse trace per application trace. Vendor trace ID is derived deterministically from the UUID when the SDK documents caller-supplied IDs in a compatible format; canonical UUID always in metadata |
| `workflow_id` | Metadata on trace and observations; not mapped to Langfuse user identity |
| `span_id` | Exactly one Langfuse observation per record; canonical UUID in metadata; a deterministic vendor observation ID only where the SDK supports one |
| `action_id` | Metadata only. Never creates a trace or extra observation; observations sharing it remain one logical action |
| `component`, `event` | Observation name from fixed vocabulary only (for example `reliability.recovery`), never free text |
| `status`, `error_classification`, `history` | Verbatim application codes in metadata, including the four Story 3 `*_exhausted` codes and the separate `unknown` |
| retry/fallback/recovery/replay fields | `retry_attempt`, `attempts`, `fallback_used`, `fallbacks`, `recovered`, `replayed`, `remaining_attempts`, `remaining_seconds` in metadata as received |
| decisions | `permission_outcome`, `safety_outcome` as observed values only |
| `evidence_class`, `source_evidence` | Verbatim metadata/tags; never upgraded |
| `evaluation_id` | Metadata join key only; no score |
| `details` | Already minimized bounded metadata, forwarded under a fixed key |

Vendor severity level is a presentation aid derived from a total, fixed table
over every `Code` member: success codes -> default; denial, pending and
cancelled codes -> warning; every other code -> error. The application code in
metadata remains the classification of record. The table is defined in the
adapter and tested exhaustively so a new `Code` member cannot be mapped silently.

Observations are flat children of their trace. Attempt history is not fabricated
into per-attempt timed spans, no parent/child hierarchy beyond trace ->
observation is required, and new vendor observations never create new logical
actions, effects, attempts or budget consumption.

### Latency

`duration_ms` is preserved exactly as the observation duration. Records carry no
wall-clock timestamps (accepted Story 4 decision), so the adapter anchors the
interval with an injected clock at mapping time (end = anchor, start = anchor -
duration) and records `timing_anchor=export_time` in metadata. This is placement
only; it does not claim measured execution start, per-attempt latency or
production latency, and does not alter Story 3 deadlines. Overlapping
measurements are never summed by the adapter.

### Usage and Cost

Langfuse may display usage/cost; it is never authoritative for Story 3 budgets,
expenditure authorization, retry decisions or accounting correctness.

1. Native vendor usage/cost fields are populated only when the record's `basis`
   is `fixture` or `supported_usage` and the corresponding value is non-null.
   For `unknown` basis, native cost is omitted entirely, never sent as zero, and
   native token counts are sent only if the record exposes them as known.
2. Native cost uses the record's `new_cost_usd` unchanged; the adapter performs
   no recomputation, pricing lookup or reconciliation. A genuine fixture zero is
   sent as zero with `basis=fixture` in metadata.
3. Replayed records (`replayed=true`) send no native token usage; historical
   usage stays in metadata labeled historical, and native cost is the record's
   zero `new_cost_usd`, so replay is not counted as new consumption.
4. Budget snapshot, `actual_cost_usd`, `overage_usd` and basis go to metadata as
   received. Use the SDK's documented usage-capable observation type where
   native usage requires it; do not invent a model name, prompt or completion.
5. Langfuse totals are observational aggregates. The adapter does not
   deduplicate repeated snapshots; callers should emit one cost-bearing
   observation per action execution. Vendor-computed cost (for example from a
   vendor price table) is never written back or treated as application cost.

Inherited limitation NB-1: accepted Story 4 `new_cost_usd` may include cost
already present in the starting state. Story 5 passes it through faithfully, so
Langfuse cost aggregates can overstate in that case. This contract does not
reinterpret or fix Story 4; documentation must state the limitation, and no
Langfuse cost total may be presented as accounting truth.

### Redaction and Data Minimization

Story 4's invariant is preserved: only already-minimized records cross the
vendor boundary, and Langfuse is never trusted to sanitize. The adapter adds
defense in depth, not a replacement: field allowlisting, marker preservation and
size bounds. SDK masking hooks may be used only as an additional layer.

Credentials, API keys (including the Langfuse public and secret keys),
authorization headers, bearer/access/refresh tokens, passwords/passphrases,
cookies/session material, connection strings/DSNs, private keys, secret-bearing
exceptions and raw user/model/tool/provider/validator payloads must be absent
from all application-controlled content sent to Langfuse, from adapter status
and errors, from local records and logs, and from evidence artifacts; the only
exception is the Langfuse key protocol boundary below. Raw prompts, outputs (even
safety-approved), operation names, provider error text and exception objects are
never mapped. The accepted conservative `_is_sensitive_key` classifier is not
weakened; Story 5 claims no universal secret detection.

#### Langfuse Key Protocol Boundary (human-approved clarification, Option A)

This narrow clarification resolves only the public-key contract/authority
conflict (implementation review B-2). It distinguishes:

A. Application-controlled telemetry and evidence. Neither the Langfuse public
   key nor the Langfuse secret key may appear in application telemetry fields,
   observation data, application metadata (trace or observation), tags, names,
   logs, debugging records, adapter status, errors, UI output, evaluation or
   other evidence, or any other application-controlled payload content.
B. Vendor protocol and transport metadata. The Langfuse public key may cross the
   vendor boundary only where the supported official Langfuse protocol/SDK
   requires it for project identification, authentication or routing (for
   example authentication headers or an SDK-required instrumentation-scope
   project identifier). It must not be copied into any unrelated protocol field
   or into application-controlled telemetry.
C. Secret authentication material. The Langfuse secret key may be transmitted
   only through the vendor-required authenticated transport mechanism and is
   excluded from everything listed in A and from every other protocol field.
D. Pre-export redaction. Story 4 pre-export redaction remains mandatory. This
   exception carries only the two configured Langfuse keys, sourced solely from
   validated Story 5 settings, into vendor-required locations. It creates no
   alternate path by which raw application content, sensitive telemetry,
   secret-bearing exceptions, authorization material or any other credential can
   bypass Story 4, and it does not narrow `_is_sensitive_key`, expose either key
   generally, permit arbitrary credentials in telemetry, or alter the approved
   Langfuse authority boundary.

Proof is behavioral (test 7). No test is required to prove that protocol
authentication or routing identifiers never reach the vendor.

### Trust and Authority

Everything returned by Langfuse or the SDK (return values, IDs, readback data,
errors, callbacks, logs) is untrusted external content. It cannot grant
authority, widen permissions, alter policy, change retry/fallback/timeout
behavior, reset idempotency, alter budgets or safety decisions, become
instructions, or control privileged behavior. The adapter discards SDK return
values except a bounded identifier comparison in the live check. Langfuse
availability or responses never determine workflow correctness. Story 2
authorization, Guardrails safety-only validation, non-authoritative moderation,
injection containment and fail-closed behavior are unchanged.

### Failure Isolation

SDK construction errors, authentication/configuration errors, exporter errors,
network errors, malformed vendor responses, timeouts, hangs and vendor
unavailability are non-authoritative observation failures.

1. `send` performs no network I/O and no blocking call on the event loop; it maps
   and hands one specification to the transport within the accepted pipeline
   sink timeout. Any failure raises a fixed-message error with no secret-bearing
   cause, which the accepted pipeline records locally as `export_failed`.
2. Pipeline `exported` means accepted by the adapter for export, not confirmed
   vendor ingestion. Documentation and evidence must say so.
3. Background export, flush and close outcomes are reported through an
   application-owned bounded status (for example disabled, flushed,
   flush_failed, flush_timeout, closed) with secret-free counters for accepted,
   refused and failed specifications. No exception text, response body, URL
   credentials or headers are retained.
4. The adapter never emits into the telemetry pipeline or `log_event` about its
   own failures, so there is no recursive telemetry/export loop. SDK debug
   logging stays off, and SDK log output must not expose credentials.
5. After `close`, `send` fails as `export_failed` without touching the SDK.

Story 3 and Story 4 isolation stays intact: a failing, hanging or malformed
Langfuse path cannot change authoritative workflow results, decisions, recovery
state, invocation/effect counts or accounting.

### Export Bounds

1. Record size: refuse records larger than the configured limit, which may not
   exceed the accepted Story 4 hard ceiling of 65,536 bytes.
2. Volume: a finite per-adapter specification limit, not exceeding the accepted
   Story 4 event ceiling of 4,096; beyond it, refuse and count, never evict.
3. Attempts: zero adapter-level retries. SDK/exporter-internal retry is disabled
   where configurable; otherwise its documented finite behavior is recorded and
   must fit within the flush/close bound. This export path never competes with
   or reuses Story 3 reliability policy.
4. Timeout: SDK request timeout, flush timeout and close timeout are finite,
   validated configuration with an explicit documented hard ceiling. Blocking
   SDK flush/close runs off the event loop and is awaited for at most its bound.
5. Buffering: SDK queue/batch sizes are configured finite where supported.
6. Shutdown: `close` is explicit, idempotent and bounded, stops SDK background
   work owned by the adapter, and does not rely on interpreter-exit hooks.

Frozen authority sets no numeric defaults. Implementation chooses documented
finite defaults within the ceilings above, validates them and tests behavior at
each boundary.

### Configuration and Secrets

Langfuse settings are a new typed, frozen, validated settings model with a
`MODULE7_LANGFUSE_` environment prefix and `hide_input_in_errors`, leaving the
accepted `RuntimeSettings` schema unchanged. Fields: explicit enablement flag
(default false); public and secret keys as `SecretStr` with `repr=False`; an
explicit host URL (HTTPS, or HTTP only for loopback); and the finite bounds
above. No credential or host default is committed.

1. Langfuse is inactive by default. Deterministic mode makes no SDK client.
2. The SDK-backed transport may be constructed only when `RuntimeSettings` is in
   live mode with `live_integrations_enabled`, the Langfuse flag is enabled, and
   both keys and the host are present and non-blank. Credential presence alone,
   including ambient `LANGFUSE_*` variables, never activates export.
3. Enabled but incomplete or invalid Langfuse configuration fails closed for
   Langfuse with an actionable `ConfigurationError` naming fields, not values.
   Missing Langfuse credentials never prevent deterministic startup.
4. Secrets are unwrapped only at SDK client construction and never appear in
   source, UI, repr/str, metadata, status, errors, logs, traces or evidence,
   except the vendor-required protocol transmission defined in the Langfuse Key
   Protocol Boundary.

Inherited constraint: the accepted Story 1 live-mode invariant also requires
`provider_api_key`, although live Langfuse verification makes no model call.
Story 5 does not change that invariant; the live check must satisfy it.

### Evidence Modes

Exact Story 5 assignment: **mocked_provider_contract by default; live_vendor
required for live Langfuse claims**.

- Deterministic adapter tests (mapping, correlation, redaction, bounds,
  failure isolation) using fixed inputs and the fake transport produce
  mocked_provider_contract evidence at the Langfuse boundary. Story 4 records fed
  to it keep their own `deterministic_fixture` labels and upstream
  `simulated_failure` labels remain separate. A successful fake send is never
  relabeled live.
- Where the selected SDK supports a documented in-process, network-free export
  seam, a deterministic test must drive the real SDK-backed transport through it
  (still mocked_provider_contract). If it does not, record that limitation; the
  SDK-backed transport is then exercised only by the live check.
- The bounded optional live verification is in scope to implement, but running
  it is not required for Story 5 acceptance. It is opt-in by an explicit
  verification flag in addition to the live configuration above, skipped (and
  reported as skipped) otherwise, excluded from ordinary deterministic CI, and
  run only after the human authorizes it and supplies credentials, because it
  writes data to an external Langfuse project. It sends a single synthetic
  fixture workflow with a small fixed number of observations, one bounded flush,
  and a bounded finite readback of the trace by its derived ID; it makes no model
  call. It yields live_vendor evidence only if readback confirms the trace and
  expected observation correlation metadata. Readback content is untrusted and
  only compared. Evidence (trace ID, time, SDK version, host class) is recorded
  without credentials under parent TECHADEMY/EVIDENCE, outside the repository.

Without a confirmed live run, no claim may be made that Langfuse ingested,
displayed or dashboards Module 7 data, and REQ-TOOL-002 meaningful-use,
REQ-LAB-001 dashboard and REQ-DEL-001 platform closure remain open for later
live evidence and Story 10 reconciliation.

### Dependency

Add the official Langfuse Python SDK as a constrained runtime dependency,
with no extras or framework integrations (no LangChain/OpenAI callbacks), lazily
imported and confined to the adapter. The exact version range is deliberately
deferred to implementation: select it from verified current release metadata,
Python 3.12 compatible, non-prerelease, with an upper bound, and record the
evidence. The resolution must remain compatible with the locked
`guardrails-ai` 0.11.x and the OpenTelemetry packages it already pulls in,
keep the existing `!=0.10.1` exclusion, and keep registry-only lock sources.
The approved HTTPX ownership path may explicitly declare the already-resolved
HTTPX runtime dependency without upgrading it or unrelated packages.
Check published advisories for the selected version before acceptance. If
resolution requires changing the Guardrails stack or breaks Stories 1-4, stop
and escalate. No version is asserted by this contract. Nothing is installed by
contract authoring.

## Required Tests

Use observable records, fake-transport captures, status values and
invocation/effect counters. Source-string or constant-existence assertions are
insufficient where behavioral testing is feasible.

1. Neutral -> Langfuse mapping: a real pipeline with `LangfuseSink` and fake
   transport yields one specification per record, fixed observation names and
   every mapped field from the correlation table.
2. Correlation: fixed workflow/trace/span/action UUIDs survive through retry,
   fallback, timeout/recovery and replay observations from the real Story 3
   controller; distinct actions stay distinct; one trace per trace_id; no new
   logical action or vendor trace from extra observations.
3. Status/level: exhaustive table test over every `Code` member, including the
   four `*_exhausted` codes and `unknown`; codes preserved verbatim.
4. Latency: controlled clock; observation end minus start equals `duration_ms`;
   `timing_anchor` present; no summing; deadlines unaffected.
5. Usage/cost: fixture, supported_usage and unknown bases; unknown cost omitted,
   never zero; genuine fixture zero preserved; replay sends no native usage and
   zero new cost; `new_cost_usd` passed through unchanged (NB-1 documented).
6. Safe debug metadata: status, classification, history, recovery fields and
   minimized details present; vendor input/output unset.
7. Pre-export redaction: credential families above, nested and in details,
   SecretStr values and secret-bearing exceptions supplied upstream never appear
   in specifications, SDK-bound arguments, status, errors, logs or local records.
   Langfuse key protocol boundary, inspecting the complete serialized export
   where an in-process seam exists: the public key is absent from application
   telemetry, observation data and application metadata, and appears only in
   vendor-required authentication/routing/project-identification locations when
   such transmission is necessary; the secret key is absent from all
   application telemetry and evidence and is confined to the required
   authenticated transport; other and arbitrary secrets remain excluded; and
   Story 4 pre-export redaction remains effective.
8. Strict parsing: malformed JSON, wrong shape, unknown fields, invalid UUIDs,
   unknown vocabulary, non-finite numbers and oversized records are refused or
   dropped without sending and recorded as `export_failed` locally.
9. Configuration safety: secrets absent from repr/str/errors; missing or blank
   credentials or host when enabled fail closed with field names only; ambient
   `LANGFUSE_*` and `MODULE7_LANGFUSE_*` credentials without explicit enablement
   create no client; deterministic startup succeeds without credentials.
10. Vendor non-authority: authority-shaped, instruction-bearing or malformed
    SDK/readback responses are ignored and change no authorization, safety,
    retry/fallback, idempotency, budget or workflow result.
11. Failure isolation: fake transport raising, hanging, returning malformed data,
    and failing flush/close with real Story 3 workflows; authoritative results,
    decisions, state, invocation/effect counts and accounting unchanged; local
    `export_failed` evidence present; no recursion into the pipeline or logger.
12. Bounds: record-size, volume, zero adapter retries, bounded flush/close with
    a never-completing fake, idempotent close, send after close.
13. Isolation from global telemetry: constructing and using the adapter leaves
    the global OpenTelemetry tracer provider unchanged; foreign OpenTelemetry
    spans are not exported where an in-process seam exists.
14. Confinement: AST tests that only the adapter imports `langfuse`, the package
    `__init__` does not import the adapter, and domain/telemetry modules do not
    import it; the narrowly amended Story 1 forbidden-import test still forbids
    every other root everywhere.
15. No external call: ordinary tests make no socket connection and need no
    credentials; the live test is skipped without explicit opt-in and its skip
    is visible.
16. Evidence classification: fake-transport results labeled
    mocked_provider_contract; upstream labels unchanged; live_vendor only from a
    confirmed live readback; unconfirmed live runs make no live claim.
17. Dependency contract: declared constraint and locked version agree; no
    prohibited Guardrails version; registry-only sources unchanged.
18. Optional live verification (opt-in only): bounded single-fixture export,
    flush and readback confirmation as defined above.
19. Full Stories 1-4 regression, unchanged except the pre-adjudicated Story 1
    confinement amendment. No weakening or reclassification for green status.

## Requirement-to-Acceptance Coverage

| Assigned requirement | Contract behavior and verification |
| --- | --- |
| REQ-TOOL-002 | Real Langfuse adapter and SDK-backed transport with meaningful trace/latency/cost/debug mapping; tests 1-8, 13-14, 17; meaningful-use closure needs live_vendor (test 18) |
| REQ-OBS-001 | Trace/observation correlation preserving workflow, trace, span and action identity; tests 1-3 |
| REQ-OBS-003 | Exact duration projection with documented anchoring; test 4 |
| REQ-OBS-004 | Faithful known/unknown usage and cost without replay double counting; test 5 |
| REQ-OBS-005 | Safe correlated debugging metadata and failure evidence; tests 6, 8, 11 |
| REQ-LAB-001 | Langfuse-side observability data path for dashboards; dashboard claims require live_vendor (test 18); Streamlit dashboards remain Story 9 |
| REQ-DEL-001 | Langfuse component of the observability platform; platform closure remains Stories 9-10 |

ADR-007-001 is exercised by the pipeline-only ingress and core independence
(tests 1, 11, 15). ADR-007-002 by non-authority and application-owned resilience
(tests 2, 10, 11). ADR-007-006 by pre-export minimization, local failure evidence
and isolation (tests 7, 8, 11, 12). ADR-007-008 by credential-free deterministic
tests and opt-in bounded live verification (tests 9, 15, 16, 18).

## Prior Non-Blocking Findings

- NB-1 (`new_cost_usd` may include starting-state cost): inherited and passed
  through unchanged; documented as a Langfuse cost-aggregate limitation. Not a
  Story 5 blocker; not fixed here; any Story 4 redesign needs human approval.
- NB-3 (no single table-driven test over every Story 3 classification): remains
  open. Story 5 test 3 is an exhaustive table over the Story 4 `Code` vocabulary
  for its own mapping only and is not a substitute for closing NB-3.

## Quality Gates

Implementation acceptance requires the complete Module 7 fail-fast sequence:

1. `ruff check .`
2. `pytest`
3. `python -m compileall -q src tests`

Stop at the first failure. Safe Ruff fixes only; no unsafe fixes. Preserve
bounded repair; never weaken tests, security controls or requirements. After a
repair, rerun the failed gate and then the full sequence. Independent
implementation review is mandatory before acceptance and controlled commit.
Contract authoring runs no implementation gates and proves no implementation
milestone. Temporary engineering evidence belongs under parent
TECHADEMY/EVIDENCE, outside the repository.

## Isolation

Only Module 7 belongs to this slice. No sibling implementation, tests, runtime
state or configuration may be copied, imported, modified or depended upon.
Foreign dirty state and unrelated descendant commits are not blockers. Stop for
conflicting concurrent Module 7 changes, history divergence invalidating
accepted lineage, a real dependency/isolation conflict or a genuine
frozen-authority contradiction. Preserve frozen requirements, traceability,
architecture, ADRs and accepted Stories 1-4.

## Non-Goals

The frozen plan reserves automated evaluation, regression, benchmarking,
evaluation datasets and LangSmith for Story 6; Helicone gateway observability
for Story 7; the failure-recovery simulation lab for Story 8; the guided
Streamlit console and its dashboards for Story 9; and integrated verification,
release live evidence and release closure for Story 10. Story 5 does not export
evaluation scores, run evaluators, add model execution, prompt management,
Langfuse datasets, distributed storage, a pricing service, OpenTelemetry
auto-instrumentation, wall-clock execution timestamps, or any authority or
architecture change, and does not redesign Story 4.

## Definition of Done

- All seven assigned requirements and four assigned ADRs have traceable behavior
  and verification within this slice, with live-dependent claims explicitly
  open unless live_vendor evidence exists.
- Langfuse receives only Story 4-minimized records through the pipeline-only
  adapter ingress; correlation, latency, usage/cost and debugging map faithfully.
- Langfuse remains untrusted and non-authoritative; failures are bounded,
  non-recursive and locally observable.
- Configuration is explicit, secret-safe and inactive by default; ordinary tests
  are credential-free and make no external calls.
- Accepted Stories 1-4 and frozen authorities remain intact apart from the
  pre-adjudicated Story 1 confinement amendment; all required tests pass.
- Evidence is mocked_provider_contract by default; live_vendor only from a
  confirmed, human-authorized live run.
- Ruff -> full Module 7 pytest -> compileall pass; independent implementation
  review accepts the slice before lifecycle recording and controlled commit.

Story 6 remains blocked until this contract is independently accepted, Story 5
implementation completes, independent implementation acceptance succeeds, and
lifecycle recording/controlled commit completes. Contract acceptance alone does
not unblock Story 6. Authoring this document implements no Story 5 behavior.
