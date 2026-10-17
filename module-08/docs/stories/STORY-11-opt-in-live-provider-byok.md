# Story 11 — Opt-in live provider / BYOK mode (post-release, additive)

## Status and baseline

Implemented for independent review; uncommitted. Date: 2026-10-16. Verified baseline:
HEAD `d3ae9e9d68b73597b11ffcbb45769fa00cd06b4b` (style: reduce module 8 reviewer glare);
`git merge-base --is-ancestor d3ae9e9d… HEAD` returned 0. The published tag
`v0.8.0-module-8` still resolves to `06f1c8e34fcc8f7958e7e7e69057aaec731a2957` and was
not touched. Module 8 began clean. Requirements are unchanged: the frozen architecture
already permitted isolated, opt-in, bounded, classified live-provider execution.

## Design

The smallest live demonstration that stays inside the MCP interoperability workflow:
each live model, through its own SDK, uses one application-authorized MCP capability
of the existing OpenAI SDK → Google ADK → OpenAI SDK workflow. No standalone chat
completion was added.

| Stage | Deterministic Demo (default) | Live Provider Demo (opt-in) |
|---|---|---|
| 1 `get_customer` | OpenAI Agents SDK MCP call, no model | Genuine OpenAI model via Agents SDK `Runner` and `MCPServerStreamableHttp` |
| 2 `get_account_status` | Google ADK `McpToolset` call, no model | Genuine Gemini model via ADK `Runner`, `Gemini` and `McpToolset` |
| 3 `evaluate_enterprise_policy` | OpenAI SDK MCP call, no model | Same; never a model |

A reviewer may enable either provider or both; an unselected stage uses the accepted
deterministic SDK path. Locked versions inspected: `openai-agents` 0.23.1, `openai`
3.29.0, `google-adk` 2.10.0, `google-genai` 2.30.0, `mcp` 2.3.0, `streamlit` 1.66.0.
Interfaces were taken from the installed sources (`OpenAIResponsesModel(openai_client=…)`,
`RunConfig(tracing_disabled=…)`, `MCPServerStreamableHttp(failure_error_function=None)`,
static tool filters, ADK `Gemini(client_kwargs=…)`, `RunConfig(max_llm_calls=…)`,
tool/model callbacks), not guessed.

## Authority and security controls

- Role and customer come only from the fixed application scenario.
- `CapabilityPolicy` authorizes the stage's single capability before the model sees
  anything; an unknown role is denied before any model request.
- The model is shown only that capability (SDK tool filter).
- Every model-proposed call passes an application guard: policy re-check, exact
  capability name, exact application-bound arguments and one call only. A violation
  stops the stage before the unauthorized MCP call runs.
- MCP results are strictly validated with the existing workflow contracts.
- Model text is bounded to 600 characters, rendered with `st.text` as untrusted
  narrative, and never feeds role, identity, arguments or the policy decision.
- No enterprise state is mutated; the policy evaluation remains read-only.

## Credential lifecycle and consent

- Keys enter only through password-masked inputs inside a Streamlit form.
- They are wrapped in `ProviderCredential` (`SecretStr`, redacting `repr`/`str`) and
  validated locally for presence and shape; no provider request validates a key.
- They are passed directly to a per-run client: `AsyncOpenAI(api_key=…, max_retries=0)`
  and ADK `Gemini` with `api_key`, `vertexai=False` and no retry options. Environment
  keys and ADC are never used for model calls; Agents SDK tracing export is disabled.
- The run executes in the form-submit callback, which overwrites both key widgets and
  both acknowledgements in session state before the page renders, so keys never
  outlive the run in server-side state and every run needs fresh consent.
- Every log record created during a run is rendered and scrubbed of the run's keys
  before any handler sees it. This repaired a defect found by testing: ADK's node
  runner logs full provider exception tracebacks, which could echo request detail.
- Keys never appear in evidence, results, UI errors (fixed messages only), files or
  databases, and are never written to the process environment.
- Consent requires the mode, an enabled provider, a key for it, both acknowledgements
  and the run button. The backend enforces `ProviderPolicy` independently of the UI.
  A pasted key for an unselected provider is ignored.

## Bounds

At most 2 OpenAI and 2 Gemini model calls per run (`max_turns`/`max_llm_calls` plus
call-counting hooks), 600 output tokens per call, one MCP tool call per stage, no SDK
or HTTP retries, 30s provider request timeout, 50s per stage, 120s per run, and one
live run per process. These bound calls, tokens and time. They are not a dollar-cost
guarantee: actual charges are set by the provider's pricing and account.

## Evidence classification

`classify_provider_execution` returns `live-provider` only for a genuine provider
boundary (default factory **and** a real `OpenAIResponsesModel`/`Gemini` instance) that
completed within bounds with at least one model call and a validated MCP result. Any
injected double is `mocked`, including one patched into the default factory path.
Failures raise and record no success. Model-free stages remain `local-integration`.
Each provider stage records provider, model, execution mode, whether an external
provider executed, model calls and bound, capability, what it proves and what it does
not prove.

Live mode proves that a provider model, through its SDK, chose and called one
application-authorized MCP capability with application-bound arguments. It does not
prove model accuracy, provider availability, billing amounts, authentication,
multi-host deployment or that the model holds any authority.

## How a reviewer runs each mode

- Deterministic Demo: unchanged; choose a scenario and **Run enterprise demonstration**.
- Live Provider Demo: choose the mode, pick a scenario, enable OpenAI and/or Gemini,
  choose an allowlisted model (`gpt-5.4-mini`/`gpt-5.4-nano`;
  `gemini-3.5-flash`/`gemini-2.5-flash`; availability depends on the reviewer's
  account), paste the key, tick both acknowledgements and **Run live provider
  demonstration**. The synthetic record `CUST-001` is sent to each selected provider.

## Tests

`tests/test_live_provider.py` adds 35 tests. Only the external model boundary is
replaced (Agents SDK `ScriptedModel`, a scripted ADK `BaseLlm`); the real loopback MCP
server, both SDK runners, guard, policy and validation execute. External sockets are
forbidden and ambient `OPENAI_API_KEY`/`GOOGLE_API_KEY`/`GEMINI_API_KEY` values are
planted to prove they are never used. Coverage: credential redaction/validation;
consent and selection enforced before services start; allowlisted models; evidence
classification; offline construction of the genuine clients with explicit keys and no
retries; mocked classification through the real SDKs and the default factory path;
single-provider selection; hostile model text cannot change role or decision; model
calls to unauthorized capabilities or changed arguments are blocked before execution;
unknown roles denied before any model request; OpenAI, ADK and deadline bounds;
missing tool use; redaction in errors and logs; ambient keys never trigger live
execution; console default mode, attribution, dark theme, masked inputs, risk/bounds
text, refusal paths, the full mocked live UI run and key/consent erasure. Existing
deterministic tests, including both reviewer AppTest scenarios, are unchanged.

## Verification

From `module-08`, fail-fast in the uv-managed Python 3.12 environment:

1. `uv run ruff check .`: All checks passed.
2. `uv run pytest`: **196 passed, 347 warnings**, exit 0. The known Windows
   `pytest-current` atexit PermissionError observation may follow success.
3. `uv run python -m compileall -q src tests app.py`: exit 0.

`git diff --check -- module-08` passed. Touched and new text files are UTF-8 without
BOM. Pinned ADK experimental/deprecation warnings remain visible and unsuppressed.

**No live or paid provider call was made during implementation or automated
acceptance.** No key was requested, created or used, and no Streamlit Cloud secret was
changed. Nothing was committed, pushed or tagged.

## Changed files (module-relative)

- `src/mcp_enterprise_integration/live_provider.py` (new)
- `src/mcp_enterprise_integration/reviewer.py` (additive live entry point)
- `src/mcp_enterprise_integration/console.py` (mode selector and live mode)
- `tests/test_live_provider.py` (new)
- `README.md`, `docs/ARCHITECTURE.md` (additive section), `docs/IMPLEMENTATION_PLAN.md`,
  `docs/TRACEABILITY.md`, this record

## Limitations

- The genuine provider path is verified by construction, offline tests and source
  inspection only; it has not been executed against a real provider.
- The allowlisted model names come from the installed SDKs and may not be enabled on
  every account; an unavailable model fails safely.
- Python cannot guarantee memory erasure of strings; keys live in process memory for
  the run and in the provider client until it is released.
- Google ADK's MCP session manager may probe ambient Google credentials for mTLS
  transport configuration unless `GOOGLE_API_USE_CLIENT_CERTIFICATE=false`; this does
  not select a credential for model execution.
- Live mode keeps the existing local reviewer scope: fixed scenarios, no
  authentication, loopback services.

## Independent review repair — 2026-10-17

The rejected logging race is repaired at `_redacted_logging`, including direct
workflow calls that bypass the reviewer's existing one-run admission control.
A credential-free process lock is acquired without waiting before reading or
installing the logging factory. An overlapping attempt receives a fixed safe
`LiveProviderError` before its provider factory or workflow body executes. It
cannot install a second scrubber, expose its credential through provider logs,
or restore a stale scrubber over the owner's factory. The owner restores the
exact preceding factory before releasing the slot, even on failure or cancellation.

This preserves the accepted one-live-run-per-process bound and existing useful
redacted SDK logs. No global credential registry or additional logging hooks are
introduced. The existing per-run factory remains temporary and exclusively owned;
the lock contains no credentials. Acquisition never blocks, so same-event-loop,
recursive, and cross-thread contention cannot deadlock. Contenders must retry
deliberately after completion; no queue, automatic retry, or extra provider call
is introduced. As before, unrelated components must not replace the process
logging factory during a live run.

Six adversarial offline cases overlap two direct workflow attempts with distinct
sentinel credentials across threads/event loops. They reverse credential ownership
and inject success, failure, and cancellation. They verify rejection before the
contender's body, unchanged owner factory after contender completion, redaction
of messages and exception tracebacks before and after contention, credential-free
captured record fields, exact final factory identity, and subsequent admission of
the other credential. Existing SDK redaction tests remain unchanged. These tests
replace the workflow body and cannot contact a provider; the existing external
socket prohibition also remains enabled.

Scope: only `live_provider.py`, `test_live_provider.py`, and this Story 11 record
were changed for the repair. Deterministic behavior, UI, consent, MCP authority,
provider bounds, and evidence classification are unchanged. Verification is
offline evidence only; no live/paid execution or deployment was authorized or run.
The change remains uncommitted and unstaged for independent review.

Repair gates (from `module-08`, fail-fast): `uv run ruff check .` passed;
`uv run pytest` passed **202 tests, 347 warnings**, exit 0;
`uv run python -m compileall -q src tests app.py` passed, exit 0.
The known Windows `pytest-current` cleanup PermissionError appeared after pytest
success. Existing ADK warnings and a reviewer coroutine warning remain visible.
The first Ruff invocation caught one overlong new assertion; it was wrapped and
the complete Ruff → pytest → compileall sequence then passed.

Completion assessment: requirements preserved; product experience unchanged;
real provider functionality not exercised; reliability verified for contention,
failure and cancellation; security regression verified offline; cost exposure
unchanged with no paid calls; evidence remains deterministic/mocked and local
integration only; deployment unchanged and unverified. This is a review repair,
not a release or production-readiness declaration.
