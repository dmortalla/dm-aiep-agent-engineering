# Story 10.5 — local container integration passed; independent acceptance pending

## Baseline and scope

Starting HEAD: `6dc5f7468de0b7c4510ecdc4e1078c9ed55b83f6`.
Resumed HEAD: `44571350bdd719afc9a95a68275e0dd4b86fefc7`.
Accepted Story 10.4 `4dd2cb6e45ee5bad27d930ef145f8b39786b6ddb` is an ancestor
(`git merge-base --is-ancestor`, exit 0). No intervening commits changed Module 10.
Required architecture, requirements, traceability, stories, Definition of Done,
nine ADRs, previous story records, README, packaging, source and tests were reviewed.
Frozen architecture, production source, dependencies and lock remain unchanged.

Added: `Dockerfile`, `.dockerignore`, `scripts/container_acceptance.py`,
`tests/test_container.py`, and this document. Updated README, STORIES and TRACEABILITY.
All edits are confined to Module 10. Foreign concurrent work was preserved,
including root configuration/scripts and work in Modules 6.5, 7 and 8. No push,
global pruning, provider operation or cloud operation was performed. The original
eight paths were resumed intact; no implementation repair was needed. Only the
four documentation files were updated after runtime acceptance. A focused local
commit is authorized after all gates pass; staging is restricted to Module 10.

## Container design and reproducibility

ADR-006 is implemented with a dependency builder and slim runtime. The builder
copies uv 0.12.5 from its versioned image, uses Python 3.12.14 slim Bookworm, and
runs `uv sync --locked --no-dev --no-install-project --no-cache`. The existing
lock determines application dependency versions and distribution hashes; no
floating pip install, build backend, test package or extra runtime dependency is
introduced. Application source is copied narrowly and loaded via `/app/src`
PYTHONPATH. Avoiding project installation also avoids Hatchling's unpinned isolated
build dependencies. This is a source deployment, not installed wheel evidence.

Both Python stages use the same explicit patch/distribution tag. Tags are not
immutable digests: byte-for-byte image reproducibility and comprehensive base
security are not claimed. Reviewed digest pinning and security maintenance remain
deployment considerations. The uv builder, lock/manifests and build cache are
absent from the final runtime. Standard Python slim base utilities remain;
no compiler/toolchain/curl/wget is added.

The module-scoped build context is allowlisted: manifests, Docker instructions,
and only immediate Python files in `src/module10_ai`. All other paths, including
credentials, `.env`, `.git`, virtual environments, bytecode, tests, docs, editor
files, OS files, caches and temporary evidence are excluded. Runtime COPY targets
are only the dependency environment and application source. No ARG or secret ENV
exists. Future credentials must be runtime-injected; live mode stays deferred.

Dedicated numeric UID/GID `10001:10001` has no login shell/home. Application and
virtual environment are root-owned and stripped of write permission. Effective
identity and application write restrictions were verified at runtime. No writable paths
are required. The documented acceptance command additionally enforces read-only
root filesystem, dropped capabilities, no-new-privileges, 256 MiB memory, one CPU,
64 PIDs and an ephemeral loopback host port. These are local acceptance limits,
not measured production sizing.

Exec-form PID 1 command is Python/Uvicorn factory startup, binds `0.0.0.0:8000`,
uses one process and no reload. Access logging is disabled to avoid logging raw
request URLs; ordinary Uvicorn lifecycle logging remains. SIGTERM and a ten-second
graceful request deadline preserve the existing cooperative FastAPI shutdown and
Story 10.4 worker cleanup. Stop allows fifteen seconds before Docker escalation;
acceptance requires exit 0 and application shutdown completion, not a forced kill.

Docker readiness HEALTHCHECK uses Python urllib with a two-second timeout,
ten-second interval/start period, three-second probe ceiling and three retries.
Liveness separately checks `/health/live`; readiness checks accepted deterministic
service and worker lifespan. Neither proves capacity/cloud health. Typed bounds
stay unchanged; application settings have no existing environment parser, so none
is invented. Existing Uvicorn environment configuration remains available where
explicit CLI options do not override it. No required secret or external service.

References: [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/),
[uv locking/sync](https://docs.astral.sh/uv/concepts/projects/sync/),
[official Python image](https://hub.docker.com/_/python).

## Verification and resolved environment blocker

Module-local CPython 3.12.14 / pytest 8.4.2. Four added fast artifact tests cover
ASGI command, port, non-root declaration, signals, locked production dependencies,
narrow copies, context allowlist and Python readiness probe. These are static
contracts; actual Docker evidence is recorded separately below. Ordinary pytest does not
rebuild Docker. All 156 accepted regression cases are retained.

Formal fail-fast run:

1. `python -m ruff check .`: `All checks passed!`, exit 0.
2. `python -m pytest`: **160 passed, 1 warning in 3.20s**, exit 0.
3. `python -m compileall -q src tests scripts`: no output, exit 0.
4. `python scripts/container_acceptance.py`: all assertions passed, exit 0.
   This repeated a successful initial Docker acceptance run before the final sequence.

Initial Ruff found one long exception line; it was wrapped, the failed gate
passed, and the complete sequence was rerun. Sandboxed pytest stalled at Windows
asyncio local setup and was interrupted; pytest and the full sequence were run
outside the sandbox as for prior accepted stories. The accepted third-party
Starlette HTTPX deprecation warning remains unchanged and unsuppressed.

The initial attempt, before Docker Desktop was started, reported:
`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.`
On resume, sandbox access returned permission denied; verification outside the
sandbox succeeded: Docker Desktop 4.95.0 (242831), Engine/CLI 29.8.2,
context `desktop-linux`, server `linux/amd64`. The environmental blocker is resolved.

| Local Docker fact | Actual result |
|---|---|
| Image build / image ID | PASS, final tag `module10-story105-b42f87b83f33:local`; `sha256:6fec4c688d59f9f3aaef3f2ea7c5d62f2a7faff2632510b7e82f19713e2fd6e4` |
| Container startup / metadata | PASS; unique name `module10-story105-b42f87b83f33`, image user `10001:10001`, sole exposed port `8000/tcp`; ephemeral loopback publishing |
| Effective runtime UID / file permissions / image contents | PASS; `docker exec` Python `os.geteuid()` returned 10001; application source not writable; `.env*`, PEM, tests and `.git` absent under `/app`; uv binary, pytest and Ruff absent |
| Liveness / readiness / Docker health | PASS separately: live 200/alive/deterministic, ready 200/ready, Docker health healthy |
| Deterministic inference | PASS, HTTP 200, word count 4, keywords beta/alpha/gamma, evidence deterministic |
| Invalid / malformed requests | PASS, invalid schema 422 with fixed code/message/request_id envelope; malformed JSON safely rejected with 400 or 422 |
| SIGTERM / graceful stop / cleanup | PASS, normal `docker stop --time 15`, exit 0, not running, no OOM; logs contain application shutdown completion; own container removed and exact-name absence verified |

Evidence classification: **LOCAL CONTAINER INTEGRATION**; inference remains
deterministic lexical analysis. First successful tag was
`module10-story105-f4a42341f6ce:local`, image
`sha256:8eede8acf4f89ab3b7a88cc4467b4c6885f64ba7b16b877940afdc8e92889016`.
Both own containers were removed; tagged images remain for review. Image Config
inspection confirms the explicit Uvicorn command, no reload, readiness healthcheck,
SIGTERM and environment consisting only of base Python metadata and documented
runtime settings. The base `GPG_KEY` value is a public signing-key fingerprint,
not an application credential. No external AI credential was passed or required.
These are targeted metadata/content checks, not comprehensive vulnerability proof.

The explicit integration script uses unique names and bounded calls, actually
tests those facts when Docker works, reports partial JSON on failure after resource
creation, and removes only its own container in `finally`. It retains its own
tagged image for review and never prunes Docker. No temporary capture is committed;
future captures belong under parent `TECHADEMY/EVIDENCE`.

## Ordered completion assessment

Targeted final checks: all eight owned files decode as strict UTF-8 without BOM;
Git whitespace check passes; staging was empty before the scoped commit. Accepted production source,
pyproject, lock, architecture, requirements, ADRs and Definition of Done have no
diff. Targeted new-artifact scans find no cross-module references, future-story
dependencies or obvious credential markers. These checks do not establish image
comprehensive secret/vulnerability freedom. Foreign concurrent work
remains outside the changed/staged scope.

Requirements: Story 10.5 local Docker behavior is implemented and verified;
C-002/C-020/C-023 await independent review. Broader C-003/C-013/C-014 remain partial.
Product Experience: README provides build/run/probe/stop instructions and an
explicit repeatable acceptance command; final reviewer UI remains later work.
Real Functionality: actual local container startup and deterministic HTTP inference pass.
Reliability: readiness/worker lifecycle and real graceful shutdown pass.
Security: static contracts and targeted runtime identity, permissions, metadata
and content checks pass; comprehensive vulnerability assurance is not claimed.
Cost: no cloud/provider cost, no new infrastructure services; local resources bounded.
Evidence: 160 fast tests and local Docker acceptance pass; no cloud, distributed
scaling, production traffic, performance or SLA evidence is claimed.
Deployment: local container verified. Azure deployment, Azure Container Apps orchestration,
Azure Monitor, load balancing, distributed queue/cache, CI/CD, production SLA
evidence, and overall C-026/C-027 completion remain deferred. Story 10.6 is untouched.

Story 10.5 is **implemented with passing local acceptance**, pending independent
acceptance. Full-module Definition
of Done remains unchanged; no production-grade completion is claimed.
