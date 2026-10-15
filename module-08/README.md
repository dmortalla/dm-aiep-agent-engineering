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
loopback. SDK construction alone is not live-provider evidence. **Live-provider
and deployment evidence are absent.** The console does not establish multi-host,
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
