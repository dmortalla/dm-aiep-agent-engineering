# ADR-009-006: Normalize Multimodal Input Before Reasoning

## Status

Accepted (human-approved, 2026-10-14)

## Context

Text, images, audio, and documents arrive in different shapes and carry different risks. Reasoning
over raw, unvalidated content is unsafe and hard to test.

## Decision

All input is normalized into a validated, typed `ModalityInput` carrying modality, media type,
content reference (or bounded inline text), size, source, session, and trust classification.
Modality-specific processing (vision, document understanding, STT) precedes cross-modal reasoning.

## Consequences

- Unsupported modalities, media types, and extension mismatches are rejected, not guessed.
- Binary content is held by opaque reference, never by a caller-controlled filesystem path.
- The reasoning port receives processed, typed parts, each still marked untrusted.
