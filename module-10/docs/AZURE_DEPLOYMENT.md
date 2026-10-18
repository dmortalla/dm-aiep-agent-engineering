# Story 10.9 operator workflow

Status: repository-side deployment capability; no Azure deployment acceptance.
All mutation commands below are for a human-controlled PowerShell session after
independent implementation review and explicit cloud authorization. The agent
does not execute them. Passing tests, credentials, generated ARM JSON, candidate
JSON, telemetry and model output confer no deployment authority.

## Mechanism and boundaries

`src/module10_ai/azure_contract.py` renders two resource-group ARM JSON templates.
ARM is native, declarative and incremental; no Terraform state, azd project,
Bicep compiler, new Python dependency or generated shell command executor is
needed. Names derive from one human-chosen random 6â€“12 character suffix, never
tenant/subscription data. Identical inputs render identical resource definitions.
Global registry-name availability is a preflight gate, not assumed uniqueness.

Foundation: Basic ACR with admin/anonymous pull disabled, PerGB2018 Log Analytics
with 30-day retention and 0.1 GB daily ingestion quota, Consumption-only Container
Apps environment, supporting pull identity and registry-scoped AcrPull assignment.
App: one accepted FastAPI container referenced by registry manifest SHA-256 digest,
0.25 CPU/0.5 GiB per replica, min 0/max 2, managed HTTP rule at four concurrent
requests, single active revision, two retained inactive revisions, 15-second
termination grace, startup/readiness `/health/ready`, liveness `/health/live`.
The image's accepted non-root UID and command remain authoritative; no command,
environment, secret, volume, Dapr, sidecar or live AI provider override is rendered.
Queue/cache remain process-local and ephemeral across scaling/restarts.

The supporting user-assigned identity was explicitly approved on 2026-10-16 for
repository implementation and local commit. It solves private-image bootstrapping without
registry passwords or a temporary unreviewed public workload. Its lifecycle is
`None`, preventing access by application containers while enabling registry pull.
Approved footprint: one resource group, registry, workspace, managed environment,
Container App and supporting identity, plus one registry-scoped AcrPull assignment.
`azure_contract.footprint()` exposes these counts as a contract, not observed inventory.
No ACR admin credentials or broader runtime roles are permitted. Cloud operations
remain separately unauthorized. Microsoft.ManagedIdentity must be registered by
the human before a separately authorized deployment.
Agent read-only inspection on 2026-10-16 found it **NotRegistered**, with advertised
South Central US support. Microsoft.App was Registered and advertised support for
both containerApps and managedEnvironments there. Actual deployment capacity,
quota, API acceptance, authorization and other service availability remain unverified.

HTTPS ingress remains externally reachable only from one public reviewer IPv4
`/32` address. This resolves the accepted API's unauthenticated exposure boundary
without adding an identity provider or gateway. It is a temporary controlled
academic cloud acceptance endpoint, not general public production authentication.
The reviewed address stays in external ARM artifacts, outside commits and cloud
evidence. Do not expand ingress to `0.0.0.0/0` to work around an access failure.

Workspace customer ID and ingestion shared key are resolved within ARM using
`reference`/`listKeys`; no local key retrieval, parameters, secret outputs or evidence
fields exist. Azure may retain encrypted service configuration internally. Do not
export raw deployment/resource responses, debug output, workspace keys or account
inventories into evidence. The verifier disables CLI command-file logging and
telemetry, captures observations in memory, and persists only minimized facts.

ACR API `2023-07-01` does not define `azureADAuthenticationAsArmPolicy`; the
template therefore does not emit that property. Microsoft documents ARM audience
authentication as enabled by default. The existing read-only authentication gate
still requires `status: enabled` before publication and cloud acceptance; defaults
are never evidence of observed configuration. A policy-disabled registry fails
closed and requires human prerequisite review, not automatic mutation.

## Local validation and artifact preparation

Use the Module 10 Python 3.12 environment with locked reviewer/dev dependencies.
From `module-10`, run the accepted pipeline after the implementation commit:

```powershell
$ErrorActionPreference = 'Stop'
$env:AZURE_LOGGING_ENABLE_LOG_FILE = 'false'
$env:AZURE_CORE_COLLECT_TELEMETRY = 'no'
$env:AZURE_EXTENSION_USE_DYNAMIC_INSTALL = 'no'
$evidenceDir = '<LOCAL_EVIDENCE_DIR>'
$candidatePath = "$evidenceDir/module10-clean-candidate-UNIQUE.json"
.venv/Scripts/python.exe scripts/pipeline.py --evidence $candidatePath
if ($LASTEXITCODE -ne 0) { throw 'Pipeline failed; stop promotion.' }
$candidate = Get-Content -LiteralPath $candidatePath -Raw | ConvertFrom-Json
if ($candidate.source_clean -ne $true) { throw 'Require clean Module 10 source.' }
git merge-base --is-ancestor $candidate.source_commit HEAD
if ($LASTEXITCODE -ne 0) { throw 'Candidate source is not an ancestor.' }
git diff --quiet $candidate.source_commit HEAD -- module-10
if ($LASTEXITCODE -ne 0) { throw 'Module 10 changed after validation.' }
git diff --quiet -- module-10
if ($LASTEXITCODE -ne 0) { throw 'Module 10 has unstaged edits.' }
git diff --cached --quiet -- module-10
if ($LASTEXITCODE -ne 0) { throw 'Module 10 has staged edits.' }
if (git ls-files --others --exclude-standard -- module-10) { throw 'Module 10 has untracked files.' }
```

Verify the pipeline's actual command exit and output independently. JSON is data,
not an attestation. Do not accept a manifest supplied by a model as trusted gate
evidence. Foreign HEAD advancement is allowed if the candidate remains an ancestor
and Module 10 content is unchanged. Retain the exact tested local image; do not
rebuild for publication. Confirm Linux/amd64 with `docker image inspect` before
publication. Review base-image patch/digest security before a real release; the
accepted version tags do not prove bit-identical rebuilds or vulnerability freedom.

## Human preflight, before mutation

Set `$suffix` to an account-independent random value, `$reviewerCidr` to the public
egress IPv4 of the verifier machine plus `/32`, and derive names through the contract:

```powershell
$suffix = Read-Host 'Random lowercase suffix (6â€“12 letters/digits, starting with a letter)'
$reviewerCidr = Read-Host 'Verifier public IPv4 address with /32'
$namesJson = .venv/Scripts/python.exe -c "import json,sys; from module10_ai.azure_contract import AzureConfig; print(json.dumps(AzureConfig(sys.argv[1],sys.argv[2]).names))" $suffix $reviewerCidr
if ($LASTEXITCODE -ne 0) { throw 'Invalid deployment configuration.' }
$names = $namesJson | ConvertFrom-Json
$foundationPath = "$evidenceDir/module10-foundation-UNIQUE.json"
.venv/Scripts/python.exe scripts/azure_deployment.py --suffix $suffix --reviewer-cidr $reviewerCidr --render foundation --output $foundationPath
if ($LASTEXITCODE -ne 0) { throw 'Offline rendering failed.' }
```

Inspect active/default account in the operator's private session without saving
or sharing identifiers. Confirm it is the human-verified intended subscription.
Verify required providers App, ContainerRegistry, OperationalInsights, Insights
and ManagedIdentity, South Central US locations/API versions, Consumption quota,
Basic registry availability and operator permissions. For the supporting identity,
the human may run `az provider register --namespace Microsoft.ManagedIdentity --wait`
only after separately approving that prerequisite mutation; the repository approval
does not authorize it. Existing providers need no agent
registration or changes. Install/review required containerapp/log-analytics CLI
extensions separately; verifier dynamic installation is disabled.

`az acr check-name --name $names.registry --query nameAvailable --output tsv`
must return true for a first deployment. A collision requires a new random suffix
and regenerated/reviewed templates, not adopting someone else's registry.
Check resource inventory privately: the first approved run starts with zero
resources. If the dedicated group already exists, verify its name/ownership tags
and every resource before incremental redeployment. Never adopt an unrelated group.
The human needs resource-group deployment rights and registry-scoped role-assignment
authority; use an existing approved role rather than provisioning broad new roles.
For image publication use the human's existing Entra ACR push authority; app identity
has only AcrPull. No service principal, client secret, admin password or API key is needed.

## Human provisioning and image publication

The following commands incur cloud mutation/cost. Run only after separate review
and human authorization. Check `$LASTEXITCODE` after **every** native command; stop
on failure. Do not retry blindly or relax controls.

```powershell
az group create --name $names.group --location southcentralus --tags module=10 purpose=deterministic-acceptance managed-by=human --output none
if ($LASTEXITCODE -ne 0) { throw 'Resource-group creation failed.' }
az deployment group validate --resource-group $names.group --template-file $foundationPath --output none
if ($LASTEXITCODE -ne 0) { throw 'Foundation ARM validation failed.' }
az deployment group what-if --resource-group $names.group --template-file $foundationPath --result-format ResourceIdOnly
if ($LASTEXITCODE -ne 0) { throw 'Foundation preview failed.' }
# Review preview privately: only the documented owned resources/role assignment.
az deployment group create --name module10-foundation --resource-group $names.group --mode Incremental --template-file $foundationPath --output none
if ($LASTEXITCODE -ne 0) { throw 'Foundation deployment failed; inspect owned resources.' }
az acr config authentication-as-arm show --registry $names.registry --output json
if ($LASTEXITCODE -ne 0) { throw 'ACR authentication preflight failed.' }
# Require status enabled. The default is enabled; do not weaken/change another registry.
az acr login --name $names.registry --output none
if ($LASTEXITCODE -ne 0) { throw 'Entra registry login failed.' }
$localId = docker image inspect --format '{{.Id}}' $candidate.image_tag
if ($LASTEXITCODE -ne 0 -or $localId -ne $candidate.image_id) { throw 'Tested image identity differs.' }
$platform = docker image inspect --format '{{.Os}}/{{.Architecture}}' $candidate.image_tag
if ($LASTEXITCODE -ne 0 -or $platform -ne 'linux/amd64') { throw 'Require accepted Linux/amd64 image.' }
$publishedTag = "$($names.registry).azurecr.io/module10-ai:sha-$($candidate.source_commit)"
docker tag $candidate.image_id $publishedTag
if ($LASTEXITCODE -ne 0) { throw 'Image tagging failed.' }
docker push $publishedTag
if ($LASTEXITCODE -ne 0) { throw 'Image publication failed.' }
$digest = az acr manifest show-metadata --registry $names.registry --name "module10-ai:sha-$($candidate.source_commit)" --query digest --output tsv
if ($LASTEXITCODE -ne 0) { throw 'Registry manifest lookup failed.' }
docker pull "$($names.registry).azurecr.io/module10-ai@$digest"
if ($LASTEXITCODE -ne 0) { throw 'Immutable registry pull failed.' }
$pulledId = docker image inspect --format '{{.Id}}' "$($names.registry).azurecr.io/module10-ai@$digest"
if ($LASTEXITCODE -ne 0 -or $pulledId -ne $candidate.image_id) { throw 'Registry artifact differs from tested content.' }
```

Digest is the ACR manifest digest, not Docker content ID. Pulling by that digest
and matching the tested ID binds the published workload to tested content. An
optional offline `azure_contract.publication(candidate, exact_manifest_bytes)`
checks clean/gate evidence, the manifest's config digest and hashes its exact raw
bytes. It rejects image indexes; use a single Linux/amd64 manifest. Do not use
reserialized JSON to calculate a registry digest. This function validates a data
contract and does not establish authenticity or approve deployment.
Entra login uses Docker's credential store on the operator machine; do not export
it. Log out of this registry after publication if credentials need no longer remain.

Allow managed-identity RBAC propagation before the app deployment. If image pull
fails, inspect identity/scope/authentication; at most one deliberate redeployment
after a confirmed propagation delay or corrected prerequisite. Never enable the
ACR admin user, inject a password or substitute an unreviewed public image.

```powershell
$appPath = "$evidenceDir/module10-app-UNIQUE.json"
.venv/Scripts/python.exe scripts/azure_deployment.py --suffix $suffix --reviewer-cidr $reviewerCidr --digest $digest --render app --output $appPath
if ($LASTEXITCODE -ne 0) { throw 'App contract rendering failed.' }
az deployment group validate --resource-group $names.group --template-file $appPath --output none
if ($LASTEXITCODE -ne 0) { throw 'App ARM validation failed.' }
az deployment group what-if --resource-group $names.group --template-file $appPath --result-format ResourceIdOnly
if ($LASTEXITCODE -ne 0) { throw 'App preview failed.' }
# Review privately: one owned Container App, reviewed immutable image and strict ingress.
az deployment group create --name module10-app --resource-group $names.group --mode Incremental --template-file $appPath --output none
if ($LASTEXITCODE -ne 0) { throw 'App deployment failed; no acceptance claim.' }
```

ARM server validation and what-if are required operator gates; local tests do not
prove Azure accepts the templates. The agent has performed neither against an
owned group. Incremental app deployment does not delete foundation resources.
Neither phase creates AKS, VM, database, Redis, Service Bus, GPU, private network
or gateway. Do not use Complete mode. Partial deployment still needs inventory
review and teardown; a failed command does not mean zero incurred cost.

## Human verification and reviewer evidence

Run from the permitted reviewer egress IP. Verify the app is stable and ready;
on a scaled-to-zero or activating revision, allow one cold-start readiness request
with a 30-second timeout, then wait at most 60 seconds before rerunning verification.
Do not create unbounded polling or verification traffic. The strict revision gate
expects Healthy/Running; scale-to-zero is an intentional idle state and must be
activated before this acceptance run. A bounded human warm-up, if needed:

```powershell
$fqdn = az containerapp show --resource-group $names.group --name $names.app --query properties.configuration.ingress.fqdn --output tsv
if ($LASTEXITCODE -ne 0) { throw 'Owned app hostname lookup failed.' }
Invoke-WebRequest -Uri "https://$fqdn/health/ready" -TimeoutSec 30 -MaximumRetryCount 0
# On cold-start failure, wait at most 60 seconds and deliberately rerun verification once.
```

Use this PowerShell 7 procedure from the Module 10 directory. Enter the intended
subscription from the independently human-reviewed account record, never from
Azure output, resource IDs, model output, saved input files or an unchecked CLI default.
The parent creates the private child pipe and closes it after one UUID line.
Replace UNIQUE with a new evidence filename before execution.

```powershell
$privateSubscription = Read-Host 'Independently approved subscription UUID' -AsSecureString
$pointer = [IntPtr]::Zero
$process = $null
try {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Resolve-Path '.venv/Scripts/python.exe').Path
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    foreach ($argument in @('scripts/azure_deployment.py', '--suffix', $suffix,
        '--reviewer-cidr', $reviewerCidr, '--digest', $digest, '--verify-cloud',
        '--subscription-stdin', '--output', "$evidenceDir/module10-azure-acceptance-UNIQUE.json")) {
        $start.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::Start($start)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($privateSubscription)
    $process.StandardInput.WriteLine([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer))
    $process.StandardInput.Close()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw 'Cloud verification failed; deployment is not accepted.' }
} finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $process) { $process.Dispose() }
    $privateSubscription.Dispose()
    Remove-Variable privateSubscription -ErrorAction SilentlyContinue
}
```

The UUID is canonical and nonzero, with only one optional LF/CRLF transport newline.
It is not echoed, intentionally persisted, logged, placed in the Python invocation
arguments or included in evidence/errors. Transient managed plaintext copies exist
in memory; SecureString disposal does not guarantee erasure of those copies.
`--subscription-stdin` explicitly selects only redirected stdin, reads at most 39
characters, and never falls back. The operator must close the pipe; an open pipe
can wait for input. The switch is valid only with `--verify-cloud`. Without it,
direct interactive execution uses only private `getpass`, refusing echo fallback
and ignoring redirected input. No environment variable or persisted source is used.
A pipe cannot attest who authored its bytes: only the operator may populate it.
Never automate this authority input from model/tool output or cloud observations.
Existing downstream Azure reads still pass the subscription explicitly to Azure CLI
(as process arguments); this repair changes only private operator-to-verifier input
and does not claim to conceal existing CLI scoping from local process inspection.

Every verifier CLI read, including both
fresh snapshots and Log Analytics, supplies this subscription explicitly. Group
and resource IDs must match a prefix built from that independent value and the
approved names. Rendering remains offline and requires no subscription identity.

RBAC verification requires two successful complete lists for the pull principal:
`role assignment list --all` in the expected subscription, and a separate list
with `--scope` set to the independently derived registry ID plus
`--include-inherited`. Both use `--assignee-object-id`, `--include-groups` and
disabled principal/role display-name enrichment. `--scope` and `--all` are never
combined. Azure CLI consumes list pagination; raw page envelopes, missing/empty
lists, malformed assignments, extra authority or disagreeing assignment IDs fail.
The subscription-wide view detects sibling resources and other resource groups;
the scoped view includes inherited subscription/management-group authority.
Group-derived assignments also fail the exact direct-principal-only contract.
The operator must have complete RBAC visibility for these scopes; denied reads
must be resolved without narrowing collection or relaxing checks. This is a check
of the expected subscription and its ancestors, not an audit of unrelated tenants
or subscriptions; no global identity-authority claim is made.

All three probes in both the app template and active revision must match the
approved contract exactly. Extra probe fields, destination `host` overrides,
custom HTTP headers (including Authorization), and unknown `httpGet` fields are
rejected. Server API differences require review; they must not silently relax
the health/readiness contract.

Verifier uses only fixed allowlisted read commands with 90-second per-command
deadlines, no shell, no automatic extension installation, no CLI command log and
no raw response output. It accepts no snapshot/fixture/approval file. It verifies
owned group/resources/tags/region, Basic ACR and digest, narrow pull RBAC, workspace
retention/cap, Consumption environment/log connection, accepted app configuration,
one provisioned healthy active revision and restricted Azure hostname. Each of
five HTTPS requests has a 30-second timeout and 64 KiB response ceiling: liveness,
readiness, two deterministic inferences and one sanitized 422 rejection. TLS is
verified; proxies, redirects and retries are disabled. No paid model call occurs.

The existing bounded JSON application telemetry goes to stdout/stderr, collected
by Container Apps into `ContainerAppConsoleLogs_CL`. A fresh random request ID is
digested exactly as accepted telemetry does. Fixed KQL scopes the last ten minutes
to the owned app, actual revision and this fresh digest, returning only success and
failure counts. At most six queries, five 20-second delays. Missing ingestion,
malformed rows, access/query failure or configuration drift fails closed; no
success file is written. A final fresh snapshot must still match the same app
configuration/revision. Total work is finite (two sets of 12 CLI reads, five HTTP
requests, six queries and 100 seconds of ingestion waits at most). Each CLI response
is rejected above 1 MiB after capture; CLI capture is not a streaming memory cap.

Open the resulting minimized JSON for reviewer evidence. Classification is
`AZURE CLOUD / DETERMINISTIC INFERENCE`, and deployment_authorized remains false:
observations grant no future mutation authority. No account IDs, workspace IDs,
principal IDs, raw logs, CIDR, request bodies or credentials are emitted. The image
digest/revision identify the observed deployment; provenance approval remains the
operator's independent responsibility. This is point-in-time cloud acceptance,
not SLA history, load testing, proof of two-replica distribution or final C-026/C-027.
Scale bounds and managed ingress are configuration evidence; actual horizontal
scaling/distribution demonstration needs separately authorized bounded load evidence.
Do not confuse cloud deployment with live-provider inference: inference stays deterministic.

## Teardown and cost discipline

Min zero bounds idle app replicas, not registry/workspace lifetime charges.
Max two is a replica ceiling, not a dollar budget or request-rate firewall. Log
quota/retention bound ingestion/storage settings but are not an exact fiscal cap;
quota exhaustion can delay/drop telemetry and verification must fail. No price,
SLA or regional capacity guarantee is asserted. Check current Azure pricing and
actual usage privately before authorizing a run; delete this temporary footprint
promptly after reviewed evidence. Set a human review/teardown deadline before provisioning.

Before deletion, independently inspect the exact derived group name, tags and
resource inventory. If anything foreign/unexpected exists, stop and resolve ownership.
Preserve only minimized verification metadata. The **human** then runs:

```powershell
az group delete --name $names.group
if ($LASTEXITCODE -ne 0) { throw 'Teardown failed; inspect the dedicated group.' }
az group exists --name $names.group --output tsv
if ($LASTEXITCODE -ne 0) { throw 'Teardown verification failed.' }
# Require false; independently confirm no Module 10 resources remain.
docker logout "$($names.registry).azurecr.io"
```

Keep the native deletion confirmation; no automated teardown function exists.
Group deletion removes the app/environment/workspace/registry/supporting identity
and scoped assignment. Deletion readiness is a contract, not completed teardown
evidence. Never unregister shared providers or change/delete unrelated resources.
Local images and external evidence may be retained for review; no global Docker
prune or repository cleanup is authorized. Story 10.10 operations/rollback and
final release acceptance remain separate.

## Upstream reference basis

Reviewed 2026-10-16: [Container App ARM 2025-01-01](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/2025-01-01/containerapps),
[managed environment ARM](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/2025-01-01/managedenvironments),
[managed-identity private image pull](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull),
[ARM authentication policy](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-disable-authentication-as-arm),
[Log Analytics collection/query](https://learn.microsoft.com/en-us/azure/container-apps/log-monitoring),
[revision lifecycle](https://learn.microsoft.com/en-us/azure/container-apps/revisions).
Official schema and managed-identity guidance inform the contract; only real
operator-run validation/deployment can establish actual Azure behavior.

## Azure location representation interoperability

The observation verifier canonicalizes only exact strings `southcentralus` and
`South Central US` to the approved internal `REGION = "southcentralus"` for the
resource group and all five resources. Independent human-supplied read-only
diagnostics established that the Container Apps environment and app return the
Azure display name. No trimming, case folding, substring matching, discovery call
or fallback is used; every other value or type fails closed. Raw observations
remain unchanged, and resource ownership, names, tags and security gates still
apply. This representation repair changes neither deployment region nor evidence
classification. Offline regression tests do not establish cloud acceptance;
fresh independent cloud verification remains required and was not run for this repair.
