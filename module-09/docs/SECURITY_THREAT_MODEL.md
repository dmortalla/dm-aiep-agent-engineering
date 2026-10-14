# Module 9 Security and Threat Model

## Status

Story 9.1 design, updated for Story 9.2. Controls marked "contract" are enforced today by the
typed models in `src/multimodal_voice_platform/contracts/` and covered by automated tests. Controls
marked "9.2" are enforced by the deterministic foundation and its tests. Every other control is
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
| Sensitive content retention | Session-scoped references deleted at session end | SEC-022 |
| Error leakage | `SafeError` with code, bounded message, and retryable flag only | SEC-023 |
| Overstated evidence | `EvidenceRecord` validators; UI labels every result with its class | SEC-025 |
| Ambiguous trust or validation | Reject rather than default | SEC-026 |

## Security invariants

| ID | Invariant | Control | Enforced now | Stories |
|---|---|---|---|---|
| SEC-001 | Untrusted multimodal input separation | `TrustLevel` on every `ModalityInput` | Contract | 9.1, 9.3, 9.5 |
| SEC-002 | MIME/type validation | Per-modality media type allowlist | Contract | 9.1, 9.3, 9.4 |
| SEC-003 | Extension/content consistency | Extension must match media type; magic-byte check at ingestion | Contract (extension); 9.3/9.4 (content) | 9.1, 9.3, 9.4 |
| SEC-004 | Safe filename/path handling | Safe `display_name`; opaque `content_ref` | Contract | 9.1, 9.3 |
| SEC-005 | File-size limits | Hard byte ceilings per modality; `ResourceBudget` | Contract | 9.1, 9.3, 9.4 |
| SEC-006 | Audio-duration limits | Audio requires `duration_ms` within ceiling | Contract | 9.1, 9.4 |
| SEC-007 | Bounded document processing | Page and size ceilings | Contract | 9.1, 9.3 |
| SEC-008 | Malformed/unsupported input rejection | `extra="forbid"`; unknown types and events rejected | Contract | 9.1, 9.3, 9.7 |
| SEC-009 | Prompt-injection containment | Content as data in reasoning context | Planned | 9.5, 9.10 |
| SEC-010 | No arbitrary command execution | No shell/eval path; governance test scans source | Contract (test) | 9.1, 9.10 |
| SEC-011 | No authority from model/provider/content output | Fixed untrusted trust on results | Contract | 9.1, 9.5, 9.8 |
| SEC-012 | Provider/network trust boundaries | Only live adapters reach the network | Deterministic adapters (9.2: no network imports; socket-blocked test); 9.8 (live) | 9.2, 9.8 |
| SEC-013 | Outbound provider allowlisting | `SessionConfig.allowed_live_providers` allowlist (empty by default, so live fails closed) | Contract (allowlist); 9.8 (endpoints) | 9.1, 9.8 |
| SEC-014 | Bounded payloads | Text, delta, transcript, event size bounds | Contract | 9.1, 9.7 |
| SEC-015 | Timeout behavior | Timeout ceilings in `ResourceBudget` | Contract (bounds); 9.8 (enforcement) | 9.1, 9.8, 9.10 |
| SEC-016 | Bounded retry behavior | `max_retries` ceiling of 3 | Contract (bounds) | 9.1, 9.8 |
| SEC-017 | No uncontrolled retry loops | Retries consume provider-call budget | Contract (bounds); 9.8 (enforcement) | 9.1, 9.8, 9.10 |
| SEC-018 | Secret redaction | `SecretStr`, excluded from dumps and repr | Contract | 9.1, 9.8 |
| SEC-019 | No secrets in logs, traces, evidence, URLs, source control, or committed config | Credential never in emitted models; payload scanning tests | Planned | 9.8, 9.10 |
| SEC-020 | Explicit opt-in live credentials | Live requires `live_opt_in=True` and a credential | Contract | 9.1, 9.8 |
| SEC-021 | Ephemeral user-supplied credentials | Session memory only, never persisted | Planned | 9.8, 9.9 |
| SEC-022 | No unnecessary retention of sensitive content | Session-scoped references, deleted at session end | Deterministic content store (9.2: in-memory, released per session); 9.9/9.10 (UI and uploads) | 9.2, 9.9, 9.10 |
| SEC-023 | Safe structured errors | `SafeError` model | Contract | 9.1, 9.7 |
| SEC-024 | Testable expected failure paths | Rejection tests for every contract | Contract (tests) | 9.1, 9.10 |
| SEC-025 | Accurate evidence classification | `EvidenceRecord` validators | Contract | 9.1, 9.9, 9.10 |
| SEC-026 | Fail closed when trust or validation is uncertain | Reject, never default | Contract | 9.1, 9.10 |

"Contract" means the typed model rejects the violation today and a test proves it. It does not mean
the end-to-end runtime control exists. Runtime enforcement arrives with the listed stories.
