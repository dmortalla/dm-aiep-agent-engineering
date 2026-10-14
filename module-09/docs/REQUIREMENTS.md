# Module 9 Requirements

## Status

Story 9.1 baseline. Requirements are traced to stories in [TRACEABILITY.md](TRACEABILITY.md).
The machine-readable copy is [governance/module-09-governance.json](governance/module-09-governance.json).

Implementation status for every source requirement below is **designed only**. Story 9.1
implements no capability. Story 9.2 partially implements ENG-001 with deterministic, no-key
fixture playback, which performs no inference and satisfies no SRC requirement. Every other
requirement is designed only.

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
