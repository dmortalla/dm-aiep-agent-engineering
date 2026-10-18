"""Provider-neutral live-execution core (Story 9.8).

Live configuration, ephemeral credentials, live bindings, sanitized live errors, redaction,
application-owned prompts and output schemas, and the streamed-JSON scanner. Nothing here imports a
provider SDK; provider-specific code lives in ``adapters/openai``. The live acceptance runner
(``live.acceptance``) is invoked separately and is never imported by this package.
"""
