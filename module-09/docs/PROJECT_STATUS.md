# Module 9 Project Status

| Item | State |
|---|---|
| Module | 9: Multimodal & Voice AI Systems |
| Package | `multimodal_voice_platform` |
| Architecture | Frozen (human-approved Story 9.1 specification, 2026-10-14) |
| ADRs | 9 accepted (ADR-009-001 to ADR-009-009) |
| Requirements | 18 source-derived (17 groups) + 12 additive engineering |
| Stories | 9.1 complete (design only); 9.2 complete (deterministic foundation); 9.3 complete (local document and vision understanding); 9.4 complete (audio and speech pipeline); 9.5 complete (cross-modal reasoning workflow); 9.6 complete (voice-assistant orchestration); 9.7 to 9.10 not started |
| Implemented capabilities | Deterministic multimodal foundation (no-key fixture playback; no inference). Local document and vision understanding (validated ingestion, pixel analysis, document extraction and structure; no model inference). Audio and speech pipeline (validated PCM WAV decoding and signal measurement; STT and TTS through the provider ports with fixture-playback STT, which is not speech recognition, and tone-sequence TTS, which is not speech synthesis). Cross-modal reasoning workflow (typed observations from two to four modalities in one bounded context, related by rule-based deterministic reasoning with cited, validated findings; not model inference). Voice-assistant orchestration (synchronous turns from validated audio through STT, bounded conversational context, reasoning, TTS, and generated-audio validation to an atomic state commit, with bounded multi-turn state; fixture-playback STT, rule-based reasoning that is not model inference, and tone TTS that is not speech synthesis; nothing streamed) |
| Evidence obtained | 9.1: `design_documentation`. 9.2: `automated_test`. 9.3: `automated_test`. 9.4: `automated_test`. 9.5: `automated_test`. 9.6: `automated_test` |
| Release | Unreleased |

## What exists

- Requirements, traceability, architecture, nine ADRs, security/threat model, story roadmap,
  Definition of Done, evidence policy, and contract design in `docs/`.
- Machine-readable governance in `docs/governance/module-09-governance.json`.
- Typed contracts in `src/multimodal_voice_platform/contracts/`.
- Story 9.2 deterministic foundation in `src/multimodal_voice_platform/adapters/deterministic/`:
  four committed fixtures (text, image, audio, document), an integrity-checked fixture catalog, a
  session-scoped content store, deterministic fixture-playback adapters for the vision, document,
  and speech-to-text ports, and typed, evidence-classified run records. See
  [DETERMINISTIC_FOUNDATION.md](DETERMINISTIC_FOUNDATION.md).
- Story 9.3 local understanding in `src/multimodal_voice_platform/ingestion/`, `adapters/local/`,
  and `understanding/`: magic-byte and UTF-8 validated ingestion, Pillow-based image pixel analysis,
  Markdown/text/PDF extraction and structural analysis, and typed, evidence-classified
  `UnderstandingRecord`s. See [UNDERSTANDING.md](UNDERSTANDING.md).
- Story 9.4 audio and speech pipeline in `audio/`, `adapters/speech/`, and `speech/`: audio
  signature checks, strict RIFF/WAVE parsing cross-checked with the standard-library `wave` reader,
  byte and duration budgets, 8/16/24/32-bit PCM decoding, signal measurements, a speech-to-text
  pipeline with bounded and validated provider output, a deterministic tone-sequence
  `TextToSpeechPort` adapter with generated-audio validation, and typed, evidence-classified
  `SpeechRecord`s. See [AUDIO_SPEECH.md](AUDIO_SPEECH.md).
- Story 9.5 cross-modal workflow in `contracts/reasoning.py`, `adapters/reasoning/`, and
  `crossmodal/`: request validation and modality routing, normalized observations with origin
  labels, a bounded context of JSON-encoded parts beside a fixed task, a deterministic rule-based
  `ReasoningPort` adapter, citation checks on reasoning output, a derived conclusion, and typed,
  evidence-classified `CrossModalRecord`s. See [CROSS_MODAL.md](CROSS_MODAL.md).
- Story 9.6 voice assistant in `contracts/conversation.py`, `adapters/reasoning/conversation.py`,
  and `voice/`: the `VoiceAssistant` orchestrator, bounded application-owned conversation state with
  atomic commits and replay protection, a rule-based conversation `ReasoningPort` adapter, reply
  citation checks, committed conversation fixtures, and typed, evidence-classified
  `VoiceTurnRecord`s with stage timings. See [VOICE_ASSISTANT.md](VOICE_ASSISTANT.md).
- Contract, governance, fixture, adapter, ingestion, understanding, audio, speech, cross-modal,
  voice-assistant, and security tests in `tests/`.

## What does not exist yet

No model-based vision or semantic document understanding (Story 9.3 runs no model inference); no
OCR; no MP3 or WebM decoding; no speech recognition (Story 9.4 STT is fixture playback, which is
not speech recognition) and no speech synthesis (Story 9.4 TTS is a tone sequence, which is not
speech synthesis); no model-based reasoning (Story 9.5 reasoning is rule-based over a closed vocabulary, which is not model inference); no orchestration of genuine speech or model reasoning (Story 9.6 orchestrates the deterministic adapters only, synchronously); no WebSocket server or streaming; no live adapters or BYOK; no Streamlit UI. The
Story 9.2 deterministic adapters replay scripted output for committed fixtures and are not evidence
that any of those capabilities work.

## Next story

Story 9.7 (Real-Time WebSocket Streaming), whose dependency (9.6) is complete.
