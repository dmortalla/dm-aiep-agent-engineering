# Story 7 - Helicone Gateway Evidence Integration Boundary

## Status

CONTRACT AUTHORED - implementation not started by contract authoring.

Prerequisite: independently accepted and committed Story 6 commit
`8f6d1450f626449ac3960d274fff83d62bd39378`. Verify its ancestry and the accepted
Module 7 content before implementation; unrelated descendant commits are
allowed.

Contract-authoring baseline: branch `main`, HEAD
`8f6d1450f626449ac3960d274fff83d62bd39378` (the accepted Story 6 commit is also
HEAD). No Helicone adapter, configuration, dependency or test exists in Module
7: the only `helicone` text in Module 7 is this contract, and the lockfile holds
no `helicone` package. The Story 6 repair rounds established the repository
provenance-mint, whole-run-deadline, ownership and SDK-log-containment patterns
this contract adopts proactively (see Provenance and Mint Authority and the
Required Tests). Foreign dirty/untracked work outside Module 7 (root
documentation, Module 6.5, Module 10, repository tooling) was present and
remains outside this contract. Dirty Module 7 files (`pyproject.toml`,
`uv.lock`, `tests/test_package_contract.py`) are the carried Story 6
dependency/lockfile state; this contract changes none of them.

Post-acceptance reconciliation: an independent Reviewer ACCEPTED this contract
at SHA-256 `2d43f196dc63105b3d821e1111f6fa4957c9cba6e3c9cf0927ba5c1a79c7438f`
and identified six non-blocking findings. A bounded contract-reconciliation
pass resolved all six (readback correlation; multiple cost records; fallback
truth table; provider target URL; live-test claim wording; Story 6 docstring
adjudication) plus limited informational cleanup. This reconciliation pass
removes ambiguity only: requirement and ADR assignments, the authority model,
the evidence taxonomy, the live_vendor mint design, the deterministic CI
model, the cost/resource bounds, the 24-test structure and the Story 8/link
gating are unchanged. This pass adds no implementation and no new
architecture.

## Goal

Connect the accepted application-owned reliability, authorization, safety,
telemetry and evaluation stack to Helicone as the gateway-level evidence
boundary, so the application can (a) route model-provider traffic through the
Helicone gateway under application-owned request identity when live gateway
evidence is enabled, (b) export bounded gateway request evidence, and
(c) read back gateway-level request, latency, cost and fallback evidence as
untrusted observational data, without Helicone becoming authoritative for
anything the application owns and without core correctness depending on the
gateway.

## Authoritative Scope

This contract operationalizes Story 7 in IMPLEMENTATION_PLAN.md under frozen
REQUIREMENTS.md, ARCHITECTURE.md and the five assigned ADRs. It does not amend
them. TRACEABILITY.md maps REQ-TOOL-003 (Tools & Frameworks: Helicone),
REQ-OBS-003/004/005, REQ-REL-002 and REQ-DEL-001 individually to the course
source. Earlier-story security, reliability, cost, quality, dependency,
isolation and evidence obligations (including REQ-SEC-006 through REQ-SEC-009,
REQ-ENG-006, REQ-COST-001/002/003/004, REQ-QUAL-001 through REQ-QUAL-006,
REQ-SRC-003/004, REQ-DOD-004, ADR-007-011 and ADR-007-012) remain binding
constraints rather than additional Story 7 assignments.

Plan scope: Helicone adapter; request-level gateway evidence; latency and
usage/cost evidence; routing and fallback evidence; gateway failure behavior;
deterministic contract tests; bounded live gateway verification.

## Requirements

- REQ-TOOL-003
- REQ-OBS-003
- REQ-OBS-004
- REQ-OBS-005
- REQ-REL-002
- REQ-DEL-001

## Assigned ADRs

- ADR-007-002: Helicone owns gateway-level model observability and fallback
  evidence; application code owns authority, resilience, idempotency, budgets
  and recovery. Helicone is a vendor adapter in the accepted layering, not an
  authority layer.
- ADR-007-004: the application reliability strategy (retry, fallback, timeout,
  idempotency) remains authoritative; Helicone must not add hidden retries or
  silently substitute gateway fallback for application fallback.
- ADR-007-006: telemetry schema, redaction and provider-failure behavior; any
  Helicone-evidence observation crosses the accepted neutral redaction model
  and gateway/vendor output is untrusted.
- ADR-007-008: ordinary CI is credential-free and deterministic; live gateway
  tests are optional, bounded, separately configured and required only for
  claims that depend on live behavior.
- ADR-007-012: cost and resource governance; bounded live exposure, no
  billable calls in ordinary CI, observed cost is evidence not authority.

## Frozen Architecture Constraints

ARCHITECTURE.md assigns Helicone: gateway-level model-request observability,
latency, usage/cost evidence and gateway routing/fallback evidence where
exercised, fatally subordinate to application-owned authority; deterministic
core tests must not depend on a live gateway; "model-provider traffic may pass
through the Helicone adapter when live gateway evidence is enabled"; and, in
Provider Failure Semantics, a Helicone failure leaves deterministic and local
workflow paths testable while live gateway execution reports failure rather
than silently claiming fallback evidence. Execution Flow places the Helicone
gateway adapter in the vendor-adapter layer together with, and subordinate to,
the trusted core and the Story 2/3 controls; Story 4 neutral telemetry remains
the application-owned observability contract; Story 5 Langfuse remains primary
operational tracing; Story 6 LangSmith remains independent evaluation.
Dependencies stay minimal and constrained; live integrations require explicit
enablement, not credential presence.

Cloud gateway versus self-hosted/OSS gateway and US versus EU region are not
selected by frozen authority. This contract keeps both as explicit
configuration values (gateway base URL and evidence API base URL) and selects
neither. No gateway host default is committed.

## Implementation Boundaries

Story 7 may add, inside Module 7 only: one Helicone adapter module that alone
performs the gateway/evidence HTTP protocol; Helicone-specific typed settings
in a new module; shared adapters around the accepted boundary machinery
(imported per below); a deterministic fake transport and contract tests; an
opt-in live gateway verification; and the narrowly adjudicated amendments in
the section below. It composes with the accepted Stories 2-6 surfaces and does
not rewrite them.

Accepted source files (`config.py`, `domain.py`, `logging.py`, `telemetry.py`,
`reliability.py`, safety/authorization modules, `evaluation_*.py`,
`langfuse_*.py`, `langsmith_*.py`) and their public schemas remain unchanged.
`_is_sensitive_key`, `_redact`, `minimize`, `_project`, `TelemetryLimits`,
`UsageRecord`, `BudgetState` and the accepted `FallbackEvidence`-shaped
reliability fields are used as accepted; Story 7 must not weaken, broaden or
bypass them. The package `__init__` must not import the adapter.

### Pre-adjudicated amendments (mirror of twice-accepted precedent)

1. Story 1 forbidden-import amendment: the accepted Story 1 test currently
   permits `{"langsmith", "requests"}` only in `langsmith_adapter.py`. The
   amendment additionally permits `requests` import ONLY in the new
   `helicone_adapter.py` (exception value set `{"requests"}` plus, where the
   implementation reuses accepted machinery by import, nothing new). Every
   other permitted file keeps its current exception set; every other forbidden
   root and file is unchanged. A confinement test must prove: only the two
   adapter modules touch these roots; the package `__init__` imports no
   adapter; `domain.py`, `telemetry.py`, configuration and evaluation modules
   do not. This strengthens confinement and must not relax any other
   assertion. Any further change to an accepted test or invariant must be
   identified and adjudicated before that implementation proceeds.
2. Documentation of the choice NOT to amend: no other story boundary changes.
3. Story 6 docstring adjudication: the accepted Story 6 LangSmith adapter
   contains a statement that it is the only Module 7 file importing
   `requests`, which this contract's amendment 1 makes false. Story 7
   implementation may make the minimum comment/docstring-only correction to
   that statement. This adjudication permits exactly: comment/docstring
   only; no behavioral change; no import change; no Story 6 contract
   change; every Story 6 test preserved; the correction included
   transparently in Story 7 implementation scope and evidence. It does NOT
   authorize any broader Story 6 source modification; anything beyond the
   minimum docstring/comment correction remains a Story 6 ownership
   escalation.

### Dependency

No new runtime dependency. The Helicone integration mechanism is the documented
Helicone HTTP protocol (gateway proxying via required headers and manual/async
request-log ingestion plus bounded request-evidence queries), implemented over
the application-owned HTTP boundary on the already-declared, locked
`requests>=2.32,<3` runtime dependency (Story 6), lazily imported and confined
to the Helicone adapter module. The official `helicone-helpers`/`helicone`
Python helper packages are deliberately rejected: they are thin wrappers around
a JSON POST, would expand the locked supply chain for no capability the owned
boundary does not already own, and cannot satisfy the application-owned
redirect/retry/timeout/size controls on their own. Vendor wire details
discovered during implementation (endpoint shapes, header names, payload field
names, units) must be documented against the actual supported Helicone
protocol at implementation time; any observed protocol fact contradicting the
owned-boundary mechanism stops and escalates as a dependency/isolation
conflict rather than silently adapting. If implementation
authoring discovers a hard protocol fact that makes the owned-boundary
mechanism impossible, stop and escalate as a dependency/isolation conflict
rather than adding a package silently. No version is asserted by this contract
beyond the existing lock; nothing is installed by contract authoring.

## Adapter Boundary

Story 7 has exactly two owned data paths, both inside the adapter module:

1. Gateway routing path (outbound model-provider traffic, only when enabled):
   application-owned invocation facts -> `HeliconeGatewayRoutingSpec`
   (base URL + correlation/property headers) -> provider-call layer -> gateway.
   The adapter produces routing, never performs authorization, and never
   rewrites the request payload.
2. Gateway evidence path (observability, non-blocking): application-owned
   evidence facts -> immutable export specification (primitives only; no SDK
   objects) -> `HeliconeEvidenceTransport` -> Helicone HTTP protocol; and the
   reverse readback: gateway evidence endpoint -> owned transport -> strictly
   parsed, size-capped, allowlisted projection -> application-owned evidence
   snapshot.

- `HeliconeGatewayRoutingSpec` is an immutable, application-owned data object:
  `gateway_base_url`, fixed property headers (allowlist below), and the
  correlation bindings. Its only method composes authentication plus
  correlation headers onto a caller-supplied base header mapping, unwrapping
  credentials from validated Story 7 settings at composition time and never
  storing, logging, repr-ing or exporting them. If gateway evidence is not
  enabled, the spec is not constructible and model traffic proceeds
  unrouted under application ownership.
- `HeliconeEvidenceTransport` is a narrow protocol accepting export
  specifications plus bounded submit/readback/close lifecycle calls; two
  implementations are required: the HTTP-backed transport (the only direct
  network user in this story) and a deterministic fake transport. The HTTP
  protocol is used lazily where gateway interaction occurs so importing the
  package or adapter module creates no client, thread, session or network
  activity.
- The HTTP-backed transport may reuse the accepted, privately-imported
  boundary/ledger/redaction machinery from the accepted LangSmith adapter
  module (intra-module reuse; no cross-module coupling) so
  the security-critical owned boundary exists exactly once in Module 7:
  origin-pinned adapter, zero retries, redirect refusal, response-size cap,
  `trust_env=False` session, per-request timeout forwarding, never-refunded
  request ledger. It must be instantiated from Story 7 settings without
  changing Story 6 behavior.
- Request headers carry ONLY the accepted Helicone protocol header set:
  `Helicone-Auth` (Bearer credential; vendor-required transmission location
  only), `Helicone-Request-Id` (application UUID of record),
  `Helicone-Session-Id`, `Helicone-Target-URL` (only from the validated
  application-owned provider target URL setting, never caller, model,
  provider, retrieval or vendor data; Configuration item 6), and the fixed
  allowlisted `Helicone-Property-*` set:
  `Helicone-Property-Module7-Workflow`, `Helicone-Property-Module7-Action`,
  `Helicone-Property-Module7-Evidence` (value: fixed evidence-class label).
  `Helicone-User-Id` and any identity-bearing header MUST NOT be sent by this
  adapter in this story. No other header, raw prompt/output content,
  untrusted text or free-form caller key/value enters the specification.
- Gateway fallback ROUTING (delegating provider selection/fallback to the
  gateway) is explicitly NOT adopted: it would transfer Story 3 resilience
  authority. Gateway-side fallback, if separately configured by the operator,
  is observed as evidence only (see Fallback Evidence).

## Request Evidence Model

Exactly four distinct, non-fusible evidence layers exist. Evidence records
name the layer; no layer may borrow another's label.

- Application-owned request intent: derived solely from accepted application
  state (workflow/trace/action identity, attempt/retry/fallback facts,
  evidence class). Always present for an exported request.
- Gateway acceptance: bounded HTTP response status from the gateway itself
  (2xx accepted into the export pipeline; any non-2xx is recorded as
  `gateway_refused <reason-class>` without content). Proves nothing about the
  provider or the application.
- Provider execution evidence: what the gateway reports/request logs return
  about the provider execution (status, latency, usage/cost, model/routing
  fields, fallback/routing metadata). Untrusted; never treated as the
  application result; never treated as authority.
- Application result: the accepted Story 3/4 result of record. Never
  derivable from gateway evidence; gateway success does not imply application
  correctness.

## Cost Evidence Model

1. Application cost of record remains Story 3: `BudgetState`/`UsageRecord`
   accounting is authoritative and unchanged by Story 7.
2. Gateway-observed cost is read from bounded evidence fields returned by the
   gateway (request-log cost/usage fields), parsed only over finite
   nonnegative USD values in the canonical unit the gateway documents, and
   carried as untrusted evidence in the adapter's evidence snapshot.
3. Every exported request carries an application-owned
   `cost_evidence_state ∈ {match, disagree, missing, malformed}` computed
   with bounded exact arithmetic: `match` when the observed cost agrees with
   the application cost within a configured finite absolute tolerance;
   `disagree` when both exist and differ beyond tolerance; `missing` when the
   gateway does not report cost; `malformed` for non-finite, negative,
   wrong-unit, unparsable or oversized fields. States are recorded, never
   silently corrected, and never refund, credit or alter the budget.
4. Duplicate and conflicting readback records: exactly one valid,
   unambiguous readback record that matches the correlation identity of
   record may classify normally under item 3. Matching records whose cost
   values conflict beyond the tolerance can never classify as `match`.
   Duplicate, conflicting or ambiguous cost evidence fails safe by
   classifying as `malformed`, `disagree` or another already-defined
   non-authoritative state under the existing taxonomy above - no new
   state, no new authority class. No conflicting or ambiguous evidence
   refunds, credits, increases budget, authorizes another request or
   mutates Story 3 accounting in any way.
5. Missing, disagreeing or malformed gateway cost never blocks, retries or
   re-executes an application operation; it is visible evidence classification
   only. Application execution continues under Story 3 authority unchanged.
6. Precision: application cost is compared at its recorded value; the adapter
   performs no pricing lookup, no recomputation and no rounding of either
   side. Gateway cost totals are observational aggregates of gateway-reported
   values, never treated as accounting truth. NB-1 (Story 4 `new_cost_usd`
   may include starting-state cost) is inherited: comparing against the
   application value of record is still the honest comparison, and
   documentation must state it.

## Fallback Evidence Model

1. Story 3's fallback decision (`fallback_used`, `fallbacks`, recovery
   status) is authoritative; the adapter copies it verbatim into the export
   specification as application-owned intent evidence.
2. Gateway-side fallback evidence observed in the gateway request log is
   projected as a separate, untrusted
   `gateway_fallback_observed ∈ {none, observed, unknown}` field.
3. The adapter computes and records a bounded
   `fallback_evidence_state ∈ {agree, disagree, gateway_only, app_only,
   unknown}` comparing the two, classified exactly per this truth table:
   - `agree`: both sides present sufficient trustworthy evidence and it
     agrees (both report fallback used, or both report clearly no fallback);
   - `disagree`: both sides present sufficient trustworthy evidence and it
     differs (one reports fallback used, the other clearly not);
   - `gateway_only`: the gateway observation is trustworthy and reports
     fallback/routing while the application side of record for that request
     is trustworthy and records no fallback;
   - `app_only`: the application of record is trustworthy and used fallback
     while the trustworthy gateway observation clearly records none;
   - `unknown`: whenever either side lacks sufficient trustworthy evidence,
     including ambiguous, partial, self-contradictory or unresolved
     observations on either side; unknown is the fail-safe classification
     and is required whenever sufficiency or trustworthiness cannot be
     established on either side.
   The table is evidence classification only; it carries no authority and
   cannot modify the application disposition it classifies.
4. Gateway fallback evidence can never trigger, schedule, veto, strengthen
   or authorize an application fallback, retry, timeout or idempotency
   decision, and cannot create a new application action or effect.

## Correlation and Identity

Application-owned identifiers remain canonical across all stories:

| Application element | Helicone projection |
| --- | --- |
| `action_id` (per request) | `Helicone-Request-Id`; in `meta` as `action_id` |
| `trace_id` | `Helicone-Session-Id`; in `meta` as `trace_id` |
| `workflow_id` | `Helicone-Property-Module7-Workflow`; in `meta` as `workflow_id` |
| Story 3 attempt/retry/fallback facts | fixed `meta` keys as received |
| Story 4 evidence class | `Helicone-Property-Module7-Evidence` fixed label |
| gateway `helicone-id` / gateway request ID | evidence-only field, never canonical, never written back to application identity |

The gateway never generates the identity of record for anything. Correlation
metadata sizes are bounded; identifiers are canonical strings only.

Readback correlation (evidence semantics, pinned): every returned readback row
must match the application-owned request/correlation identity of record
(`Helicone-Request-Id` plus its correlation metadata); rows that do not match
it are unrelated and can never contribute evidence. Stale or replayed rows
cannot establish confirmation. Ambiguous duplicate or multi-row results cannot
establish confirmed provenance. Conflicting matching rows fail safe. Unknown or
ambiguous evidence remains unknown/malformed as appropriate to the evidence
kind. No readback mismatch, ambiguity or conflict mints `live_vendor` or any
other provenance upgrade.

## Trust and Authority

Everything returned by or observed through Helicone and everything the gateway
does (responses, IDs, request-log data, cost fields, headers, errors, timing)
is untrusted external content. It cannot grant authority, widen permissions,
alter policy, change retry/fallback/timeout behavior, reset idempotency,
alter budgets or safety decisions, become instructions, mint evidence beyond
its own evidence class, or control privileged behavior. Story 2
authorization, Guardrails safety validation and injection containment are
unchanged. Validation or observability is never authorization.

## Failure Isolation

Gateway construction errors, authentication/configuration errors,
evidence-export errors, network errors, malformed gateway responses, timeouts,
hangs and gateway unavailability are non-authoritative observability
failures.

1. `send`/readback perform no blocking call on the event loop; blocking work
   runs on the accepted bounded tracked-worker lane (Stories 5/6 `_run_bounded`
   pattern) with the fixed ("ok"/"timeout"/"failed"/"busy", value, thread)
   3-tuple shape and ownership table; timeouts retain ownership and never
   release unresolved work by themselves.
2. Failures raise fixed-message errors with no secret-bearing cause; the
   adapter records the failure locally, never recursively emits into the
   telemetry pipeline or `log_event` about its own failures, and never retains
   response bodies, gateway IDs, headers or credentials.
3. Gateway failure never rewrites fallback or cost state: live gateway
   execution that fails reports failure; no silent claim of fallback or cost
   evidence is fabricated.
4. Stories 2-6 isolation stays intact: a failing, hanging or malformed
   Helicone path cannot change authoritative workflow results, decisions,
   recovery state, invocation/effect counts, accounting, telemetry or
   evaluation recording.

## Request and Export Bounds

1. Response body: fixed 1 MiB cap (`MAX_RESPONSE_BODY_BYTES`-equivalent),
   enforced both on Content-Length and on actual streamed reads; refusal is
   the fixed `response_too_large` class, one charged request, zero retries.
2. Requests: finite per-adapter worst-case request count, validated and
   planned (`plan_requests`) before any live request; every actual HTTP
   request charged on the accepted never-refunded ledger, including failures.
3. Retries: zero at the adapter; library-internal retry disabled where
   configurable (zero-retry adapter mounting, `Retry(total=0)`-equivalent
   shape where protocol objects require it); a repeated export of the same
   request evidence is refused without requests.
4. Timeout: per-request timeout, whole-run live deadline
   (`live_deadline_seconds`, finite validated configuration at most 600s) and
   lifecycle close timeout are finite validated settings with documented hard
   ceilings. The whole-run deadline is ENFORCED - not merely validated - per
   the accepted Story 6 pattern: monotonic clock anchored at the live
   operation boundary, no request may begin at/after exhaustion, exhaustion
   returns the fixed `timeout_unresolved` status, deadline refusal never
   mints `live_vendor` and never refunds reservations.
5. Redirects: any 3xx is refused without following (fixed
   `redirect_refused` class); no redirect, including one toward loopback, is
   ever followed; the send call owns redirect policy (no
   `allow_redirects` argument) exactly as accepted in Story 6.
6. Transport hygiene: owned session with `trust_env=False` (never proxies from
   ambient environment), TLS certificate/hostname verification always on
   (`verify=True`), no credential unwrapping before endpoint qualification,
   explicit idempotent bounded close, no interpreter-exit reliance.
7. Reservation cost exposure is bounded by Story 7 configuration ceilings;
   consumed or uncertain work is never refunded; accounting that is
   incomplete fails closed (no request sent) and remains visibly classified.

Frozen authority sets no numeric monetary default. Implementation chooses
documented finite defaults within the ceilings above (request timeout, counts,
intervals), validates them and tests behavior at each boundary. The concrete
monetary guardrails for any live gateway run are supplied at live-run
authorization time by the human, per ADR-007-012; see Open Human Decisions.

## Configuration and Secrets

Helicone settings are a new typed, frozen, validated settings model with a
`MODULE7_HELICONE_` environment prefix, leaving the accepted `RuntimeSettings`
schema unchanged. Fields: explicit enablement flag (default false); API key as
`SecretStr` with `repr=False`; explicit gateway base URL, explicit evidence
API base URL and an explicit application-owned provider target URL used only
to compose `Helicone-Target-URL`. Gateway base URL, evidence API base URL and
provider target URL are distinct typed configuration concepts; none is derived
from or substituted by another at runtime. Gateway/evidence URLs are HTTPS, or
HTTP only for the loopback test origins, or the reserved non-routable test
origin per the accepted Story 6 seam pattern; and
the finite bounds above. No credential or host default is committed.

1. Helicone is inactive by default. Deterministic mode constructs no gateway
   routing, no session and no client.
2. Gateway routing and evidence export may be constructed only when
   `RuntimeSettings` is in live mode with `live_integrations_enabled`, the
   Helicone flag is enabled, and the key and both base URLs are present and
   non-blank. Credential presence alone, including ambient `HELICONE_*`
   variables, never activates gateway evidence.
3. Ambient-conflict refusal (Story 5/6 pattern): when Helicone evidence is
   enabled while ambient `HELICONE_*`/`HELC_*` vendor variables are present,
   the live gate refuses with a fixed actionable error; ambient variables are
   never writable into export.
4. Enabled but incomplete or invalid configuration fails closed for Helicone
   with an actionable `ConfigurationError` naming fields, not values. Missing
   Helicone credentials never prevent deterministic startup.
5. The credential is unwrapped only at header-composition and transmission
   time inside the adapter and never appears in source, tests, UI,
   repr/str, neutral telemetry, logs, gateway evidence payloads, exception
   text or reviewer evidence.
6. Provider target URL: `Helicone-Target-URL` is composed ONLY from the
   validated application-owned provider target URL setting. It never comes
   from caller, model, provider, retrieval or vendor data, and caller input
   cannot override it. The setting receives URL validation equivalent to the
   other gateway URLs before use; unsafe, local, loopback, noncanonical or
   otherwise prohibited targets are refused per the applicable endpoint
   qualification and security policy before any credential-capable
   construction. The adapter uses it only as gateway routing/target
   metadata; it performs no fetch, no traversal and no proxying of arbitrary
   content, so the Helicone adapter cannot become an open proxy or SSRF
   primitive.

Inherited constraint: the accepted Story 1 live-mode invariant requires
`provider_api_key` in live mode. Story 7 does not change that invariant; the
live check must satisfy it.

## Provenance and Mint Authority

The accepted Story 6 final design is mandated here verbatim (do not repeat
that repair round):

- Confirmed behavior is not confirmed provenance. A successful gateway
  response, matching readback, or matching IDs/counts cannot mint
  `live_vendor`.
- The bounded execution supervisor (the Story 6 `_execute_live`-shaped
  helper) performs submit/readback mechanics and has NO live_vendor mint
  authority: confirmed execution on any unqualified transport is capped at
  `mocked_provider_contract`; unconfirmed execution records `None`.
- A private `_live_qualified` authority flag exists only on the owned HTTP
  transport class, assigned ONLY on the HTTPS construction path that passed
  full bounded endpoint qualification (`is_remote_https_endpoint()` plus
  qualification), never for the reserved seam origin, loopback HTTP or any
  caller-reachable alternative.
- `_helicone_provenance_qualification(transport)`: exact owned-class type
  check (subclasses/impostors can never qualify), the flag is exactly True,
  no mounted seam, syntactically remote HTTPS, and not the reserved origin.
  Caller-supplied booleans, provider labels, response contents, matching IDs
  and mutable transport flags are never sufficient.
- The single `live_vendor` mint lives ONLY inside the owned
  `run_live_helicone_verification` wrapper, applied after every accept-listed
  gate (opt-in; activation gates; ambient refusal; qualification; budget
  plan; whole-run deadline; confirmed matching readback; clean `closed`
  close), mirroring the accepted Story 6 wrapper upgrade guarded by
  `_qualified_live_provenance`.
- Structural source-level tests must prove: zero `LIVE_VENDOR` occurrences in
  the supervisor; exactly one mint occurrence in the wrapper, guarded by the
  qualification check; the flag assigned only in the qualification path.

## Evidence Modes

Exact Story 7 assignment: **mocked_provider_contract by default; live_vendor
required for live Helicone claims**. The accepted taxonomy is reused
unchanged; no new class is invented.

- Deterministic adapter tests (routing headers, evidence export, correlation,
  cost/fallback classification, bounds, failure isolation) using fixed inputs
  and the fake transport produce mocked_provider_contract evidence at the
  Helicone boundary. Upstream Story 4 records keep `deterministic_fixture`
  labels; `simulated_failure` labels remain separate. A successful fake send
  is never relabeled live.
- Gateway endpoints driven through the in-process seam or a compatible local
  HTTP server are also mocked_provider_contract regardless of matching
  readback.
- live_vendor is produced only by the owned provenance-qualified live chain
  above. Without a confirmed live run, no claim may be made that Helicone
  displayed, priced or routed Module 7 gateway requests, and REQ-TOOL-003
  live-closure, REQ-OBS-004 gateway-cost closure and REQ-DEL-001
  platform closure remain open for later live evidence and Story 10
  reconciliation.
- production_observed is not mintable by Story 7; it is reserved for the
  accepted Module 7 production/Story 10 processes.

## Required Tests

Use observable specs, fake-transport captures, status values, ledger
accounting and invocation/effect counters. Source-string or
constant-existence assertions are insufficient where behavioral testing is
feasible.

1. Configuration/gating: defaults inactive; incomplete or invalid enabled
    configuration fails closed naming fields not values, including an
    unsafe, local or prohibited provider target URL; ambient
    `HELICONE_*`-shaped variables refuse the live gate while explicit
    enablement is required; deterministic startup succeeds with no
    credentials and constructs no session.
2. Secrets hygiene: key absent from repr/str/errors/logs/routing-spec
   persistence/export payload/evidence snapshots; credential unwrapped only
   at composition; secret-bearing exception text is contained.
3. Confinement: amended forbidden-import test proves `requests` importable
   only in the two adapter modules; AST tests that the package `__init__`
   imports no adapter and no other module imports the Helicone adapter; the
   deterministic path imports no vendor SDK (subprocess
   `sys.modules` confinement for a full deterministic run).
4. Zero-network ordinary CI: credential-free blocking subprocess test with
   ambient variables present and connection-refusal socket guard over the
   full deterministic flow, mirroring the accepted Story 6 pattern.
5. Gateway routing spec: not constructible when disabled; when enabled,
    composed headers contain exactly the accepted allowlisted set with
    canonical UUID correlation values, base-URL substitution from validated
    settings only, `Helicone-Target-URL` composed only from the validated
    application-owned provider target URL setting with caller-side override
    refused, unsafe/local/prohibited target URLs failing closed per the
    endpoint/security policy and no open-proxy/SSRF behavior, no
    `Helicone-User-Id`, no free-form properties, no raw payload content.
6. Request evidence layering: behavioral proof that gateway 2xx acceptance
   and provider-execution evidence do not alter the application result;
   application intent layer always present; fixed reason classes for
   refuse paths.
7. Evidence export body: exact allowlisted body shape (provider request
   intent, application meta, observed untrusted response evidence, bounded
   timing), no secrets/prompts/outputs, marker preservation, size bounds.
8. Readback projection: strictly parsed bounded gateway request-log
   projection by `Helicone-Request-Id`; unknown fields dropped; malformed
   rows fail safe as classifications; oversized response refused
   (`response_too_large`), one charged request, zero retries. Behavioral
   readback-correlation assertions: rows that do not match the
   application-owned request/correlation identity contribute nothing;
   stale or replayed rows cannot establish confirmation; ambiguous
   duplicate or multi-row results cannot establish confirmed provenance;
   conflicting matching rows fail safe; unknown/ambiguous states stay
   unknown/malformed; no mismatch mints `live_vendor`.
9. Cost evidence classification table: match within tolerance; disagree
   beyond tolerance; missing; malformed for non-finite/negative/unit
   mismatch/unparsable; one valid unambiguous matching record may classify
   normally while duplicate, conflicting or ambiguous records never classify
   as `match` and fail safe to already-defined non-authoritative states
   (`malformed`/`disagree`); observed cost never mutates `BudgetState`, never
   refunds, never authorizes more budget. Tolerance bound tested exactly.
10. Fallback evidence: application `fallback_used`/`fallbacks` copied
    verbatim; gateway fallback observed/none/unknown projections; the exact
    truth table (agree/disagree/gateway_only/app_only/unknown, with unknown
    required whenever either side lacks sufficient trustworthy evidence) is
    tested as evidence classification only; gateway fallback evidence can
    never trigger, veto, strengthen, or authorize any application
    fallback/retry/execution (behavioral proof with the real Story 3
    controller).
11. Story 3 authority preservation: with real Story 3 workflows, using the
    Helicone adapters (failing, hanging, malformed, disagreeing-cost and
    gateway-fallback variants) leaves attempts, fallbacks, idempotency,
    recovery status, invocation/effect counts, budget and outcome unchanged.
12. Zero hidden retries: gateway routing and evidence transport adapters
    counted single-send (no library-internal retries); repeated export of the
    same evidence refused without requests.
13. Timeout/resource bounds: per-request timeout forwarded; response cap
    (Content-Length and streamed) durable tests; whole-run deadline enforced
    (exhausted before request, exhausted between operations, readback loop
    cannot begin after exhaustion, deadline refusal cannot mint
    `live_vendor`, per-op timeout vs whole-run deadline proven distinct,
    charges never refunded).
14. Ownership: retained ownership past per-op timeout; conflicting
    operation refused `busy`; `close_busy` while unresolved; eventual release
    only on genuine resolution; no duplicate side effect; no evidence upgrade
    while unresolved.
15. Redirect refusal: all 3xx refused unfollowed; loopback Location never
    used; `trust_env=False` and `verify=True` enforced on the owned session.
16. Endpoint qualification: full fail-closed matrix (HTTPS required,
    noncanonical numeric forms refused, local suffixes refused, prohibited
    addresses refused, reserved test origin exempted only for the seam,
    fail-closed bounded DNS resolution per the preserved accepted Story 6
    DNS qualification precedent) before any credential-capable
    construction.
17. Provenance mint cap: local matching HTTP server, in-process seam, fake
    transport and impostor-subclass/caller-label attacks at the actual mint
    path -- all capped at `mocked_provider_contract`; structural proof that
    the supervisor contains no mint and the wrapper's single mint is guarded
    by `_helicone_provenance_qualification`.
18. Live wrapper refusal: prohibited local/loopback/noncanonical endpoints
    refuse before credential-capable construction; ambient variables refuse
    even with valid configuration.
19. Logging/exception containment: any gateway/vendor-adjacent log attachment
    collapses vendor message text to a fixed application-owned
    representation (Story 6 `_SecretLogFilter` pattern, including configured
    values, shaped secrets, password-style content, canaries, tracebacks and
    ordinary application records).
20. Lifecycle cleanup: relevant-thread lifecycle observed before
    construction/after construction/after use/after close (no background
    gateway thread or session left); idempotent bounded close; send after
    close fails safe; no interpreter-exit reliance.
21. Deterministic reproducibility: identical application inputs yield
    identical routing specs and evidence specifications byte-for-byte (UUID
    derivation, fixed allowlists); no wall-clock-fabricated field beyond
    documented timing anchors.
22. Cross-story non-interference: full Stories 1-6 regression passes
    unchanged except the adjudicated forbidden-import amendment; Story 4
    pipeline semantics and Story 5 Langfuse adapters are unmodified by
    implementation files and tests; the Story 6 LangSmith adapter receives
    only the comment/docstring-only correction adjudicated in
    Pre-adjudicated amendments item 3, with every Story 6 test preserved.
23. Dependency contract: declared constraint and locked version agree (the
    existing `requests>=2.32,<3` roots only); no `helicone` package in the
    lockfile; registry-only sources unchanged; no prohibited Guardrails
    version.
24. Optional live gateway verification (opt-in only, skipped by default with
    visible skip): under `MODULE7_HELICONE_LIVE_VERIFICATION=1` AND complete
    live configuration after human authorization of one bounded external
    write: exactly one synthetic custom request-log write (fixed
    `_type: data`, non-model, zero billable model call) then one bounded
    readback of that request by its application request ID with matching
    correlation metadata; ambiguous, mismatched, conflicting, duplicate or
    stale readback results fail safe and can never mint `live_vendor`;
    `live_vendor` only per the mint rule; skips and never runs in ordinary
    CI. Claim scope: proves only custom-log ingestion, readback, correlation
    and owned live provenance for this bounded operation - not gateway
    routing, billable execution, provider-cost observation, gateway
    fallback, REQ-TOOL-003 meaningful-use closure or REQ-OBS-004
    gateway-cost closure (see the note in Requirement-to-Acceptance
    Coverage).

## Requirement-to-Acceptance Coverage

| Assigned requirement | Contract behavior and verification |
| --- | --- |
| REQ-TOOL-003 | Real gateway routing spec, evidence transport and request/cost/fallback evidence with meaningful correlated use; tests 1, 5-9, 17; live meaningful-use closure is NOT closed by test 24 - it needs a separately authorized live gateway run and later Story 10 reconciliation (test 24 proves only its own bounded live scope, see note below) |
| REQ-OBS-003 | Application-observed latency carried in bounded timing evidence; gateway latency projected as untrusted evidence; tests 7-9 |
| REQ-OBS-004 | Cost evidence classification with strict non-authoritative relationship to Story 3 budgets; tests 9, 13; gateway-cost closure is NOT closed by test 24 (its bounded operation observes no provider cost) - it needs the separately authorized live run per Definition of Done and Open Human Decisions |
| REQ-OBS-005 | Safe correlated debugging evidence and failure isolation with allowlisted correlation; tests 6, 8, 11, 19 |
| REQ-REL-002 | Fallback observable with application-owned authority intact; gateway fallback evidence cannot behave as authority; tests 10-12 |
| REQ-DEL-001 | Helicone gateway component of the observability platform; platform closure remains Stories 9-10 |

ADR-007-002 is exercised by the two-path boundary and non-authority (tests
1, 5, 10, 11). ADR-007-004 by zero hidden retries and gateway-fallback
non-authority (tests 10-12). ADR-007-006 by allowlisted redaction-safe export
and bounded failure isolation (tests 7, 8, 11, 19). ADR-007-008 by
credential-free deterministic tests and opt-in bounded live verification
(tests 1, 4, 18, 24). ADR-007-012 by request ledger, deadline and cost-bound
discipline (tests 9, 13, 14).

Test 24 live-claim scope: the opt-in live check proves only the live Helicone
capabilities it actually exercises - custom request-log ingestion, bounded
readback of that record, its correlation, and owned live provenance for that
bounded operation when all gates succeed. It does NOT prove gateway proxy
routing, billable provider execution, provider-cost observation, gateway
fallback behavior, complete REQ-TOOL-003 meaningful gateway use, REQ-OBS-004
gateway-cost closure or production behavior. Gateway-routed meaningful use and
provider-cost evidence require the separately authorized live run and later
reconciliation already described in Definition of Done and Open Human
Decisions. This scope statement does not weaken test 24.

## Prior Non-Blocking Findings

- NB-1 (Story 4 `new_cost_usd` may include starting-state cost): inherited;
  gateway/app cost comparison uses the application value of record and the
  limitation is documented. Not fixed here; Story 4 redesign needs human
  approval.
- NB-3 (no single table-driven test over every Story 3 classification):
  remains open; Story 7 tests are not a substitute.

## Quality Gates

Implementation acceptance requires the complete Module 7 fail-fast sequence:

1. `ruff check .`
2. `pytest`
3. `python -m compileall -q src tests`

Stop at the first failure. Safe Ruff fixes only; no unsafe fixes. Preserve
bounded repair; never weaken tests, security controls, provenance controls,
evidence classification or requirements. After a repair, rerun the failed gate
and then the full sequence. Independent implementation review is mandatory
before acceptance and controlled commit. Contract authoring runs no
implementation gates and proves no implementation milestone. Temporary
engineering evidence belongs under parent TECHADEMY/EVIDENCE, outside the
repository.

## Isolation

Only Module 7 belongs to this slice. No sibling implementation, tests, runtime
state or configuration may be copied, imported, modified or depended upon.
Foreign dirty state and unrelated descendant commits are not blockers. Stop
for conflicting concurrent Module 7 changes, history divergence invalidating
the accepted Story 6 commit lineage, a real dependency/isolation conflict or a
genuine frozen-authority contradiction. Preserve frozen requirements,
TRACEABILITY, ARCHITECTURE, the ADRs and accepted Stories 1-6.

## Non-Goals

Story 7 does not export per-span operational tracing (Story 5/Langfuse owns
that), evaluation scores or regression evidence (Story 6/LangSmith owns
that), run evaluation datasets, add model execution out of Story 3 lanes,
adopt gateway fallback routing, adopt gateway rate-limit policies, send
`Helicone-User-Id` or any identity header, feed gateway cost back into the
budget, mint or claim live_vendor from mocks/seams/local servers, perform a
billable live model call through the gateway, implement the failure-recovery
simulation lab (Story 8), the Streamlit console/dashboards (Story 9), or the
overall verification/release closure (Story 10), or make any authority,
frozen-authority or Story 4 architecture change. Ordinary CI makes zero
external network calls and needs zero credentials.

## Definition of Done

Separate, non-fusible closures:

- Implementation closure: the two-path Helicone adapter boundary, settings,
  routing spec, evidence transport (HTTP-backed reusing the accepted owned
  machinery plus fake), provenance mint rule, bounds and failure isolation
  are implemented inside Module 7 only, within the published boundaries.
- Deterministic contract closure: all required tests 1-23 pass in ordinary CI
  (credential-free, zero external network); the fail-fast sequence passes;
  Stories 1-6 regression preserved with only the adjudicated amendment.
- Live-evidence closure: NOT closed by Story 7 implementation alone. The
  bounded opt-in live gateway verification (test 24), when run under
  explicit human authorization with real configuration and confirmed
  readback, yields live_vendor per the mint rule for that bounded
  operation only. REQ-TOOL-003 live meaningful gateway use, REQ-OBS-004
  gateway-cost analytics and REQ-DEL-001 platform closure remain open for
  Story 10 reconciliation even after test 24 succeeds, because test 24's
  live scope is the bounded custom-log/readback operation (see
  Requirement-to-Acceptance Coverage); they require the separately
  authorized live run. Until then, documentation and evidence must not
  claim otherwise.

Additional DoD invariants: Helicone remains untrusted and non-authoritative
end-to-end; secrets never leave the accepted boundary; ordinary CI remains
deterministic; evidence claims match evidence modes; module isolation and
frozen-authority preservation verified before independent review; quality
gates pass; independent implementation review accepts the slice before
lifecycle recording and controlled commit.

## Open Human Decisions

1. Gateway region/host selection (US vs EU vs self-hosted/OSS): kept as
   explicit configuration; not decided by frozen authority; no default
   committed by this contract.
2. Any live model call THROUGH the gateway (billable beyond the non-model
   synthetic log write of the live check): out of Story 7 scope; requires an
   explicit separate human authorization tied to ADR-007-012 budget floors
   and belongs to Story 10 live reconciliation.
3. The exact live-run monetary ceilings (request quota/cost limit values) for
   the separately authorized live run: supplied at live-run authorization
   time by the human per ADR-007-012; no value is guessed here.

Story 8 remains blocked until this contract is independently accepted, Story 7
implementation completes, independent implementation acceptance succeeds and
lifecycle recording/controlled commit completes. Contract acceptance alone
does not unblock Story 8. Authoring this document implements no Story 7
behavior.
