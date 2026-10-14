# Module 9 Traceability

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) maps to the stories that will deliver it
and to the evidence that must exist before it counts as satisfied. The machine-readable copy is
[governance/module-09-governance.json](governance/module-09-governance.json). Automated tests
keep the two in sync.

**Current status: every row is designed, not implemented, except ENG-001, SRC-002, SRC-004, and
ENG-006, which are partially implemented.** Story 9.1 contributes architecture and contract design
only, which is `design_documentation` evidence. Story 9.2 contributes the deterministic foundation
for ENG-001 (`automated_test` evidence). Deterministic fixture playback is not evidence for any SRC
requirement. Story 9.3 contributes `automated_test` evidence of validated ingestion, local image
analysis, and local document extraction and structural analysis, with no model inference (see
[UNDERSTANDING.md](UNDERSTANDING.md)). Planned evidence is never completed evidence.

## Source-derived requirements

| Requirement | Delivering stories | Contract / architecture anchor | Required evidence before "satisfied" |
|---|---|---|---|
| SRC-001 Engineer multimodal AI applications | 9.1, 9.5, 9.9, 9.10 | Whole architecture | Integrated platform acceptance, reviewer-visible |
| SRC-002 Vision models (partially implemented: 9.3 local pixel analysis, no vision model) | 9.3, 9.8 | `VisionPort`, `Modality.IMAGE` | automated_test + deterministic_demo; live_integration for live vision |
| SRC-003 Audio processing | 9.4 | `Modality.AUDIO`, audio limits | automated_test + deterministic_demo |
| SRC-004 Document understanding (partially implemented: 9.3 local extraction and structure, no semantic understanding) | 9.3 | `DocumentUnderstandingPort`, `Modality.DOCUMENT` | automated_test + deterministic_demo |
| SRC-005 Cross-modal reasoning | 9.5 | `ReasoningPort`, `ReasoningRequest.inputs` | automated_test + deterministic_demo |
| SRC-006 Speech-to-text | 9.4, 9.8 | `SpeechToTextPort`, `transcript_partial/final` | automated_test + deterministic_demo; live_integration for live STT |
| SRC-007 Text-to-speech | 9.4, 9.8 | `TextToSpeechPort`, `audio_ready` | automated_test + deterministic_demo; live_integration for live TTS |
| SRC-008 Real-time conversations | 9.6, 9.7 | `SessionConfig`, `ConversationTurn`, stream events | WebSocket multi-turn acceptance test |
| SRC-009 Voice orchestration | 9.6 | Voice orchestrator (core layer) | automated_test of STT -> reasoning -> TTS turn |
| SRC-010 Streaming responses | 9.7 | `response_delta`, `response_complete` | Streamed delta acceptance test |
| SRC-011 WebSockets | 9.7 | WebSocket gateway (application interface layer) | Genuine WebSocket client/server test |
| SRC-012 Low-latency pipelines | 9.7, 9.10 | `LatencyStage`, `metric` event | Measured stage latencies, reviewer-visible |
| SRC-013 Voice interaction systems | 9.6, 9.9 | Voice controls in presentation layer | deterministic_demo in Streamlit |
| SRC-014 Lab: voice-enabled assistant | 9.6, 9.9 | Voice assistant workflow | deterministic_demo in Streamlit |
| SRC-015 Lab: multimodal AI workflow | 9.5, 9.9 | Multimodal workflow | deterministic_demo in Streamlit |
| SRC-016 Lab: real-time streaming system | 9.7, 9.9 | WebSocket streaming workflow | deterministic_demo with visible stream events |
| SRC-017 Deliverable: voice-enabled AI assistant | 9.6, 9.9, 9.10 | Voice assistant | Production acceptance evidence |
| SRC-018 Deliverable: multimodal AI platform | 9.5, 9.9, 9.10 | Multimodal platform | Production acceptance evidence |

## Additive engineering requirements

| Requirement | Delivering stories | Anchor |
|---|---|---|
| ENG-001 Deterministic no-key mode (partially implemented: 9.2 foundation) | 9.2, 9.9 | `ExecutionMode.DETERMINISTIC` default, `adapters.deterministic` |
| ENG-002 Opt-in ephemeral BYOK live mode | 9.8 | `SessionConfig.live_opt_in`, `LiveCredential` |
| ENG-003 Streamlit presentation layer | 9.9 | ADR-009-002 |
| ENG-004 Logic outside Streamlit | 9.1, 9.2, 9.9 | ADR-009-002, `multimodal_voice_platform` package |
| ENG-005 Reviewer-visible working results | 9.9, 9.10 | ADR-009-009 |
| ENG-006 Untrusted content never grants authority (partially implemented: 9.3 image and document path) | 9.1, 9.3, 9.5, 9.10 | ADR-009-007, `TrustLevel` |
| ENG-007 Bounded cost and latency | 9.1, 9.8, 9.10 | ADR-009-008, `ResourceBudget` |
| ENG-008 Observability without secrets | 9.7, 9.10 | `metric` event, `SafeError` |
| ENG-009 Accurate evidence classification | 9.1, 9.9, 9.10 | `EvidenceClass`, `EvidenceRecord` |
| ENG-010 Standalone Module 9 | 9.1, 9.10 | ADR-009-001, isolation test |
| ENG-011 Python engineering standard | 9.1, 9.10 | `pyproject.toml`, quality gates |
| ENG-012 Built-in reviewer guidance | 9.9 | ADR-009-009 |

## Coverage summary

- Source requirement groups traced: 17 of 17 (18 requirement IDs).
- Additive engineering requirements traced: 12 of 12.
- Requirements fully implemented: 0. Partially implemented: ENG-001 (Story 9.2 deterministic
  foundation); SRC-002, SRC-004, and ENG-006 (Story 9.3 local understanding). Story 9.1 is design
  only.
