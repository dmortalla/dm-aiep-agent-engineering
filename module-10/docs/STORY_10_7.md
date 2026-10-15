# Story 10.7 — Streamlit production-system console

## Baseline and scope

Starting HEAD: `50e811f6f0c852710eb5798c8817c00549acd2c6`.
Accepted Story 10.6 `dabccead1b19e693f60f7fd7feef72dce9a0acb7` is an ancestor
(merge-base exit 0). No intervening Module 10 commits or active Module 10 changes
were present. Required governance, module documents, all nine ADRs, prior story
records, packaging and relevant implementation/tests were reviewed. Frozen
architecture and accepted business implementation remain unchanged.

Added `src/module10_ai/reviewer.py`, `ui/app.py`, `tests/test_reviewer.py` and this
record. Updated README, STORIES, TRACEABILITY, pyproject and uv.lock. No other
module was modified, staged or reused. Existing foreign work remains protected.
Story 10.8 is not started. This is functional Story 10.7 implementation evidence;
independent acceptance and overall production-grade completion are not claimed.

## Launch and architecture

From `module-10/`:

```powershell
uv sync --locked --group reviewer --python 3.12
.venv/Scripts/python.exe -m streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8517 --server.headless true --browser.gatherUsageStats false --client.showErrorDetails none
```

Streamlit is a native presentation script. The framework-independent async
`reviewer.exercise` adapter invokes accepted InferenceRequest, InferenceService,
LocalExecution and Telemetry interfaces directly. It does not duplicate inference,
queue, cache or validation algorithms. FastAPI remains the production HTTP boundary;
the console exercises local application interfaces, not a running HTTP container.

One form submission runs exactly two sequential jobs within a fresh execution
instance: four workers, 32 pending slots, five-second worker deadline, 128 cache
entries and 60-second TTL. An additional 12-second exercise deadline bounds the
pair cooperatively. There are no retries. Admission is queued and outcome is
succeeded on the normal path. The exercise intentionally does not saturate the
queue; its configuration and backpressure semantics are explained visibly.

The default text returns four words and beta/alpha/gamma. Actual backend statistics
show one initial miss and then one hit with identical deterministic output. No
timing speedup claim is made. Events include actual cache, inference and job
outcomes, monotonic durations and safe correlation metadata. A deque retains at
most 32 events per exercise; aggregate metrics come from Story 10.6 Telemetry.
The normal path produces seven correlated events with zero telemetry failures.

## State, health and security

Session state retains widget values and one detached report only; it is not queue,
cache, telemetry or deployment authority. Every exercise closes its workers in
finally before returning. Reruns redisplay the report without running jobs. Cache
truth lives exclusively in the accepted cache during that exercise. Input and
user-derived keywords remain in session memory until replacement/session end;
the console tells reviewers not to enter sensitive data.

Readiness is actually observed from accepting workers during the exercise, with
closed state and queue cleanup captured afterward. These are recorded local
application observations. The console explains process liveness versus service
readiness without inventing container or cloud health. Docker is optional for UI
use. Container facts are explicitly recorded human-supplied Story 10.6 acceptance,
identified by commit, not a live running-container badge.

Text length is bounded to 4096 in the widget and revalidated by accepted contracts;
keyword limits are 1–10. Blank/invalid input, job deadline, saturation/unavailability
and application defects receive fixed safe messages. Unrelated provider timeouts
remain application failures. Arbitrary exception details, paths, causes and stacks
are never placed in reports; accepted telemetry retains fixed diagnostic categories.
Cancellation propagates with resource cleanup. The local launch disables framework
error details as defense in depth. Native text/data/JSON primitives render untrusted
output; no unsafe HTML, environment display, credential entry, shell execution,
deployment controls, filesystem-path display or privileged authority exists.

## Dependency and Docker boundary

Streamlit 1.66.0 is locked in the optional reviewer group, including its required
transitive packages. No separately selected chart, provider, Azure or distributed
system dependency was added. Production dependencies and their existing versions
are unchanged. The accepted Dockerfile still installs with `--no-dev` and no
reviewer group; no UI script is copied into that artifact. The adapter itself
imports no Streamlit. A disposable, network-disabled rebuilt-image check verified
Streamlit absent, reviewer adapter importable and effective UID 10001.

## Verification

Module environment: Python 3.12.14, pytest 8.4.2, Streamlit 1.66.0.
Twelve reviewer cases plus 188 retained accepted regressions: **200 total**.
Tests cover real inference/cache/telemetry, inclusive input ceiling, invalid input,
safe defect/capacity/deadline feedback, unrelated timeout classification, cleanup,
UI import/form/results, evidence warnings, and reruns preserving presentation only.
The high-value AppTest exercises blank-input rejection as well as successful output.

Final fail-fast sequence:

1. `python -m ruff check .`: `All checks passed!`, exit 0.
2. `python -m pytest`: **200 passed, 1 warning in 4.46s**, exit 0.
3. `python -m compileall -q src tests scripts ui`: no output, exit 0.
4. Launched Streamlit on loopback 8517; health endpoint returned HTTP 200 `ok`.
   Browser form execution rendered four words, the actual miss/hit counters and
   keywords. Operations rendered correlated events, metrics and readiness/cleanup.
   Evidence tab rendered recorded local-container facts and explicit deferred labels.
   Native screenshots were visually reviewed at 1280×720: clear tab organization,
   readable metrics, no page horizontal overflow, compact event columns, detailed
   JSON behind expanders, native accessible controls and no immediate exception.
   Streamlit was stopped with Ctrl+C (command wrapper exit 1); listener absence was
   verified. No reviewer server or worker resources were intentionally left running.
5. `python scripts/container_acceptance.py`: exit 0. Image
   `module10-story105-cb72f4fb4702:local`, ID
   `sha256:75d0a6c4955f7d50e81ffc64d38af7682719d8c26f27c41f00c5816440aa6171`.
   Build/startup, liveness/readiness, Docker health, UID 10001, targeted contents and
   permissions, deterministic inference, invalid/malformed rejection, correlated
   minimized telemetry, graceful container stop exit 0 and own-container cleanup pass.

The existing unsuppressed Starlette HTTPX deprecation warning remains. Initial
sandboxed tests stalled in Windows local asyncio socket plumbing and were stopped;
authorized execution outside the sandbox passed. A sandboxed health probe similarly
failed socket permission and passed outside the sandbox. Initial Ruff identified
one long UI line, repaired without weakening rules. Timeout handling and event
layout received bounded refinements, followed by the full formal gate sequence.

Targeted review: owned files decode as UTF-8 without BOM; Git whitespace checks
pass; imports stay module-local; frozen architecture, ADRs, Dockerfile and allowlist
are unchanged; no credential artifacts or production/provider configuration were
introduced. Failure minimization is tested with sensitive sentinel diagnostics.
These checks are not a comprehensive vulnerability or secret-detection audit.
Only Module 10 paths are staged for the focused local commit; no push is performed.
No temporary captures are committed.

## Ordered completion assessment

Requirements: E-002/E-003/E-004 now have concrete local presentation evidence.
Product Experience: runnable self-explanatory console and actual rendered review.
Real Functionality: real accepted application interfaces and backend-generated evidence.
Reliability: bounded jobs, cooperative deadlines, safe failures and unconditional cleanup.
Security: backend validation, safe primitives, minimized errors and no privileged controls.
Cost: local deterministic execution, no keys, cloud resources or paid model calls.
Evidence: deterministic tests, local UI smoke and local-container regression only.
Deployment: hardened backend dependency separation preserved; cloud remains deferred.

CI/CD, Azure Container Apps, Azure Monitor integration, production load balancing,
distributed queue/cache, production traffic/SLA evidence, live provider integration,
E-006 final dual-mode completion and final C-026/C-027 acceptance remain deferred.
The full-module Definition of Done is unchanged. Streamlit presentation does not
complete cloud, deployment, SLA or production-grade acceptance requirements.
