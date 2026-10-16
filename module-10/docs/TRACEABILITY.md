# Module 10 Traceability

| Requirement | Planned Story | Planned Evidence |
|---|---|---|
| C-001, C-003, C-019, C-022 | 10.3 | FastAPI contract and acceptance tests |
| C-002, C-020, C-023 | 10.5 | Container build and runtime acceptance |
| C-004, C-008, C-024 | 10.9 | Azure Container Apps live-cloud evidence |
| C-005, C-006, C-007, C-009 | 10.4 | Async, queue, cache, backpressure and performance tests |
| C-010, C-021 | 10.8 | CI/CD pipeline and gated container acceptance |
| C-011, C-025 | 10.6, 10.9 | Structured telemetry and Azure Monitor live-cloud evidence |
| C-012 | 10.9, 10.10 | Resource boundaries, cost controls and teardown evidence |
| C-013 | 10.3, 10.4, 10.10 | Reliability and failure-path evidence |
| C-014 | 10.2-10.10 | Security tests and operational evidence |
| C-015, C-016, C-017, C-018 | 10.10 | Operational runbooks and exercised evidence |
| C-026 | 10.11 | Independent production-deployment acceptance |
| C-027 | 10.4, 10.9, 10.11 | Scalable-backend acceptance evidence |
| E-001-E-012 | 10.1-10.11 | Architecture, tests, UI, operational and release evidence |

Traceability is updated as implementation evidence becomes concrete. Planned evidence must never be represented as completed evidence.

## Concrete Story 10.2 evidence

The table above retains the full-module planned evidence. The following evidence
is limited to the framework-independent deterministic core, not full requirement
completion across Stories 10.3–10.11.

| Requirement | Implementation | Verified evidence |
|---|---|---|
| E-001 | Standalone `pyproject.toml`, `src/module10_ai`, `uv.lock` | Installed-package subprocess import, no runtime dependencies; foreign-file preservation check |
| E-003 | Framework-independent `service.py` and `runtime.py` | `test_package_import_and_framework_isolation`; UI remains planned |
| E-005 | `RuntimeConfig` defaults and `DeterministicRuntime` | Valid inference, reproducibility, no-key and no-network tests |
| E-007 | `EvidenceClass` and result validation | Deterministic classification and mismatch tests; no local-runtime/live-cloud execution evidence |
| E-008, C-014 (partial) | Strict immutable contracts, bounded data-only output, safe errors | Request/result validation, prompt-as-data, repr/error protection, credential-presence/no-network tests |
| E-009 | Module-local Ruff, pytest, compileall configuration | Native gate results recorded in `STORY_10_2.md` |
| E-011 | Typed public interfaces and Google-style docstrings | Ruff includes Google-style docstring rules; source inspection |
| E-012 | Narrow service failure translation, preserved cancellation and defects | Failure translation, cause preservation, malformed output, cancellation, and programming-error tests |

E-002, E-004, E-006, E-010 and all remaining course deliverables retain planned
status. Unsupported live configuration is rejected; secure live execution itself
has not been implemented or verified.


## Concrete Story 10.3 evidence

| Requirement | Implementation | Verified evidence |
|---|---|---|
| C-001, C-022 | `api.py` factory, `http_schemas.py`, accepted service invocation | Typed deterministic HTTP inference and OpenAPI schema tests |
| C-003, C-019 (application portion only) | Runnable Uvicorn factory, liveness/readiness routes | In-process HTTP lifecycle checks; actual deployment remains planned |
| C-013 (API boundary) | Body-read and inference deadlines, lifecycle readiness | Timeout cleanup, external cancellation, disconnect and failure tests |
| C-014, E-008 (API boundary) | `http_boundary.py`, strict HTTP schemas, sanitized failures | Actual streamed body/header bounds, input rejection, no sensitive public/log details |
| E-001, E-003 | Module-local dependencies and separate transport files | Core import isolation regression; unchanged accepted core source |
| E-005, E-007 | Accepted deterministic service and explicit output evidence | HTTP deterministic output and no-key core regression tests |
| E-009, E-011, E-012 | Typed HTTP configuration/interfaces, bounded diagnostic logging | Ruff, pytest, compileall and expected/unexpected failure tests |
| E-004 (API reviewer interface only) | README runnable example and OpenAPI | HTTP contract checks; Streamlit reviewer interface remains Story 10.7 |

See `STORY_10_3.md` for exact gate results and limitations. No container,
local-model, live-provider, external deployment, scaling, queue/cache, or cloud
telemetry evidence has been added. Full requirement acceptance remains pending.


## Concrete Story 10.4 evidence — pending independent acceptance

| Requirement | Implementation | Tested evidence |
|---|---|---|
| C-005, C-006 | `execution.py` bounded `JobQueue` / `LocalExecution` | Fixed workers, pending capacity, saturation, states, success/failure, cancellation, timeout, startup/shutdown, invalid handles; `test_execution.py` |
| C-007 | `cache.py` explicit `InferenceCache`, TTL/LRU and hashed keys | Exact keys, hit/miss, TTL expiration, eviction, invalidation, concurrent access, counters and preserved deterministic evidence |
| C-009 | Reproducible local workload test | Two concurrent workers, eight cold calls, eight warm cache hits with zero additional runtime calls; actual batch timings in `STORY_10_4.md` |
| C-013 (local portion), E-012 | Queue/API lifecycle and controlled failures | Cleanup, surviving workers, cache defects, saturation 503, execution 504; accepted 10.2/10.3 regressions retained |
| C-014, E-008 | Pre-cache service admission, untrusted cached result revalidation | Runtime ceiling cannot be bypassed by prepopulated cache; bad evidence rejected; IDs/output grant no privileged authority |
| E-001, E-003, E-005, E-007, E-009, E-011 | Standalone standard-library application composition | No new dependency, no provider calls, separate HTTP/domain contracts, native gates and deterministic evidence |
| C-027 (partial only) | Bounded process-local backend behavior | Local invariants only; scalable-backend deliverable remains incomplete pending distributed/cloud and independent acceptance evidence |

No durable/distributed queue, distributed cache, C-004 orchestration, C-008 load
balancing, cloud performance, or production deployment is established here.

## Story 10.5 — local container integration; independently accepted

| Requirement | Implementation | Evidence status |
|---|---|---|
| C-002, C-020, C-023 | Multi-stage Dockerfile, allowlisted context, repeatable container acceptance command | Four fast artifact contracts and actual local image build/container acceptance pass |
| C-003, C-013, C-014 (partial only) | Direct Uvicorn startup, readiness probe, non-root execution, read-only source, no embedded application credentials | Effective UID 10001, separate liveness/readiness and Docker health, deterministic HTTP inference, safe invalid/malformed requests, targeted runtime content/permission checks, SIGTERM exit 0 and cleanup |
| E-001, E-005, E-007, E-009 | Module-only context, deterministic defaults, classified facts, separate integration gate | 160 tests and native gates pass; LOCAL CONTAINER INTEGRATION evidence with deterministic inference; no live-provider/cloud success claimed |

Human-supplied independent acceptance applies to commit
`1a010ca82bb88b90f2358af0bf7417f62d192d39`. See `STORY_10_5.md` for historical
implementation evidence. No broader deliverable is completed solely from local Docker evidence.
Azure deployment, Azure Container Apps orchestration, Azure Monitor, load balancing,
distributed queue/cache, CI/CD, production SLA evidence and overall C-026/C-027
completion remain deferred. Full-module Definition of Done stays unchanged.


## Concrete Story 10.6 evidence — pending independent acceptance

| Requirement | Implementation | Evidence and limit |
|---|---|---|
| C-011 (application side) | `telemetry.py` JSON sink, fixed event/status schema, internal snapshots | `test_telemetry.py`, local demo and container telemetry checks; no external pipeline delivery claim |
| C-013 (local operational foundation) | HTTP/worker monotonic durations, outcomes, readiness and occupancy | Backpressure, timeout, cancellation, failure and failure-isolation tests; no production reliability/SLA claim |
| C-014, E-008 | Field allowlist, correlation digests, fixed failure categories, no bodies/stacks/exception text | Adversarial headers/IDs/prompts/exception tests; telemetry grants no authority; secret detection is not claimed |
| E-001, E-003, E-005, E-007 | Standard-library boundary beneath HTTP/UI/cloud; module-local deterministic demo | No new runtime dependencies or cross-module coupling; local deterministic evidence |
| E-009, E-011, E-012 | Typed interfaces, fail-fast gates and tested telemetry failure boundaries | Exact gate results and ordered completion assessment in `STORY_10_6.md` |
| C-025 | Future adapter to event sink and aggregate snapshot | **DEFERRED**: actual Azure Monitor integration requires later real Azure evidence |

C-026/C-027 overall completion remains deferred. Azure deployment, Container Apps,
load balancing, distributed queue/cache, CI/CD and production traffic/SLA evidence
are deferred. The unified Streamlit reviewer UI belongs to Story 10.7.


## Concrete Story 10.7 evidence

Story 10.6 independent acceptance was supplied by the human for
`dabccead1b19e693f60f7fd7feef72dce9a0acb7` (local deterministic/container only).

| Requirement | Implementation | Evidence and limit |
|---|---|---|
| E-002 | `ui/app.py`, optional reviewer dependency group | Native AppTest and launched browser review; local Streamlit only |
| E-003 | Framework-independent `reviewer.exercise` calls accepted service/queue/cache/telemetry | Real cold/warm jobs, authoritative contract validation; no algorithm duplication |
| E-004 | Results, cache counters, queue outcomes, correlated events, readiness and evidence tabs | Reviewer-visible deterministic working results; no cloud completion claim |
| E-005, E-007 | Default no-key operation, explicit local and recorded container labels | No provider calls; planned Azure targets visibly deferred |
| E-008, E-012, C-014 (presentation) | Bounded native inputs, domain validation, safe output primitives and fixed errors | Invalid-input, defect minimization, capacity/deadline and rerun tests |
| E-001, E-009, E-011 | Module-local packaging, typed adapter, native gates | Story 10.7 verification record; Docker dependency separation regression |

Existing queue/cache/telemetry course evidence gains a presentation surface only.
CI/CD, Azure Container Apps deployment, Azure Monitor delivery, production load
balancing, distributed queue/cache, production traffic/SLA, live providers/E-006,
and final C-026/C-027 acceptance remain deferred. Story 10.8 status is recorded below.


## Story 10.8 implementation

Module-local fail-fast CI/CD specification, deterministic materializer, native
quality/container runner, bounded metadata and data-only promotion/rollback
contract are implemented. See [CI/CD](CI_CD.md) and [Story 10.8](STORY_10_8.md).
C-010/C-021 have local CI/CD contract evidence only; C-003/C-013/C-014/C-015/C-017
receive partial pipeline discipline evidence. Root workflow installation and actual
GitHub execution are deferred. Azure deployment and full C-026/C-027 remain deferred.
