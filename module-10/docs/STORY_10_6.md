# Story 10.6 — provider-neutral observability implemented; independent acceptance pending

## Baseline and scope

Starting HEAD: `a9297817f45acd88308a145b6eb8da1645e49337`.
Accepted Story 10.5: `1a010ca82bb88b90f2358af0bf7417f62d192d39`.
Ancestry check passed (merge-base exit 0); intervening Module 10 history was empty.
Module 10 started clean. Architecture, requirements, traceability, stories,
Definition of Done, all nine accepted ADRs, prior story evidence, README,
packaging and relevant source/tests were reviewed. Frozen architecture is unchanged.

Story 10.5's independent acceptance is supplied by the human request and is
classified LOCAL CONTAINER INTEGRATION / deterministic. Historical Story 10.5
implementation notes retain their original pending-acceptance statements; current
README/STORIES/TRACEABILITY reflect the supplied acceptance. No other module is implementation
source or a dependency. Foreign concurrent work is protected and untouched.

Added `src/module10_ai/telemetry.py`, `tests/test_telemetry.py`,
`scripts/observability_demo.py`, and this document. Changed `api.py`,
`http_boundary.py`, `execution.py`, `cache.py`, `scripts/container_acceptance.py`,
README, STORIES and TRACEABILITY. No dependency, lockfile, Dockerfile, core domain,
authoritative requirement, accepted ADR or architecture change is required.

## Application-side architecture and authority

One application-owned `Telemetry` instance composes the HTTP boundary, existing
local execution queue and default cache. Direct queue/cache construction supports
the same optional trusted instance. The domain service and runtime remain separate
from HTTP/UI/cloud. Custom injected caches keep their existing protocol; adapters
may publish through the same telemetry boundary, but their internal maintenance
cannot be inferred automatically. The accepted process-local queue/cache design
and resource bounds are preserved.

The standard-library implementation provides an event sink and detached internal
aggregate snapshot. No tracing SDK or span system is needed to connect the existing
operations; these correlated events make no distributed tracing, W3C or
OpenTelemetry compatibility claim. Telemetry does not feed business decisions,
readiness, security checks, configuration, output validation or evidence selection.
It grants no authentication, authorization, approval, deployment, rollback, model,
tool or infrastructure authority. A successful metric is not business evidence of
success unless the authoritative operation actually succeeded.

## Event schema and correlation

Each emitted JSON object contains:

| Field | Meaning |
|---|---|
| schema_version | 1 |
| event | Fixed allowlisted operation name |
| timestamp | UTC ISO-8601 emission time |
| severity | INFO for success; ERROR for other operational outcomes |
| status | success, failure, timeout, cancelled or rejected |
| category | none, contract, inference, internal or deadline |
| correlation_id | Optional 32 hex characters: first 128 bits of SHA-256 of the bounded request ID |
| job_id | Optional internally generated UUID hex on queue admission/job completion |
| duration_seconds | Optional finite nonnegative monotonic elapsed seconds, at most 86400 |

The nine event names are `http.completed`, `application.failure`, `queue.admitted`,
`queue.rejected`, `job.completed`, `inference.completed`, `cache.hit`, `cache.miss`,
and `readiness.failed`. There are no arbitrary attributes or free-form messages.
Timestamp and generated job IDs vary; deterministic inference output does not.
Zero measured duration is valid on a coarse local clock.

Accepted HTTP ID validation, replacement, public headers/bodies and OpenAPI stay
unchanged. The HTTP boundary hashes the accepted ID into task-local context; each
bounded job copies that digest explicitly. Fixed workers bind it per job, child
inference tasks inherit it, and context is reset after completion/cancellation.
HTTP -> queue admission -> cache -> inference (on a miss) -> job completion ->
HTTP outcome can therefore be followed by digest. Job IDs distinguish admissions
and completions without a public job endpoint. Caller IDs need not be unique and
are never user identity. Digests are correlation metadata, not anonymization or
perfect secret detection; predictable values can be guessed. Do not send secrets
in request IDs. No raw HTTP ID is emitted, even if it looks syntactically safe.

## Metrics and bounded retention

`Telemetry.snapshot()` and `app.state.telemetry.snapshot()` expose detached
process-local aggregates internally; no public diagnostic/metrics route exists.

- Counters use only event/status keys: at most 9 x 5 = 45 entries.
- Duration aggregates use the same fixed keys: count, sum and maximum, at most
  45 entries. No samples, percentiles or request histories are retained.
- Six fixed gauges cover pending queue slots, active workers, configured workers,
  cache entries, cumulative expirations and cumulative evictions.
- A saturating local telemetry-failure counter reports dropped invalid inputs and
  serialization/sink failures. Metric updates precede event export.
- Integers saturate at 2^63-1; sums saturate at its finite float representation.
  Negative, boolean, non-finite, oversized timing and invalid dimension input is
  rejected without creating registry entries or changing business execution.

HTTP counts are sums of `http.completed` status counters; timeout/cancelled are
explicit non-success outcomes. They cover framing, validation, inference and
routing outcomes. Successful liveness/readiness probes are deliberately excluded
from both logs and HTTP aggregates to avoid probe noise. Failed readiness records
an operational signal. HTTP duration includes body reads, queue waiting and
response delivery; worker duration starts at dequeue, and inference duration
measures the actual service call on a cache miss. Worker deadline cancellation may
record cancelled inference and timed-out job, reflecting the two distinct layers.
Queue rejection covers both saturation and unavailable worker lifecycle.

Cache hit/miss events expose no keys or contents. TTL/LRU maintenance counts are
cumulative gauges from the accepted cache, not fabricated expiration events.
Gauges update after operations/snapshots; TTL expiration remains lazy, exactly as
before. Export callbacks run outside cache/telemetry locks. Concurrent cache gauge
publication is best-effort, not a globally atomic operational snapshot. Restart
loses all telemetry; no cross-process or cross-replica aggregation is implemented.

## Data minimization and failure isolation

The allowlist excludes raw bodies, prompts, model output, cache keys, URLs/query
strings, headers, cookies, environment values, exception names/text/causes,
tracebacks, filesystem paths and stack locals. Failure categories are application
controlled rather than reflecting arbitrary provider-defined class names. Source
exception chaining and business failure/cancellation propagation remain intact.
No credential discovery or attempted blacklist-based secret detection is added.
Schema literals, bounded hashes/UUIDs and bounded numeric fields keep record size
independent of input/model length; tests verify records stay below 600 characters.

The default dedicated logger writes pre-serialized JSON to stderr without changing
root/Uvicorn logging. Its `SafeStreamHandler` rethrows stream failures into the
telemetry boundary, avoiding standard logging's traceback-printing diagnostic
fallback. Optional sink absence still records metrics. Sink/serialization errors
increment one local counter, never recursively log, never retry, and do not fail
successful business execution or turn business errors into success. The broad
exception catch is confined to the untrusted telemetry adapter/serialization
boundary; application exceptions are classified and re-raised or translated using
the accepted safe HTTP contract. BaseException/cancellation is not swallowed.

Configuration adds only trusted constructor/factory injection: `Telemetry(sink)`
or `Telemetry(None)` for metric-only operation. Invalid sink/recorder types fail
construction. No environment variables, secrets, arbitrary dimensions, per-request
configuration, disableable security controls or new dependency are introduced.
Sinks must be synchronous, bounded and prompt. This implementation cannot forcibly
interrupt a blocking third-party handler; later exporters must supply explicit
bounded buffering, deadlines, retry/drop policy and shutdown behavior. Current
stderr/container logging is local evidence, not external-delivery assurance.

## Verification

Module environment: Python 3.12.14, pytest 8.4.2. All 160 accepted Story 10.2–10.5
regressions remain; 28 telemetry cases bring the exact total to **188**.
They cover JSON schema/timestamps/severity, correlation, caller-header/prompt
minimization, exception sanitization, fixed cardinality/saturation, detached
snapshots, finite durations, cache TTL/LRU signals, explicit queue saturation,
worker activity, per-job context isolation, cancellation/shutdown, timeout,
readiness, optional/broken sinks, serialization failure and actual stream-write
failure without diagnostic leakage. Existing HTTP bounds, OpenAPI, deadlines,
cancellation, deterministic execution and Docker artifact tests pass unchanged.

Final formal fail-fast sequence:

1. `python -m ruff check .`: `All checks passed!`, exit 0.
2. `python -m pytest`: **188 passed, 1 warning in 1.62s**, exit 0.
3. `python -m compileall -q src tests scripts`: no output, exit 0.
4. `python scripts/container_acceptance.py`: local Docker regression, reported below.

The existing third-party Starlette HTTPX deprecation warning remains unsuppressed.
An initial sandboxed pytest stalled in Windows asyncio local socketpair startup
and was interrupted; unsandboxed execution works, matching prior story evidence.
Initial Ruff line lengths received safe formatting repair. A new adversarial
100000-character input initially produced a Windows pytest setup error because
pytest used it as a test ID; explicit short test IDs repaired the harness without
reducing the input or assertions. The failed gate passed and the full sequence
was rerun. Final review also added the real broken-stream test and reran all gates.

`python scripts/observability_demo.py` passed: seven bounded correlated events,
two admitted/successful jobs, one cache miss, one actual inference, one cache hit,
zero pending/active work after close and zero telemetry failures. Elapsed aggregates
were finite (locally 0.0 seconds, within clock resolution); no speedup or SLA claim
is made. The capture deque is capped at 32 records. HTTP invalid/failure evidence
is separately reproducible through `tests/test_telemetry.py`. No temporary evidence
files are shipped; external captures belong under parent `TECHADEMY/EVIDENCE`.

Final local Docker regression: exit 0, image tag
`module10-story105-6f71b22da6b4:local`, image ID
`sha256:05870578cd3a32951d2906d965987a35cac369b8a2e4d4ce3f355125c5bf3b81`.
Build/startup, readiness, Docker healthcheck, liveness, effective UID 10001,
targeted content/permissions, deterministic inference, invalid schema 422,
malformed JSON rejection, correlated/minimized structured telemetry and graceful
stop exit 0 all passed. The own container was removed and exact-name absence
verified; its unique tagged image remains. No cloud deployment is implied.
The script's historical story105 resource prefix is retained for compatibility.

Targeted final checks cover owned-file UTF-8 without BOM, Git whitespace,
module-only staging, unchanged architecture/core/dependencies, no cross-module
imports, no credential artifacts or obvious credential literals in shipped source,
and explicit deferred evidence classifications. Initial owned-document encoding
review found and repaired Windows default-decoding corruption of Unicode dashes;
final documents use explicit UTF-8. These checks and adversarial tests are not
comprehensive secret/vulnerability detection. Only Module 10 files are committed;
foreign concurrent work remains untouched.

## Future adapter boundary and deferred capability

A later trusted Azure Monitor adapter can consume serialized schema-v1 events via
`Telemetry(sink=...)` and poll detached snapshots with explicit delta/reset handling.
No business-logic rewrite is needed to attach that adapter. Mapping/export,
authentication, delivery reliability, resource/cost bounds and genuine Azure receipt
need their own implementation and evidence. C-011/C-013/C-014 receive partial
application-side evidence here; **C-025 actual Azure Monitor integration is DEFERRED**.

Azure deployment, Azure Container Apps, load balancing, distributed queue/cache,
CI/CD, live providers, production traffic/SLA evidence, and overall C-026/C-027
completion are DEFERRED. Unified Streamlit reviewer UI belongs to Story 10.7,
which has not begun. No cloud/AI calls or billable operations were performed.

## Ordered completion assessment

Requirements: Story 10.6 implemented against the frozen architecture; broader
course monitoring/deployment requirements remain partial/deferred.
Product Experience: runnable bounded CLI evidence and HTTP/injection tests;
unified reviewer UI remains Story 10.7.
Real Functionality: actual deterministic HTTP/queue/cache operations emit JSON and
update internal aggregates; external collection/export remains unimplemented.
Reliability: cancellation, deadlines, queue bounds and business failures preserved;
telemetry failure isolated with a bounded local counter.
Security: allowlisted schema, hashed caller metadata and fixed categories; no public
operational endpoint or privileged telemetry authority; no perfect secret-detection claim.
Cost: no added dependencies/provider/cloud calls; fixed memory/cardinality and no
export retries; host log retention/rate policy remains deployment responsibility.
Evidence: deterministic tests, local demo and local container integration only;
independent Story 10.6 acceptance is pending.
Deployment: existing hardened local Docker contract exercised because production
image source changed; Azure and production-grade validation remain deferred.

The full-module Definition of Done remains unchanged. Functional Story 10.6
implementation is not overall production-grade completion or release acceptance.
