# Module 9 Deterministic Multimodal Foundation (Story 9.2)

## What this is

Story 9.2 provides reproducible, no-key execution through the Story 9.1 provider ports. It lives in
`src/multimodal_voice_platform/adapters/deterministic/`.

The deterministic adapters perform **no inference**. They do fixture playback: each adapter resolves
the request's opaque content reference, confirms by exact SHA-256 digest that the content is a
committed fixture, and returns that fixture's scripted output from the manifest. Content that is not
a committed fixture is rejected, never guessed at. Scripted output is fixed annotation written for
this project. It is not produced by any model, and it does not prove vision, document, or speech
capability.

## Fixtures

All fixtures are generated for or written by this project, contain no personal data or secrets, and
are committed byte for byte (`fixture_data/.gitattributes` sets `-text`). The manifest
(`fixture_data/manifest.json`) records each fixture's media type, size, SHA-256 digest, provenance,
and scripted output. The catalog verifies every fixture against the manifest when it loads and
fails closed on any mismatch.

| Fixture ID | Modality | File | Size | Content |
|---|---|---|---|---|
| `text-brief` | text | `text-brief.txt` (`text/plain`) | 153 B | Short plain-text passage |
| `image-quadrants` | image | `image-quadrants.png` (`image/png`) | 82 B | 8x8 RGB test pattern: red, green / blue, white quadrants |
| `audio-tone` | audio | `audio-tone.wav` (`audio/wav`) | 4,044 B | 500 ms, 8 kHz, mono, 8-bit PCM, 400 Hz square tone (no speech) |
| `document-brief` | document | `document-brief.md` (`text/markdown`) | 505 B | Three-section Markdown document, one section carrying a deliberate embedded instruction for trust tests |

The image and audio fixtures are generated with the Python standard library by `build_png()` and
`build_wav()` in `tests/test_deterministic_fixtures.py`. Those tests check that the committed bytes
still decode to the generator's pixels and samples. To change a fixture, update the generator or
text, regenerate the file, and update its size and digest in the manifest. Every fixture must stay
under the 64 KiB repository ceiling (`MAX_FIXTURE_BYTES`).

## Adapters

| Adapter | Port | Provider ID | Handles | Output |
|---|---|---|---|---|
| `DeterministicVisionProvider` | `VisionPort` | `deterministic-fixture-vision` | `image-quadrants` | `VisionResult` |
| `DeterministicDocumentProvider` | `DocumentUnderstandingPort` | `deterministic-fixture-document` | `document-brief` | `DocumentResult` |
| `DeterministicSpeechToTextProvider` | `SpeechToTextPort` | `deterministic-fixture-stt` | `audio-tone` | partial then final `TranscriptSegment`s |

Text input has no processing port. The text fixture is normalized into an inline `ModalityInput`
and recorded with no provider.

Every result carries a `ProviderDescriptor` with `mode=deterministic` and is classified
`untrusted_model_output`. Scripted text also says plainly that no model ran.

Deterministic `TextToSpeechPort` and `ReasoningPort` adapters are not part of Story 9.2. No Story 9.2
fixture is an input to those ports, and their deterministic behavior belongs with the stories that
own TTS (9.4) and cross-modal reasoning (9.5). Story 9.4 adds a deterministic tone-sequence
`TextToSpeechPort` adapter, which is procedural audio generation rather than fixture playback (see
[AUDIO_SPEECH.md](AUDIO_SPEECH.md)).

## Running a fixture

```python
import asyncio

from multimodal_voice_platform.adapters.deterministic import DeterministicFoundation
from multimodal_voice_platform.contracts.session import SessionConfig

foundation = DeterministicFoundation()
session = SessionConfig(session_id="demo")
record = asyncio.run(foundation.run(session, "image-quadrants"))
foundation.release(session.session_id)
```

`DeterministicRunRecord` tells a reviewer which fixture ran (ID and digest), its modality, the
validated input, which deterministic adapter executed, the typed output, that no live provider was
called (`live_provider_called` is always `False`), and an `EvidenceRecord`. The record serializes
to JSON for the later Streamlit layer (Story 9.9), which is not implemented here.

## Controls

| Control | Behavior |
|---|---|
| Session mode | Live sessions are rejected. Deterministic sessions carry no credentials (Story 9.1 contract). |
| Budget | Fixture bytes, audio duration, and document pages are checked against the session `ResourceBudget` (`LIMIT_EXCEEDED`). |
| Lookup | Fixtures are looked up by ID only. No caller value is used as a path. Unknown IDs raise `UnknownFixtureError` (`INPUT_REJECTED`). |
| Content | Binary content is held by opaque reference in a session-scoped in-memory store and deleted by `release(session_id)` (SEC-022). |
| Matching | Adapters accept only exact committed fixture bytes with matching media type and size. |
| Network | The package imports no network, process, or environment modules. A test runs every fixture with sockets blocked. |
| Errors | Failures are `Module9Error` subclasses with stable codes, chained causes, and safe messages. No broad exception handlers. |
| Trust | Inputs stay `untrusted_external`. Outputs stay `untrusted_model_output`. Embedded instructions in content change nothing. |

## Evidence

Deterministic runs may produce only `deterministic_demo` (the default, for reviewer runs) or
`automated_test`. `DeterministicRunRecord` and `EvidenceRecord` reject any live or stronger claim.
Story 9.2 evidence obtained so far is `automated_test`. It proves that the deterministic path runs
reproducibly with no key, network, or spend. It is not evidence of genuine vision, document,
speech, cross-modal, voice, streaming, or live-provider capability.
