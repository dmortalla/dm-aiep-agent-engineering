# Module 8 - Architecture

## Status

APPROVED AND FROZEN - Human-approved architecture baseline, 2026-10-12.

## Purpose

Module 8 implements a production-grade, standalone MCP-powered enterprise AI integration system demonstrating modern AI infrastructure and interoperability.

The architecture genuinely exercises the MCP SDK, OpenAI SDK, and Google ADK while preserving MCP as the vendor-neutral enterprise capability boundary.

## Architecture Invariants

1. The authoritative Module 8 source and all 33 frozen requirements remain controlling.
2. Module 8 remains standalone and imports no implementation from another module.
3. MCP is a genuine protocol boundary, not a cosmetic Python abstraction.
4. OpenAI and Google ADK integrations consume shared enterprise capabilities without either framework owning the enterprise integration plane.
5. Capability discovery never implies execution authorization.
6. Application-owned policy controls execution authority.
7. External, model, agent, tool, API, database, MCP, and retrieved output is untrusted until validated where applicable.
8. Normal deterministic tests and reviewer demonstrations require no paid model execution.
9. Live-provider evidence remains explicitly distinct from deterministic and local-integration evidence.
10. External calls, retries, loops, latency, resources, and monetary exposure are bounded where applicable.
11. Streamlit contains no authoritative business logic.
12. Material capabilities must produce reviewer-visible working results and appropriate execution evidence.
13. Recruiters and reviewers are expected users of the completed system.
14. The unified presentation layer must expose real underlying system results rather than merely declare, simulate, or visually imply functionality.
15. Evidence and implementation claims must be accurately classified and supported.

## System Topology

`mermaid
flowchart TD
    UI[Streamlit Infrastructure Console]
    APP[Application Controller]
    OAI[OpenAI SDK Client]
    ADK[Google ADK Agent]
    MCPCLIENT[MCP Client Boundary]
    SERVER[Enterprise Integration MCP Server]
    DB[(Enterprise Database)]
    API[Enterprise API]
    INTERNAL[Internal System]
    POLICY[Validation and Capability Policy]
    EVIDENCE[Structured Execution Evidence]

    UI --> APP
    APP --> OAI
    APP --> ADK
    OAI --> MCPCLIENT
    ADK --> MCPCLIENT
    MCPCLIENT -->|Streamable HTTP| SERVER
    SERVER --> POLICY
    POLICY --> DB
    POLICY --> API
    POLICY --> INTERNAL
    DB --> EVIDENCE
    API --> EVIDENCE
    INTERNAL --> EVIDENCE
    POLICY --> EVIDENCE
    EVIDENCE --> APP
    APP --> UI
`",
            ",
            

The official MCP SDK provides the enterprise MCP server and genuine MCP client/server interaction.

The server exposes bounded enterprise capabilities representing database access, API orchestration, and internal-system integration.

MCP capability discovery, schema exchange, context exchange, transport, invocation, validation, and execution evidence are observable system behaviors.

Streamable HTTP is the primary reviewer-visible MCP transport. Deterministic in-process mechanisms may be used where appropriate for isolated tests but do not replace the genuine transport demonstration.

## OpenAI Integration

The OpenAI SDK has a genuine MCP-consuming role. Its integration must discover and exercise the shared MCP enterprise capability plane through supported SDK mechanisms.

Normal deterministic verification must not require a paid OpenAI model call. Any optional live-provider execution is separately authorized and evidence-classified.

## Google ADK Integration

Google ADK has a genuine MCP-consuming role and connects agents to the same enterprise MCP capability plane.

The ADK path must demonstrate real framework integration without duplicating enterprise capability implementations.

## Agent Interoperability and Emerging Standards

The primary interoperability demonstration is heterogeneous agent ecosystems consuming the same vendor-neutral MCP enterprise capabilities.

A bounded Agent2Agent interoperability demonstration may be included to show the complementary distinction between agent-to-tool interoperability through MCP and agent-to-agent interoperability through A2A.

A2A remains subordinate to the Module 8 MCP objective and must not create unnecessary infrastructure.

## Enterprise Integration Boundaries

### Database

A local enterprise-style database provides genuine database connectivity behind an application-owned repository or service boundary. SQLite is the default smallest sufficient implementation unless implementation evidence demonstrates a reason to change it.

### API

A deterministic local API integration provides genuine request orchestration and structured response handling without requiring an external paid service.

### Internal System

A bounded local enterprise-service simulation represents an internal system and exposes genuine callable behavior rather than static fixture text.

These three integrations remain independently observable while participating in an end-to-end interoperable workflow.

## Discovery and Authorization

The execution sequence is:

discovered -> schema validated -> policy evaluated -> authorized or denied -> invoked -> output validated -> evidence recorded

A discovered MCP capability cannot grant itself authority. Model or agent output cannot bypass application-owned policy.

## Unified Reviewer, Demonstration, and Evidence Layer

Streamlit is the unified reviewer, demonstration, and evidence presentation layer.

It must be self-explanatory and provide concise guidance describing what each demonstration does, how to run it, what result to expect, and what the result proves.

Streamlit invokes application-layer interfaces and presents their structured results. It does not implement authoritative enterprise, authorization, MCP, agent, or business logic.

The reviewer experience must expose at minimum:

- architecture and guided usage;
- discovered MCP capabilities and relevant schemas;
- genuine MCP transport and invocation evidence;
- database execution results and appropriate returned records;
- API orchestration results and sanitized request/response evidence;
- internal-system execution and policy/result evidence;
- OpenAI SDK use of the shared MCP capability plane;
- Google ADK use of the same MCP capability plane;
- an end-to-end interoperable enterprise workflow;
- a runnable MCP-versus-traditional-tool-calling comparison;
- authorization allow/deny evidence where relevant;
- validation and failure-path evidence where appropriate;
- evidence classification for displayed results.

## Reviewer-Visible Working-Results Invariant

A material capability is not complete merely because architecture, source code, documentation, or automated tests declare that it exists.

Every material Module 8 capability must produce demonstrable working results and appropriate execution evidence for expected users, including recruiters and reviewers.

The unified UI must expose those real results from the authoritative underlying implementation. It must never manufacture success states or substitute presentation logic for system behavior.

Automated tests remain mandatory but complement rather than replace reviewer-visible functional evidence.

This invariant must propagate into ADRs, traceability, implementation stories, acceptance tests, Definition of Done, and release evidence.

## Evidence Model

Evidence is classified as appropriate into deterministic, mocked, adapter, local-integration, live-provider, and deployment evidence.

The UI and documentation must not imply a stronger evidence class than was actually demonstrated.

Structured evidence may include capability name, client/framework, transport, discovery state, authorization decision, invocation status, validation status, sanitized result, latency, and evidence classification.

## Security Boundaries

Untrusted inputs and outputs are validated at architectural boundaries.

Credentials and secrets are never exposed through reviewer evidence.

Capability discovery is separated from authorization.

The system follows least privilege and prevents agent, model, MCP, or tool output from self-authorizing privileged behavior.

Expected denial and malformed-output paths are tested.

## Cost and Reliability

The normal reviewer path is deterministic and requires zero paid model spend.

External operations are bounded. Optional live-provider execution is isolated, explicitly classified, and must not be required for normal tests or reviewer demonstrations.

## Architecture Exclusions

The approved baseline does not require Kubernetes, cloud infrastructure, LangGraph, Redis, a vector database, or a custom JavaScript frontend.

Such technologies may not be added merely for perceived production sophistication. Any later addition requires demonstrated architectural need and applicable human approval.

## Architecture Freeze

This architecture was explicitly human-approved on 2026-10-12 after requirements review and current architecture research.

Material architecture changes require explicit human review and approval before implementation relies on them.

## Additive Extension - Opt-In Live Provider / BYOK Mode (Story 11, post-release)

This section records a post-release additive extension. It does not rewrite the frozen
baseline above, which remains controlling. Invariants 8, 9, 10 and 12 already permitted
optional live-provider execution that is isolated, explicitly opt-in, bounded, accurately
classified and not required for tests or reviewer demonstrations; this extension
implements exactly that. No requirement changed.

### Modes

- **Deterministic Demo** remains the default reviewer path, unchanged: no key, zero model
  calls, local-integration evidence.
- **Live Provider Demo (opt-in)** runs the same OpenAI SDK -> Google ADK -> OpenAI SDK
  workflow over the same loopback MCP plane. Stage 1 may be driven by a genuine OpenAI
  model through the OpenAI Agents SDK; stage 2 may be driven by a genuine Gemini model
  through Google ADK. Stage 3, the enterprise policy decision, never uses a model.

### Authority boundary

For each live stage the application:

1. discovers capabilities over MCP (availability evidence only);
2. authorizes exactly one capability for the application-owned role with
   `CapabilityPolicy` before the model sees anything;
3. exposes only that capability to the model (SDK tool filter);
4. gates every model-proposed call: policy is re-checked, the name and arguments must
   equal the application-bound values, and only one call is permitted;
5. validates the MCP result strictly before use.

Model text is bounded, displayed as plain untrusted narrative, and never feeds identity,
role, capability, arguments or the policy decision. Violations stop the stage without
running the unauthorized MCP call.

### Credential lifecycle and consent

Credentials are ephemeral, user-supplied capability material, never consent or
authority. They enter through masked Streamlit inputs inside a form, are held in a
redacting wrapper, passed directly to a per-run provider client (`AsyncOpenAI` or the
ADK `Gemini` client with `vertexai=False`), and overwritten in session state as soon as
the run ends. Environment keys and ADC are never used for model calls; OpenAI Agents SDK
tracing export is disabled. Log records created during a run are scrubbed of the run's
keys. Consent requires selecting the mode, enabling a provider, both acknowledgements
and an explicit run action; the backend enforces `ProviderPolicy` independently of the UI.

### Bounds

At most 2 model calls per selected provider, 600 output tokens per call, one MCP tool
call per stage, no SDK or HTTP retries, 50s per stage, 120s per run and one live run
per process. These bound calls, tokens and time; they are not a billing guarantee.

### Evidence

`live-provider` is produced only when the genuine provider boundary completed within
bounds and the authorized MCP result passed validation. Injected test doubles are
classified `mocked` even through the default path; failures produce no success evidence;
unselected or model-free stages remain `local-integration`.

Google ADK's MCP session manager may still probe ambient Google credentials for MCP
client-certificate (mTLS) transport configuration unless
`GOOGLE_API_USE_CLIENT_CERTIFICATE=false`, as recorded for the deployment. That probe
configures loopback transport only and never selects a credential for model execution.

The reviewer-visible working-results invariant applies unchanged: live results are
rendered only from actual backend execution and are never fabricated.
