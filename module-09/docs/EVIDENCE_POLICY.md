# Module 9 Evidence Policy

## Evidence classes

| Class | Runtime executed | Live provider | What it proves |
|---|---|---|---|
| `design_documentation` | No | No | Architecture, contracts, and plans exist. Design intent only. |
| `automated_test` | Yes | No | Code paths behave as tested, using deterministic inputs. |
| `deterministic_demo` | Yes | No | A reviewer ran the workflow with deterministic adapters and no key. |
| `live_integration` | Yes | Yes | The workflow ran against a real provider with opt-in credentials. |
| `deployment_release` | Yes | No | A packaged, deployed, or released artifact was exercised in its target environment. |

Rules, enforced by `EvidenceRecord` in `contracts/evidence.py`:

- `design_documentation` cannot claim runtime or live execution.
- `automated_test`, `deterministic_demo`, and `deployment_release` require runtime execution.
- Only `live_integration` may record live-provider execution, and it must.
- Deterministic-mode results can never be labeled `live_integration`. Live-mode results can never
  be labeled `deterministic_demo`.

## Deterministic versus live execution

| | Deterministic mode | Live mode |
|---|---|---|
| Default | Yes | No |
| Activation | Always available | `live_opt_in=True` plus a user-supplied credential |
| Network | None | Allowlisted providers only |
| Cost | None | Bounded by `ResourceBudget` |
| Evidence | `automated_test`, `deterministic_demo` | `live_integration` |

## Reviewer-visible results invariant

Every material capability must ultimately show its real output in the Streamlit UI, labeled with
its execution mode and evidence class, next to concise guidance on how to run it and what the
result demonstrates (ADR-009-009). A capability without reviewer-visible evidence is not done.

## Story 9.1 classification

Story 9.1 evidence is **`design_documentation` only**. It is not deterministic runtime evidence,
not automated functional capability evidence, not live integration evidence, and not proof that any
multimodal, voice, streaming, provider, or UI functionality works.

The Story 9.1 automated tests check contract and governance consistency (for example, that a
contract rejects an oversized file). They do not exercise any multimodal capability, so they do
not count as functional capability evidence for any SRC requirement.

## Story 9.2 classification

Story 9.2 evidence is **`automated_test`**: the test suite runs every committed fixture through the
deterministic adapters with sockets blocked and no credentials. `DeterministicRunRecord` can also
emit `deterministic_demo` records for reviewer runs. It rejects every other class, so deterministic
runs can never be labeled `live_integration`.

This evidence proves that the deterministic, no-key path runs reproducibly through the provider
ports. It does not prove vision, document understanding, speech-to-text, or any other SRC
capability: the adapters replay scripted output for committed fixtures and perform no inference.

## Story 9.3 classification

Story 9.3 evidence is **`automated_test`**: the suite runs generated PNG, JPEG, WebP, PDF, Markdown,
and text inputs through validated ingestion and the local vision and document adapters, with
sockets blocked and no credentials. `UnderstandingRecord` can emit `deterministic_demo` records for
reviewer runs and rejects every other class.

Story 9.3 performs local extraction and structural analysis with no model inference. Its records
name their processing kinds (`local_extraction`, `local_structural_analysis`) and reject
`fixture_playback` and `model_inference`. This evidence partially supports SRC-002, SRC-004, and
ENG-006. It is not evidence of model-based vision, semantic document understanding, live
integration, or reviewer-visible results. See [UNDERSTANDING.md](UNDERSTANDING.md).

## Story 9.4 classification

Story 9.4 evidence is **`automated_test`**: the suite runs generated WAV files, the committed audio
fixture, and generated tone audio through validated audio processing and the speech-to-text and
text-to-speech pipelines, with sockets blocked and no credentials. `SpeechRecord` can emit
`deterministic_demo` records for reviewer runs and rejects every other class.

Each class of Story 9.4 behavior is kept distinct:

| Behavior | Evidence it provides |
|---|---|
| WAV decoding and signal measurement | Real local audio processing |
| Fixture-playback transcript | Deterministic pipeline evidence; not speech recognition |
| Tone-sequence audio | Real deterministic audio generation; not speech synthesis |
| Provider-contract test doubles | Port-boundary and failure-handling evidence only (`automated_test`) |
| External STT or TTS provider | None yet; would be `live_integration` (Story 9.8) |

Records name their processing kinds and reject `speech_recognition` and `speech_synthesis`. This
evidence partially supports SRC-003, SRC-006, SRC-007, and ENG-006. See
[AUDIO_SPEECH.md](AUDIO_SPEECH.md).

## Story 9.5 classification

Story 9.5 evidence is **`automated_test`**: the suite runs generated and committed inputs from two
to four modalities through the real cross-modal workflow, with sockets blocked and no credentials.
`CrossModalRecord` can emit `deterministic_demo` records for reviewer runs and rejects every other
class.

| Behavior | Evidence it provides |
|---|---|
| Local image, document, and audio processing | Actual local processing evidence |
| Fixture-playback transcript | Deterministic fixture evidence; not speech recognition |
| Rule-based cross-modal inference | Genuine deterministic cross-modal reasoning evidence; not model inference |
| Reasoning provider-contract test doubles | Provider-contract evidence only (`automated_test`) |
| External reasoning model | None yet; would be `live_integration` (Story 9.8) |

Records name their reasoning kind (`deterministic_rule_inference` or
`provider_contract_test_double`) and reject `model_inference`. This evidence partially supports
SRC-005, SRC-015, and ENG-006. See [CROSS_MODAL.md](CROSS_MODAL.md).

## Story 9.6 classification

Story 9.6 evidence is **`automated_test`**: the suite runs the committed conversation fixtures,
generated audio, and scripted test doubles through the real voice-assistant orchestrator, across
multiple turns and sessions, with sockets blocked and no credentials. Turns are synchronous; nothing
is streamed. `VoiceTurnRecord` can emit
`deterministic_demo` records for reviewer runs and rejects every other class; turns that use any
test-double provider may only be `automated_test`.

| Behavior | Evidence it provides |
|---|---|
| Voice orchestration and transaction semantics | Genuine application-level orchestration evidence |
| Bounded multi-turn conversation state | Genuine state evidence; later turns demonstrably depend on it |
| Fixture-playback transcript | Deterministic fixture evidence; not speech recognition |
| Rule-based conversation reasoning | Deterministic rule-based reasoning; not model inference |
| Tone-sequence output audio | Deterministic audio generation; not speech synthesis |
| Stage and end-to-end timings | Local measurements of deterministic adapters; not production latency or real-time streaming |
| External STT, reasoning, or TTS provider | None yet; would be `live_integration` (Story 9.8) |

Records state `speech_recognition_performed`, `speech_synthesis_performed`,
`model_inference_performed`, `live_provider_called`, and `streaming_performed` as `False`. This
evidence partially supports SRC-008, SRC-009, SRC-013, SRC-014, SRC-017, ENG-006, and ENG-007. See
[VOICE_ASSISTANT.md](VOICE_ASSISTANT.md).
