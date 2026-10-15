# Module 9 Audio and Speech Pipeline (Story 9.4)

## What this is

Story 9.4 adds a genuine, bounded audio-processing path and the speech-to-text and text-to-speech
pipeline architecture, through the accepted provider ports. It lives in three packages:

| Package | Role |
|---|---|
| `audio/` | Audio ingestion boundary and processing: signature sniffing, strict PCM WAV parsing, byte and duration budgets, sample decoding, signal measurement |
| `adapters/speech/` | `ToneSequenceSynthesizer`, a deterministic `TextToSpeechPort` adapter |
| `speech/` | `SpeechService` and `SpeechRecord`: the application-facing entry point and reviewer-visible result |

Speech-to-text in deterministic mode uses the unchanged Story 9.2 `DeterministicSpeechToTextProvider`
(fixture playback) through the `SpeechToTextPort`.

## What each part is, and is not

| Capability | What actually happens | What it is not |
|---|---|---|
| Audio processing | PCM WAV bytes are parsed, decoded, and measured in-process. Real local audio processing | Not speech detection or speech recognition |
| Speech-to-text (default) | Story 9.2 fixture playback: the committed `audio-tone` fixture is matched by SHA-256 digest and its scripted transcript is replayed. Any other audio is rejected | Not speech recognition. No STT model runs |
| Text-to-speech (default) | `ToneSequenceSynthesizer` renders text into a reproducible sequence of sine-tone bursts and pauses, encoded as genuine WAV | Not speech synthesis. The audio is not intelligible speech and no voice model runs |
| Provider-contract test doubles | Tests inject scripted STT and TTS adapters to exercise the port boundary, timeouts, and failures | Provider-contract evidence only (`automated_test`), never speech capability |
| Live STT and TTS | Not implemented. Provider selection and BYOK belong to Story 9.8 | |

Genuine speech recognition and speech synthesis need either a live provider (Story 9.8, which owns
provider and cost decisions) or a bundled local speech model, which would be a large new dependency
needing human approval. Story 9.4 adds neither, so SRC-006 and SRC-007 stay partially implemented.

## Processing kinds

Every `SpeechRecord` lists the processing each completed stage performed, and names the processing
kind its speech provider declared.

| Kind | Meaning | Produced by |
|---|---|---|
| `local_audio_decoding` | WAV container parsed and samples decoded from the actual bytes | `audio/` |
| `local_signal_analysis` | Levels, clipping, silence, and zero crossings measured from samples | `audio/` |
| `fixture_playback` | Scripted transcript for a committed fixture, matched by digest | Story 9.2 STT adapter |
| `deterministic_tone_synthesis` | Procedural tone-sequence audio rendered from text | `ToneSequenceSynthesizer` |
| `provider_contract_test_double` | A scripted adapter used by tests; `automated_test` evidence only | Tests |
| `speech_recognition`, `speech_synthesis` | Model-based speech. Reserved; every record rejects them | Not implemented (Story 9.8) |

`speech_recognition_performed`, `speech_synthesis_performed`, `model_inference_performed`, and
`live_provider_called` are fixed to `False` on every Story 9.4 record.

## Audio processing

| Step | Behavior |
|---|---|
| Media type | Must be on the audio allowlist and match the bytes: `RIFF....WAVE` for WAV, an EBML header for WebM, an ID3 tag or MPEG frame sync for MP3. Only WAV is decodable; MP3 and WebM are recognized and rejected as unsupported (no codec dependency is added) |
| Structure | The RIFF chunk list is walked with `struct` and every declared size is checked against the real length. Rejected: truncated containers or chunk headers, chunks that overrun the container, trailing bytes, more than 64 chunks, missing, duplicate, or misordered `fmt`/`data` chunks, empty audio, a partial final frame, inconsistent block alignment or byte rate |
| Encoding | Integer PCM (`WAVE_FORMAT_PCM`, or `WAVE_FORMAT_EXTENSIBLE` with the PCM subformat) at 8, 16, 24, or 32 bits. Float, ADPCM, other codecs, and padded sample containers are rejected as unsupported |
| Parameters | 1 to 8 channels; 8,000 to 192,000 Hz |
| Cross-check | The standard-library `wave` reader parses the same in-memory bytes; both readers must agree on channels, sample width, rate, and frame count |
| Budgets | Session byte budget before parsing; duration (frames / rate, from the header, never from the caller) against the session duration budget before any sample is decoded |
| Decoding | `array` and byte slicing convert samples to signed integers (8-bit unsigned is re-centered, 24-bit is widened) |
| Measurements | Peak and RMS level (linear and dBFS), per-channel peak and RMS, DC offset, clipped-sample share, share of silent 20 ms windows (below -60 dBFS), zero-crossing rate, and a coarse `silent`/`signal` label |
| Time | Decoding and measurement run in a worker thread bounded by `request_timeout_s`; a timeout is a retryable `provider_timeout` failure. Byte, duration, channel, and rate ceilings bound the work |

Example: the committed `audio-tone` fixture decodes to 8 kHz mono unsigned 8-bit PCM, 4,000 frames,
500 ms, peak level 0.39 (-8.16 dBFS), and 798 zero crossings per second, consistent with its 400 Hz
square tone. These values are measured from the samples, not read from the manifest.

## Speech-to-text pipeline

`SpeechService.transcribe_upload` and `transcribe_fixture` run: ingestion -> audio processing ->
`SpeechToTextPort.transcribe` -> transcript validation.

| Control | Behavior |
|---|---|
| Provider binding | `SpeechToTextBinding(factory, processing)` supplies the adapter and declares its processing kind. Only `fixture_playback` and `provider_contract_test_double` are accepted; reserved kinds raise `SpeechConfigurationError` |
| Wiring checks | The adapter must describe itself as a deterministic `speech_to_text` adapter, or the run raises before any processing |
| Timeout | The whole transcript stream is bounded by `request_timeout_s`; a timeout is a retryable `provider_timeout` failure and the stream is closed |
| Output validation | At most 200 segments (the stream is cut off beyond that); every item must be a `TranscriptSegment` attributed to the bound adapter; starts are ordered; no segment ends after the audio; exactly one final segment, last. Violations are `provider_unavailable` failures that never echo the provider's payload |
| Provider errors | Adapters translate their own failures into `Module9Error` subclasses such as `SpeechProviderUnavailableError` (retryable). Any other exception is a defect and propagates |
| Trust | The transcript is `untrusted_model_output`. Nothing in the pipeline parses or acts on it; tests show an injected instruction transcript changes no session, budget, or provider |

## Text-to-speech pipeline

`SpeechService.synthesize_text` runs: text ingestion -> `TextToSpeechPort.synthesize` -> generated
audio validation.

| Control | Behavior |
|---|---|
| Text ingestion | Text becomes an `untrusted_external` text `ModalityInput`. Rejected: blank text, control characters other than tab and newlines, unencodable characters, more than 20,000 characters, invalid voice identifiers |
| Tone synthesizer | 16 kHz mono 16-bit PCM. Each letter or digit is a 60 ms sine burst at `220 + (code point mod 48) * 20` Hz with 5 ms fades; whitespace is 40 ms of silence; other characters 90 ms; 50 ms of silence at each end. One voice, `tone-default`. Output exceeding the session duration or byte budget is refused before or after rendering |
| Timeout | The provider call is bounded by `request_timeout_s` |
| Output validation | The returned audio must be attributed to the bound adapter, resolve to stored bytes, decode as valid WAV within budget through the same audio path as uploads, and match its declared duration within 1 ms |
| Result | `SynthesisResult` carries the port result, the digest and size of the audio, and the WAV bytes. The bytes are excluded from JSON and repr; in-process callers (the later Streamlit layer) can play them |

## Reviewer-visible record

`SpeechRecord` serializes to JSON and shows: the operation (`audio_analysis`, `transcription`,
`synthesis`), status (`succeeded`, `rejected`, `failed`), the validated input, the speech provider
and its declared processing kind, the processing kinds that completed, the `AudioAnalysis`, the
`TranscriptResult` or `SynthesisResult`, per-stage timings, the failed stage and `SafeError` for
unsuccessful runs, and a Story 9.4 `EvidenceRecord` whose summary states what did and did not happen.
Records reject any claim of speech recognition, speech synthesis, model inference, live execution,
or non-deterministic evidence, and test-double runs may only be `automated_test` evidence.

```python
import asyncio

from multimodal_voice_platform.contracts.session import SessionConfig
from multimodal_voice_platform.speech import SpeechService

service = SpeechService()
session = SessionConfig(session_id="demo")
record = asyncio.run(service.transcribe_fixture(session, "audio-tone"))
print(record.model_dump_json(indent=2))
spoken = asyncio.run(service.synthesize_text(session, "Hello from Module 9"))
wav = spoken.synthesis.wav_bytes  # playable WAV; a tone sequence, not speech
```

## Other controls

| Control | Behavior |
|---|---|
| Mode | Live sessions are refused with `live_mode_not_authorized` before any processing. Everything runs in `deterministic` mode: in-process, no network, no key, no spend |
| Names and paths | Display names are validated by the `ModalityInput` contract; content is held by opaque reference; `wave` reads and writes only `io.BytesIO` buffers. AST tests enforce no filesystem, network, process, or environment access |
| Retention | Each call uses its own content store and releases it before returning, including generated audio (SEC-022). WAV metadata chunks (such as `LIST`) are counted, never copied |
| Errors | Failures are `Module9Error` subclasses with stable codes, safe messages, and chained causes; input problems are `rejected`, provider problems and timeouts are `failed` |

## Dependencies

None added. WAV parsing, decoding, measurement, and generation use the Python standard library
(`struct`, `wave`, `array`, `math`). A codec or speech-model dependency would need a concrete
justification and, for large local speech models, human approval.

## Evidence

Story 9.4 evidence is `automated_test`: the suite runs generated WAV files (8/16/24/32-bit, mono and
multichannel, extensible, malformed, and pathological), the committed fixture, and generated tone
audio through the real pipeline with sockets blocked and no credentials. `SpeechRecord` can also
emit `deterministic_demo` records for reviewer runs and rejects every other class. No
`live_integration` evidence exists.

This evidence proves validated local audio processing, the speech-to-text and text-to-speech port
pipelines with validated, bounded provider output, and deterministic tone generation. It does not
prove speech recognition, speech synthesis, or anything reviewer-visible in Streamlit.

## Requirement status

| Requirement | Status | Justification |
|---|---|---|
| SRC-003 Audio processing | Partially implemented | Validated, bounded decoding and measurement of PCM WAV is implemented and tested. MP3 and WebM are allowlisted but not decodable, and reviewer-visible `deterministic_demo` evidence (Story 9.9) is not yet delivered |
| SRC-006 Speech-to-text | Partially implemented | The STT pipeline and port boundary are implemented and tested, but the only STT adapter is fixture playback, which is not speech recognition. Genuine STT and partial-transcript streaming to a client need Stories 9.8 and 9.7 |
| SRC-007 Text-to-speech | Partially implemented | The TTS port, a deterministic tone-sequence adapter, and generated-audio validation are implemented and tested. Tone sequences are not speech synthesis. Genuine TTS needs Story 9.8 |
| ENG-006 Untrusted content never grants authority | Partially implemented | Now enforced and tested on the audio, transcript, and synthesis text paths as well. Cross-modal reasoning (9.5) and release acceptance (9.10) remain |

## Out of scope

Cross-modal reasoning (9.5); conversation state and voice orchestration (9.6); WebSocket streaming
and streamed partial transcripts (9.7); live providers, BYOK, genuine STT and TTS (9.8); Streamlit
(9.9); release (9.10); MP3 and WebM decoding; resampling and format conversion.
