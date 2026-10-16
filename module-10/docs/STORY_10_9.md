# Story 10.9 — repository-side Azure Container Apps deployment capability

## Baseline and scope

Starting HEAD: `6dad527033e09f5703c697454c71046b44d82f1d`.
Accepted Story 10.8 `529cc2293606eb70738581b909bca5737adcc110` is an ancestor
(merge-base exit 0). No intervening Module 10 commits or initial Module 10 edits.
Foreign concurrent changes are protected; no foreign files are changed/staged.
The approved architecture and accepted core/API/queue/cache/telemetry/UI/Docker/
CI contracts were inspected. This story adds no root workflow, new dependency,
live-provider capability, cloud executor or cross-module coupling.

## Repository implementation

Added `src/module10_ai/azure_contract.py`, `azure_verification.py`,
`scripts/azure_deployment.py`, `tests/test_azure.py`, `docs/AZURE_DEPLOYMENT.md`,
`docs/adr/ADR-010-human-controlled-azure-contract.md` and this record. Updated
README, STORIES and TRACEABILITY for repository capability and deferred cloud evidence.

Native resource-group ARM JSON is rendered deterministically in two incremental
phases. It avoids IaC state/compiler dependencies, exposes reviewed resource
definitions and resolves workspace ingestion authorization only server-side.
Secure private-image bootstrapping proposes one supporting user-assigned pull
identity with registry-only AcrPull and lifecycle None. This adds an identity to
the listed footprint and was explicitly approved by the human on 2026-10-16 for
repository implementation/local commit only. Approved services/compute/scaling
remain unchanged. Exactly one identity and one registry-scoped AcrPull assignment
are permitted; no ACR admin credentials, broader runtime roles or runtime identity
access. `azure_contract.footprint()` records the amended counts. No cloud mutation
was authorized by this amendment.

Account-independent random-suffix names, exact manifest digest, Basic ACR,
0.25 CPU/0.5 GiB, min 0/max 2, reviewer /32 HTTPS ingress, accepted API probes,
15-second termination grace, single revision, two inactive revisions, bounded
Log Analytics retention/ingestion and explicit group teardown are encoded/tested.
The accepted unauthenticated API is restricted by ingress, not broadened publicly.
No application credentials or live inference configuration are introduced.

Publication validation distinguishes Docker config/content ID from the registry
manifest digest, rejects dirty/failed candidates and indexes, checks exact manifest
config binding and returns data without authority. The human additionally observes
the actual clean pipeline, publishes the same accepted image without rebuilding,
pulls by digest and verifies the content ID. Untrusted JSON cannot prove provenance.
Story 10.8 hosted Environment/OIDC integration remains separately authorized;
its module-local workflow/promotion specification remains intact.

Read-only verification requires fresh CLI state, not supplied fixture files. It
checks ownership/inventory/region, registry tier/auth/digest, narrow identity RBAC,
workspace limits/log connection, app security/configuration/probes/scaling and
healthy active ready revision/traffic. Only then does it send five bounded HTTPS
acceptance calls and query fresh correlated telemetry aggregates (six attempts
maximum). A final fresh configuration/revision check precedes minimized metadata.
CLI calls are allowlisted, bounded to 90 seconds, log/telemetry/auto-install disabled;
Windows calls use Azure's MSI Python directly, avoiding batch shell parsing.
HTTP uses verified TLS, no proxies/redirects, a 30-second complete-call deadline
and a 64 KiB response ceiling. Failure does not produce success evidence.

## Verification record

Python 3.12.14; pytest 8.4.2. **96 new tests**, retaining all 215 accepted tests,
for **311 tests**. Ordinary tests use offline data and injected transports only;
they incur no Azure or model charges. Coverage includes names/CIDR/digests,
template/source/security/cost invariants, untrusted/missing/drifting observations,
extra resources/roles, unhealthy revisions, command allowlist, CLI errors/timeouts,
Windows shell avoidance, correlated/minimized KQL, finite retries, transport
failures/redirects/response bounds, exact five-request success, offline rendering
and publication content/gate binding.

First pytest run exposed an absent explicit /32 validation and a Windows path
problem from a large parameter's generated test ID. Both were repaired; 90 new
tests then passed. Two further boundary tests were added. Ruff length/import
issues were fixed without unsafe fixes. No test, acceptance or security criterion
was weakened. One full pipeline attempt stopped at Ruff before later stages;
after repair the complete native sequence was rerun.

Pre-amendment full local pipeline after starting the installed Docker engine:

1. `python -m ruff check .`: All checks passed, exit 0.
2. `python -m pytest`: **307 passed, 1 warning in 4.10s**, exit 0.
3. `python -m compileall -q src tests scripts ui`: passed, exit 0.
4. Accepted workflow security contract: passed.
5. Docker build and native runtime acceptance: passed, pipeline exit 0.

The existing unsuppressed Starlette HTTPX deprecation warning remains. Temporary
pytest data is under parent TECHADEMY/EVIDENCE. An earlier pipeline correctly
stopped at Docker build while the engine was inactive and wrote no manifest.
Docker Desktop was started for the authorized local integration check, then the
complete native sequence was rerun. Container startup/readiness/liveness/Docker
health, UID 10001, targeted content/permissions, deterministic inference,
422/malformed JSON, correlated minimized telemetry, graceful stop exit 0 and
exact owned-container cleanup passed. No global prune occurred.

External local manifest: `TECHADEMY/EVIDENCE/module10-story109-local-e.json`.
Image tag: `module10-ai:sha-6dad527033e09f5703c697454c71046b44d82f1d-worktree-b34d6a31a83f`.
Docker image content ID:
`sha256:c03a718b6023cdd89cc67af29e86a0c3d4b02fda26579410bd6354bdb49647d9`.
It is not a registry manifest digest. This is dirty implementation-worktree
acceptance, with source_clean=false, deployment_authorized=false and
registry_digest=null; it is not a clean releasable candidate or cloud evidence.

Native offline renderer smoke passed for both phases using explicitly synthetic
`localqa`, reviewer CIDR and all-a digest inputs. External outputs are
`TECHADEMY/EVIDENCE/module10-story109-fixture-foundation-a.json` and
`module10-story109-fixture-app-a.json`. They are review fixtures, never deployable
approval/evidence of an actual registry image or intended reviewer IP. Git whitespace
check passed; nothing was staged. Current HEAD remained the starting HEAD and
Module 10 intervening history remained empty at that local check.

### Approved amendment verification and commit preparation

Approval-turn starting/final-pipeline source HEAD:
`d6232797d62499d13943696119a60a9d3c03214a`. Precommit HEAD advanced to
`22fa61c0f5290075c698b6ac3b05597469f02e12` through foreign history;
accepted Story 10.8 remains an ancestor (exit 0), with no intervening Module 10
commits or unexpected owned edits. No fixed-HEAD requirement was imposed.
The approved footprint contract and four explicit authority-boundary tests were
added, bringing the total to 311 tests. ADR, runbook, README, STORIES and TRACEABILITY
record approval for exactly one supporting identity and registry-only AcrPull.

First approved pipeline stopped at the unchanged Streamlit AppTest button-run
15-second timeout: 310 passed, one UI failure; no build or success manifest followed.
No UI code, assertion or timeout was altered. The failed pytest gate was rerun
unchanged: 311 passed, one warning in 4.69s. The complete fail-fast pipeline was
then rerun, using a fresh external pytest directory:

1. `python -m ruff check .`: All checks passed, exit 0.
2. `python -m pytest`: **311 passed, 1 warning in 4.89s**, exit 0.
3. `python -m compileall -q src tests scripts ui`: passed, exit 0.
4. Accepted workflow security contract: passed.
5. Docker build and native runtime acceptance: passed, pipeline exit 0.

Latest manifest: `TECHADEMY/EVIDENCE/module10-story109-approved-local-c.json`.
Image tag: `module10-ai:sha-d6232797d62499d13943696119a60a9d3c03214a-worktree-0f5aeb1676ad`.
Image content ID:
`sha256:0274d6a6a555a330cac603631065ccb2fe3bb72bd6f9a1897798d26b72b8146e`.
All accepted local container checks passed, including effective UID 10001,
health/readiness, deterministic inference, safe rejection, minimized telemetry,
graceful stop and exact cleanup. Evidence remains implementation-worktree/local
with source_clean=false, deployment_authorized=false and registry_digest=null.
An approved clean postcommit candidate must be built/validated separately before
human-controlled publication; this record grants no cloud authority.

The existing Starlette warning and intermittent UI AppTest timeout are non-blocking
local verification concerns after the unchanged recheck/full pipeline passed;
neither supports a production-reliability claim. Independent review, Azure server
validation and genuine cloud evidence remain deferred.

Read-only Azure inspection on 2026-10-16: Microsoft.App Registered, both apps and
managed environments advertise South Central US. Microsoft.ManagedIdentity
NotRegistered, user-assigned identities advertise South Central US. Only minimized
registration/capability metadata was displayed. Initial sandboxed CLI read failed
on local command-log access; the successful bounded read disabled command-file
logging/telemetry. No Azure mutation or provider registration occurred. These
capability observations do not establish capacity, permissions or deployment.

## Ordered completion assessment

Requirements: repository capability implemented; supporting identity amendment
approved; independent review and course cloud execution remain deferred.
Product Experience: exact human PowerShell runbook, offline render command and
reviewable bounded JSON output; accepted Streamlit reviewer remains unchanged.
Real Functionality: actual offline/native tests; ARM server execution and cloud
behavior remain unverified. Reliability: accepted probes and graceful shutdown,
finite subprocess/HTTP/log waits and fail-closed drift/failure handling.
Security: no mutation executor, narrow approved pull identity, restricted HTTPS,
no secret/account outputs, no authority from model/candidate/observed data.
Cost: smallest Consumption pair, min zero/max two, Basic ACR, bounded verification
traffic, retention/quota and prompt explicit teardown; no dollar guarantees.
Evidence: OFFLINE AZURE CONTRACT / DETERMINISTIC FIXTURES, local native gates,
READ-ONLY AZURE CAPABILITY METADATA; genuine cloud verification remains deferred.
Deployment: human server validation, reviewed provisioning/publication/verification
and teardown remain undone. No final C-026/C-027 or production-grade claim.

The human authorized the requested module-only local commit after full local gates. No push,
merge, tag, Azure provisioning, Azure image publication or teardown has occurred.
No Azure resource was created, modified or deleted by the agent. Story 10.10
has not begun.
