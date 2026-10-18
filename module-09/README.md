# Module 9: Multimodal & Voice AI Systems

Standalone module that will deliver a **voice-enabled AI assistant** and a **multimodal AI
platform**: vision, audio, and document understanding; cross-modal reasoning; speech-to-text and
text-to-speech; real-time conversations and voice orchestration; and genuine WebSocket streaming
with measured latency. Streamlit is the local reviewer-facing UI. Business logic lives outside it.

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

**Story 9.6 (Voice-Enabled AI Assistant) is complete.** It adds the application-level voice
assistant: bounded, multi-turn conversations whose turns run validated audio through local audio
processing, speech-to-text, a bounded conversational context, reasoning, text-to-speech, and
generated-audio validation, then commit to session state atomically. Later turns can recall what
earlier turns established. The default adapters are fixture playback, which is not speech
recognition; rule-based conversation reasoning over two fixed phrasings, which is not model
inference; and tone-sequence audio, which is not speech synthesis. Turns are synchronous; nothing
is streamed. Story 9.6 evidence is `automated_test`. See
[docs/VOICE_ASSISTANT.md](docs/VOICE_ASSISTANT.md).

**Story 9.7 (Real-Time WebSocket Streaming) is complete.** It adds a genuine WebSocket boundary
(a Starlette ASGI gateway hosted by Uvicorn on loopback) and a typed streaming protocol for voice
turns. Each turn streams `turn_accepted`, `transcript_final`, one `response_delta` per reply
fragment while reasoning is still running, `response_complete`, `audio_ready`, `turn_complete`,
and latency metrics including time to first response. Fragments are whole rule-based reply acts,
not model tokens, and are produced before the reply exists rather than split from a finished
reply. Disconnects and timeouts cancel the running turn without committing it. Story 9.7 itself includes no
authentication, live provider, or reviewer UI. Story 9.8 adds live providers below. Story 9.7 evidence is `automated_test`,
including loopback socket-level WebSocket tests. See [docs/STREAMING.md](docs/STREAMING.md).

**Story 9.8 (Secure Opt-In Live Providers) is complete, with accepted `live_integration` evidence.**
OpenAI adapters for vision, speech-to-text, text-to-speech, and streamed reasoning sit behind the
unchanged ports, reachable only from an explicit, opted-in live session with an ephemeral key.
Deterministic tests exercise the real SDK over an in-process fake API (`automated_test`).
Separately authorized real-provider verification established vision, speech-to-text, text-to-speech,
model reasoning, and provider streaming (`live_integration`). See [docs/LIVE_PROVIDERS.md](docs/LIVE_PROVIDERS.md).

Semantic document understanding remains unestablished. Story 9.9 provides the local reviewer UI.
Module 9 is incomplete: Stories 9.1-9.9 are accepted; Story 9.10 local engineering acceptance is ready for independent review. Streamlit deployment, deployment
verification, final production/security acceptance, and LinkedIn publication have not occurred. See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## Local production acceptance and release boundary

Story 9.10 is complete for local engineering acceptance and ready for independent review.
Module 9 remains incomplete. Publication/push, Streamlit deployment, deployed verification,
deployed deterministic/demo and separately authorized BYOK/live verification, and LinkedIn
publication remain pending human-controlled release closeout.

See [docs/RELEASE_READINESS.md](docs/RELEASE_READINESS.md) for all 30 requirement decisions,
local security/functional evidence, regression repairs and residual risks. Five source requirements
remain partial: SRC-003, SRC-004, SRC-006, SRC-012 and SRC-013. No production SLO, live UI,
public deployment or microphone hardware verification is claimed.

## Launch the reviewer application

From `module-09/`, using the module-owned environment:

```bash
uv sync --extra dev
uv run streamlit run streamlit_app.py
```

Start with **Multimodal workflow -> Run selected workflow** for a four-modality sample.
Try **Voice assistant** with `voice-remember`, then `voice-recall`; listen to the generated tone
audio. **Document & vision** shows local measurements/extracted text. **WebSocket streaming**
runs two turns through a real short-lived loopback gateway and displays events on receipt;
select disconnect-after-first-fragment to exercise cancellation. No key or provider is needed.
These are deterministic fixtures, local processing, and rule-based reasoning, not model inference,
speech recognition, or speech synthesis. Local/demo latency is not a production SLO.

Optional **Live / BYOK** requires a masked credential, cost acknowledgement and explicit submit
for each operation. Keys are removed from widget state before execution and never cached or saved.
Live failures do not fall back. Live voice uses one fresh session per operation; deterministic
voice preserves bounded multi-turn history. The streaming reviewer demonstration stays deterministic.
See [docs/REVIEWER_UI.md](docs/REVIEWER_UI.md) for controls, evidence and limitations.

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
| [VOICE_ASSISTANT.md](docs/VOICE_ASSISTANT.md) | Story 9.6 voice orchestration, conversation state and bounds, transaction semantics, conversation rules, records |
| [STREAMING.md](docs/STREAMING.md) | Story 9.7 WebSocket gateway, streaming protocol, incremental streaming evidence, bounds, cancellation, latency metrics |
| [LIVE_PROVIDERS.md](docs/LIVE_PROVIDERS.md) | Story 9.8 OpenAI live adapters, mode selection, ephemeral BYOK, redaction, failures, cost controls, evidence ladder, live acceptance |
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

Run the deterministic WebSocket gateway locally on `ws://127.0.0.1:8765/ws/voice`:

```bash
uv run python -m multimodal_voice_platform.interface
```
