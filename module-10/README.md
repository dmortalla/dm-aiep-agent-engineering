# Module 10 deterministic inference service — Stories 10.2–10.3

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
retry loop or external cost. HTTP deadlines are now implemented in Story 10.3. Queueing, cache behavior,
and concurrency controls remain later-story work.

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
`HttpConfig(docs_enabled=True)`. ReDoc stays disabled. Readiness checks no future
provider, queue, cache, cloud, or telemetry dependency. It does not prove capacity,
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
Failure diagnostics log only bounded correlation, exception/cause types, and
function names/line numbers; original service exception chaining remains intact.
No response grants privileged authority. `nosniff` is set on responses.

No authentication, CORS allowance, or trusted-host policy is invented for this story.
The service has no consequential operations. Restrict ingress and choose the real
authentication/host policy before exposing it externally in the deployment stories.
ASGI body bounds apply after server delivery; server/proxy connection, transport
header, and aggregate concurrency limits are separate later deployment controls.

See [Story 10.3 evidence](docs/STORY_10_3.md). HTTP integration is exercised in-process
with no external listener or provider. Story 10.4+ capabilities and overall production
readiness remain unproven. The locked Starlette version warns that HTTPX TestClient
support is deprecated; it remains supported and all current HTTP checks pass.
