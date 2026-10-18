# Module 9 Requirements

## Status

Story 9.1 baseline. Requirements are traced to stories in [TRACEABILITY.md](TRACEABILITY.md).
The machine-readable copy is [governance/module-09-governance.json](governance/module-09-governance.json).

Story 9.1 implements no capability. Story 9.2 partially implements ENG-001 with deterministic,
no-key fixture playback, which performs no inference and satisfies no SRC requirement. Story 9.3
partially implements SRC-002, SRC-004, and ENG-006 with validated ingestion and genuine local image
analysis and document extraction, with no model inference (see [UNDERSTANDING.md](UNDERSTANDING.md)).
Story 9.4 partially implements SRC-003, SRC-006, SRC-007, and ENG-006 with validated local PCM WAV
processing and speech-to-text and text-to-speech pipelines whose deterministic adapters are fixture
playback (not speech recognition) and tone generation (not speech synthesis) (see
[AUDIO_SPEECH.md](AUDIO_SPEECH.md)). Story 9.5 partially implements SRC-005, SRC-015, and ENG-006 with
a cross-modal workflow whose default reasoner is rule-based deterministic reasoning over a closed
vocabulary, which is not model inference (see [CROSS_MODAL.md](CROSS_MODAL.md)). Story 9.6 partially
implements SRC-008, SRC-009, SRC-013, SRC-014, SRC-017, ENG-006, and ENG-007 with synchronous
voice-assistant orchestration and bounded multi-turn conversation state; its default adapters are
fixture playback (not speech recognition), rule-based reasoning (not model inference), and tone
generation (not speech synthesis), and nothing is streamed (see
[VOICE_ASSISTANT.md](VOICE_ASSISTANT.md)). Story 9.7 implements SRC-011 with a genuine WebSocket
gateway exercised over a loopback socket, and partially implements SRC-008, SRC-010, SRC-012,
SRC-016, ENG-006, ENG-007, and ENG-008 with incremental streaming of rule-based reply fragments
(not model tokens), measured stage and first-response latency, and transport bounds (see
[STREAMING.md](STREAMING.md)). SRC-011 and ENG-002 are implemented. ENG-002's explicit opt-in, secure ephemeral BYOK contract is
supported by deterministic security tests and accepted real-provider execution. Story 9.8 adds
accepted live vision, STT, TTS, model reasoning, provider streaming, and one live voice turn.
Source statuses remain partial where required reviewer demonstrations or final acceptance remain;
SRC-006 additionally lacks genuine partial transcripts. SRC-012 has measured provider latency,
not a production SLO. SRC-018 is partial because the platform core exists, but UI and production
acceptance remain. Other designed requirements remain designed. Stories 9.9 and 9.10 are not
started; Module 9 is incomplete. See [LIVE_PROVIDERS.md](LIVE_PROVIDERS.md).

## Source-derived requirements

Derived from [AUTHORITATIVE_SOURCE.md](AUTHORITATIVE_SOURCE.md). 17 source groups, 18 IDs.

| ID | Group | Requirement |
|---|---|---|
| SRC-001 | 1 | Engineer a multimodal AI application end to end (objective). |
| SRC-002 | 2 | Use vision models to understand image input. |
| SRC-003 | 3 | Process audio input (validation, decoding bounds, duration). |
| SRC-004 | 4 | Understand document input and produce structured understanding. |
| SRC-005 | 5 | Reason across processed modalities in a single reasoning context. |
| SRC-006 | 6 | Convert speech to text (STT), with partial and final transcripts. |
| SRC-007 | 7 | Convert text to speech (TTS) and deliver playable audio. |
| SRC-008 | 8 | Support real-time, multi-turn conversations with session state. |
| SRC-009 | 9 | Orchestrate voice turns: audio -> STT -> reasoning -> TTS. |
| SRC-010 | 10 | Stream responses incrementally rather than only as a final block. |
| SRC-011 | 11 | Use a genuine WebSocket boundary for real-time streaming. |
| SRC-012 | 12 | Build low-latency pipelines with measured stage latency. |
| SRC-013 | 13 | Provide a voice interaction system a user can actually talk to. |
| SRC-014 | 14 | Lab: build a voice-enabled assistant. |
| SRC-015 | 15 | Lab: create a multimodal AI workflow. |
| SRC-016 | 16 | Lab: implement a real-time streaming system. |
| SRC-017 | 17 | Deliverable: voice-enabled AI assistant. |
| SRC-018 | 17 | Deliverable: multimodal AI platform. |

## Additive engineering requirements

These come from the human-approved Story 9.1 system target and the repository SOP. They extend
the source and never replace it.

| ID | Requirement |
|---|---|
| ENG-001 | Deterministic reviewer mode runs every essential workflow with no external API key. |
| ENG-002 | Live-provider mode is explicit opt-in; users may supply supported credentials securely and ephemerally. |
| ENG-003 | Streamlit is the unified reviewer-facing presentation layer. |
| ENG-004 | Authoritative business/application logic lives outside Streamlit. |
| ENG-005 | Reviewers see actual working results and classified evidence in the UI. |
| ENG-006 | Untrusted multimodal and model-derived content never grants authority. |
| ENG-007 | Requests, inputs, outputs, timeouts, retries, histories, and provider activity are bounded. |
| ENG-008 | Structured observability with stage latency metrics and no secret leakage. |
| ENG-009 | Evidence is classified accurately; deterministic and live evidence stay distinct. |
| ENG-010 | Module 9 is standalone and does not depend on other modules. |
| ENG-011 | Python 3.12, typed public interfaces, Google-style docstrings, intentional errors, fail-fast gates. |
| ENG-012 | The UI includes concise built-in guidance on how to use and test each workflow and what results show. |
