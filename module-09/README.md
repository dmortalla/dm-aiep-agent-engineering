# Module 9: Multimodal & Voice AI Systems

Standalone module that will deliver a **voice-enabled AI assistant** and a **multimodal AI
platform**: vision, audio, and document understanding; cross-modal reasoning; speech-to-text and
text-to-speech; real-time conversations and voice orchestration; and genuine WebSocket streaming
with measured latency. Streamlit will be the reviewer-facing UI. Business logic lives outside it.

## Current status

**Story 9.1 (Architecture & Contracts) is complete. It is design only.** Story 9.1 evidence is
`design_documentation` and proves design intent only.

**Story 9.2 (Deterministic Multimodal Foundation) is complete.** It adds committed text, image,
audio, and document fixtures and deterministic, no-key fixture-playback adapters for the vision,
document, and speech-to-text ports. They perform no inference and need no network, key, or spend.
Story 9.2 evidence is `automated_test`. See [docs/DETERMINISTIC_FOUNDATION.md](docs/DETERMINISTIC_FOUNDATION.md).

**Story 9.3 (Document + Vision Understanding) is complete.** It adds validated image and document
ingestion (magic bytes, UTF-8 checks, budgets) and genuine local processing: Pillow-based pixel
analysis of PNG, JPEG, and WebP images, and extraction and structural analysis of Markdown, plain
text, and PDF documents. There is no model inference, so this is not semantic understanding. Story
9.3 evidence is `automated_test`. See [docs/UNDERSTANDING.md](docs/UNDERSTANDING.md).

**Story 9.4 (Audio + Speech Pipeline) is complete.** It adds validated, bounded local audio
processing (strict PCM WAV parsing, decoding, and signal measurement with the standard library)
and speech-to-text and text-to-speech pipelines through the provider ports. In deterministic mode
the transcript is Story 9.2 fixture playback, which is not speech recognition, and the generated
audio is a deterministic tone sequence, which is not speech synthesis. There is no model
inference. Story 9.4 evidence is `automated_test`. See [docs/AUDIO_SPEECH.md](docs/AUDIO_SPEECH.md).

**Story 9.5 (Cross-Modal Reasoning Workflow) is complete.** It adds the application-level
multimodal workflow: inputs from two to four modalities are processed through the Story 9.3 and 9.4
paths, normalized into typed observations, combined into one bounded reasoning context, and related
through the `ReasoningPort`. The default reasoner is rule-based deterministic reasoning over a
closed vocabulary that judges claims from one modality against measurements from another, reports
conflicts without resolving them, and cites every statement and measurement it uses. It is not model
inference. Story 9.5 evidence is `automated_test`. See [docs/CROSS_MODAL.md](docs/CROSS_MODAL.md).

No model-based vision, semantic document, speech recognition, speech synthesis, model-based
reasoning, voice orchestration, streaming, live-provider, or UI capability is implemented yet. See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## Documentation

| Document | Contents |
|---|---|
| [AUTHORITATIVE_SOURCE.md](docs/AUTHORITATIVE_SOURCE.md) | Verbatim source requirements |
| [REQUIREMENTS.md](docs/REQUIREMENTS.md) | Source-derived and additive requirements |
| [TRACEABILITY.md](docs/TRACEABILITY.md) | Requirement to story and evidence mapping |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, trust boundaries, flows (Mermaid) |
| [adr/](docs/adr/) | ADR-009-001 to ADR-009-009 |
| [CONTRACTS.md](docs/CONTRACTS.md) | Modality, session, provider, streaming, evidence contracts |
| [DETERMINISTIC_FOUNDATION.md](docs/DETERMINISTIC_FOUNDATION.md) | Story 9.2 fixtures, deterministic adapters, run records |
| [UNDERSTANDING.md](docs/UNDERSTANDING.md) | Story 9.3 ingestion, local vision and document adapters, understanding records |
| [AUDIO_SPEECH.md](docs/AUDIO_SPEECH.md) | Story 9.4 audio processing, speech-to-text and text-to-speech pipelines, speech records |
| [CROSS_MODAL.md](docs/CROSS_MODAL.md) | Story 9.5 cross-modal workflow, observations, bounded context, deterministic reasoning rules, records |
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
