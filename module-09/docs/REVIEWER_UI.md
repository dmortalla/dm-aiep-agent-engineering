# Story 9.9 presentation implementation

The frozen architecture assigns Streamlit to presentation. This story implements that approved
boundary without moving orchestration or validation into the UI.

- `ui/app.py`: native widgets, forms, plain-text results, bounded result retention per browser session.
- `ui/reviewer.py`: typed presentation facade selecting existing services and returning their records.
- `ui/socket_demo.py`: transport client for the existing gateway, hosted for one bounded operation
  on an ephemeral loopback port. Events are parsed through the existing typed protocol and delivered
  to the renderer on receipt. Disconnect-after-first-fragment demonstrates genuine cancellation.
- `streamlit_app.py`: launcher; `.streamlit/config.toml`: local-only, no usage telemetry, upload bound.

Deterministic mode is default. Fixture-based voice turns share one bounded conversation until reset;
live voice sessions last only one submitted operation so no credential-bearing object survives it.
Live form submit callbacks remove the password widget value before execution and never store the
credential in application results, caches, query parameters, or retained service instances. Live
binding construction is lazy and exists only within the explicit operation. No provider call is
made on render, widget changes, or rerun. Credentials are not loaded from environment or secrets.

This is local reviewer integration, not authenticated hosting. No application server survives a
streaming action. The WebSocket protocol carries audio references, not raw generated audio; the
voice path supplies playable audio separately. Local/demo latency is not a production SLO.


## Reviewer guide

Launch from Module 9: `uv run streamlit run streamlit_app.py`. The server binds loopback only;
usage telemetry is disabled and each uploaded file is capped at 2 MiB. No external fonts/assets
or browser audio subsystem are required. Use the native microphone widget or PCM WAV upload;
the core rejects unsupported or malformed encodings. AppTest does not exercise browser hardware.

1. Multimodal workflow: submit the four-modality repository sample, inspect normalized observations
   and citations, then disable samples to supply text plus another supported modality. The default
   reasoner is rule-based, not model inference. Fixture playback is not speech recognition.
2. Voice assistant: run `voice-remember`, then select `voice-recall`. Transcript, reply, generated
   WAV audio, adapter identities and stage timings come from `VoiceAssistant`. The deterministic
   audio is a tone sequence, not speech synthesis. Reset clears history, results and retained audio.
3. Document & vision: run the default image, then select document and submit again. Primary output
   shows measured image descriptions or locally extracted document sections; raw structured results
   remain inspectable. No OCR or semantic document model is claimed.
4. WebSocket streaming: submit to observe a real connection, typed events, fragments, completion
   and client receipt timings. The client sends remember/recall turns through the existing gateway.
   Disconnect-after-first-fragment exercises real transport cancellation; it does not fabricate a
   successful result. This reviewer streaming path deliberately remains deterministic even when the
   global selector is live. Audio references in this protocol are not playable bytes.
5. Live / BYOK: choose multimodal, voice or image analysis, enter a masked key, acknowledge cost,
   then explicitly submit. No provider call occurs on render, rerun, or widget changes. Documents
   always use local processing. A live voice operation is one turn; no live multi-turn recall is
   claimed. The key and acknowledgement are removed on submit, including failed submissions. Enter
   both again for a subsequent action. No environment variable is consulted for credentials.

## Evidence and acceptance

Story 9.9 is complete and ready for independent review. Evidence is `automated_test`: native
Streamlit AppTest exercises actual renderer/services and guarded real loopback WebSocket tests
exercise receipt order and cancellation. Runtime reviewer records request `deterministic_demo`;
those records are inspected by the UI tests, but the test run itself is automated evidence.
Optional live UI execution uses Story 9.8's existing evidence ladder. Mocked transport cannot claim
`live_integration`; tests explicitly prove the UI fails closed instead of relabeling or falling back.
No live UI acceptance or real provider call was performed for Story 9.9. Prior Story 9.8 accepted
live evidence remains separate. No production latency SLO is inferred from local measurements.

Module 9 remains incomplete. Story 9.10 local engineering acceptance is ready for independent review. Deployment, deployed
verification/security acceptance, live UI acceptance and LinkedIn publication remain outstanding.
No deployed or publicly accessible Streamlit application is claimed. Microphone hardware/browser
permission UX is not covered by headless tests. The framework necessarily holds widget inputs in
browser/process memory; clearing references is not a claim of cryptographic memory erasure.

## Security and lifetime

Results are rendered only as plain text, native data/media or JSON, with central redaction. There
is no untrusted HTML renderer, external URL input, arbitrary filesystem selector, shared credential
cache, or persisted live service. One result and generated audio are retained per browser session
until replaced/reset or the session ends; deterministic history has existing core bounds/timeouts.
A new submission clears prior output so a failure cannot display an old result as current success.
The short-lived streaming server is shut down in `finally`; disconnect cancels the active gateway
turn. Only loopback sockets are required for deterministic streaming.

## Story 9.10 regression acceptance

Structured records are redacted after JSON decoding, so JSON escaping cannot conceal known
credential values. Reset recovers from a conversation already closed by expiry. Production
acceptance exercises concurrent UI worker WebSocket isolation and renderer-failure cleanup.
The full local review and pending release gates are in [RELEASE_READINESS.md](RELEASE_READINESS.md).
No live UI or deployed browser behavior is established by this automated acceptance.
