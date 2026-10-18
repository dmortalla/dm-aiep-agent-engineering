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

## Provenance

Developed from Techademy AI Engineering program requirements, with independent implementation, engineering enhancements, security hardening, testing, and deployment.

The educational requirements establish the source objectives and constraints; the architecture, implementation, production-grade enhancements, verification, deployment, and supporting engineering evidence in this repository are independently developed.
