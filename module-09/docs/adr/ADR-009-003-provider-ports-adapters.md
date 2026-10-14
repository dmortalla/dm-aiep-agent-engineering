# ADR-009-003: Use Ports/Adapters for Multimodal Providers

## Status

Accepted (human-approved, 2026-10-14)

## Context

The platform needs STT, TTS, vision, document understanding, and reasoning, each in a deterministic
form for reviewers and CI and a live form for opt-in real providers.

## Decision

Each capability sits behind an explicit typed port: `SpeechToTextPort`, `TextToSpeechPort`,
`VisionPort`, `DocumentUnderstandingPort`, and `ReasoningPort`. Deterministic and live adapters
implement those same ports. No further abstraction is added unless a concrete need justifies it.

## Consequences

- The core depends on ports, not vendors.
- Ports expose no tool execution, shell access, or authority-granting operations.
- Every port result is marked `UNTRUSTED_MODEL_OUTPUT` (ADR-009-007).
- Story 9.1 defines the ports as `typing.Protocol` contracts. No adapter exists yet.
