# Agentic AI Engineering Program — Agent Engineering

![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)
![pytest](https://img.shields.io/badge/tests-pytest-brightgreen)
![Ruff](https://img.shields.io/badge/code%20quality-Ruff-brightgreen)
![Pydantic](https://img.shields.io/badge/validation-Pydantic-blueviolet)

![OpenAI](https://img.shields.io/badge/LLM-OpenAI-412991)
![Gemini](https://img.shields.io/badge/LLM-Gemini-4285F4)
![Google ADK](https://img.shields.io/badge/Agents-Google%20ADK-4285F4)
![MCP](https://img.shields.io/badge/Protocol-MCP-6C5CE7)

![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B)

![Techademy](https://img.shields.io/badge/Techademy-AI%20Engineering%20Program-informational)

Production-grade agent-engineering systems covering Modules 6.5–10 of the Techademy AI Engineering program.

This repository is standalone from the earlier program repository. Each module is independently source-faithful and isolated from the other modules while following a shared production-grade engineering standard.

## Engineering approach

The systems in this repository are built using an architecture-first, AI-assisted engineering workflow. Requirements and architecture are established before implementation, and material capabilities are validated through automated quality gates, adversarial review, security testing, independent acceptance, deployment verification, and human validation.

Engineering standards include:

- source-faithful requirements and explicit traceability from requirements through implementation and evidence;
- production-grade architecture with typed interfaces, intentional failure handling, reliability controls, and maintainable boundaries;
- security by design, including least-authority controls, untrusted-input boundaries, secrets protection, and prompt-injection defenses where applicable;
- fail-fast linting, automated tests, compilation checks, integration and acceptance testing, and bounded repair workflows;
- reviewer-visible evidence of working functionality rather than unsupported implementation claims;
- independently reviewable Git history, documentation, acceptance evidence, and release discipline;
- runnable Streamlit presentation layers that expose real system behavior while keeping authoritative business logic outside the UI; and
- verified deployment before a module is considered complete.

AI coding agents are used as engineering tools within this controlled process. Generated or agent-authored implementation is not accepted solely because it runs: it remains subject to the same architecture, security, testing, evidence, and human-acceptance requirements.

## Engineering Roadmap

| Module | Topic | Status |
| --- | --- | --- |
| 6.5 | Harness Engineering | In Progress (engineering, live-provider evidence and secure BYOK accepted; main integration under release closeout; deployment pending) |
| 7 | Reliability, Safety and Observability | In Progress |
| 8 | MCP and Modern AI Infrastructure | ✅ Complete |
| 9 | Multimodal and Voice AI Systems | ✅ Complete |
| 10 | Deployment and Production AI Systems | In Progress |

Module development can proceed independently and out of numerical order. Consult each module's documentation for its authoritative implementation and acceptance state; completed modules also provide a deployed reviewer experience.

## Module 6.5 - Harness Engineering

Module 6.5 implements a harness-engineered agent runtime: an application that keeps end-to-end operational control and governance over an agent workflow from task decomposition through safe execution, state recovery, human oversight and cost governance. Model output is always treated as untrusted data; application-owned, typed policy retains every authority decision.

**Reviewer app (local):** run `streamlit run streamlit_app.py` from `module-06-5`. The default deterministic mode requests no API key and requires no paid inference; live provider mode is an explicit opt-in that accepts a temporary, session-only BYOK key.

### Architecture and control plane

A compiled LangGraph state graph owns the finite lifecycle (schedule → execute → complete or safe stop). Around it, separate application-owned services form the control plane: `planning.py` (decomposition, dependencies, priority scheduling), `context.py`/`memory.py` (prompt construction, token budgets, compression, sliding window, memory routing), `capabilities.py`/`permissions.py`/`execution.py` (discovery and selection kept strictly separate from authorization; per-attempt reauthorized, bounded tool execution), `providers.py`/`vendor_providers.py` (provider-neutral contracts with optional live-provider adapters), `persistence.py`/`recovery.py`/`effects.py` (SQLite checkpoints, crash recovery, committed-effect tracking with no replay), the approval family (`approvals.py`, `approval_persistence.py`, `approval_lifecycle.py`), and `observability.py`/`telemetry_projections.py`/`cost_governance.py`/`latency.py` (structured events, anomaly advisory signals, token/cost accounting, latency cohorts against a frozen p95 SLO). Selection never confers authority: the capability registry returns metadata candidates only, and an independent authorizer decides.

### Implemented capabilities

- Deterministic task planning with dependency validation, priority execution, cycle rejection and bounded plan size.
- Context construction with explicit budgets, summarization compression, sliding-window strategy and memory routing.
- Capability registry, explicit permission scopes, blocklists, approval-required metadata and an application-level bounded tool executor (sandbox is application-level, not OS isolation).
- Bounded execution controls: exponential backoff, circuit breaker, graceful degradation, hard stops, workflow deadlines and an application-owned off-switch.
- Durable checkpointing, crash recovery, safe resume and idempotent re-entry without replaying committed effects.
- Confidence-thresholded human-approval gates with asynchronous suspension/resume, durable stores, exact-action bindings, override handling and audit trails.
- MCP SDK integration where discovery is inert until explicit trusted binding; denied and cancelled calls stay inert and unbound candidates never register.
- Structured observability with optional offline-boundary LangSmith/Langfuse projections, a strict disabled Helicone boundary, spend alerts, hard token budgets and latency SLO measurement.
- Golden-set evaluation and an exact-comparison regression harness with bounded guided CLI.
- Dual-mode provider operation: deterministic/no-key reviewer mode (the default) plus secure explicit opt-in BYOK/live mode with allowlisted providers and models (OpenAI `gpt-6-luna`, Anthropic `claude-haiku-5-5`), fixed application-owned bounds, and credentials that grant connectivity only, never authority. Server-side credentials may supplement BYOK but are disabled by default and must stay disabled on a public deployment unless a separate operator-spend control exists.
- A composed deterministic story board executing four disjoint governance segments — the core governed workflow, the MCP SDK transport, the durable approval lifecycle with its out-of-band consumption redline, and recovery after commit — without credentials or paid inference.

### Testing and evidence posture

1,996 automated tests (full module suite) plus Ruff and compileall pass in fail-fast order, independently reviewed on the accepted release. Tests actively cover security, authority, recovery, failure, budget, latency, off-switch and secret-handling paths, including zero-external-attempt guarantees in reviewer paths. Evidence classes stay separate: `deterministic` and `local-integration` (local SQLite, in-process MCP SDK transport) for the reviewer labs, whose providers and MCP handlers are deterministic local fixtures; `adapter` for the runtime and the genuine OpenAI/Anthropic SDK adapters (the runtime never classifies itself higher); `live_provider` only as an independently accepted, hash-pinned record of one bounded, human-authorized exercise per provider (OpenAI `gpt-6-luna`, Anthropic `claude-haiku-5-5`; one attempt, no retries, fixed token, byte, time and cost caps); and `deployment`, which is still pending and not verified.

### Boundaries and exact status

- No live OpenAI/Anthropic provider verification beyond the single bounded, independently accepted Story 13 exercise per provider (not an SLA, billing or deployment validation); no hosted LangSmith/Langfuse; no live Helicone routing; no live Mem0 service.
- Fixture monetary values are not provider prices; local latency cohorts are not production certification.
- No genuine production identity/authentication claim; approval identities are simulated fixtures.
- No provider-level production-readiness claim: provider adapters are verified at their accepted boundaries, and live-provider execution remains explicit opt-in with an approved credential source (a temporary session-only BYOK key, or trusted server-side/secret-store credentials that may supplement but never replace BYOK), provider/model allowlists, and bounded cost/latency; BYOK credentials grant connectivity only, are not persisted by the application (Streamlit may hold the widget value in server memory until its lifecycle clears it), and a session call is adapter-class evidence at most. One bounded live exercise per provider (gpt-6-luna, claude-haiku-5-5; one attempt, no retries) was independently accepted as live-provider evidence on 2026-10-27 (ENG-008, ADR 002); it does not validate deployment, an SLA, billing accuracy, or every provider scenario. The planned public deployment allows BYOK live mode with operator/server credentials disabled.
- State: Stories 1–11 implemented and independently accepted; the end-to-end story board (Story 12 Slice 1) accepted at commit `1666e99`; Story 12 Slice 2 module-wide release reconciliation (69/69 requirements, 6/6 labs, 5/5 deliverables, 9/9 technologies) closed and accepted (commit `d4d2fd0`); the corrective production-grade dual-mode contract (Story 13) has its live-evidence gate satisfied (2026-10-27), and the secure explicit opt-in BYOK/live mode is implemented and independently accepted; the accepted release is under main-integration closeout. Deployment verification (deployed deterministic and BYOK behavior) and final module closeout are separate gates; Module 6.5 is not yet complete.

See [Module 6.5](module-06-5/docs/RELEASE_READINESS.md) and [Traceability](module-06-5/docs/TRACEABILITY.md) for exact requirement-to-implementation evidence and the full release non-claims record.

---

## Module 9 - Multimodal & Voice AI Systems

Module 9 implements a production-grade reviewer-facing multimodal and voice AI platform spanning vision, documents, audio, cross-modal reasoning, voice orchestration, and genuine WebSocket streaming. Authoritative application logic remains outside the Streamlit presentation layer.

**Reviewer app:** https://dm-aiep-agent-engineering-module-09.streamlit.app

### Implemented capabilities

- Text, image, document, and audio workflows with bounded validated inputs and explicit provenance.
- Local image measurement and document extraction kept distinct from model-derived interpretation.
- Cross-modal reasoning over normalized observations with cited findings and untrusted-output boundaries.
- Voice orchestration through STT, bounded conversational state, reasoning, and TTS interfaces.
- Genuine loopback WebSocket streaming with incremental events, multi-turn interaction, cancellation, deadlines, and latency evidence.
- Deterministic no-key reviewer mode with zero provider spend.
- Explicit opt-in BYOK live mode with ephemeral credentials, bounded provider operations, and no silent fallback.
- Security controls for prompt-injection containment, malformed and oversized inputs, secret redaction, resource bounds, timeout/cancellation, and evidence integrity.

Production acceptance included **827 automated tests**, Ruff, compileall, integrated adversarial checks, and deployed reviewer verification. Deterministic multimodal, voice, browser-microphone, document/vision, WebSocket, cancellation, and opt-in live BYOK vision paths were exercised.

Five source requirements retain explicit partial status rather than being overstated: broader audio-format processing, semantic document understanding, genuine partial transcription, production latency/SLO evidence, and deployed live spoken interaction. The loopback WebSocket reviewer gateway is not represented as an authenticated TLS-protected public service.

Run locally:

```text
cd module-09
uv run streamlit run streamlit_app.py
```

See [Module 9](module-09/README.md) and [Release Readiness](module-09/docs/RELEASE_READINESS.md) for exact implementation evidence, requirement status, and residual boundaries.

---

## Module 8 - MCP & Modern AI Infrastructure

Module 8 implements a standalone enterprise MCP capability plane in which OpenAI Agents SDK and Google ADK consumers interoperate with shared, application-controlled MCP capabilities. Application policy - not model output - retains authority.

**Reviewer app:** https://dm-aiep-module-08.streamlit.app

### Implemented capabilities

- MCP server and Streamable HTTP client integration over application-owned capabilities.
- Shared capability discovery and invocation across OpenAI Agents SDK and Google ADK.
- Independent application authorization and capability-policy enforcement.
- Deterministic reviewer mode requiring no API key and making zero external model calls.
- Explicit opt-in BYOK live-provider mode with bounded calls, tool use, tokens, stage deadlines, and run lifetime.
- Strict separation of discovery, capability exposure, and per-call authorization.
- Typed workflow envelopes, identity correlation, bounded execution, safe failure paths, and accurate evidence classification.
- Streamlit reviewer console demonstrating MCP discovery and interoperable multi-SDK workflows.

Verified Streamlit Cloud deployment discovered **3 MCP capabilities** and completed **3 interoperable workflow stages: OpenAI SDK -> Google ADK -> OpenAI SDK, with zero model calls** in the deterministic reviewer path. The allowed customer read completed through the MCP capability boundary.

Deployment verification also established `GOOGLE_API_USE_CLIENT_CERTIFICATE=false` as the accepted credential-free configuration preventing an unnecessary Google client-certificate/ambient-credential probe during bounded MCP discovery.

The reviewer services are integration and demonstration surfaces; they are not represented as an authenticated multi-host public MCP service or as production availability/performance certification.

Run locally:

```text
cd module-08
uv run streamlit run src/mcp_enterprise_integration/console.py
```

See [Module 8](module-08/README.md) for implementation, security, evidence, deployment, and live-provider boundaries.

---
## Provenance

Developed from Techademy AI Engineering program requirements, with independent implementation, engineering enhancements, security hardening, testing, and deployment.

The educational requirements establish the source objectives and constraints; the architecture, implementation, production-grade enhancements, verification, deployment, and supporting engineering evidence in this repository are independently developed.
