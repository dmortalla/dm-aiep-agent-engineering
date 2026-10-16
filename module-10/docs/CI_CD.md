# Module 10 CI/CD contract

Story 10.8 implements LOCAL CI/CD CONTRACT evidence. GitHub-hosted execution and
Azure deployment are not verified. ADR-008 remains unchanged.

## Ownership and installation

`ci/workflow.json` is the authoritative JSON-form YAML workflow specification.
GitHub does not discover it in this module. No root workflow is modified.
After repository-integration authorization, materialize a new external staging file:

```powershell
.venv/Scripts/python.exe scripts/pipeline.py --materialize E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-10.yml
```

An authorized integration step must review and copy that exact file to
`.github/workflows/module-10.yml`. The helper deliberately rejects repository
output destinations and existing files. Root integration must be separately owned;
it affects workflow discovery, not another module's implementation. No actual
GitHub execution or protected Environment is established by this story.

## Execution and reproducibility

The prepared workflow uses Ubuntu 24.04, Python 3.12.14, uv 0.12.5, and
`uv sync --locked --group reviewer --python 3.12`. The existing uv.lock mechanism
remains authoritative. Reviewer tests include locked Streamlit; Docker still uses
`uv sync --locked --no-dev --no-install-project --no-cache`. No lock/dependency
changes were needed. Existing build-backend constraints and version-tagged base
images remain; bit-identical build reproducibility is not claimed.

Single-job ordering is environment setup -> Ruff -> pytest -> compileall ->
targeted specification security contract -> Docker build -> native container
acceptance -> bounded manifest -> evidence upload. Every required command fails
closed. No continue-on-error, retry, matrix, registry push or duplicate image build.
The security check verifies the reviewed fixed workflow; it is not a general
vulnerability scan, SBOM, secret scanner, signed attestation or SLSA guarantee.

From this module, after locked environment setup, run:

```powershell
.venv/Scripts/python.exe scripts/pipeline.py --evidence E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module10-validation-UNIQUE.json
```

Use a new filename with an existing parent directory. This executes the native
quality gates and real Docker acceptance. Docker engine must be available. Ordinary
pytest remains deterministic and does not invoke Docker or cloud services.

## Trust and cost boundaries

Push/PR triggers scope paths to module-10 and the future root workflow itself.
Manual dispatch validates only. PR merge source is untrusted; no deployment job,
Environment, id-token permission, Azure action or credential input exists. Platform
token permission is contents:read; checkout does not persist credentials. Run script
text is fixed; untrusted branch names/PR titles never enter shell commands. GitHub
expressions occur only in platform concurrency/artifact names. Never add cloud
secrets at repository scope accessible to this job; use separately protected future
deployment credentials. Validation results and model output cannot approve release.

Only three GitHub first-party actions are used. Upstream tag refs were verified
with git ls-remote on 2026-10-15 (not guessed):

| Action | Upstream tag | Immutable commit |
|---|---|---|
| actions/checkout | v4.3.1 | 34e114876b0b11c390a56381ad16ebd13914f8d5 |
| actions/setup-python | v6.1.0 | 83679a892e2d95755f2dac6acb0bfd1e9ac5d548 |
| actions/upload-artifact | v4.6.2 | ea165f8d65b6e75b540449e92b4886f43607fa02 |

Review upstream security updates before integration and update pins deliberately.
No floating action refs. The small dependency installation uses locked package
selection; uv bootstrap itself uses an exact version, without an independent hash
attestation. No shared dependency cache is added: this avoids cross-trust cache
writes; Docker's local layer cache remains useful. Job timeout 25 minutes, native
gates 300 seconds each, Docker build 600 seconds, and accepted container limits
bound work. Concurrency cancels superseded same-ref runs. Evidence retention is
seven days. No paid model calls or Azure operations occur.

## Artifact and acceptance

Clean candidates use `module10-ai:sha-<full-source-commit>` and Docker content ID.
Tags provide traceability, not registry-enforced immutability: the content ID is
required. Dirty local builds append a random worktree suffix and set source_clean
false; they cannot represent release candidates. The manifest includes source,
Python version, lock SHA-256, native gate outcomes, build and acceptance outcomes,
classification, and deployment_authorized=false. It contains no environment dump,
logs, raw requests or credentials and is limited to 8192 bytes. Success is written
exclusively after acceptance returns and owned-container cleanup succeeds. Failure
leaves no new success manifest. Existing output files cannot be overwritten.

`scripts/container_acceptance.accept(image)` reuses the accepted native system and
avoids a second build. Its no-argument CLI behavior is retained. It exercises UID
10001, read-only source/runtime, health/readiness, deterministic inference, malformed
requests, telemetry, graceful shutdown and own-container cleanup. Streamlit absence
is now checked in the actual runtime as well. No global Docker cleanup occurs;
uniquely tagged local images remain for review. Only JSON metadata is uploaded;
no image archive/registry artifact is preserved remotely yet. A later deployment
must transfer the tested image, not rebuild it and assume equivalence.

## Promotion and rollback preparation

`ci/promotion.json` is a versioned data contract, not a deployment command.
VALIDATED ARTIFACT never means AUTHORIZED DEPLOYMENT. Story 10.8 has no executable
privileged deployment path, even on manual dispatch. Missing or malformed full
commit/content identity fails candidate preparation. A successful manifest still
has deployment_authorized=false and cannot be accepted as an approval token.

Story 10.9 must implement a trusted controller that verifies source cleanliness,
trusted successful validation run, artifact content identity and an actual registry
manifest digest. Docker image ID is not a registry manifest digest. It must bind
that digest to the uploaded tested artifact and trusted commit; arbitrary user or
model-supplied JSON cannot establish that binding. Require an externally configured
protected GitHub Environment with required reviewers, branch restrictions and
self-approval prevention as appropriate; verify those settings before enabling
any deployment job. PR code must never run with that job's credentials. GitHub
Environment protection cannot be created truthfully by a workflow declaration alone.

Federated Azure OIDC is the preferred future credential boundary, with id-token:
write only on that separately protected deployment job. No federated trust, role,
subscription, client ID, resource, registry or secrets are fabricated here.

Record previous accepted commit, registry manifest digest and Container Apps
revision outside untrusted build authority. After approved promotion, check live
health, readiness, deterministic inference, revision traffic and Azure Monitor
receipt. Health/inference failure or operational regression triggers rollback
consideration by the protected operator mechanism to that previous accepted digest
and revision. No Azure rollback has been implemented or exercised.

## Evidence limits

Local runs establish LOCAL CI/CD CONTRACT and LOCAL CONTAINER INTEGRATION with
deterministic inference. A future GitHub run supplies separate run-URL evidence;
the manifest conservatively never asserts hosted execution verification itself.
Azure authentication, ACR if chosen, Container Apps, Azure Monitor, production
load balancing/traffic/SLA, distributed queue/cache, live providers and final
C-026/C-027 acceptance remain deferred to Story 10.9+. No release is authorized.
