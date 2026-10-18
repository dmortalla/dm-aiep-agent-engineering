# Module 9 Traceability

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) maps to the stories that will deliver it
and to the evidence that must exist before it counts as satisfied. The machine-readable copy is
[governance/module-09-governance.json](governance/module-09-governance.json). Automated tests
keep the two in sync.

**Current status: SRC-011 and ENG-002 are implemented. SRC-002 through SRC-010,
SRC-012 through SRC-018, ENG-001, ENG-006, ENG-007, and ENG-008 are partially implemented.
Every other row is designed.** Story 9.1 contributes architecture and contract design
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
| SRC-001 Engineer multimodal AI applications | 9.1, 9.5, 9.9, 9.10 | Whole architecture | Integrated platform acceptance, reviewer-visible |
| SRC-002 Vision models (partially implemented: 9.3 local analysis and 9.8 accepted live vision; reviewer demonstration remains) | 9.3, 9.8 | `VisionPort`, `Modality.IMAGE` | automated_test + deterministic_demo; live_integration for live vision |
| SRC-003 Audio processing (partially implemented: 9.4 PCM WAV decoding and measurement; MP3/WebM not decodable) | 9.4 | `Modality.AUDIO`, audio limits | automated_test + deterministic_demo |
| SRC-004 Document understanding (partially implemented: 9.3 local extraction and structure, no semantic understanding) | 9.3 | `DocumentUnderstandingPort`, `Modality.DOCUMENT` | automated_test + deterministic_demo |
| SRC-005 Cross-modal reasoning (partially implemented: 9.5 deterministic workflow and 9.8 accepted live model reasoning; reviewer demonstration remains) | 9.5, 9.8 | `ReasoningPort`, `ReasoningRequest.parts`, `contracts/reasoning.py` | automated_test + deterministic_demo |
| SRC-006 Speech-to-text (partially implemented: 9.8 live speech recognition established; genuine partial transcripts and reviewer demonstration remain) | 9.4, 9.8 | `SpeechToTextPort`, `transcript_partial/final` | automated_test + deterministic_demo; live_integration for live STT |
| SRC-007 Text-to-speech (partially implemented: 9.8 live speech synthesis established; reviewer demonstration remains) | 9.4, 9.8 | `TextToSpeechPort`, `audio_ready` | automated_test + deterministic_demo; live_integration for live TTS |
| SRC-008 Real-time conversations (partially implemented: 9.6 multi-turn conversations with bounded state; 9.7 real-time multi-turn sessions over WebSocket; one live voice turn established in 9.8; live multi-turn and UI acceptance remain) | 9.6, 9.7, 9.8 | `SessionConfig`, `ConversationTurn`, stream events | WebSocket multi-turn acceptance test |
| SRC-009 Voice orchestration (partially implemented: 9.8 live STT -> reasoning -> TTS turn established; reviewer demonstration remains) | 9.6, 9.8 | `VoiceAssistant` (core layer) | automated_test of STT -> reasoning -> TTS turn |
| SRC-010 Streaming responses (partially implemented: 9.7 incremental reply acts, not model tokens; 9.8 live provider streaming established; reviewer demonstration remains) | 9.7, 9.8 | `response_delta`, `response_complete` | Streamed delta acceptance test |
| SRC-011 WebSockets (implemented: 9.7 Starlette/Uvicorn gateway, loopback socket-level client/server tests) | 9.7 | WebSocket gateway (application interface layer) | Genuine WebSocket client/server test |
| SRC-012 Low-latency pipelines (partially implemented: 9.7 stage, milestone, and first-response latency measured and streamed locally; 9.8 provider latency measured; no production SLO) | 9.7, 9.10 | `LatencyStage`, `metric` event | Measured stage latencies, reviewer-visible |
| SRC-013 Voice interaction systems (partially implemented: 9.6 application-level sessions and spoken turns; live speech recognition established; no UI) | 9.6, 9.9 | Voice controls in presentation layer | deterministic_demo in Streamlit |
| SRC-014 Lab: voice-enabled assistant (partially implemented: 9.6 assistant built and tested; no Streamlit demo) | 9.6, 9.9 | `VoiceAssistant` workflow | deterministic_demo in Streamlit |
| SRC-015 Lab: multimodal AI workflow (partially implemented: 9.5 application workflow; no Streamlit demo) | 9.5, 9.9 | `CrossModalWorkflow` | deterministic_demo in Streamlit |
| SRC-016 Lab: real-time streaming system (partially implemented: 9.7 streaming system built and tested; no Streamlit demo) | 9.7, 9.9 | WebSocket streaming workflow | deterministic_demo with visible stream events |
| SRC-017 Deliverable: voice-enabled AI assistant (partially implemented: 9.6 application core) | 9.6, 9.9, 9.10 | Voice assistant | Production acceptance evidence |
| SRC-018 Deliverable: multimodal AI platform (partially implemented: integrated core; UI and production acceptance remain) | 9.5, 9.9, 9.10 | Multimodal platform | Production acceptance evidence |

## Additive engineering requirements

| Requirement | Delivering stories | Anchor |
|---|---|---|
| ENG-001 Deterministic no-key mode (partially implemented: 9.2 foundation) | 9.2, 9.9 | `ExecutionMode.DETERMINISTIC` default, `adapters.deterministic` |
| ENG-002 Opt-in ephemeral BYOK live mode (implemented: 9.8 explicit opt-in ephemeral BYOK, security tests, and accepted live execution) | 9.8 | `SessionConfig.live_opt_in`, `LiveCredential` |
| ENG-003 Streamlit presentation layer | 9.9 | ADR-009-002 |
| ENG-004 Logic outside Streamlit | 9.1, 9.2, 9.9 | ADR-009-002, `multimodal_voice_platform` package |
| ENG-005 Reviewer-visible working results | 9.9, 9.10 | ADR-009-009 |
| ENG-006 Untrusted content never grants authority (partially implemented: 9.3 image and document path; 9.4 audio, transcript, and synthesis-text path; 9.5 reasoning context and reasoning output; 9.6 transcripts, conversation history, and replies; 9.7 client messages and transcripts streamed as data) | 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.10 | ADR-009-007, `TrustLevel` |
| ENG-007 Bounded cost and latency (partially implemented: 9.6 conversation, turn, reply, output, and provider-call bounds; 9.7 message, audio, fragment, event, timeout, and connection bounds) | 9.1, 9.6, 9.7, 9.8, 9.10 | ADR-009-008, `ResourceBudget` |
| ENG-008 Observability without secrets (partially implemented: 9.7 typed latency metrics and sanitized errors) | 9.7, 9.10 | `metric` event, `SafeError` |
| ENG-009 Accurate evidence classification | 9.1, 9.9, 9.10 | `EvidenceClass`, `EvidenceRecord` |
| ENG-010 Standalone Module 9 | 9.1, 9.10 | ADR-009-001, isolation test |
| ENG-011 Python engineering standard | 9.1, 9.10 | `pyproject.toml`, quality gates |
| ENG-012 Built-in reviewer guidance | 9.9 | ADR-009-009 |

## Coverage summary

- Source requirement groups traced: 17 of 17 (18 requirement IDs).
- Additive engineering requirements traced: 12 of 12.
- Requirements fully implemented: SRC-011 and ENG-002.
- Source requirements SRC-002 through SRC-010 and SRC-012 through SRC-018 remain partial.
  Live behavior is established where recorded above; required reviewer demonstrations, genuine
  partial STT, low-latency acceptance, and/or final production acceptance remain outstanding.
- ENG-001, ENG-006, ENG-007, and ENG-008 remain partial across later stories.
- Stories 9.9 and 9.10 are not started; Module 9 is incomplete.
