# Module 8 — MCP & Modern AI Infrastructure

A standalone enterprise capability plane: an MCP server exposes SQLite customer
lookup, a local HTTP account API, and an internal policy service. Genuine OpenAI
Agents SDK and Google ADK MCP consumers share those capabilities in a validated
three-stage workflow. Enterprise capabilities belong to the protocol boundary,
independent of the AI vendor.

## Run the reviewer console

Install Python 3.12 and uv. From this directory:

```powershell
uv sync --locked --extra dev
uv run streamlit run src/mcp_enterprise_integration/console.py
```

Open the local address printed by Streamlit. No virtual-environment activation,
API key, OpenAI model call, Gemini model call, or paid provider call is required.
Dependency installation may require network access; demonstrations use loopback.
The module configuration binds the console to `127.0.0.1` and disables usage telemetry.

Choose **Manager review** or **Support review**, then **Run enterprise demonstration**.
Expect three discovered capabilities, an allowed customer read, a discovered
policy capability denied to the viewer before invocation, and three MCP workflow
stages: OpenAI SDK → Google ADK → OpenAI SDK. Inspect the SQLite customer, HTTP
account, validated cross-stage policy request, final policy decision, negotiated
protocol, transport and evidence tables. Manager review permits the proposal;
Support review denies it. Neither scenario changes an account.

Both identities are fixed demonstration scenarios, not real authentication.
Execution creates and cleans up isolated temporary services and a seeded database.
At most two demonstrations run concurrently per process. Failures clear stale
success and show a safe error; retry or ask a maintainer to inspect the cause.

## Reviewer modes

The console opens in **Deterministic Demo**, the accepted default described above:
no key, zero model or provider calls, deterministic local-integration evidence.

**Live Provider Demo (opt-in)** is an optional, additive mode for reviewers who want
to see genuine external models use the same MCP capability plane with their own keys
(BYOK). It never runs because a key exists in the environment, and it never starts
until the reviewer selects the mode, enables at least one provider, pastes that
provider's key into a masked field, ticks both acknowledgements (external provider
calls; possible charges to their own provider account) and clicks **Run live provider
demonstration**.

- Stage 1 (optional live): an OpenAI model, run by the OpenAI Agents SDK, sees only
  the application-authorized `get_customer` MCP tool and must call it once with the
  application-bound customer.
- Stage 2 (optional live): a Gemini model, run by Google ADK through `McpToolset`,
  sees only `get_account_status` under the same rules.
- Stage 3 (never a model): the internal policy decision runs through the accepted
  OpenAI SDK MCP path with application-built context.
- An unselected provider's stage uses the accepted deterministic SDK path.

Bounds per run: at most 2 OpenAI and 2 Gemini model calls, 600 output tokens per
call, one MCP tool call per stage, no SDK/HTTP retries, 50s per stage, 120s per run,
one live run per process. These are call, token and time bounds, not a billing
guarantee; providers bill by their own pricing. The synthetic record `CUST-001` is
sent to each selected provider.

Keys are session-only capability material: never read from `OPENAI_API_KEY`,
`GOOGLE_API_KEY`, `GEMINI_API_KEY` or ADC for model calls; passed directly to a
per-run provider client; erased from the form widgets as soon as the run ends;
never stored, printed, placed in evidence or shown in errors; and scrubbed from
every log record created during the run. A key never grants authority, and model
output can never change the role, identity, capabilities or policy decision.

Evidence is `live-provider` only when the genuine provider client completed within
bounds and the authorized MCP result passed application validation. Injected test
doubles produce `mocked`; failures produce no success evidence. Live mode proves a
provider model can choose and call an application-authorized MCP capability through
its SDK. It does not prove model accuracy, provider availability, billing amounts,
authentication, multi-host deployment or that a model holds any authority. No paid or
live provider call was made while implementing or testing this mode; see
[Story 11](docs/stories/STORY-11-opt-in-live-provider-byok.md).

## What the demonstration establishes

The MCP SDK implements the server and Streamable HTTP client. OpenAI Agents SDK
executes its MCP discovery/tool integration; Google ADK executes its `McpToolset`
and tool integration. Agent objects are configured, but neither model runner runs.
The workflow carries validated, bounded, identity-correlated context between SDKs.
Application-owned `CapabilityPolicy` independently authorizes every SDK invocation.
Discovery, requester fields and returned decisions cannot grant privileges.

The direct-versus-MCP comparison executes the same customer lookup using the
Python repository and the protocol workflow. Direct calling couples the caller
to that implementation; MCP exposes discoverable typed capabilities through a
transport boundary. This is not a model tool-calling or performance benchmark.

Capability registration, context, orchestration and authority boundaries illustrate
building blocks relevant to AI operating systems. This module is not an operating
system. Independently addressed loopback services illustrate a small distributed
ecosystem. MCP provides application/agent-to-tools, context and system
interoperability here. A2A complements it for agent-to-agent interoperability;
A2A is not implemented.

## Verification and limits

```powershell
uv run ruff check .
uv run pytest
uv run python -m compileall -q src tests
```

Run in that fail-fast order. Tests include actual Streamlit AppTest execution of
both scenarios with model runners and external connections forbidden. No browser
automation is necessary for the accepted reviewer behavior.

Evidence distinguishes deterministic contract/policy tests, mocked failure
injection, adapter construction, and genuine **local-integration** execution over
loopback. SDK construction alone is not live-provider evidence. **No live-provider
evidence exists in this repository**: automated tests replace only the external model
boundary and are classified `mocked`; only a reviewer's own opt-in live run can
produce `live-provider` evidence. **Deployment evidence is absent from this local
verification.** The console does not establish multi-host,
cloud, authentication, availability or production deployment readiness. The raw
MCP server and low-level clients are integration primitives; application-owned
authorization is enforced by the authorized consumer paths, not an authenticated
server perimeter. Do not expose these reviewer services to untrusted networks.

Pinned ADK internals emit experimental/deprecation warnings; they remain visible.
Secondary caption contrast depends on the active Streamlit/browser theme and is
a non-blocking presentation observation; no custom CSS or contrast compliance
claim is introduced. See the [Story 10 audit](docs/stories/STORY-10-integrated-verification-release-evidence.md)
for exact verification, limitations and the Definition of Done assessment, and
the [traceability matrix](docs/TRACEABILITY.md) for all 33 requirements.

## Verified Streamlit Cloud Deployment

The reviewer-facing MCP Enterprise Infrastructure Console is deployed at https://dm-aiep-module-08.streamlit.app.

A fresh Streamlit Cloud reboot and Manager review verified the production demonstration path:

- 3 MCP capabilities discovered through the deployed integration path.
- 3 interoperable workflow stages completed: OpenAI SDK -> Google ADK -> OpenAI SDK.
- 0 model calls in the deterministic reviewer demonstration.
- The allowed customer read completed through the MCP capability boundary.
- The policy capability remained denied before unauthorized remote execution.
- Streamable HTTP, validated context exchange, and the final enterprise decision were demonstrated.
- Streamlit Cloud installed the Module 8 environment from module-08/uv.lock using uv-sync.

### Deployment operational lesson

Google ADK 2.10.0 can perform a Google mTLS/client-certificate credential probe during MCP discovery. In this credential-free loopback MCP deployment, that unnecessary probe could fall through to Google metadata credential discovery and consume the bounded discovery window before the intended MCP connection.

The accepted deployment configuration sets GOOGLE_API_USE_CLIENT_CERTIFICATE=false. This disables the unnecessary client-certificate probe, removes the ambient-credential dependency, and allows the intended bounded MCP discovery path to complete. This value is deployment configuration, not secret credential material. Increasing the discovery timeout is not the accepted repair.

The deployed Streamlit console remains a reviewer-facing presentation and execution layer over the production architecture; it does not fabricate success or replace the authoritative application, MCP, authorization, or workflow logic.
