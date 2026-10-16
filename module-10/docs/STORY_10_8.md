# Story 10.8 — CI/CD deployment pipeline

## Baseline and ownership

Starting HEAD: `5d9e475775cd53052b9a90079743749a4fa0ed53`.
Accepted Story 10.7 `bf52960e98eff9db2e91be73260ae4d3cee0d446` is an
ancestor (merge-base exit 0). No intervening Module 10 changes or initial active
Module 10 edits were present. Concurrent foreign commits advanced HEAD to
`a012e376bf4eb3f18f2db4735d0dd7d0c76d3143` during implementation; Module 10 history
remained unchanged. Required governance, architecture, requirements, traceability,
DoD, all accepted ADRs, Stories 10.2–10.7, manifests and relevant scripts/tests
were read. Frozen architecture and dependency lock remain unchanged.

The human explicitly allowed module-local specifications plus deterministic
materialization. That approach is implemented without crossing root ownership.
Actual GitHub discovery requires `.github/workflows/module-10.yml`; no such root
file was installed or modified. There is no unresolved architecture exception for
this local scope. Future root integration requires explicit authorization.

## Shipped changes

Added `ci/workflow.json`, `ci/promotion.json`, `scripts/pipeline.py`,
`tests/test_pipeline.py`, `docs/CI_CD.md` and this story record.
Changed `scripts/container_acceptance.py` to accept an already-built image and
return successful facts after cleanup, preserving its standalone CLI. Added an
actual runtime Streamlit exclusion assertion. Updated README, STORIES and
TRACEABILITY for partial C-010/C-021 and contributing pipeline discipline evidence.
No application/domain/UI logic, Dockerfile, dependencies, architecture or ADR changed.

See [CI/CD](CI_CD.md) for complete architecture, upstream pin/version table,
installation command, trust boundaries, permissions and operational instructions.
The order is setup -> Ruff -> pytest -> compileall -> security contract -> one
Docker build -> existing container acceptance -> manifest -> evidence upload.
All required stages stop on failure. PR/push paths are scoped; manual dispatch
also validates only. Token permission is contents:read. Actions are pinned to
verified upstream commits; checkout credentials are not persisted. No secrets,
cloud authentication, registry push or deployment job exists.

`ci/promotion.json` preserves candidate commit/content identity, previous accepted
registry digest/revision and future verification/rollback authority. It does not
execute promotion. A protected GitHub Environment, operator approval and actual
OIDC/Azure trust must be separately configured and verified in Story 10.9. Every
manifest explicitly has deployment_authorized=false. A malformed identity fails
preparation. Passing tests/builds, model output and CI logs grant no authority.

## Verification

Module environment: Python 3.12.14, pytest 8.4.2. Fifteen new pipeline tests retain
all 200 accepted regressions, for **215 tests**. Coverage includes parsed workflow
trust/permissions/pins/dependency setup/path scoping, native gate order, each native
failure preventing Docker, build/acceptance/identity failures preventing evidence,
valid immutable candidate with no authority, one build/native acceptance reuse,
bounded successful manifest and external materialization/refusal to overwrite,
and future promotion/rollback identity contract. Ordinary tests invoke no Docker.

Final executable pipeline `scripts/pipeline.py --evidence <external-new-path>`:

1. `python -m ruff check .`: **All checks passed!**, exit 0.
2. `python -m pytest`: **215 passed, 1 warning in 4.09s**, exit 0.
3. `python -m compileall -q src tests scripts ui`: no output, exit 0.
4. Parsed workflow specification equals the reviewed bounded contract: pass.
5. Docker build and project-native runtime acceptance: pass, pipeline exit 0.

The accepted Starlette HTTPX deprecation warning remains unsuppressed. An earlier
214-test run passed but pytest's shared Windows temporary-root cleanup reported an
access error at exit. Final verification used a fresh dedicated basetemp under
TECHADEMY/EVIDENCE; cleanup diagnostics did not recur. No test/control was weakened.
No Ruff or semantic failure repair was required.

Local evidence manifest is outside the repository:
`TECHADEMY/EVIDENCE/module10-story108-validation-20261015-a.json`.
It records source `a012e376bf4eb3f18f2db4735d0dd7d0c76d3143`, source_clean=false,
Python, lock SHA-256, all required outcomes and deferred deployment authority.
Image tag:
`module10-ai:sha-a012e376bf4eb3f18f2db4735d0dd7d0c76d3143-worktree-cfa323cdf87d`.
Image ID:
`sha256:2b88d5b7fc3ac5920c1ad737419a9524c11592a0aa4895e12785f810d8eda08f`.
It is an image content ID, not a registry manifest digest. This is implementation
worktree acceptance evidence, not a clean committed release artifact.

Container results: build/startup, readiness, Docker healthcheck, liveness, effective
UID 10001, targeted content/permissions including no Streamlit, deterministic
inference, invalid schema 422, malformed JSON rejection, correlated/minimized
telemetry, graceful stop exit 0 and exact own-container cleanup all passed.
Only the uniquely tagged local image remains; no global pruning occurred.

Targeted review includes UTF-8 without BOM for every owned file, Git whitespace,
module-only changes/staging, no Azure/provider credential literals or credential
files in additions, no cross-module imports and accurate evidence classification.
These are targeted checks, not a comprehensive vulnerability/secret audit.
Foreign work is not modified, staged, reset, restored, cleaned or stashed.
Only `git add -- module-10` is used for the focused local commit; no push.

## Ordered completion assessment

Requirements: Story 10.8 local contract implemented; CI/CD-related course
requirements gain partial evidence, not full hosted/cloud acceptance.
Product Experience: documented single local command and self-explanatory bounded
JSON; accepted reviewer UI remains unchanged.
Real Functionality: actual native quality gates, Docker build and native runtime
acceptance; module-local workflow materializes deterministically.
Reliability: fail-fast required gates, bounded subprocesses, no retries and accepted
container cleanup; failure paths tested.
Security: read-only platform permissions, immutable action pins, credential-free
validation, data-only promotion and no executable deployment authority.
Cost: scoped triggers, concurrency cancellation, single build, no matrix, seven-day
metadata retention, no paid calls or cloud resources.
Evidence: LOCAL CI/CD CONTRACT plus LOCAL CONTAINER INTEGRATION/deterministic.
GITHUB-HOSTED CI is unverified; no signed provenance/SBOM/SLSA claim.
Deployment: future protected promotion, OIDC and rollback contracts prepared;
actual deployment and production-grade completion are deferred.

Real Azure authentication, ACR if used, Azure Container Apps, Azure Monitor,
production load balancing, traffic/SLA, distributed queue/cache, live providers
and final C-026/C-027 remain deferred to Story 10.9+. Story 10.9 was not started.
Independent Story 10.8 acceptance and full-module DoD remain pending.
