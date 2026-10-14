# Story 10.4 implementation evidence

## Baseline, scope and files

Starting HEAD: `7b72001a2f3a0ff7395551f1acb5a8ce8668a1ef`.
Accepted Story 10.3 `439d8ebb37b5d75899c675d0e27182d0740f515f` is an
ancestor (merge-base exit 0). No intervening commit changed Module 10.
Module 10 began clean; existing foreign changes were protected throughout.
Frozen architecture and all ADRs remain unchanged. No Story 10.5 work or push.

Added `src/module10_ai/execution_config.py`, `cache.py`, `execution.py`,
`tests/test_execution.py`, and `docs/STORY_10_4.md`.
Changed `src/module10_ai/api.py`, `service.py`, `README.md`, `docs/STORIES.md`,
and `docs/TRACEABILITY.md`. No packaging/lock/dependency change.

The accepted service change extracts its existing request validation, verbatim,
into `validate_request`, still invoked by `infer`. Queue admission invokes it too:
a prepopulated cache must not bypass the service's configured text ceiling.
A regression test verifies rejection before cache lookup or queue acceptance.
The API change composes the queue with lifespan, readiness, inference and safe
503/504 mappings. Accepted schemas, body/header controls and core runtime remain
unchanged; all 123 accepted tests remain intact.

## Async, queue and failure boundaries

`JobQueue` exposes start, submit, cancel, close; `LocalExecution` implements it
using standard asyncio primitives on one event loop. There are fixed worker tasks
and at most one cooperative execution task per worker. Submission creates no task
and never waits for capacity. Defaults: four workers, 32 pending slots; hard bounds
1–32 workers and 1–1024 slots. Outstanding server job records are bounded by
pending slots plus workers. Completed handles belong to callers, with no global
terminal history or public polling/lookup API. UUID job IDs are metadata; handle
ownership uses object identity, never an ID-based authorization decision.

States: queued -> running -> succeeded / failed / timed-out / cancelled;
queued -> cancelled is also supported. Unknown/foreign handles fail safely.
Saturation or unavailable lifecycle raises QueueUnavailable; HTTP returns safe
503. Transient saturation does not make healthy workers unready. Unexpected
execution/cache defects are stored internally and propagated to the established
sanitized HTTP 500 boundary. Expected application/cache-result failures map to
503. Provider TimeoutError remains a defect, distinct from an expired worker
or HTTP deadline. No automatic retries or external calls exist.

HTTP's accepted five-second deadline includes waiting and execution. Worker
execution separately defaults to five seconds (validated 0.01–30). Expired
deadlines produce 504. Caller cancellation cancels its owned work and awaits
cooperative runtime cleanup before propagation. Cancelled queued entries occupy
bounded tombstone slots until consumed, preventing cancellation churn from
expanding retention. Fixed workers survive job failure and provider cancellation.

Startup is idempotent, shutdown permanently closes an execution instance.
Shutdown rejects new work, cancels workers and their running executions, awaits
cleanup, then drains queued jobs as cancelled. Tests verify no remaining owned
tasks. These promises require runtimes to honor cooperative cancellation; blocking
CPU work/cancellation suppression cannot be forcibly preempted by asyncio.
Production process/transport isolation remains later work. No busy waiting exists.
Aggregate QueueStats reports submitted/rejected counts, pending slots, running
job states and worker count, without payload/job-ID telemetry.

## Cache contract and configuration

`InferenceCache` exposes get, put, invalidate, stats. `LocalInferenceCache` uses
one threading lock for intended concurrent process-local access, bounded
OrderedDict LRU retention and monotonic TTL. Default 128 entries / 60 seconds;
hard bounds 1–4096 entries / 0.01–3600 seconds. Typed frozen ExecutionConfig
rejects bool coercion, invalid types, nonfinite durations and excessive bounds.

Cache keys hash exact text, keyword limit and versioned lexical semantics using
SHA-256 over canonical JSON. Raw values are absent from keys. Hashes are not
confidential encryption and keys/content should not be logged. Cache values may
contain sensitive user-derived keywords and remain in process memory until
expiration/eviction/invalidation/process exit; no disk persistence exists.
TTL runs from put/refresh, never slides on get. Get/put/stats remove expired
entries; invalidation is idempotent; hits promote LRU order. Observable counters:
hits, misses, expirations, evictions, entries. Concurrent cold misses may repeat
work within worker limits; single-flight coalescing is not promised.

Only validated inference results are inserted. Cached outputs are revalidated
before use, including deterministic classification and request keyword bound.
Cache reuse never changes execution evidence into live/cloud evidence and grants
no privileged authority. Cache lookup/storage defects fail through existing safe
HTTP errors. There is no unbounded cache dictionary or per-key metrics history.

No new runtime or development dependency. No model/cloud SDK, infrastructure,
credential read, paid operation, Redis/Celery/Kafka/RabbitMQ or UI added.

## LOCAL / DETERMINISTIC / NON-PRODUCTION performance evidence

Environment: local Windows, dedicated Module 10 CPython 3.12.14, pytest 8.4.2.
Reproduce:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_execution.py::test_local_performance --capture=tee-sys
```

Workload: eight distinct exact-input lexical requests, two workers, eight pending
slots, default 128-entry / 60-second cache. Explicit event gates ensure two runtime
calls overlap. A ninth submission before consumption proves immediate saturation.
Await all cold results, then repeat the eight exact requests sequentially.

Actual recorded run: cold batch **0.000400 seconds**, warm batch **0.000283
seconds**, **eight cold runtime calls**, **eight warm cache hits**, **zero
additional runtime calls**, **peak concurrency two**. Measurements use perf_counter;
batch times include local orchestration. There is no percentile/throughput/SLA or
required speedup claim. Acceptance relies on concurrency/capacity invariants,
backpressure and avoided repeated execution, with no microsecond timing threshold.

Limitations: tiny lexical deterministic workload, event-controlled scheduling,
one local process, no representative production model or network load. These are
not Azure, distributed, cloud, capacity-planning or production performance results.
Queue/cache are volatile and process-local; restart loses work/results. Distributed
scaling, load balancing and cloud performance evidence are deferred. C-027 and the
production-ready deployment deliverable remain incomplete.

## Verification

33 added cases plus 123 retained cases: **156 total**. Added coverage: configuration
bounds, exact keys, TTL/LRU/invalidation/statistics, threaded cache calls, fixed
worker concurrency, saturation, states, success/failure/provider timeout,
worker timeout/recovery, running/queued/caller cancellation, startup/shutdown,
no post-close admission, invalid handles, bounded submission task count,
actual HTTP cache/saturation/worker timeout, corrupt cache evidence, cache defects,
and pre-cache service admission. Accepted HTTP/core regression tests are unchanged.

Final formal fail-fast gates:

1. `python -m ruff check .`: `All checks passed!`, exit 0.
2. `python -m pytest`: 156 passed, one accepted external Starlette warning, exit 0.
3. `python -m compileall -q src tests`: no output, exit 0.

Ruff safe fixes/formatting resolved imports/line lengths without rule changes.
An initial test used a 0.01-second worker deadline below this host's observed
GetTickCount64 monotonic resolution of 0.015625 seconds; even immediate follow-up
work could expire early under asyncio's clock-resolution scheduling. The test uses
0.1 seconds with the same timeout/cleanup/recovery assertions. Production bounds
are unchanged. The failed pytest gate was rerun, then the full sequence repeated.
Tests execute outside the sandbox for Windows local asyncio socketpair plumbing;
no external provider, listener, cloud resource or paid operation is involved.

Targeted checks: UTF-8 without BOM, module-only changed/staged paths, no new
credentials/config artifacts or forbidden dependency/import, unchanged accepted
core files except the documented validation seam, no cross-module imports,
and explicit deterministic/non-production evidence. Foreign files were neither
edited nor staged. Git whitespace check passes. Architecture, requirements and
full-module Definition of Done remain unchanged. Stories records implemented /
pending independent acceptance; traceability adds only supported local evidence.

## Ordered completion assessment

Requirements: Story 10.4 application scope implemented; independent acceptance
pending. C-005/006/007/009 have local tested evidence; C-013/C-027 remain partial.
Product Experience: existing runnable API/OpenAPI contract and README instructions
exercise real queued/cached results; final Streamlit interface remains Story 10.7.
Real Functionality: actual bounded deterministic inference and process-local
queue/cache; no simulated distributed infrastructure or live AI claim.
Reliability: bounded admission, fixed workers, cooperative deadlines, failure
survival, cancellation/shutdown cleanup; restart durability explicitly absent.
Security: pre-cache input validation, untrusted output revalidation, sanitized
failures, no privileged identifier/output authority or credential handling.
Cost: zero external costs, no retries, strict queue/cache/concurrency/time bounds.
Evidence: deterministic tests and measured local batches only; no production SLA.
Deployment: containers, CI/CD, Azure, monitoring, distributed scaling, load
balancing, production deployment and governed release acceptance remain deferred.

Story 10.4 is functionally implemented pending independent acceptance. This is
not a claim of overall module production readiness or C-027 completion.
