# Module 9 Security and Threat Model

## Status

Story 9.1 design, updated for Stories 9.2 to 9.6. Controls marked "contract" are enforced today by
the typed models in `src/multimodal_voice_platform/contracts/` and covered by automated tests.
Controls marked "9.2" are enforced by the deterministic foundation and its tests. Controls marked
"9.3" are enforced at runtime on the image and document path (`ingestion/`, `adapters/local/`,
`understanding/`) and its tests (see [UNDERSTANDING.md](UNDERSTANDING.md)). Controls marked "9.4"
are enforced at runtime on the audio and speech path (`audio/`, `adapters/speech/`, `speech/`) and
its tests (see [AUDIO_SPEECH.md](AUDIO_SPEECH.md)). Controls marked "9.5" are enforced at runtime
on the cross-modal reasoning path (`contracts/reasoning.py`, `adapters/reasoning/`, `crossmodal/`)
and its tests (see [CROSS_MODAL.md](CROSS_MODAL.md)). Controls marked "9.6" are enforced at runtime
on the voice-assistant path (`contracts/conversation.py`, `adapters/reasoning/conversation.py`,
`voice/`) and its tests (see [VOICE_ASSISTANT.md](VOICE_ASSISTANT.md)). Every other control is
planned for the listed story and is **not implemented yet**.

## Assets

- User-supplied credentials (live mode only).
- Uploaded images, audio, documents, and text (potentially sensitive).
- Provider budgets (money) and service availability.
- Integrity of evidence shown to reviewers.

## Trust zones

| Zone | Trust | Examples |
|---|---|---|
| Application code and committed configuration | Trusted | Execution mode defaults, budgets, provider allowlist |
| Reviewer/user input | Untrusted (`UNTRUSTED_EXTERNAL`) | Uploads, microphone audio, typed text, filenames, metadata |
| Provider and model output | Untrusted (`UNTRUSTED_MODEL_OUTPUT`) | Transcripts, vision descriptions, document extractions, reasoning text |
| External providers | Untrusted network peer | STT, TTS, vision, document, reasoning APIs |

## Threats and mitigations

| Threat | Mitigation | Invariants |
|---|---|---|
| Prompt injection in image, audio, document, or text | Content is data in the reasoning context; never instructions, tool authority, or configuration | SEC-001, SEC-009, SEC-011 |
| Model output escalating privilege | Provider results are fixed to `UNTRUSTED_MODEL_OUTPUT`; mode, budgets, and credentials come only from application config | SEC-011 |
| Malicious or malformed files | Media type allowlist, extension consistency, size and page ceilings, strict models | SEC-002 to SEC-008 |
| Path traversal through filenames | `display_name` rejects separators, traversal, and control characters; content held by opaque reference | SEC-004 |
| Resource exhaustion and cost blowout | Hard ceilings plus `ResourceBudget`: sizes, audio duration, pages, tokens, timeouts, retries, history, provider calls | SEC-005 to SEC-007, SEC-014 to SEC-017 |
| Command execution | No shell, subprocess, or eval path; ports expose no tool execution | SEC-010 |
| Unapproved outbound calls | Live adapters only, allowlisted providers only, explicit opt-in only | SEC-012, SEC-013, SEC-020 |
| Credential leakage | `SecretStr`, excluded from serialization and repr; never in logs, events, evidence, URLs, or committed config; session memory only | SEC-018, SEC-019, SEC-021 |
| Sensitive content retention | Session-scoped references deleted at session end; conversations keep bounded text only | SEC-022 |
| Conversation-state abuse (forged state, replayed or concurrent turns, unbounded history) | Session configuration bound by application code; turn requests carry no authority fields; committed turn IDs rejected on replay; one running turn per session; bounded retention, context, turns, and provider calls; history changes only by atomic commit | SEC-001, SEC-011, SEC-017, SEC-022 |
| Error leakage | `SafeError` with code, bounded message, and retryable flag only | SEC-023 |
| Live provider credential exposure, implicit live use, or cost blowout (Story 9.8) | Explicit live sessions and bindings only; `SecretStr` key passed only to a per-call client; translated errors without chaining; redaction; fixed endpoint; zero retries; per-operation call, token, size, and time budgets | SEC-013, SEC-016 to SEC-021 |
| WebSocket abuse (cross-site hijacking, forged protocol fields, floods, slow or silent clients, oversized frames) | Exact-origin allowlist (empty by default); typed client messages with no authority fields; server-generated session IDs bound to the connection; connection, message, audio, fragment, event, and timeout bounds; compression off; disconnect cancels the turn without a commit. No authentication yet (Story 9.10) | SEC-008, SEC-011, SEC-014, SEC-015, SEC-022, SEC-023 |
| Overstated evidence | `EvidenceRecord` validators; UI labels every result with its class | SEC-025 |
| Ambiguous trust or validation | Reject rather than default | SEC-026 |

## Security invariants

| ID | Invariant | Control | Enforced now | Stories |
|---|---|---|---|---|
| SEC-001 | Untrusted multimodal input separation | `TrustLevel` on every `ModalityInput` | Contract; 9.3 (image/document runtime path); 9.4 (audio input and synthesis text); 9.5 (every observation and reasoning part untrusted, with origin labels); 9.6 (transcripts, conversation history, and replies untrusted) | 9.1, 9.3, 9.4, 9.5, 9.6 |
| SEC-002 | MIME/type validation | Per-modality media type allowlist | Contract; 9.3 (ingestion and adapter re-check); 9.4 (audio ingestion and analysis re-check) | 9.1, 9.3, 9.4 |
| SEC-003 | Extension/content consistency | Extension must match media type; magic-byte check at ingestion | Contract (extension); 9.3 (image/document magic bytes and UTF-8 checks); 9.4 (audio signatures and strict RIFF/WAVE parsing) | 9.1, 9.3, 9.4 |
| SEC-004 | Safe filename/path handling | Safe `display_name`; opaque `content_ref` | Contract; 9.3 (decoders read in-memory buffers only) | 9.1, 9.3 |
| SEC-005 | File-size limits | Hard byte ceilings per modality; `ResourceBudget` | Contract; 9.3 (byte budget at ingestion and in adapters; pixel limit before decoding); 9.4 (audio byte budget before parsing; generated-audio byte budget) | 9.1, 9.3, 9.4 |
| SEC-006 | Audio-duration limits | Audio requires `duration_ms` within ceiling | Contract; 9.4 (duration measured from the WAV header and checked before decoding; synthesis duration checked before rendering) | 9.1, 9.4 |
| SEC-007 | Bounded document processing | Page and size ceilings | Contract; 9.3 (page budget before PDF extraction; section and character caps) | 9.1, 9.3 |
| SEC-008 | Malformed/unsupported input rejection | `extra="forbid"`; unknown types and events rejected | Contract; 9.3 (malformed, encrypted, and text-less inputs rejected safely); 9.4 (malformed, truncated, pathological, and unsupported audio rejected); 9.7 (malformed, unknown, server-only, binary, and extra-field client messages and non-canonical base64 rejected with safe protocol errors; repeated errors end the session) | 9.1, 9.3, 9.4, 9.7 |
| SEC-009 | Prompt-injection containment | Content as data in reasoning context | 9.5 (each observation is a JSON-encoded part beside a fixed task; document, transcript, and forged-findings injections tested as inert data); 9.6 (transcript as one JSON-encoded part and history as untrusted turns beside a fixed task; injection-like transcripts, history, and forged reply documents tested as inert data; every reply act citation-checked) | 9.5, 9.6, 9.10 |
| SEC-010 | No arbitrary command execution | No shell/eval path; governance test scans source | Contract (test) | 9.1, 9.10 |
| SEC-011 | No authority from model/provider/content output | Fixed untrusted trust on results | Contract; 9.3 (embedded document instructions tested as inert data); 9.4 (injected transcripts and synthesis text tested as inert data); 9.5 (reasoning output citation-checked; conclusion derived by the workflow); 9.6 (turn requests carry no mode, budget, provider, or evidence fields; session configuration bound by application code; replies are spoken text only); 9.7 (client messages carry no session, mode, budget, provider, trust, or evidence fields; session IDs are server-generated; streamed classifications are server-authored) | 9.1, 9.4, 9.5, 9.6, 9.7, 9.8 |
| SEC-012 | Provider/network trust boundaries | Only live adapters reach the network | Deterministic adapters (9.2: no network imports; socket-blocked test); 9.3 local adapters (same checks); 9.4 audio and speech code (same checks); 9.5 cross-modal code (same checks); 9.6 voice code (same checks); 9.8 (live) | 9.2, 9.3, 9.4, 9.6, 9.8 |
| SEC-013 | Outbound provider allowlisting | `SessionConfig.allowed_live_providers` allowlist (empty by default, so live fails closed) | Contract (allowlist); 9.8 (endpoints) | 9.1, 9.8 |
| SEC-014 | Bounded payloads | Text, delta, transcript, event size bounds | Contract; 9.7 (client message, decoded audio, fragment, per-turn event, frame, frame-queue, and connection bounds; event size bound on send) | 9.1, 9.7 |
| SEC-015 | Timeout behavior | Timeout ceilings in `ResourceBudget` | Contract (bounds); 9.3 (local decoding bounded by `request_timeout_s`); 9.4 (audio decoding and every speech provider call bounded by `request_timeout_s`); 9.5 (reasoning call bounded by `request_timeout_s`); 9.6 (voice-turn reasoning bounded by `request_timeout_s`; sessions closed after `session_timeout_s`); 9.7 (streamed reasoning bounded by a request deadline; send, idle, and turn timeouts); 9.8 (enforcement) | 9.1, 9.3, 9.4, 9.6, 9.7, 9.8, 9.10 |
| SEC-016 | Bounded retry behavior | `max_retries` ceiling of 3 | Contract (bounds) | 9.1, 9.8 |
| SEC-017 | No uncontrolled retry loops | Retries consume provider-call budget | Contract (bounds); 9.6 (each voice turn reserves its three provider calls against `max_provider_calls_per_session`; failed turns are not refunded; no automatic retries); 9.8 (enforcement) | 9.1, 9.6, 9.8, 9.10 |
| SEC-018 | Secret redaction | `SecretStr`, excluded from dumps and repr | Contract | 9.1, 9.8 |
| SEC-019 | No secrets in logs, traces, evidence, URLs, source control, or committed config | Credential never in emitted models; payload scanning tests | 9.8 redaction and emitted-payload tests; final acceptance 9.10 | 9.8, 9.10 |
| SEC-020 | Explicit opt-in live credentials | Live requires `live_opt_in=True` and a credential | Contract | 9.1, 9.8 |
| SEC-021 | Ephemeral user-supplied credentials | Session memory only, never persisted | 9.8 ephemeral BYOK implemented; UI lifecycle acceptance 9.9 | 9.8, 9.9 |
| SEC-022 | No unnecessary retention of sensitive content | Session-scoped references, deleted at session end | Deterministic content store (9.2: in-memory, released per session); 9.3 (uploads released before each call returns); 9.4 (audio uploads and generated audio released before each call returns); 9.6 (conversations retain bounded text only, never audio, and release it when the session closes or expires); 9.7 (WebSocket sessions closed and released when the connection ends; audio never echoed); 9.9/9.10 (UI) | 9.2, 9.3, 9.4, 9.6, 9.7, 9.9, 9.10 |
| SEC-023 | Safe structured errors | `SafeError` model | Contract; 9.7 (only `SafeError` crosses the WebSocket; unexpected failures logged server-side and replaced by a fixed `internal_error`) | 9.1, 9.7 |
| SEC-024 | Testable expected failure paths | Rejection tests for every contract | Contract (tests) | 9.1, 9.10 |
| SEC-025 | Accurate evidence classification | `EvidenceRecord` validators | Contract | 9.1, 9.9, 9.10 |
| SEC-026 | Fail closed when trust or validation is uncertain | Reject, never default | Contract | 9.1, 9.10 |

"Contract" means the typed model rejects the violation today and a test proves it. It does not mean
the end-to-end runtime control exists. Runtime enforcement arrives with the listed stories.

## Story 9.8 evidence boundary

Accepted live integration establishes vision, STT, TTS, model reasoning, and provider streaming;
it does not confer trust or authority on model output. Explicit live opt-in, ephemeral BYOK,
secret redaction, fixed provider endpoint allowlisting, bounded provider calls/cost/time,
`max_retries=0`, and no deterministic fallback remain mandatory. Pydantic and provenance checks
fail closed. Shared-concept terms must occur literally as whole words, case-insensitively, in
each cited observation's statement text; omit the finding if fewer than two terms qualify.
Mocked/test-double/deterministic execution cannot claim `live_integration`. Credentials and raw
sensitive provider payloads are excluded from repository evidence. Final production/security
acceptance, WebSocket authentication, TLS, and deployment remain Story 9.10 work.
