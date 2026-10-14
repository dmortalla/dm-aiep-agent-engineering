# ADR-009-007: External and Model-Derived Content Is Untrusted

## Status

Accepted (human-approved, 2026-10-14)

## Context

Images, audio, documents, text, metadata, transcripts, and model output can all carry prompt
injection or forged instructions.

## Decision

All such content is untrusted. It cannot grant authority or directly control privileged
application behavior. Only application configuration and code decide execution mode, budgets,
provider selection, credentials, and any consequential action.

## Consequences

- `ModalityInput.trust` must be `UNTRUSTED_EXTERNAL`, and provider results must be
  `UNTRUSTED_MODEL_OUTPUT`. Contracts reject anything else.
- Reasoning prompts present content as data, not as instructions.
- No shell, subprocess, or eval path is reachable from content or model output.
