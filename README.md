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
| 6.5 | Harness Engineering | In Progress |
| 7 | Reliability, Safety and Observability | In Progress |
| 8 | MCP and Modern AI Infrastructure | ✅ Complete |
| 9 | Multimodal and Voice AI Systems | ✅ Complete |
| 10 | Deployment and Production AI Systems | In Progress |

Module development can proceed independently and out of numerical order. Consult each module's documentation for its authoritative implementation and acceptance state; completed modules also provide a deployed reviewer experience.

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
