# Story 10.3 implementation evidence

## Baseline and isolation

Starting HEAD: `8e178915cb04a8b78fcaa4c5dcfaeb914c6d74d9`.
Accepted Story 10.2: `add9655ad0bd04aa05f0ce957e88eacf25f21cf5` is an
ancestor (merge-base exit 0). No intervening commit changed Module 10.
All requested Module 10 documents, nine accepted ADRs, source and tests were read
before editing. The frozen architecture and accepted core implementation are unchanged.
Only Module 10 paths were edited/staged; unrelated concurrent work was left alone.
No push or other-module implementation occurred.

## Files and implemented boundary

Added `src/module10_ai/api.py`, `http_config.py`, `http_schemas.py`,
`http_boundary.py`, `tests/test_api.py`, and this evidence document.
Changed `pyproject.toml`, `uv.lock`, `README.md`, `docs/STORIES.md`,
`docs/TRACEABILITY.md`, and the package-dependency assertion in `tests/test_core.py`.
The core import-isolation assertion and all 58 Story 10.2 behavior tests remain.

The factory constructs the accepted InferenceService, while HTTP schemas explicitly
convert to/from domain contracts. Routes contain transport orchestration only.
`POST /api/v1/inference` returns strict deterministic lexical results, not live AI.
`GET /health/live` reports process liveness. `GET /health/ready` reports whether
the constructed deterministic service's lifespan is accepting work (503 otherwise).
No fake dependency readiness checks are introduced. `/openapi.json` describes
routes, input/output bounds, deterministic provenance, error models and request IDs.
Interactive docs require explicit opt-in; ReDoc is disabled.

Correlation policy: propagate one 1–64 character ASCII alphanumeric/underscore/
hyphen identifier; otherwise generate UUID hex, including duplicates. Configurable
ID ceiling is 32–128. Every HTTP response has X-Request-ID; inference/error bodies
carry it too. Request state makes it available to future observability. It conveys
no identity or authority.

Pure ASGI middleware bounds actual accumulated body bytes before FastAPI JSON
parsing. Default 32768 bytes, configurable 128–65536; oversize returns 413.
Malformed/duplicate declared lengths and actual mismatch return 400. Total body
read deadline defaults to five seconds (408). Compression is rejected (415).
Inference requires a single application/json content type (parameters allowed).
Headers have fixed per-name/per-value/count/aggregate bounds and return 431.
Schema requires nonblank strict text (1–4096), strict integer keyword limits
(1–10), and no extra fields. HTTP text ceiling can be lower than the domain bound.

Inference deadline defaults to five seconds, bounded 0.01–30 (504). Awaited work
is cancelled, cleanup executes, and caller CancelledError propagates. No retry
is added. Provider TimeoutError is distinguished from expiry of the API deadline.
Cooperative asyncio deadlines cannot preempt CPU work or cancellation-suppressing
providers. The accepted deterministic CPU calculation remains bounded by input size;
transport/concurrency/process isolation remains later-story work.

Public failures use fixed-size code/message/request_id envelopes. Caller domain
rejection is 422, expected inference failure 503, unexpected defects 500, malformed
JSON/encoding sanitized 400 or 422. Errors never serialize exception text, causes,
validation input/location, stack traces, file paths or secrets. Server diagnostics
retain bounded exception/cause types and function/line context, excluding exception
messages, filenames and locals. The core preserves original chained causes.

## Dependencies and security decisions

Added runtime FastAPI (locked 0.143.1) for the authoritative HTTP requirement and
Uvicorn (0.54.0) for the runnable ASGI service. Added development HTTPX (0.28.1)
for in-process HTTP testing. Transitive Pydantic/Starlette stay in the HTTP layer;
no FastAPI/Pydantic/Starlette/Uvicorn imports enter the accepted core.
The lock records reproducible module-local dependency resolution. No model/cloud/
queue/cache/UI SDKs or secrets are introduced. Starlette's supported HTTPX
TestClient emits one deprecation warning recommending HTTPX2; migration is not
required for these passing tests and is not hidden by warning suppression.

No fake authentication, CORS allowance, or host policy is introduced. Default
runnable command binds loopback; external ingress/authentication policy must be
established during deployment. Responses set nosniff. Correlation is not identity;
model-derived keywords remain data with no privileged control. Readiness does not
prove capacity, cloud dependencies, load balancing or deployment.

Design references: [Starlette pure ASGI middleware](https://starlette.dev/middleware/)
and [FastAPI validation/error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/).

## Verification

Dedicated Module 10 CPython 3.12.14 environment, pytest 8.4.2.
65 added HTTP tests plus 58 retained core tests: **123 total**.
Coverage includes construction, lifecycle readiness, deterministic HTTP contracts,
IDs, input schemas, malformed JSON/encoding/nesting, content types, actual streamed
body bounds, declared framing, header ceilings, compressed bodies, read timeout,
disconnects, inference timeout cleanup, injected and external task cancellation,
domain/application/defect mapping, sensitive-detail exclusion, OpenAPI contracts,
configuration bounds and inclusive Unicode/identifier limits.

Final formal fail-fast sequence:

1. `python -m ruff check .`: `All checks passed!`, exit 0.
2. `python -m pytest`: `123 passed, 1 warning in 1.28s`, exit 0.
3. `python -m compileall -q src tests`: no output, exit 0.

Ruff safe formatting repaired line lengths without rule changes or unsafe fixes.
Initial pytest diagnosed a package metadata assertion that assumed dependency
specifier order. A bounded repair parses both allowed ordering forms; no behavior
or isolation assertion was weakened. The failed gate and complete sequence were
rerun. Tests run outside the sandbox for Windows asyncio local socketpair plumbing,
with no external provider/listener or billable operation.

Targeted checks: all changed/untracked story paths are Module 10 only; UTF-8
without BOM; no accidental credential/config artifact or future-story dependency;
accepted core source unchanged and free of HTTP framework imports; index scope
verified before one focused local commit. Documentation records implemented status,
not independent acceptance. Full-module Definition of Done stays unchanged.

## Completion assessment

Requirements: Story 10.3 application boundary implemented; C-003/C-019 deployment
portions remain pending. Full course deliverables remain partial/planned.
Product Experience: runnable loopback API, README examples, OpenAPI; Streamlit pending.
Real Functionality: genuine deterministic application execution through in-process
HTTP integration, correctly classified; no external live inference or deployment.
Reliability: bounded input/read/deadline failures, cancellation, lifecycle readiness;
queue/cache/concurrency/scaling and process-level controls deferred.
Security: strict input, safe errors/log diagnostics, no privileged output authority
or secret handling; external authentication/ingress policy remains unproven.
Cost: no provider calls, cloud resources, retries, or paid operations.
Evidence: deterministic core and in-process HTTP checks, native gates and isolation.
Deployment: Uvicorn construction/run command supplied; Docker, Azure, Azure Monitor,
CI/CD, load balancing, live providers and deployment acceptance remain unproven.

Story 10.3 functional implementation is complete; independent acceptance is pending.
No overall production-grade module or release completion is claimed. Story 10.4
has not begun.
