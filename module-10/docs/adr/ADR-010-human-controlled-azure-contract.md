# ADR-010: Native ARM contract and human-controlled cloud execution

## Status

Approved human deployment architecture is retained. Implementation mechanism:
native ARM JSON and read-only Python verification. Supporting pull-identity
footprint amendment explicitly approved by the human on 2026-10-16 for repository
implementation and local commit only. Cloud execution remains unauthorized.

## Decision and rationale

Render two incremental resource-group templates: foundation before private-image
publication, then the accepted digest-pinned app. ARM provides declarative Azure
resource convergence without new compiler/state/tool dependencies. Separate phases
allow the registry and least-privilege image-pull authorization to exist before
app provisioning, avoiding a dependency cycle and a public bootstrap workload.
The repository contains no Azure mutation executor. The human runs the reviewed
PowerShell commands after independent review and cloud authorization.

A supporting user-assigned identity plus registry-only AcrPull assignment is
approved. Its `None` lifecycle removes identity access from application containers.
It requires Microsoft.ManagedIdentity registration by the human and adds an
identity resource to the originally listed footprint. Approval permits exactly
one supporting identity and one registry-scoped AcrPull assignment; no ACR admin
credentials or broader runtime roles. This decision does not change the accepted
FastAPI/Streamlit/domain architecture. No provider registration, Azure RBAC or
resource mutation, image push, deployment, Git push, merge or tag is authorized.

One reviewer IPv4 /32 allow rule limits the externally reachable unauthenticated
API. HTTPS is required. No new live provider, API credential, general public access,
network service or distributed queue/cache is added. The unchanged Docker workload
uses minimum supported Consumption compute with min zero/max two replicas.

Log Analytics receives existing bounded JSON stderr/stdout telemetry through the
managed environment. Its ingestion key is resolved only server-side in ARM and
never emitted. Retention/daily ingestion settings and prompt teardown contain
exposure; they are not guaranteed dollar caps. Registry lifetime costs persist
even while the app has zero replicas.

## Consequences

Local template/fixture tests are distinct from server validation, cloud deployment,
telemetry delivery, scaling demonstration and independent production acceptance.
The read-only collector rejects drift, verifies immutable image/revision identity,
exercises tiny deterministic traffic, queries only correlated log aggregates and
rechecks state before writing minimized evidence. No CLI/query/HTTP observation
confers privileged authority. Candidate provenance is established by the human
from the actual clean pipeline run and the same tested Docker content, not forged JSON.

The existing GitHub promotion contract is retained; root workflow installation,
protected Environment and hosted OIDC configuration remain separately authorized.
The human-controlled path implements the currently requested scope without
claiming hosted deployment automation. Azure server validation, capacity, app
deployment, cloud verification and teardown remain human work. C-026/C-027 and
Story 10.10 are not accepted or started by this ADR.

See [operator workflow](../AZURE_DEPLOYMENT.md) for exact commands, references,
failure handling, evidence bounds and teardown.
