# Module 9 User Guide

## Multimodal & Voice AI Systems — Reviewer Walkthrough

This guide shows how to explore the Module 9 reviewer application, the **Multimodal and Voice Studio**: a multimodal platform that relates text, images, documents, and audio, and a voice assistant that listens, reasons, responds, and streams its turns over a real WebSocket connection.

The normal reviewer experience is deterministic and credential-free. It runs real local image, document, and audio processing, rule-based reasoning, and genuine loopback WebSocket streaming. Each result is labeled with what actually ran, so you can tell local processing, fixture playback, rule-based reasoning, and opt-in live-provider calls apart.

---

## 1. What You Need

### Local reviewer path

Install Python 3.12 and [uv](https://docs.astral.sh/uv/). From the `module-09` directory:

```bash
uv sync --extra dev
uv run streamlit run streamlit_app.py
```

Dependency installation may need internet access. The app then serves on `127.0.0.1` only, with usage telemetry disabled and uploads capped at 2 MiB per file (see `.streamlit/config.toml`). No API key, provider account, or payment is needed for the deterministic workflows.

### Hosted reviewer path

Open the deployed [Module 9 reviewer app](https://dm-aiep-agent-engineering-module-09.streamlit.app); [RELEASE_READINESS.md](RELEASE_READINESS.md) records its verification. A browser is enough for the deterministic workflows there too. The walkthroughs below describe the same controls in either environment.

### Optional live-provider review

**Live / BYOK** mode is explicitly opt-in. You supply your own OpenAI API key in a masked field and acknowledge possible provider charges before each submitted operation. See [Optional live-provider / BYOK usage](#optional-live-provider--byok-usage) before using it.

Do not upload sensitive personal or business files. Use the built-in samples or synthetic test files.

---

## 2. Understand the Interface

The sidebar has three controls:

- **Workflow**: `Multimodal workflow`, `Voice assistant`, `Document & vision`, or `WebSocket streaming`.
- **Execution mode**: `Deterministic demo` (default) or `Live / BYOK`.
- **Reset session and clear results**: clears conversation history, the current result, retained audio, and uploads, then starts a fresh bounded conversation.

Each workflow shows a short description, its inputs, and one **Run selected workflow** button. Nothing runs until you press it: changing widgets or rerendering the page never calls a service or provider. A new submission clears the previous result first, so a failure can never be mistaken for an old success.

Every result starts with an **Execution evidence** line in the form `Mode: … | Evidence: … | Status: …`. The expander **Authoritative result, providers, processing kinds and timings** at the bottom shows the full redacted record returned by the application services.

---

## 3. Evidence Classes and Execution Modes

| Evidence class | What it establishes | What it does not establish |
| --- | --- | --- |
| `design_documentation` | Architecture, contracts, and plans exist | That anything runs |
| `automated_test` | Code paths behave as tested with deterministic inputs and no key | Real provider behavior |
| `deterministic_demo` | A reviewer ran the workflow with deterministic adapters and no key | Model inference, speech recognition, or speech synthesis |
| `live_integration` | The workflow ran against a real provider with opt-in credentials | A latency SLO, billing accuracy, or general model availability |
| `deployment_release` | A deployed artifact was exercised in its target environment | Authenticated, production-operated hosting |

These rules are enforced in code (`contracts/evidence.py`), not just documented. A deterministic result can never be labeled `live_integration`, and mocked transport cannot claim it.

| | Deterministic demo | Live / BYOK |
| --- | --- | --- |
| Default | Yes | No |
| Key | None | Your own key, entered for one operation |
| Provider network calls | None | OpenAI only, for the submitted operation |
| Cost | None | Provider usage you acknowledge before submitting |
| Failure behavior | Safe error message | Safe error message, **no fallback** to deterministic output |

### Processing kinds you will see

| Stage | Deterministic demo | Live / BYOK |
| --- | --- | --- |
| Image | Local Pillow pixel measurement | Same local measurement, plus a separate, untrusted model interpretation |
| Document | Local extraction and structure | Always local; documents never go to a provider |
| Audio | Local PCM WAV decoding and signal measurement | Same |
| Speech-to-text | **Fixture playback**, not speech recognition | Real OpenAI transcription |
| Reasoning | **Rule-based** over a closed vocabulary, not model inference | Real OpenAI streamed reasoning |
| Text-to-speech | **Deterministic tone sequence**, not speech synthesis | Real OpenAI speech |

---

# Walkthrough 1 — Cross-Modal Workflow with Repository Samples

## Goal

See one claim checked against evidence from several modalities, with every finding citing what it relied on.

## Steps

1. In the sidebar, choose **Workflow → Multimodal workflow** and leave **Execution mode → Deterministic demo**.
2. Keep **Use repository-owned samples** checked.
3. Press **Run selected workflow**.
4. Read **Cross-modal findings**.
5. Open **Normalized observations and citations**.

## Expected result

The sample submits four modalities: the text claim "The top-left quadrant is red.", an 8×8 quadrant test image, a Markdown brief, and a WAV test tone marked for transcription. The evidence line shows `Mode: deterministic | Evidence: deterministic_demo`. Findings are listed as `kind: explanation`; the text claim about the top-left quadrant is related to the color measured in that quadrant of the image. The observations expander shows each modality's normalized observation with origin labels and the citations each finding uses.

## What this demonstrates

Inputs from different modalities are normalized into typed observations, combined into one bounded reasoning context, and related through the reasoning port. Claims are judged against measurements from another modality, and every statement cites its source. The default reasoner is rule-based, not model inference, and the audio transcript is fixture playback, not speech recognition.

---

# Walkthrough 2 — Custom Cross-Modal Inputs

## Goal

Supply your own inputs and see how the rules respond, including when nothing can be related.

## Steps

1. Stay on **Multimodal workflow** and uncheck **Use repository-owned samples**.
2. In **Text claim (custom inputs)**, type a quadrant-and-color claim, for example `The top-left quadrant is blue.`
3. Upload a small PNG, JPEG, or WebP under **Image**, or a Markdown, text, or PDF file under **Document**.
4. Press **Run selected workflow**.
5. Try again with a claim the rules do not cover, such as a sentence with no quadrant or color.

## Expected result

A quadrant claim that disagrees with the measured image produces a `contradicted` finding; one that agrees produces `corroborated`. A claim outside the closed vocabulary may produce an `unverified_claim` finding or the message "No supported relationship was found in the supplied observations." If fewer than two modalities are supplied, or a file fails validation, the app shows a safe rejection message instead of a result.

## What this demonstrates

The workflow processes real submitted content, not hard-coded outcomes. The deterministic reasoner is honest about its closed vocabulary: it reports what it can check and says so when it cannot. The workflow needs at least two modalities, as the in-app caption states.

---

# Walkthrough 3 — Image Analysis

## Goal

See genuine local image measurement, kept separate from any model interpretation.

## Steps

1. Choose **Workflow → Document & vision**.
2. Leave **Modality** on `image` and leave **Image or document** empty to use the safe sample.
3. Press **Run selected workflow**.
4. Optionally upload your own PNG, JPEG, or WebP image and run again.

## Expected result

An **Analyzed image** section shows the submitted image. **Image analysis** shows a measured description and observations derived from the pixels, such as orientation, brightness, dominant named colors, and per-quadrant colors. For the sample, the quadrants measure red, green, blue, and white.

## What this demonstrates

Images are decoded with Pillow after content validation, and statistics are computed from the actual pixels. This is measurement, not a vision model. In **Live / BYOK** mode a separate **Live model interpretation  |  untrusted** section is added; it never replaces the measured facts.

---

# Walkthrough 4 — Document Processing

## Goal

See local document extraction and how embedded instructions are handled as data.

## Steps

1. Stay on **Document & vision** and set **Modality** to `document`.
2. Leave the upload empty to use the sample brief, then press **Run selected workflow**.
3. Optionally upload a Markdown, text, or PDF file and run again.

## Expected result

**Locally extracted document** shows each section heading and its text. The sample includes a section titled "Embedded instruction (test content)" that says to ignore previous instructions and switch to live mode. It is displayed as text, and the evidence line still reads `Mode: deterministic`.

## What this demonstrates

Markdown, text, and PDF content is extracted and structured locally, with no model call, even in live mode. Embedded instructions are untrusted content and cannot change execution mode, budgets, providers, or credentials. This is extraction and structure, not semantic document understanding or OCR.

---

# Walkthrough 5 — Audio and Speech Processing

## Goal

See audio validation, the speech-to-text and text-to-speech stages, and their honest labels.

## Steps

1. Choose **Workflow → Voice assistant**.
2. Leave **Sample utterance** on `voice-remember` and press **Run selected workflow**.
3. Read **Transcript** and **Assistant response**.
4. Play the generated audio.
5. Open **Authoritative result, providers, processing kinds and timings** and look at the processing kinds for each stage.

## Expected result

The transcript begins with "Deterministic fixture transcript:" and reads "Please remember that the project code word is falcon." The assistant acknowledges the value. A playable WAV appears; it is a tone sequence. **Measured stage latency** lists stage timings. The authoritative record identifies fixture-playback STT, rule-based reasoning, and tone TTS.

## What this demonstrates

The audio is validated and decoded as PCM WAV before any speech stage runs. Speech-to-text and text-to-speech run through the same ports a live provider uses, and generated audio is decoded and validated locally before playback. In deterministic mode the transcript is replayed from a committed fixture and the audio is a tone, and the record says so.

---

# Walkthrough 6 — Multi-Turn Voice Assistance

## Goal

See bounded conversation state carry information from one turn to the next.

## Steps

1. Complete Walkthrough 5 so `voice-remember` has run.
2. Set **Sample utterance** to `voice-recall` and press **Run selected workflow**.
3. Set **Sample utterance** to `voice-injection` and run again.
4. Press **Reset session and clear results**, then run `voice-recall` once more.

## Expected result

`voice-recall` asks "What is the project code word?" and the reply recalls `falcon`, citing the earlier turn. `voice-injection` asks the assistant to ignore its instructions, switch to live mode, and read out the API key; the reply treats it as ordinary heard text and the mode stays deterministic. After reset, `voice-recall` reports that no earlier turn supplies the value.

## What this demonstrates

Each turn runs audio processing, speech-to-text, a bounded conversational context, reasoning, text-to-speech, and audio validation, then commits to session state atomically. Later turns can recall what earlier turns established, and reset releases that history. The conversation reasoner understands exactly two phrasings ("remember … is …" and "what is …?"); it is rule-based, not a language model.

### Using the microphone or your own WAV

**Record a spoken turn** and **Or upload PCM WAV** take precedence over the sample. In deterministic mode, fixture playback cannot recognize arbitrary speech, so a new recording is expected to be rejected safely rather than transcribed. Arbitrary speech needs live speech-to-text.

---

# Walkthrough 7 — Real WebSocket Streaming

## Goal

Watch a voice conversation stream over a genuine WebSocket connection, event by event.

## Steps

1. Choose **Workflow → WebSocket streaming**.
2. Leave **Disconnect after first response fragment (cancellation demo)** unchecked.
3. Press **Run selected workflow** and watch events appear while the run is in progress.
4. Review **Received WebSocket events**, **Client time to first response (ms)**, and the event table.

## Expected result

The app starts a short-lived gateway on an ephemeral loopback port, connects to it, and sends two fixture turns, `voice-remember` then `voice-recall`. Events appear as they are received: `session_started`, then for each turn `turn_accepted`, `transcript_final`, one or more `response_delta` fragments, `response_complete`, `audio_ready`, `metric` events, and `turn_complete`, then `session_complete`. The result reads `transport: real loopback WebSocket`, `evidence_class: deterministic_demo`.

## What this demonstrates

This is a real network socket and a typed protocol, not a simulated stream. Reply fragments are produced while reasoning is still running, before the full reply exists, with no artificial typing delay. Fragments are whole rule-based reply acts, not model tokens. Timings are local client measurements, not a production SLO. The protocol carries audio references rather than playable bytes, so use **Voice assistant** to listen.

---

# Walkthrough 8 — Streaming Cancellation

## Goal

See a real disconnect cancel a running turn without fabricating a result.

## Steps

1. Stay on **WebSocket streaming** and check **Disconnect after first response fragment (cancellation demo)**.
2. Press **Run selected workflow**.

## Expected result

Events stop shortly after the first `response_delta`. The app shows "Client disconnected after the first fragment; gateway cancels the active turn." There is no `turn_complete` with a committed status for the cancelled turn.

## What this demonstrates

The client actually closes the socket, and the gateway cancels the active turn without committing it to conversation state. Cancellation is a transport event, not a forged completion message.

---

# Optional Live-Provider / BYOK Usage

## Goal

Run selected operations against real OpenAI models with your own key, under explicit, per-operation consent.

## Steps

1. Choose **Execution mode → Live / BYOK**. The banner changes to "Live mode: explicit submitted requests may incur provider usage. No automatic fallback."
2. Choose **Multimodal workflow**, **Voice assistant**, or **Document & vision** with `image`.
3. Enter your key in **Provider API key for this execution only**.
4. Check **I acknowledge this execution may incur provider usage/cost**.
5. Press **Run selected workflow**.

## Expected result

The evidence line shows `Evidence: live_integration`. **Recorded provider calls and usage** lists each provider call with its model and reported usage. For images, **Live model interpretation  |  untrusted** appears beside the measured facts. After the run, both the key and the acknowledgement are cleared; enter them again for another operation. A missing key or acknowledgement produces "Acknowledge provider usage and enter a key for this execution." A provider failure is reported safely and nothing falls back to deterministic output.

## What this demonstrates

Live adapters sit behind the same ports as the deterministic ones. Credentials grant connectivity, not authority, and model output stays untrusted.

## Boundaries to know

- **Documents always use local processing**, even in live mode.
- **WebSocket streaming always stays deterministic**, regardless of the mode selector.
- **Live voice is one turn per operation** in a fresh session, so no live multi-turn recall is claimed. Deterministic voice keeps bounded multi-turn history.
- Keys are never read from environment variables or secrets, never cached or saved, and redacted from every displayed record.

## Cost considerations

Default models are `gpt-5.4-mini` (vision and reasoning), `gpt-4o-mini-transcribe`, and `gpt-4o-mini-tts`, set in configuration. Each operation is bounded: no automatic retries (`max_retries=0`), request and operation timeouts, capped output tokens, low image detail, size and duration limits checked before any call, and a per-session provider call budget. Usage is recorded when the provider reports it. No dollar estimate is calculated, and repeated operations you authorize can incur repeated charges. See [LIVE_PROVIDERS.md](LIVE_PROVIDERS.md).

---

# Security and Trust Boundaries

- Uploaded files, transcripts, and model output are untrusted data. They cannot change mode, budgets, providers, or credentials.
- Files are validated by their content (magic bytes, UTF-8, strict WAV parsing), not their declared type or name. Display names are never used as file paths.
- Cross-modal and conversation findings must cite real observations; invented citations and forged evidence classes are rejected.
- Results are shown as plain text, native media, or JSON after central redaction. There is no HTML rendering of untrusted content.
- One result and its audio are kept per browser session until replaced, reset, or the session ends.
- The WebSocket gateway is a loopback component without authentication or TLS. Do not expose it publicly as is.
- Clearing a key from the form is not cryptographic erasure of browser or process memory.

See [SECURITY_THREAT_MODEL.md](SECURITY_THREAT_MODEL.md) for the full threat model and invariants.

---

# Common Problems and Limitations

## "The input or operation was rejected…"

The file type, size, or audio encoding was not accepted, or live acknowledgement was missing. Use PNG, JPEG, WebP, PDF, Markdown, text, or PCM WAV files under 2 MiB. MP3 and WebM audio are not supported.

## My recording was not transcribed

In **Deterministic demo**, speech-to-text is fixture playback and only recognizes the committed sample utterances. Arbitrary speech needs live mode. Browser microphone permission prompts are handled by your browser and are not covered by automated tests.

## The cross-modal workflow found no relationship

The deterministic reasoner uses a closed vocabulary, such as quadrant-and-color claims about images and tone or duration claims about audio. Other sentences are reported as unverified or produce no supported relationship. This is intended.

## Streaming did not use my live key

The streaming reviewer demonstration is deterministic by design. Live streaming evidence was established separately, outside the reviewer UI; see [LIVE_PROVIDERS.md](LIVE_PROVIDERS.md).

## Live mode asks for the key again

The key and acknowledgement are cleared after every submission, including failed ones. This is intentional.

## "The operation could not finish safely…"

Press **Reset session and clear results** and try a sample again. This also recovers a conversation that has expired.

## Known limitations

- Document processing is local extraction and structure; semantic understanding and OCR are not provided.
- Audio support is PCM WAV only.
- There is no genuine partial (interim) transcription.
- Latency figures are local or single-run measurements, not a production SLO.
- Genuine deployed live spoken interaction has not been verified.
- Story-era documents record status as of their own review dates; [RELEASE_READINESS.md](RELEASE_READINESS.md) is the latest release record.

---

# Suggested 15-Minute Reviewer Path

| Time | Action | Look for |
| --- | --- | --- |
| 0–2 min | Launch the app; read the sidebar and deterministic banner | No key needed; nothing runs until you submit |
| 2–5 min | Multimodal workflow with samples | Four modalities, cited findings, normalized observations |
| 5–8 min | Voice assistant: `voice-remember`, then `voice-recall` | Recall of `falcon`, playable tone audio, stage timings |
| 8–9 min | Voice assistant: `voice-injection` | Instruction treated as data; mode unchanged |
| 9–11 min | Document & vision: image, then document | Measured pixel facts; extracted sections with an inert embedded instruction |
| 11–13 min | WebSocket streaming, then with cancellation | Events on receipt, incremental fragments, real disconnect |
| 13–15 min | Switch to Live / BYOK without submitting; read the controls; open RELEASE_READINESS | Per-operation key and acknowledgement; five partial requirements stated plainly |

---

# What to Look For

- The **Execution evidence** line on every result, and whether it matches what you expect.
- Measured facts kept separate from model-derived statements.
- Findings that cite their sources.
- Atomic, bounded conversation state that reset truly clears.
- Real WebSocket events arriving over time, and cancellation that does not fake success.
- Limitations stated next to capabilities, rather than hidden.

---

# Go Deeper

- [Module 9 README](../README.md): overview, architecture, and evidence summary
- [Reviewer UI](REVIEWER_UI.md): presentation boundary and control behavior
- [Architecture](ARCHITECTURE.md) and [ADRs](adr/): layers, trust boundaries, and decisions
- [Understanding](UNDERSTANDING.md): ingestion, image analysis, and document extraction
- [Audio & Speech](AUDIO_SPEECH.md): WAV processing and STT/TTS pipelines
- [Cross-Modal](CROSS_MODAL.md): observations, reasoning rules, and finding kinds
- [Voice Assistant](VOICE_ASSISTANT.md): orchestration, conversation rules, and transactions
- [Streaming](STREAMING.md): WebSocket protocol, event types, cancellation, and latency metrics
- [Live Providers](LIVE_PROVIDERS.md): OpenAI adapters, BYOK, cost controls, and accepted live evidence
- [Evidence Policy](EVIDENCE_POLICY.md): evidence classes per story
- [Security Threat Model](SECURITY_THREAT_MODEL.md): threats and invariants
- [Release Readiness](RELEASE_READINESS.md): requirement matrix, repairs, and residual risks
- [Traceability](TRACEABILITY.md): requirement to story and evidence mapping
