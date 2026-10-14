# Module 9: Multimodal & Voice AI Systems

Standalone module that will deliver a **voice-enabled AI assistant** and a **multimodal AI
platform**: vision, audio, and document understanding; cross-modal reasoning; speech-to-text and
text-to-speech; real-time conversations and voice orchestration; and genuine WebSocket streaming
with measured latency. Streamlit will be the reviewer-facing UI. Business logic lives outside it.

## Current status

**Story 9.1 (Architecture & Contracts) is complete. It is design only.** No multimodal, voice,
streaming, provider, or UI capability is implemented yet. Story 9.1 evidence is
`design_documentation` and proves design intent only. See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## Documentation

| Document | Contents |
|---|---|
| [AUTHORITATIVE_SOURCE.md](docs/AUTHORITATIVE_SOURCE.md) | Verbatim source requirements |
| [REQUIREMENTS.md](docs/REQUIREMENTS.md) | Source-derived and additive requirements |
| [TRACEABILITY.md](docs/TRACEABILITY.md) | Requirement to story and evidence mapping |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, trust boundaries, flows (Mermaid) |
| [adr/](docs/adr/) | ADR-009-001 to ADR-009-009 |
| [CONTRACTS.md](docs/CONTRACTS.md) | Modality, session, provider, streaming, evidence contracts |
| [SECURITY_THREAT_MODEL.md](docs/SECURITY_THREAT_MODEL.md) | Threats and 26 security invariants |
| [STORIES.md](docs/STORIES.md) | Stories 9.1 to 9.10 |
| [DEFINITION_OF_DONE.md](docs/DEFINITION_OF_DONE.md) | Module completion criteria and quality gates |
| [EVIDENCE_POLICY.md](docs/EVIDENCE_POLICY.md) | Evidence classes; deterministic vs live |
| [governance/module-09-governance.json](docs/governance/module-09-governance.json) | Machine-readable governance |

## Quality gates

From `module-09/`, fail-fast:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv run python -m compileall -q src tests
```
