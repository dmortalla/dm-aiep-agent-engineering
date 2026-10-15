# Module 10 deterministic inference service — Stories 10.2–10.6

This standalone Python 3.12 package supplies a framework-independent inference
core and a FastAPI HTTP boundary. Deterministic inference performs no external
network calls, credential loading, or privileged actions. Streamlit remains planned.

From `module-10/`, install the module-local environment with `uv sync --locked
--python 3.12`. The committed `uv.lock` fixes development dependency resolution;
Hatchling builds the installable `src/module10_ai` package. Ruff, pytest, and HTTPX are development tools. FastAPI and Uvicorn are runtime
dependencies; Pydantic handles HTTP schemas only. Frozen standard-library
dataclasses continue to define the framework-independent core.

The deterministic runtime counts Unicode alphabetic words, ignoring numbers,
punctuation, and underscores. It lowercases before tokenization, ranks words by
descending frequency and then alphabetical order, and returns at most the
requested keyword limit. This is lexical fixture analysis, not live AI generation.
The same input produces the same structured output; no timestamps or random values
enter the result.

```python
import asyncio
from dataclasses import asdict
from module10_ai import InferenceRequest, InferenceService

result = asyncio.run(
    InferenceService().infer(InferenceRequest("Beta alpha beta gamma", keyword_limit=3))
)
print(asdict(result))
# {'word_count': 4, 'keywords': ('beta', 'alpha', 'gamma'), 'evidence': 'deterministic'}
```

Requests accept 1–4096 characters of nonblank text and a strict integer keyword
limit of 1–10. Configuration can reduce the input ceiling; unsupported modes fail
closed. Boolean values do not count as integers. Contracts are immutable and do
not coerce input. The service revalidates requests and provider results, checks
request-specific output bounds, and rejects evidence inconsistent with its
deterministic configuration. Local-runtime and live-cloud labels exist solely
to distinguish future evidence; neither mode is implemented or authorized here.

The asynchronous `InferenceRuntime` protocol supports trusted provider injection
without HTTP or UI imports. Execution is one bounded deterministic pass, with no
retry loop or external cost. HTTP deadlines are implemented in Story 10.3.
Story 10.4 adds process-local queueing, caching, and concurrency controls around
this core.

Invalid caller input raises `ContractError`; invalid configuration raises
`ConfigurationError`. Expected provider `RuntimeFailure` or `ContractError`
failures become `InferenceFailure`, preserving causal context. Malformed provider
results also become `InferenceFailure`. Unexpected programming defects and caller
cancellation propagate. Public failure messages never interpolate input/provider
details, and request/result reprs omit text/keywords. Exception causes are internal
diagnostic context: the Story 10.3 API never serializes tracebacks or causes to clients.
Keyword output remains untrusted user-derived data and may be sensitive; a future
presentation layer must escape it and avoid logging raw content. It grants no
deployment, rollback, or infrastructure authority.

Run the gates sequentially, stopping at the first failure:

```powershell
.venv/Scripts/ruff.exe check .
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m compileall src tests
```

See [Story 10.2 evidence](docs/STORY_10_2.md) for current verification and scope.
This core is functionally complete for Story 10.2; the Module 10 production
deployment and full reviewer experience remain unproven.


## Run the Story 10.3 HTTP service

From `module-10/`, run:

```powershell
uv sync --locked --python 3.12
.venv/Scripts/python.exe -m uvicorn module10_ai.api:create_app --factory --host 127.0.0.1 --port 8000
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/inference -ContentType application/json -Body '{"text":"Beta alpha beta gamma","keyword_limit":3}'
```

`create_app(HttpConfig(...), service=...)` supports validated trusted configuration
and accepted service injection. There are no required secrets or environment
credential reads. The default CLI binds loopback. This is a local runnable service,
not evidence of container or cloud deployment.

| Endpoint | Meaning |
|---|---|
| `POST /api/v1/inference` | Strict JSON lexical input; structured deterministic result and request ID |
| `GET /health/live` | HTTP process alive; no dependency probe |
| `GET /health/ready` | Deterministic service constructed and lifespan accepting work; 503 otherwise |
| `GET /openapi.json` | Typed API contract, bounds, error responses and correlation header |

Interactive `/docs` is disabled by default; opt in with
`HttpConfig(docs_enabled=True)`. ReDoc stays disabled. Readiness now checks the
fixed worker lifecycle alongside service lifespan. It checks no future provider,
cloud, or telemetry dependency. It does not prove capacity,
scaling, or cloud readiness.

Every HTTP response gets `X-Request-ID`. A single inbound ID containing 1–64 ASCII
letters, digits, underscores or hyphens is propagated. Missing, malformed,
non-ASCII, oversized or duplicate values are replaced with a fresh UUID hex ID.
The configurable ceiling is 32–128. IDs are correlation metadata, never identity
or authorization; do not put secrets into them. Error/result bodies also include
the safe ID, available internally on `request.state.request_id`.

The pure ASGI boundary buffers at most 32768 actual raw body bytes before normal
JSON parsing, including streaming requests without Content-Length. Oversize is
413; malformed/duplicate lengths or actual length mismatch are 400. Bodies have
a five-second total read deadline (408); compression is rejected (415). Inference
requires `application/json` (parameters allowed); missing/unsupported/duplicate
content type is 415. Headers are capped at 64 entries, 8192 aggregate name/value
bytes, 128 bytes per name and 2048 bytes per value (431). Text is strict nonblank
Unicode, 1–4096 characters; keyword limits are strict integers 1–10; extra fields
are rejected. HTTP text/body ceilings can be lowered independently.

Inference has a configurable five-second cooperative asyncio deadline (504).
Caller cancellation propagates and awaited work is cancelled without retries.
A provider's own unrelated TimeoutError is an internal failure, not an API deadline.
The deterministic runtime does a short bounded synchronous calculation inside its
async method: cooperative deadlines cannot preempt CPU code or a provider that
suppresses cancellation. Such providers are outside the accepted runtime contract;
process-level resource isolation remains a later deployment concern.

All errors use fixed `code`, `message`, `request_id` fields. Validation is 422;
malformed JSON/encoding is sanitized 400 or 422. Domain caller errors map to 422,
expected inference failures to 503, unexpected defects to 500. No exception text,
traceback, file paths, raw input, secret values or validation locations are returned.
Failure diagnostics emit only a correlation digest and fixed operational
categories; original service exception chaining remains intact internally.
No response grants privileged authority. `nosniff` is set on responses.

No authentication, CORS allowance, or trusted-host policy is invented for this story.
The service has no consequential operations. Restrict ingress and choose the real
authentication/host policy before exposing it externally in the deployment stories.
ASGI body bounds apply after server delivery; server/proxy connection, transport
header, and aggregate concurrency limits are separate later deployment controls.

See [Story 10.3 evidence](docs/STORY_10_3.md). HTTP integration is exercised in-process
with no external listener or provider. Story 10.5+ capabilities and overall
production readiness remain unproven. The locked Starlette version warns that HTTPX TestClient
support is deprecated; it remains supported and all current HTTP checks pass.


## Story 10.4 bounded local execution

The same inference endpoint now queues work and awaits its result. Its response
schema and request-ID behavior are preserved. Saturation returns a sanitized 503
`queue_unavailable`; unavailable workers return 503 `not_ready`. Healthy saturation
does not make readiness fail. The existing HTTP deadline includes queue waiting;
a separate worker deadline bounds execution. Both return the established 504.

Pass `execution_config=ExecutionConfig(...)` to `create_app`; import the settings
from `module10_ai.execution_config`. No new dependencies or environment reads exist.

| Setting | Default | Supported range |
|---|---:|---:|
| max_workers | 4 | 1–32 |
| queue_capacity | 32 pending slots | 1–1024 |
| job_timeout_seconds | 5 | 0.01–30 |
| cache_capacity | 128 entries | 1–4096 |
| cache_ttl_seconds | 60 | 0.01–3600 |

`LocalExecution` in `module10_ai.execution` implements the `JobQueue` application
contract: `start`, `submit`, `cancel`, `close`. `submit` returns an opaque `Job`
whose `state` and awaitable `result()` expose completion. No public HTTP job
identifiers or polling endpoints are added. Handles and IDs grant no authority.
Queue/cache aggregate statistics are available for later telemetry integration.
Use each execution instance on one event loop and close it before that loop exits.
Startup is idempotent; shutdown permanently closes that instance.

There are fixed worker tasks and at most one execution task per worker; submissions
create no tasks. Pending slots plus workers bound retained outstanding records.
Cancellation removes no pending slot until its bounded tombstone is consumed.
Shutdown rejects submissions, cancels running work, drains pending work, and awaits
cooperative runtime cleanup. There are no retries. Runtimes must honor cancellation;
asyncio cannot forcibly preempt blocking CPU work or cancellation suppression.

The thread-safe process-local cache implements `InferenceCache`: exact-input,
versioned SHA-256 keys, TTL from insertion/refresh (not access), LRU eviction,
idempotent invalidation, and hit/miss/expiration/eviction statistics. Expiration
occurs on get/put/stats; stale entries are never returned. Hashes avoid raw values
but are not encryption; do not log keys or sensitive result content. Results remain
untrusted deterministic data; cache metadata does not change their evidence class.
Concurrent cold misses may repeat work within the worker bound; single-flight
coalescing is not promised. Cache errors fail safely rather than returning corrupt
output. Service request limits are checked before cache lookup.

Queue and cache are neither durable nor distributed. Restart loses jobs/results;
completed job handles are not retained in a server history. Distributed scaling,
load balancing, cloud performance, deployment, and full C-027 acceptance are deferred.

Reproduce local deterministic performance evidence:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_execution.py::test_local_performance --capture=tee-sys
```

The test reports actual batch elapsed times, runtime calls, hits, and peak
concurrency. Acceptance uses resource invariants and avoided repeated calls,
without fragile timing/speedup thresholds. See [Story 10.4 evidence](docs/STORY_10_4.md).

## Story 10.5 local container workflow

Story 10.5 is independently accepted at
`1a010ca82bb88b90f2358af0bf7417f62d192d39` (local container integration / deterministic).
See [Story 10.5](docs/STORY_10_5.md) for actual evidence and limitations.
From `module-10/`, with a healthy Linux Docker engine:

```powershell
docker build --tag module10-ai:story105 .
docker run --detach --name module10-story105 --read-only --cap-drop=ALL --security-opt=no-new-privileges --memory=256m --cpus=1 --pids-limit=64 --publish 127.0.0.1:8000:8000 module10-ai:story105
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/inference -ContentType application/json -Body '{"text":"Beta alpha beta gamma","keyword_limit":3}'
docker stop --time 15 module10-story105
docker rm module10-story105
```

Use an unused container name and host port if these are already occupied. Port
8000 is the sole declared container port; publish to loopback for local review.
The image requires no secrets and runs deterministic lexical inference only.
Dedicated UID/GID 10001 owns no application files; source and runtime environment
are root-owned and read-only. The service needs no writable application paths.
Uvicorn runs directly as PID 1 with one process, no reload and no access log.
SIGTERM permits the accepted lifespan/worker cleanup; the command bounds graceful
request draining to ten seconds. Default Python/Uvicorn lifecycle logs remain.

Docker HEALTHCHECK probes `/health/ready` using Python's standard library.
`/health/live` checks HTTP process liveness separately. Readiness represents the
accepted deterministic service/worker lifecycle, not cloud capacity or an SLA.
Existing application bounds remain unchanged. They currently use trusted typed
factory configuration, not application environment variables; this story adds
no environment parser. Uvicorn's existing runtime environment settings remain
available via `docker run --env` where not overridden by explicit CLI options.
Future live credentials must be injected at runtime; no live provider is enabled.

Run explicit integration acceptance separately from ordinary pytest:

```powershell
.venv/Scripts/python.exe scripts/container_acceptance.py
```

It uses a unique image/container name and an ephemeral loopback host port, builds
from this module only, exercises read-only execution, effective UID, image/content
checks, Docker health, both HTTP health routes, deterministic inference, invalid
and malformed requests, and graceful stop. It removes only its own container in
`finally`, retaining its uniquely tagged image for review. JSON facts print to
stdout; store temporary captures under parent `TECHADEMY/EVIDENCE`, never here.
Failed assertions/CLI calls exit nonzero; partial facts do not mean acceptance.
No Compose, external service, cloud cost or global Docker pruning is involved.

Application dependencies are selected and hash-verified from `uv.lock` with
`uv sync --locked --no-dev --no-install-project`. The pure Python application
source is copied explicitly and loaded via `PYTHONPATH`, avoiding an unpinned
isolated Hatchling build. No editable install or build backend is needed in the
image. The builder's uv/cache/manifests and local tests/docs never enter runtime.
Python 3.12.14 slim Bookworm and uv 0.12.5 use explicit version tags. Tags may be
republished; bit-identical image rebuilds are not claimed without reviewed digest
pins. Base security patch/digest review remains necessary before deployment.

Azure deployment, Azure Container Apps orchestration, Azure Monitor, load balancing,
distributed queue/cache, CI/CD, production SLA evidence, and overall C-026/C-027
completion remain deferred to later stories.


## Story 10.6 provider-neutral observability

Application events emit bounded JSON to stderr through a dedicated standard-library
logger. Uvicorn lifecycle logs retain their existing format. No dependency, cloud
exporter, credential, environment parser or public metrics endpoint is added.
`create_app(telemetry=Telemetry(...))` accepts a trusted synchronous event sink;
`Telemetry(None)` disables event emission while retaining bounded local metrics.
Invalid recorder/sink configuration is rejected. Sinks must return promptly;
blocking exporters must later supply their own bounded buffering and timeouts.

From `module-10/`, reproduce cold/warm queue/cache evidence:

```powershell
.venv/Scripts/python.exe scripts/observability_demo.py
.venv/Scripts/python.exe -m pytest tests/test_telemetry.py
```

The helper prints at most 32 captured events and a metrics snapshot, uses no
network or keys, and retains no payloads in telemetry. Tests separately exercise
HTTP success/rejection/failure, timeout, backpressure, cancellation, malicious
metadata and sink failures. In an embedded app, use
`app.state.telemetry.snapshot()` for an internal detached metrics snapshot.
No metrics are served over HTTP in this unauthenticated application.

HTTP request IDs and public responses retain their accepted behavior. To find a
request in events, compute `module10_ai.telemetry.correlation_id(request_id)`;
raw caller IDs are never logged, even when they satisfy the public syntax check.
The digest is correlation metadata, not identity or authorization. It is not
anonymization or secret detection. Do not put secrets in request IDs.

See [Story 10.6](docs/STORY_10_6.md) for schema, fixed metrics, trust boundaries,
failure isolation, adapter contract and limitations. Evidence is local and
deterministic, not production traffic, SLA validation or Azure Monitor delivery.
Streamlit remains Story 10.7; Azure deployment/Container Apps/Monitor, load
balancing, distributed queue/cache, CI/CD and overall C-026/C-027 remain deferred.
