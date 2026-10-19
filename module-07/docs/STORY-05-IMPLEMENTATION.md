# Story 5 implementation boundary

Implementation is ready for independent review, not independently accepted.
Contract: `docs/stories/STORY-05-langfuse-integration-boundary.md`, with the
independently accepted human-approved Option A clarification (SHA-256
`6D8D8D4E02693D584F9154664BF3D0F81BEF0A3621DD859F813F52259950478B`).
Round 3 adds only the human-approved confined HTTPX import/resource-ownership
and existing-dependency declaration clarification. Current contract SHA-256:
`634B44D83F999EB6326DA618599FF2D5EB3758DEE3AE48D13A5F79F92220EFB1`.
The lifecycle requirement and Option A remain unchanged. Story 6 remains blocked until independent
implementation acceptance and lifecycle recording/controlled commit.

## Files

| File | Change |
| --- | --- |
| `src/.../langfuse_config.py` | New `LangfuseSettings` and `require_live_langfuse` |
| `src/.../langfuse_adapter.py` | Sink, spec, public LangfuseAPI/owned HTTP transport and live verification; the only `langfuse`/`httpx` importer |
| `tests/test_langfuse_adapter.py` | New Story 5 groups 1-17 |
| `tests/test_langfuse_live.py` | New opt-in group 18, skipped by default |
| `tests/test_package_contract.py` | Approved narrow Story 1 evolution: `langfuse` and `httpx` permitted only in `langfuse_adapter.py` |
| `pyproject.toml`, `uv.lock` | Langfuse 4.17.0 retained; existing HTTPX 0.28.1 declared directly; `live_vendor` marker retained |

No other accepted source, test, frozen authority or sibling module changed.
`RuntimeSettings`, `telemetry.py`, `_is_sensitive_key`, `_redact` and `minimize`
are untouched; Story 1 live mode still requires `provider_api_key`.

## Boundary

`TelemetryPipeline(exporter=LangfuseSink(...))` is the only ingress. `send`
receives the Story 4 minimized JSON string, parses it strictly (size bound, no
NaN/Infinity, no duplicate keys, exact top-level shape, required field set,
canonical lowercase UUIDs, non-zero trace ID, fixed `Event`/`Component`/`Code`/
`Decision` vocabulary, non-live evidence labels, finite nonnegative amounts,
bounded counters, `minimize`-shaped details with markers or UUID strings only).
Unknown fields are dropped; any other defect refuses the whole record, which the
accepted pipeline records locally as `export_failed`. Refusals raise
`LangfuseExportError` with a fixed reason and no `__cause__`/`__context__`.

`to_export_spec` produces an immutable primitive-only `LangfuseExportSpec`.
`LangfuseTransport` (`submit`, `flush`, `close`, `evidence_class`) is the seam;
tests use a fake transport and the real `LangfuseSdkTransport`. SDK types never
appear in specs, settings or any domain/telemetry contract.

## Mapping and correlation

One Langfuse trace per application trace: OTLP trace ID = `trace_id.hex`, with
`langfuse.internal.as_root`. One span per record; the native 64-bit span ID is
derived deterministically from SHA-256 of the canonical `span_id` UUID, which
is retained in full in metadata. `workflow_id` and `trace_id` are trace and observation metadata;
`action_id` is metadata only. Name is fixed `component.event`. Status, error
classification and history are verbatim codes (including the four Story 3
`*_exhausted` codes and `unknown`). Retry/fallback/recovery/replay/remaining,
permission/safety outcomes, record and source evidence, evaluation join UUID,
budget and minimized details are metadata. Observations are flat; history is
not turned into spans. `SEVERITY` lists every `Code` explicitly (success codes
DEFAULT; denials, pending, cancelled WARNING; all others ERROR); it is
presentation only and a forged status is refused. Vendor input/output are never
set.

## Latency, usage and cost

`duration_ms` is preserved exactly: end = injected export-time anchor, start =
end - duration, metadata `timing_anchor=export_time`. This is placement only.
Native usage is sent only for non-replayed records with known units; native cost
(`{"total": new_cost_usd}`) only for `fixture`/`supported_usage` bases. Unknown
cost is omitted, never zero; genuine fixture zero is sent as zero. Replays send
no native usage and the zero `new_cost_usd`; historical values stay in metadata
with `usage_scope=historical`. Usage-bearing observations use the SDK
`generation` type with no model name, prompt or completion.

NB-1 (inherited, unchanged): `new_cost_usd` may include starting-state cost, so
Langfuse cost totals can overstate. A test pins that the neutral value is
forwarded unchanged. Langfuse totals are display data; Story 3 budgets remain
authoritative. Repeated snapshots are not deduplicated by the adapter.

## Security and non-authority

Only Story 4-minimized records reach the adapter. Tests cover every credential
family in nested details, `SecretStr`, secret-bearing exceptions and raw
operation text across fake specs, SDK span attributes, local records, status,
settings repr and captured logs. A logging filter on the `langfuse` logger
replaces the configured key values and drops tracebacks while the transport is
open, including with ambient `LANGFUSE_DEBUG=true`.

Credential placement (Option A): the secret key appears only in the SDK's
required HTTP Basic authentication. The public key appears there and in the
SDK project-routing header. The public API path needs no key in the OTLP body,
instrumentation scope, observations or application metadata. The application
creates the OTLP models from the strictly parsed specification, not ambient state.

SDK return values, exporter results and read-back content are ignored except
counters and the bounded span-ID comparison. Tests prove authority-shaped,
instruction-bearing and malformed replies change no authorization, safety,
retry, idempotency, budget or workflow result.

## Global OpenTelemetry containment

The public `langfuse.api.LangfuseAPI` path creates no high-level Langfuse client,
resource manager, prompt cache, OTel provider or instrumentation. The adapter
constructs public OTLP models directly from the application-owned specification.
It never reads or writes current OTel context, so ambient Langfuse propagation,
baggage and foreign instrumentation cannot append data. Caller context remains
unchanged on success and failure. Tests retain ambient credentials, foreign
provider spans, serialized-payload inspection and global-provider identity checks.
Story 4 minimization/redaction and strict allowlisting remain unchanged.

## Configuration

`LangfuseSettings` (`MODULE7_LANGFUSE_` prefix, frozen, `hide_input_in_errors`)
defaults to disabled. Keys are `SecretStr`; host must be HTTPS (HTTP only for
loopback) without userinfo, query, fragment, whitespace or control characters,
and errors never echo it. Enabled settings require non-blank keys and host;
errors name fields only. Bounds: request timeout 1-30 s (default 5), lifecycle
wait 0-60 s (10), record bytes 512-65,536 (16,384), observations 1-4,096 (256),
batch 1-512 (64), flush interval 0.1-60 s (1), read-back attempts 1-10 (6),
interval 0-30 s (5). Defaults are implementation choices within Story 4 ceilings.
Network export requires `RuntimeSettings` live mode with live enablement (and
thus `provider_api_key`) plus the Langfuse flag; otherwise
`create_langfuse_sink` returns None or raises `ConfigurationError`. Ambient
`LANGFUSE_*` credentials and `MODULE7_LANGFUSE_*` credentials without the flag
construct nothing.

## Dependency and approved import evolution

Langfuse remains `>=4.17,<5`, locked 4.17.0 without extras. Installed HTTPX 0.28.1
already satisfies the supported public API. Round 3 declares `httpx>=0.28,<1`
explicitly because application code now directly imports and owns that resource;
only the root lock dependency/requirement entries are added. No resolved package,
artifact digest, registry source or version changes; no installation or upgrade.
No fresh advisory or transitive security certification is claimed.

The human approved `httpx` imports only in `langfuse_adapter.py`, only for this
Langfuse integration's owned HTTP transport. The accepted import test permits
exactly `langfuse` and `httpx` there, with every other root/file unchanged, and
AST confinement verifies that the package gains no broader networking exception.
The contract records only this approved evolution. Its lifecycle requirement,
Story 4 boundary, Option A and evidence taxonomy are preserved.

No private Langfuse API remains: public `LangfuseAPI`, public OTLP models,
`opentelemetry.export_traces`, `observations.get_many`, request options and public
HTTPX client/transport close are used. The prior `_resources` binding check is gone.

## SDK/HTTP lifecycle and bounded ownership

Construction uses the public API with an explicitly retained HTTPX client. It
creates no SDK background worker. The client disables ambient proxy inheritance
and redirects, uses finite phase timeouts and a single connection, and is closed
through public `close()`. A finite application queue accepts at most configured
`max_observations`; flush sends chunks no larger than `flush_at`. No scheduler or
background auto-flush is installed; `flush_interval_seconds` remains accepted
configuration but is unused on this explicit-flush path.

`submit` only queues; flush/readback/close run in the existing tracked operation
lane. Each attempted batch is removed before the call (no implicit retry), and
SDK `max_retries=0` is explicit. Only an empty successful export response counts
as success: partialSuccess/rejectedSpans and unrecognized results fail closed.
Readback fetches one page (limit 100, enough for the two verification observations)
and requires matching trace and canonical span metadata. No pagination loop.

The retained shared transport-identity registry registers before await. Timeout
or cancellation never cancels the underlying Python thread or loses ownership.
Conflicting operations/submissions are refused; readback stops at timeout and
close reports busy while it is unresolved. Eventual completion releases ownership.
Cancelled close remains unconfirmed and is not retried or upgraded. These are
bounded caller waits, not forced termination or distributed lifecycle guarantees.

Close flushes then closes the owned HTTP resource in finally. Successful close
requires public HTTP cleanup to return and is_closed to be true. At-most-once
transport closure retains its original result, including after cleanup failure;
repeat cannot upgrade a failed cleanup merely because HTTPX set its state flag.
Tests observe actual process threads and real HTTPX client state, and inject
hanging/failing cleanup to prove bounded truthful outcomes and credential safety.
No interpreter-exit hook or private worker cleanup is needed.

## Application-owned live verification

The ordinary sink and injected verification path always have an evidence ceiling
of `mocked_provider_contract`, regardless of object type, factory, flags or replies.
No class identity or mutable evidence property grants live authority.

Only explicit opt-in plus accepted live runtime/Langfuse settings enters the
separate owned-network branch. It constructs its own HTTP transport/client and
public SDK API internally; no caller-supplied transport or factory is accepted by
that branch. It reuses the ordinary pipeline/operation lane for two synthetic
observations, bounded flush and bounded readback.

Round 4 removes the vulnerable response-metadata mechanism. The live branch's
HTTPX transport executes its endpoint operation itself; it does not delegate to
replaceable `HTTPTransport.handle_request` or inspect response `network_stream`
extensions. It validates the request scheme, host, port and fixed API route
against accepted settings before I/O. The SDK still formats and validates the
public API call; only this confined transport executes the serialized request.

Inside that non-injectable transport, normal standard-library socket/TLS/HTTP
APIs connect to the configured destination, send the exact SDK HTTP request and
read its response from the same owned connection. HTTPS uses normal certificate
and configured-host verification; loopback HTTP remains supported. Peer checking
is only a destination constraint, never evidence authority. Redirects and ambient
proxies cannot redirect execution. Connections and response resources close in
finally, within the existing tracked operation lane and timeout semantics.

A closure-owned receipt is recorded only after that exact operation finishes
with a successful bounded response (1 MiB maximum). The request asks for identity
content encoding and refuses unexpected encoded responses. Receipts contain only
minimized request/response JSON, never authentication headers or socket claims.

`live_vendor` additionally requires matching successful submission and subsequent
readback receipts for the configured routes and the same trace/span artifacts,
plus successful required cleanup. Ordinary/injected verification remains capped
at mocked evidence. A fake response or successful fake count cannot supply the
missing endpoint operation. Fake HTTPX executors, unrelated connected sockets,
changed origins, redirects, and actual local submission plus fake readback are
regression-tested without a Langfuse service call.

Offline tests validate this control flow; they do not cryptographically prove a
remote server's identity. Production still relies on the explicitly authorized
configured endpoint and normal authenticated/TLS HTTP semantics. Trusted runtime
code and the standard-library I/O/parser remain part of the application boundary;
this is not a sandbox against arbitrary replacement of the verifier/runtime.

A real authorized verification remains opt-in in `test_langfuse_live.py`.
**No actual live vendor call is made in Round 3 or Round 4 ordinary tests.** No live evidence,
vendor ingestion/dashboard, deployment or production-scale claim is established.

## Evidence

Story 5 evidence is mocked_provider_contract: the fake transport and the real
SDK transport through an in-process exporter. Records keep `deterministic_fixture`
and upstream `simulated_failure` labels. The ordinary API transport reports mocked evidence; only the separate owned
network verification path can mint live evidence after the complete chain. Open claims: Langfuse ingestion, display,
dashboards (REQ-LAB-001), meaningful live use (REQ-TOOL-002) and platform
closure (REQ-DEL-001) need live_vendor evidence and Stories 9-10. No deployment
or production claim is made.

## Verification traceability

| Contract group | Tests (`test_langfuse_adapter.py` unless noted) |
| --- | --- |
| 1 | pipeline record maps to one fixed specification; real SDK span through in-process exporter |
| 2 | real retry/fallback/replay identity; distinct actions and extra observations |
| 3 | total severity table; every `Code` parametrized; real-controller exhaustion codes |
| 4 | export-time anchor; SDK span duration; anchor smaller than duration refused |
| 5 | four basis cases; fixture zero, replay and NB-1 pass-through |
| 6 | useful minimized debug metadata without input/output |
| 7 | 12 credential families, ambient context, public API serialized body, auth-only key placement and SDK log filtering |
| 8 | 21 malformed cases; oversized/unknown fields; local `export_failed` evidence |
| 9 | secret-safe settings, fail-closed fields, unsafe hosts, loopback, ambient non-activation, live/provider-key requirement, env bounds, independent public API clients |
| 10 | vendor replies vs real controller; forged read-back never confirms |
| 11 | submit failure local/non-recursive; flush outcomes; hanging lifecycle; SDK exporter failure/raise/hang |
| 12 | capacity, single attempt, HTTP close once, send after close, no SDK workers; hanging/failing HTTP cleanup |
| 13 | global provider and foreign spans with real Guardrails run |
| 14 | AST confinement of `langfuse`/`httpx` to the exact adapter; no production OTel imports; approved Story 1 import evolution |
| 15 | socket-guarded SDK lifecycle; live opt-in and default skip |
| 16 | ordinary/injected ceiling; same-type, official-object, forged flags and mocked-network cases; owned endpoint submission/readback execution required for live |
| 17 | constrained, locked, registry-sourced dependency |
| 18 | `test_langfuse_live.py` (skipped without opt-in) |
| 19 | full unchanged Stories 1-4 suite |

NB-3 remains open: group 3 is exhaustive over the Story 4 `Code` vocabulary for
Story 5's mapping, and five real-controller cases are mapped, but there is still
no single real-controller case for every Story 3 classification. Selected
evaluation scores are deferred to Story 6 (decision A): Story 5 forwards only the
`evaluation_id` join UUID and exports no score; Stories 6/10 must compose them.

## Historical implementation gate result (before independent rejection)

On 2026-10-16, Python 3.12.14, Module 7 environment: `ruff check .` passed;
`pytest` passed (400 passed, 1 skipped: 118 new Story 5 cases, 282 earlier
cases, the opt-in live test skipped) with six upstream Typer/Click deprecation
warnings; `python -m compileall -q src tests` passed. Mutation checks (removing
the log filter, sending unknown cost, using the SDK default provider) each made
the corresponding tests fail and were reverted. No credentials, vendor account,
external network or billable call was used. Independent acceptance is pending.

## Repair verification (builder only)

The independent rejection and re-review remain the review baseline; this document
issues no acceptance verdict. Round 3 replaces the high-level client rather than
waiving cleanup: regressions cover absence of its workers, actual public HTTP
resource closure, repeated and failed cleanup, ambient-context/serialized-key
isolation, cancelled flush/readback, conflicting re-entry and eventual ownership
release. Provenance regressions cover injected and same-type transports, subclasses,
wrappers, returned official API objects, forged flags, mocked successful network
responses and fabricated network-stream claims.

Round 3 gate/probe evidence is recorded in
`TECHADEMY/EVIDENCE/module-07-story-05-implementation-repair-round-3-gates.txt`.
Earlier reports, including the round-1 rejected-adapter sensitivity results, are
preserved as historical evidence and do not establish round-3 acceptance.
Story 4 NB-1 and NB-3 remain open. Evaluation scores remain deferred to Stories
6/10. No deployment or production readiness is claimed; independent implementation
review and controlled lifecycle commit remain outstanding.

## Round 4 provenance repair (builder only)

The independent Round 3 review closed lifecycle and reproduced a provenance
forgery with a real unrelated socket and fabricated HTTP responses. Round 4
changes only the live endpoint execution boundary and directly necessary tests
and documentation. The lifecycle transport/public SDK APIs, operation registry,
import confinement, contract, dependencies and earlier-story behavior are retained.

New evidence and exact vulnerable-source regression sensitivity are recorded in
`TECHADEMY/EVIDENCE/module-07-story-05-implementation-repair-round-4-gates.txt`.
No independent acceptance, live vendor behavior, deployment or production-scale
claim is made. Story 6 remains blocked pending independent implementation review
and controlled lifecycle completion. NB-1/NB-3 and score deferral are unchanged.
