# Module 9 Traceability

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) maps to the stories that will deliver it
and to the evidence that must exist before it counts as satisfied. The machine-readable copy is
[governance/module-09-governance.json](governance/module-09-governance.json). Automated tests
keep the two in sync.

**Current status: 13 source requirements and all 12 engineering requirements are implemented
locally. SRC-003, SRC-004, SRC-006, SRC-012 and SRC-013 remain partially implemented.** The final
individual matrix, evidence and residual limitations are in [RELEASE_READINESS.md](RELEASE_READINESS.md).
Deployment/publication are pending; Module 9 is incomplete.

Earlier story contributions (historical evidence scopes, unchanged): Story 9.1 contributes architecture and contract design
only, which is `design_documentation` evidence. Story 9.2 contributes the deterministic foundation
for ENG-001 (`automated_test` evidence). Deterministic fixture playback is not evidence for any SRC
requirement. Story 9.3 contributes `automated_test` evidence of validated ingestion, local image
analysis, and local document extraction and structural analysis, with no model inference (see
[UNDERSTANDING.md](UNDERSTANDING.md)). Story 9.4 contributes `automated_test` evidence of validated
local audio processing and of the speech-to-text and text-to-speech port pipelines; its default
STT adapter is fixture playback, which is not speech recognition, and its TTS adapter generates
tone sequences, which is not speech synthesis (see [AUDIO_SPEECH.md](AUDIO_SPEECH.md)). Story 9.5
contributes `automated_test` evidence of a cross-modal workflow that relates observations from two
to four modalities in one bounded context; its default reasoner is rule-based deterministic
reasoning over a closed vocabulary, which is not model inference (see
[CROSS_MODAL.md](CROSS_MODAL.md)). Story 9.6 contributes `automated_test` evidence of synchronous
voice-assistant orchestration (audio -> STT -> bounded conversational context -> reasoning -> TTS ->
validated output audio -> atomic state commit) and of bounded multi-turn state that later turns
demonstrably depend on; its default adapters are fixture playback (not speech recognition),
rule-based reasoning (not model inference), and tone generation (not speech synthesis), and nothing
is streamed (see [VOICE_ASSISTANT.md](VOICE_ASSISTANT.md)). Story 9.7 contributes `automated_test`
evidence of a genuine WebSocket gateway (in-process ASGI tests and loopback socket-level tests with
an independent client) and of incremental streaming: each reply fragment is produced, validated, and
sent before the next exists. Fragments are whole rule-based reply acts, not model tokens; latency is
measured locally and is not a production claim (see [STREAMING.md](STREAMING.md)). Story 9.8 contributes deterministic `automated_test` evidence and separately authorized,
accepted `live_integration` evidence for vision, STT, TTS, model reasoning, provider streaming,
and one live voice turn over loopback WebSocket. See [LIVE_PROVIDERS.md](LIVE_PROVIDERS.md).
Planned reviewer demonstrations and production acceptance remain incomplete.

## Source-derived requirements

| Requirement | Delivering stories | Contract / architecture anchor | Required evidence before "satisfied" |
|---|---|---|---|
| SRC-001 Engineer multimodal AI applications (implemented locally) | 9.1, 9.5, 9.9, 9.10 | Whole architecture | Integrated platform acceptance, reviewer-visible |
| SRC-002 Vision models (implemented locally) | 9.3, 9.8 | `VisionPort`, `Modality.IMAGE` | automated_test + deterministic_demo; live_integration for live vision |
| SRC-003 Audio processing (partially-implemented locally) | 9.4 | `Modality.AUDIO`, audio limits | automated_test + deterministic_demo |
| SRC-004 Document understanding (partially-implemented locally) | 9.3 | `DocumentUnderstandingPort`, `Modality.DOCUMENT` | automated_test + deterministic_demo |
| SRC-005 Cross-modal reasoning (implemented locally) | 9.5, 9.8 | `ReasoningPort`, `ReasoningRequest.parts`, `contracts/reasoning.py` | automated_test + deterministic_demo |
| SRC-006 Speech-to-text (partially-implemented locally) | 9.4, 9.8 | `SpeechToTextPort`, `transcript_partial/final` | automated_test + deterministic_demo; live_integration for live STT |
| SRC-007 Text-to-speech (implemented locally) | 9.4, 9.8 | `TextToSpeechPort`, `audio_ready` | automated_test + deterministic_demo; live_integration for live TTS |
| SRC-008 Real-time conversations (implemented locally) | 9.6, 9.7, 9.8 | `SessionConfig`, `ConversationTurn`, stream events | WebSocket multi-turn acceptance test |
| SRC-009 Voice orchestration (implemented locally) | 9.6, 9.8 | `VoiceAssistant` (core layer) | automated_test of STT -> reasoning -> TTS turn |
| SRC-010 Streaming responses (implemented locally) | 9.7, 9.8 | `response_delta`, `response_complete` | Streamed delta acceptance test |
| SRC-011 WebSockets (implemented locally) | 9.7 | WebSocket gateway (application interface layer) | Genuine WebSocket client/server test |
| SRC-012 Low-latency pipelines (partially-implemented locally) | 9.7, 9.10 | `LatencyStage`, `metric` event | Measured stage latencies, reviewer-visible |
| SRC-013 Voice interaction systems (partially-implemented locally) | 9.6, 9.9 | Voice controls in presentation layer | deterministic_demo in Streamlit |
| SRC-014 Lab: build voice-enabled assistant (implemented locally) | 9.6, 9.9 | `VoiceAssistant` workflow | deterministic_demo in Streamlit |
| SRC-015 Lab: create multimodal AI workflow (implemented locally) | 9.5, 9.9 | `CrossModalWorkflow` | deterministic_demo in Streamlit |
| SRC-016 Lab: implement real-time streaming system (implemented locally) | 9.7, 9.9 | WebSocket streaming workflow | deterministic_demo with visible stream events |
| SRC-017 Deliverable: voice-enabled AI assistant (implemented locally) | 9.6, 9.9, 9.10 | Voice assistant | Production acceptance evidence |
| SRC-018 Deliverable: multimodal AI platform (implemented locally) | 9.5, 9.9, 9.10 | Multimodal platform | Production acceptance evidence |

## Additive engineering requirements

| Requirement | Delivering stories | Anchor |
|---|---|---|
| ENG-001 Deterministic no-key reviewer mode (implemented locally) | 9.2, 9.9 | `ExecutionMode.DETERMINISTIC` default, `adapters.deterministic` |
| ENG-002 Explicit opt-in ephemeral BYOK live mode (implemented locally) | 9.8 | `SessionConfig.live_opt_in`, `LiveCredential` |
| ENG-003 Streamlit unified presentation layer (implemented locally) | 9.9 | ADR-009-002 |
| ENG-004 Application logic outside Streamlit (implemented locally) | 9.1, 9.2, 9.9 | ADR-009-002, `multimodal_voice_platform` package |
| ENG-005 Reviewer-visible working results (implemented locally) | 9.9, 9.10 | ADR-009-009 |
| ENG-006 Untrusted content never grants authority (implemented locally) | 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.10 | ADR-009-007, `TrustLevel` |
| ENG-007 Bounded cost and latency exposure (implemented locally) | 9.1, 9.6, 9.7, 9.8, 9.10 | ADR-009-008, `ResourceBudget` |
| ENG-008 Structured observability without secrets (implemented locally) | 9.7, 9.10 | `metric` event, `SafeError` |
| ENG-009 Accurate evidence classification (implemented locally) | 9.1, 9.9, 9.10 | `EvidenceClass`, `EvidenceRecord` |
| ENG-010 Standalone Module 9 (implemented locally) | 9.1, 9.10 | ADR-009-001, isolation test |
| ENG-011 Python engineering standard and fail-fast gates (implemented locally) | 9.1, 9.10 | `pyproject.toml`, quality gates |
| ENG-012 Built-in reviewer guidance in the UI (implemented locally) | 9.9 | ADR-009-009 |

## Coverage summary

- All 17 source groups, 18 source IDs and 12 engineering IDs remain traced.
- 13 SRC requirements and 12 ENG requirements are implemented for the documented local scope.
- SRC-003/004/006/012/013 remain partial; their criteria are preserved, not waived.
- Story 9.10 local production/security acceptance is `automated_test`; prior accepted Story 9.8
  `live_integration` remains separate. See the final [matrix and evidence](RELEASE_READINESS.md).
- SRC-017/018 local deliverables are demonstrable; deployment/publication remain pending.
- Module 9 remains incomplete until the separate human-controlled release-closeout gates pass.
