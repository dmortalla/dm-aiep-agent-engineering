# Module 9 Traceability

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) maps to the stories that will deliver it
and to the evidence that must exist before it counts as satisfied. The machine-readable copy is
[governance/module-09-governance.json](governance/module-09-governance.json). Automated tests
keep the two in sync.

**Current status: every row is designed, not implemented, except ENG-001, SRC-002, SRC-003,
SRC-004, SRC-005, SRC-006, SRC-007, SRC-008, SRC-009, SRC-013, SRC-014, SRC-015, SRC-017, ENG-006,
and ENG-007, which are partially implemented.** Story 9.1 contributes architecture and contract design
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
is streamed (see [VOICE_ASSISTANT.md](VOICE_ASSISTANT.md)). Planned evidence is never completed
evidence.

## Source-derived requirements

| Requirement | Delivering stories | Contract / architecture anchor | Required evidence before "satisfied" |
|---|---|---|---|
| SRC-001 Engineer multimodal AI applications | 9.1, 9.5, 9.9, 9.10 | Whole architecture | Integrated platform acceptance, reviewer-visible |
| SRC-002 Vision models (partially implemented: 9.3 local pixel analysis, no vision model) | 9.3, 9.8 | `VisionPort`, `Modality.IMAGE` | automated_test + deterministic_demo; live_integration for live vision |
| SRC-003 Audio processing (partially implemented: 9.4 PCM WAV decoding and measurement; MP3/WebM not decodable) | 9.4 | `Modality.AUDIO`, audio limits | automated_test + deterministic_demo |
| SRC-004 Document understanding (partially implemented: 9.3 local extraction and structure, no semantic understanding) | 9.3 | `DocumentUnderstandingPort`, `Modality.DOCUMENT` | automated_test + deterministic_demo |
| SRC-005 Cross-modal reasoning (partially implemented: 9.5 rule-based deterministic reasoning over a closed vocabulary; no model-based reasoning) | 9.5 | `ReasoningPort`, `ReasoningRequest.parts`, `contracts/reasoning.py` | automated_test + deterministic_demo |
| SRC-006 Speech-to-text (partially implemented: 9.4 pipeline and port; fixture-playback STT, no speech recognition) | 9.4, 9.8 | `SpeechToTextPort`, `transcript_partial/final` | automated_test + deterministic_demo; live_integration for live STT |
| SRC-007 Text-to-speech (partially implemented: 9.4 port and tone-sequence adapter, no speech synthesis) | 9.4, 9.8 | `TextToSpeechPort`, `audio_ready` | automated_test + deterministic_demo; live_integration for live TTS |
| SRC-008 Real-time conversations (partially implemented: 9.6 synchronous multi-turn conversations with bounded state; no real-time streaming) | 9.6, 9.7 | `SessionConfig`, `ConversationTurn`, stream events | WebSocket multi-turn acceptance test |
| SRC-009 Voice orchestration (partially implemented: 9.6 orchestration with fixture-playback STT, rule-based reasoning, and tone TTS) | 9.6, 9.8 | `VoiceAssistant` (core layer) | automated_test of STT -> reasoning -> TTS turn |
| SRC-010 Streaming responses | 9.7 | `response_delta`, `response_complete` | Streamed delta acceptance test |
| SRC-011 WebSockets | 9.7 | WebSocket gateway (application interface layer) | Genuine WebSocket client/server test |
| SRC-012 Low-latency pipelines | 9.7, 9.10 | `LatencyStage`, `metric` event | Measured stage latencies, reviewer-visible |
| SRC-013 Voice interaction systems (partially implemented: 9.6 application-level sessions and spoken turns; no UI or speech recognition) | 9.6, 9.9 | Voice controls in presentation layer | deterministic_demo in Streamlit |
| SRC-014 Lab: voice-enabled assistant (partially implemented: 9.6 assistant built and tested; no Streamlit demo) | 9.6, 9.9 | `VoiceAssistant` workflow | deterministic_demo in Streamlit |
| SRC-015 Lab: multimodal AI workflow (partially implemented: 9.5 application workflow; no Streamlit demo) | 9.5, 9.9 | `CrossModalWorkflow` | deterministic_demo in Streamlit |
| SRC-016 Lab: real-time streaming system | 9.7, 9.9 | WebSocket streaming workflow | deterministic_demo with visible stream events |
| SRC-017 Deliverable: voice-enabled AI assistant (partially implemented: 9.6 application core) | 9.6, 9.9, 9.10 | Voice assistant | Production acceptance evidence |
| SRC-018 Deliverable: multimodal AI platform | 9.5, 9.9, 9.10 | Multimodal platform | Production acceptance evidence |

## Additive engineering requirements

| Requirement | Delivering stories | Anchor |
|---|---|---|
| ENG-001 Deterministic no-key mode (partially implemented: 9.2 foundation) | 9.2, 9.9 | `ExecutionMode.DETERMINISTIC` default, `adapters.deterministic` |
| ENG-002 Opt-in ephemeral BYOK live mode | 9.8 | `SessionConfig.live_opt_in`, `LiveCredential` |
| ENG-003 Streamlit presentation layer | 9.9 | ADR-009-002 |
| ENG-004 Logic outside Streamlit | 9.1, 9.2, 9.9 | ADR-009-002, `multimodal_voice_platform` package |
| ENG-005 Reviewer-visible working results | 9.9, 9.10 | ADR-009-009 |
| ENG-006 Untrusted content never grants authority (partially implemented: 9.3 image and document path; 9.4 audio, transcript, and synthesis-text path; 9.5 reasoning context and reasoning output; 9.6 transcripts, conversation history, and replies) | 9.1, 9.3, 9.4, 9.5, 9.6, 9.10 | ADR-009-007, `TrustLevel` |
| ENG-007 Bounded cost and latency (partially implemented: 9.6 conversation, turn, reply, output, and provider-call bounds) | 9.1, 9.6, 9.8, 9.10 | ADR-009-008, `ResourceBudget` |
| ENG-008 Observability without secrets | 9.7, 9.10 | `metric` event, `SafeError` |
| ENG-009 Accurate evidence classification | 9.1, 9.9, 9.10 | `EvidenceClass`, `EvidenceRecord` |
| ENG-010 Standalone Module 9 | 9.1, 9.10 | ADR-009-001, isolation test |
| ENG-011 Python engineering standard | 9.1, 9.10 | `pyproject.toml`, quality gates |
| ENG-012 Built-in reviewer guidance | 9.9 | ADR-009-009 |

## Coverage summary

- Source requirement groups traced: 17 of 17 (18 requirement IDs).
- Additive engineering requirements traced: 12 of 12.
- Requirements fully implemented: 0. Partially implemented: ENG-001 (Story 9.2 deterministic
  foundation); SRC-002, SRC-004, and ENG-006 (Story 9.3 local understanding); SRC-003, SRC-006,
  SRC-007, and ENG-006 (Story 9.4 audio and speech pipeline); SRC-005, SRC-015, and ENG-006 (Story
  9.5 cross-modal workflow); SRC-008, SRC-009, SRC-013, SRC-014, SRC-017, ENG-006, and ENG-007
  (Story 9.6 voice assistant). Story 9.1 is design only.
