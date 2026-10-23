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

## Bounded independent-review repair — 2026-10-17

Repair baseline HEAD: `8f4cfa8132c18987a15efe2c3de3c9b91484743b`.
Story 10.9 implementation `fec6e016aa93cf693d2a8d2b38f1b10d59f46b4e`
remains an ancestor. The repair owns only Module 10 and retains the approved
infrastructure, compute, cost and human-only mutation architecture.

The rejected RBAC command is replaced by separate subscription-wide `--all` and
registry-scoped `--include-inherited` reads, both explicitly bound to the expected
subscription and including group-derived authority. Both complete results must
contain exactly the same direct registry-scoped AcrPull assignment with validated
principal, role-definition and assignment identities. Sibling/group/ancestor
grants, missing lists, page envelopes and failed reads prevent acceptance. Scope
is the expected subscription and its ancestors; this is not a cross-tenant or
unrelated-subscription authority audit.

The expected subscription is entered privately at verification time, validated
as a nonzero canonical UUID, held in memory, and supplied on every CLI read.
Resource-ID prefixes are constructed from that independent input. No real account
identifiers are introduced in source, documentation, tests or success evidence;
test identifiers are generated from explicitly synthetic labels at runtime.
All three probes must exactly match the approved fields in both app and active
revision. Host overrides, custom/Authorization headers and unknown fields fail.
The unsupported ACR API 2023-07-01 authentication policy property is removed;
Microsoft's documented enabled default remains subject to the explicit read-only
enabled-state gate. Null/malformed principal and assignment UUIDs are rejected.
The documented post-buffering CLI output limit remains unchanged.

The original 311 tests remain; **101 added cases**, **412 total**, include:

- `test_real_collector_and_verifier_bind_every_read`
- `test_collector_rejects_authority_outside_registry`
- `test_rbac_partial_or_malformed_lists_fail`
- `test_rbac_missing_required_fields_fail`
- `test_missing_inherited_collection_fails`
- `test_rbac_exact_identity_and_authority`
- `test_null_or_malformed_principals_fail`
- `test_probe_extra_fields_fail_closed`
- `test_consistently_wrong_subscription_fails`
- `test_invalid_subscription_never_reaches_cli`
- `test_cli_forbids_invalid_scope_and_subscription_override`
- `test_cli_explicit_subscription_ignores_default`
- `test_failed_rbac_read_prevents_evidence`
- `test_acr_uses_documented_default_and_retains_receipt_gate`
- `test_private_subscription_refuses_echo_fallback`
- `test_cli_acceptance_never_writes_failed_evidence`

Independent local repair gates (Python 3.12.14, pytest 8.4.2):

1. `python -m ruff check . --no-cache`: passed, exit 0.
2. `python -m pytest -p no:cacheprovider --basetemp <external-evidence-directory>`:
   **412 passed, one existing Starlette warning in 4.05s**, exit 0.
3. `python -m compileall -q src tests scripts ui`: passed, exit 0; bytecode redirected
   to external evidence with `PYTHONPYCACHEPREFIX`.
4. Existing `pipeline.validate_contract()`: passed, exit 0.
5. `python -B scripts/container_acceptance.py`: blocked at `docker info`, exit 1,
   before any image build or container creation. Starting installed Docker Desktop
   did not recover the Linux engine. Its local startup log reports a secrets-engine
   socket rename/access failure. No Docker reset, socket deletion, host repair,
   image publication or Azure operation was attempted. Container acceptance has
   not passed at that checkpoint; the conditional repair commit was held pending
   recovery, as explicitly requested by the human. The resumed results below
   supersede that environmental blocker.

Initial Ruff found three line-length issues; those were repaired before testing.
The earlier 408-test run passed before four command-entry-point cases were added.
No assertion or security invariant was weakened. Temporary test and bytecode files
are under parent `TECHADEMY/EVIDENCE/story109-bounded-repair-20261017`.

Requirements: review findings addressed locally. Product experience: private
subscription prompt and updated operator workflow. Real functionality: deterministic
collector/command regressions pass; cloud execution remains unverified. Reliability:
both snapshots and probes fail closed. Security: explicit subscription and authority
checks; no additional privilege. Cost: unchanged bounded footprint/traffic. Evidence:
offline tests and the resumed local-container acceptance below. Deployment: no
Azure mutation, fresh independent review and genuine cloud evidence remain deferred.
No production-grade completion claim or Story 10.10 work is made.

Reference basis: [Microsoft CLI RBAC implementation](https://github.com/Azure/azure-cli/blob/dev/src/azure-cli/azure/cli/command_modules/role/custom.py)
and [ACR documented authentication default](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-disable-authentication-as-arm),
consulted read-only for this repair.

### Resumed final acceptance after human-restored Docker

The human independently restored Docker and authorized resuming the preserved
seven-file repair, without broadening implementation. Resumed HEAD remained
`8f4cfa8132c18987a15efe2c3de3c9b91484743b`. First, the previously blocked
`python -B scripts/container_acceptance.py` passed, exit 0. Then the entire
required fail-fast sequence passed again:

1. `python -m ruff check . --no-cache`: all checks passed, exit 0.
2. `python -m pytest -p no:cacheprovider --basetemp <external-evidence-directory>`:
   **412 passed, one existing Starlette warning in 4.23s**, exit 0.
3. `python -m compileall -q src tests scripts ui`: passed, exit 0; external bytecode.
4. Existing `pipeline.validate_contract()`: passed, exit 0.
5. `python -B scripts/container_acceptance.py`: passed, exit 0. Local build,
   startup/readiness/liveness/Docker health, UID 10001, targeted content/permissions,
   deterministic inference, 422/malformed JSON rejection, correlated minimized
   telemetry, graceful stop exit 0 and exact owned-container cleanup all passed.

Final local image: `module10-story105-c98365382c79:local`; Docker content ID:
`sha256:17266c97b4a47028d698fa386a4b11a5a068ee7035597dc37e7997cd5921cf88`.
This is local implementation-worktree acceptance, not a clean postcommit promotion
candidate, registry manifest identity, cloud evidence or deployment authority.
The human-authorized repair commit may now proceed after exact module-only diff
inspection. No implementation or tests were changed during resumption. The seven
files remain the repair's entire scope; only this verification record was updated.
No Azure operation, provider registration, RBAC mutation, image publication, Git
push/merge/tag, deployment or Story 10.10 work occurred. Fresh independent semantic
acceptance and genuine human-controlled Azure evidence remain deferred.

## RBAC default-stability repair — 2026-10-23

Repair baseline HEAD: `8f6d1450f626449ac3960d274fff83d62bd39378` (Module 10
content unchanged from `1666e99…` by an intervening foreign module-07 commit
that also touched nothing under Module 10), with candidate
`130955f37af873c3fa8ca54c72021ae81957c5ec` verified as an ancestor (merge-base
exit 0), the module-10 scripts/tests/docs-tracked content byte-identical to that
candidate before this repair (`git diff 130955f HEAD -- module-10` empty), no
later Module 10 commit, and a clean Module 10 working tree with empty staging
before mutation. Foreign concurrent work outside Module 10 is untouched.

The two prior fixes left `--resource-group` omitted from both RBAC reads, but the
Azure CLI can still inject `resource_group_name` from the operator's configured
group default (``defaults.group``) or from persisted parameter/local-context
state. On the subscription-wide `--all` read such an injected group fails with
"group or scope are not required when --all is used" before sibling-authority
detection can run; the scoped read fails as redundant. Local operator CLI state
therefore still breathes nondeterminism into verification.

The repair, per the independent adversarial review contract:

1. `az_read` now builds its child environment through a `child_environment()`
   boundary that preserves `os.environ` and only overrides the child copy:
   `AZURE_DEFAULTS_GROUP=""` (neutralizing `defaults.group`) and
   `AZURE_LOCAL_CONTEXT_<USERNAME>="off"`, where `<USERNAME>` is
   `getpass.getuser().upper()`, disabling local context/persistence. A failed
   username lookup fabricates no username variable and keeps the CLI's own
   fail-safe behavior. Nothing under `~/.azure/config`, `az configure` defaults,
   param-persist state, local-context files or the parent process environment is
   changed, and `AZURE_CONFIG_DIR` isolation is not used so operator auth/token
   state is untouched. All argv and read allowlist semantics remain as accepted.
2. On a nonzero CLI exit code, the three known operator-local contract failure
   messages (`--all` conflict, scope-redundant group, empty-string group usage
   error) are classified into one distinct, sanitized, actionable
   `VerificationError` that names resource-group defaults or parameter
   persistence as the interference and states that no acceptance evidence was
   recorded. Raw stderr, group names, subscription/principal/credential values
   and arbitrary CLI output are never echoed; other failures keep the existing
   generic non-echoing message and verification still fails closed.

New effective-behavior regressions (no `--resource-group` or empty elements in
RBAC argv, both reads keep `--all`/registry-scope+`--include-inherited`,
`--assignee-object-id`, `--include-groups`, both fill flags and the explicit
`--subscription` binding) cover: injected `defaults.group`, injected persisted
group state, failed username resolution, the sanitized residual-state error at
the CLI boundary and through the full `main()` entry point without an evidence
file, and preserved generic handling of unrelated CLI failures. The child-state
assertions fail against the candidate 130955f implementation (verified
externally: its child environment contains no `AZURE_DEFAULTS_GROUP` and the
classification functions are absent). Existing argv assertions were retained
unchanged; `--all` was not replaced by a subscription scope.

Independent local repair gates (Python 3.12.14, pytest 8.4.2, external basetemp
and bytecode under parent `TECHADEMY/EVIDENCE/module10-story109-default-stability-20261022`):

1. `python -m ruff check . --no-cache`: all checks passed, exit 0.
2. `python -m pytest tests/test_azure.py -q`: **707 passed in 4.46s**.
3. `python -m pytest -p no:cacheprovider --basetemp <external-evidence-directory>`:
   **922 passed, one existing Starlette warning in 20.49s**, exit 0. The known
   intermittent Streamlit AppTest timeout did not occur.
4. `python -m compileall -q src tests scripts ui`: passed, exit 0; bytecode redirected
   to external evidence with `PYTHONPYCACHEPREFIX`.
5. Existing `pipeline.validate_contract()`: passed, exit 0.

Requirements: review contract/R4 semantics addressed locally. Product experience:
a deterministic verifier regardless of operator CLI defaults, plus the documented
sanitized resolution error. Real functionality: effective child-state and
failure-classification regressions pass; cloud execution remains unverified.
Reliability: both RBAC read shapes fail closed and deterministically. Security:
child-only neutralization with no access/state/config mutation and no new echo
surface. Cost: unchanged. Evidence: offline regressions only; genuine cloud
verification remains deferred. Deployment/no cloud mutation unchanged. No
production-grade completion claim is made; this is a bounded DEFAULT-STABILITY
repair, and Story 10.10 work does not start.
