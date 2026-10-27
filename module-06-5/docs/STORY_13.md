# Story 13: secure dual-mode provider completion (ENG-008, ADR 002)

Story 13 implements the secure opt-in live-provider seam and the deterministic
verification proving it ready for a separately authorized live exercise. The
sections up to "Second live-run compatibility repair" are the original Builder
record, written before any live call; at that time no live call was made and
live-provider evidence was none. A later bounded, human-authorized exercise
succeeded and was independently accepted as live-provider evidence; see "Live-
provider evidence chronology and acceptance" below. That evidence is not
deployment validation.

## Baseline

Isolated worktree `WORKTREES/dm-aiep-agent-engineering/module-06-5`, branch
`isolated/module-06-5`, HEAD `4c4a2f5` ("fix(module-06-5): enforce
production-grade dual-mode contract"), nothing staged, no upstream. The tree
held an unstaged, uncommitted Module 6.5-owned Story 13 draft (config,
cost-governance, provider, vendor-adapter, reviewer-UI edits and a draft test
module). It was reviewed rather than accepted as-is: it broke three accepted
tests, left credential sourcing to SDK environment discovery, enforced no
pre-dispatch cost bound, never checked that its tariff matched the bound
provider/model, and would have replaced the fixture ledger's unconditional
live-tariff denial. Useful parts were kept; the cost-governance change was
reverted to baseline.

## Architecture implemented

Dispatch on the live path happens only when every gate below passes, in order.
Each gate fails closed and none can be satisfied by model, tool, MCP, memory,
browser, or serialized data.

1. **Configuration** (`config.py`). `HarnessConfig` stays deterministic by
   default (`live=None`). The optional `LiveProviderPolicy` (strict, frozen)
   holds `allowed_providers`, per-provider `allowed_models`, and
   `credential_source` (`environment` or `secret_store`). Every model must be
   in the application-owned `SUPPORTED_LIVE_MODELS` catalog; every allowed
   provider needs its own non-empty model allowlist. A policy is valid only
   with `deterministic_mode=False`, `allow_live_providers=True`,
   `require_human_approval=True`, a finite `max_cost_usd`, and limits inside
   the live ceilings (cost ≤ 1.00 USD, attempts ≤ 4, retries per action ≤ 1,
   output ≤ 1,024 and context ≤ 8,000 token units, action timeout ≤ 30 s,
   workflow deadline ≤ 120 s). Legacy opt-in without a policy stays
   constructible but can never bind a vendor adapter.
2. **Binding** (`vendor_providers._validate_binding`). The adapter's exact
   provider/model must be allowlisted by the revalidated policy, and the
   runtime budget must equal the configured budget.
3. **Trusted credentials** (`live_credentials.py`).
   `EnvironmentCredentialSource` reads only the fixed server variables
   `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`; `SecretStoreCredentialSource` calls a
   trusted lookup bound at bootstrap with fixed secret names. A live runtime
   requires a source whose kind matches the policy; offline runtimes reject
   any source. Credentials resolve only at invocation into an opaque
   `LiveCredential` (redacted repr, identity-only equality, unhashable,
   unpicklable, uncopyable) and are passed explicitly to one call-local SDK
   client, which disables SDK environment, profile, and federation credential
   discovery. Lookup failures surface one fixed message with no chained
   diagnostic. Credentials are never stored on runtime state.
4. **Human authorization** (`live_authorization.py`). An exact
   `LiveExecutionAuthorization` (provider, catalogued model, approved per-million
   input/output tariff upper bounds, `authorized_by`,
   `authorization_reference`, timezone-aware `expires_at`) must be bound at
   bootstrap for exactly the adapter's provider/model, expiring within seven
   days. `require_live_execution_authorization` re-checks type, scope, and
   expiry immediately before dispatch. Without it, a fully configured runtime
   with credentials present still cannot dispatch.
5. **Bounds** (`providers.ProviderRuntime`). Retries: SDK `max_retries=0`;
   application attempt and per-action budgets; failed attempts stay consumed.
   Latency: action and workflow deadlines feed the SDK timeout; late results
   are discarded. Tokens/output: request input bound before dispatch, SDK
   `max_output_tokens`/`max_tokens` set from the budget, reported usage and
   text validated against it. Cost: before dispatch the runtime reserves the
   fully bounded worst case, `(max_context_tokens + 256) × input tariff +
   max_output_tokens × output tariff`, and denies the call if cumulative
   exposure would exceed `max_cost_usd`. Bootstrap rejects an authorization
   whose single worst-case call cannot fit the budget. A provably undispatched
   attempt releases its reservation; reported usage settles it to the actual
   bound; otherwise the worst case stays consumed.
6. **Authority**. Output stays `ModelResult` (text plus `untrusted_model`
   trust, `grants_authority` is always False) and still passes the output
   filter and optional Guardrails. Capability permissions, HITL, workflow
   policy, the off-switch, the fixture-only ledger, MCP and external-tool
   flags are unchanged; a live policy cannot disable human approval.

The fixture ledger's `require_real_monetary_admission` is unchanged and still
denies every live tariff; the live path now uses the Story 13 authorization
gate instead.

## Evidence classification

`live_readiness.py` derives reviewer readiness from classified
`EvidenceRecord`s, never from credentials, adapter construction, or test
success. A `live_provider` record requires both an authorization reference and
an independent review reference; lower classes may not carry either.
`REPOSITORY_EVIDENCE` holds deterministic, adapter, and mocked records only, so
live OpenAI and Anthropic evidence report `not_executed` and provider-level
production readiness reports `not_claimed`. `ProviderRuntime.evidence_class`
never self-reports above `adapter`.

| Class | Story 13 basis |
| --- | --- |
| deterministic | Fake provider default; reviewer labs |
| mocked | Live seam with patched SDK resource `create` (`tests/test_story13_dual_mode.py`) |
| adapter | Genuine SDKs over MockTransport (`tests/test_vendor_providers.py`) |
| live-provider | None. Requires a separately authorized, independently evidenced exercise |
| deployment | Not part of Story 13 |

## Reviewer UI

`streamlit_app.py` gains a "Provider modes" section rendering
`provider_readiness()` and explaining that live execution needs trusted
server-side configuration plus explicit human authorization and cannot be
enabled from the page. No input widget, credential field, or BYOK control was
added; deterministic demonstrations are unchanged.

## Tests

New `tests/test_story13_dual_mode.py` (35 tests) covers the eighteen Story 13
verification items: deterministic default; explicit activation; credentials
alone insufficient; unknown provider; disallowed model; missing credential
before dispatch; accepted allowlisted path (credential reaches the SDK
explicitly, exposure settles); retry, latency, token/output, and cost bounds;
credential opacity and redaction in errors, runtime state, receipts, and audit;
untrusted output; HITL/policy/capability/off-switch preservation;
authorization scope, window, expiry, and forgery; adapter/mocked evidence never
satisfying live readiness; no credential-capable reviewer widget; keyless
reviewer demonstration; external-socket denial. New helper `tests/live_seam.py`
builds credential-free live fixtures.

Accepted tests realigned to the allowlist contract ENG-008 mandates, each
keeping and strengthening its original intent:

- `test_vendor_providers.py::test_missing_live_configuration_is_safe_without_looking_up_real_credentials`:
  legacy opt-in without policy is now denied at bootstrap; a missing trusted
  credential now fails before SDK construction; with a dummy credential the
  SDK receives only the application-resolved key and its configuration error
  stays sanitized. The old assertion that the SDK read its own environment
  credential is replaced, because Story 13 forbids SDK credential discovery.
- `test_vendor_providers.py::test_actual_sdk_missing_credentials_fails_before_request`:
  same check on an allowlisted, authorized runtime, plus reservation release.
- `test_usage_governance.py::test_real_dispatch_is_denied_even_with_legacy_optin_and_dummy_auth`:
  legacy opt-in is denied at bootstrap; an allowlisted runtime with dummy
  credentials and no human authorization is still denied before dispatch.

## Provider catalog currency repair (2026-10-25)

An operator-supplied official-provider check before the authorized live
exercise found the accepted OpenAI catalog stale (`gpt-4.1-mini` deprecated,
`gpt-4.1-nano` shut down; `gpt-5-mini`/`gpt-5-nano` also deprecated). The
repair, verified credential-free only:

- `SUPPORTED_LIVE_MODELS` is now `gpt-6-luna` (OpenAI) and
  `claude-haiku-5-5` (Anthropic). The deprecated and shut-down OpenAI models
  are rejected by the policy, the authorization, and the adapter binding.
  `claude-haiku-4-5` was removed because no current tariff was supplied for it,
  so its exposure could not be floor-checked.
- `PUBLISHED_LIVE_TARIFFS` records the supplied standard prices per million
  tokens: `gpt-6-luna` 0.10 input / 0.50 output; `claude-haiku-5-5` 0.10 /
  0.50 for prompts up to 100K tokens and 0.50 / 2.50 above 100K.
- Bootstrap now rejects any `LiveExecutionAuthorization` priced below the
  published tier covering the runtime's full prompt exposure
  (`max_context_tokens + 256`), so worst-case reservation can never be
  underpriced. An exposure above 100K takes the higher Haiku 5.5 tier. The
  live context ceiling (8,000 + 256 tokens) additionally keeps every live
  prompt inside the short-context tier.

At the time of this repair neither model had been live-tested.

## Output unit contract repair (2026-10-26)

Offline diagnosis of the two `ProviderOutputRejected` results from the first
authorized live exercise (`max_output_tokens=64`) found a unit-contract defect:
one field, `RuntimeBudget.max_output_tokens`, was both the provider token cap
sent to the SDK and the UTF-8 byte ceiling for returned text
(`vendor_providers.py` `_units(text) > context.max_output_tokens`;
`_units` counts bytes). Under valid reported usage (19 tokens), a 78-byte
sentence was rejected at the post-parse check with 64 as the cap, for both
adapters, while 64 bytes passed and 65 failed. This is deterministic and
reproduced offline. It is not established that the actual live responses had
this property: the failed run retained no response text, length, or rejection
message. Other offline-possible causes (for example an OpenAI reasoning item,
`incomplete` status, or unmodeled response fields) remain unresolved.

Repair: `RuntimeBudget.max_output_bytes` (new, optional, 1 to 16,384) is an
explicit local UTF-8 byte ceiling distinct from `max_output_tokens`, which
stays the provider token cap sent to the SDK and checked against reported
usage. When unset the legacy rule applies unchanged (byte ceiling equals
`max_output_tokens`), so no accepted behavior changed. The live policy now
requires it explicitly and caps it at `LIVE_MAX_OUTPUT_BYTES` (8,192). The
byte ceiling is not an unlimited path; the provider token cap, cost
reservation, usage validation, and payload limits are unchanged. This repair
does not claim to resolve the live failures and, at that time, the new models were not
live-tested.

## Second live-run compatibility repair (2026-10-26)

Evidence: the sanitized artifact of the second human-authorized live exercise
(256 output tokens, 4,096 output bytes; one attempt per provider). Proven live:
both providers authenticated and returned SDK-parsed responses and reached
application response validation. At that time no successful application-level live-provider
result existed yet, so no live-provider readiness was claimed. The first run's
exact rejection points remain unknown.

Proven rejection boundaries (rejecting source lines from the retained traces,
reproduced offline with genuine SDK classes over mocked HTTP):

- OpenAI `gpt-6-luna`: generic `_payload()` at the check that the dumped
  response has no top-level key outside the installed SDK model's fields.
  Reproduced at the identical line only with an unmodeled top-level key. The
  size of `encrypted_content` is not the cause: sizes of 16,385 bytes and above
  reject at a different line (the per-string check), and smaller values pass
  `_payload()`. Which unmodeled key the live response carried is unknown (the
  sanitizer retained field names only for output items). Independently, the
  observed reasoning item would have been rejected next by the former
  single-output-item rule.
- Anthropic `claude-haiku-5-5`: `_usage()` (the handler that re-raises every
  usage failure). With the observed values (35/33, cache counts 0, within all
  bounds) every field the installed SDK models is accepted; the only offline
  reproduction at this line is a usage key the SDK does not model. By
  elimination the live usage carried such a key, whose name is unknown.

Repairs, all fail-closed and text-only:

- Unknown top-level response fields and unknown usage keys are untrusted
  informational metadata under one shared rule (`_unknown_names_acceptable`):
  at most 16 unknown fields per object (top level: fields outside the SDK
  model; usage: keys outside the application's per-provider known usage keys,
  which do not count toward the 16), each named by an ASCII identifier of 1 to
  64 characters (`[A-Za-z0-9_]`); any other name, or a 17th field, fails closed
  (`payload_shape` at the top level, `usage_shape` for usage). Values are
  subject to every generic bound (depth, collection, string, 65,536-byte
  total). Unknown fields are ignored and discarded and do not influence
  authority, accounting, returned text, provider or model selection, tools,
  retries, budgets or pricing; their names are never echoed. Models unknown to the SDK still cannot change
  text extraction, accounting, budget, retry, pricing, or authority.
- OpenAI output accepts only zero to four validated `reasoning` items followed
  by exactly one final assistant message (last). The reasoning structure is
  closed (known keys, bounded summary/content parts, `encrypted_content` string
  only, status absent or completed) and is discarded before text extraction;
  tool, function, computer, MCP, search, unknown, extra or misplaced items are
  rejected. Reasoning text and encrypted content are never returned, persisted,
  or granted authority.
- `encrypted_content` alone has an explicit separate 32,768-byte cap; every
  other string keeps 16,384; the 65,536-byte total is unchanged.
- Usage normalization trusts only exact integer `input_tokens`/`output_tokens`
  within the context and output-token bounds (plus a consistent OpenAI
  `total_tokens`). Anthropic cache token counts must be absent or zero because
  caching is never requested. Anything else records MALFORMED (or MISSING),
  never an invented zero. Cost settlement uses only these normalized facts.
- `ProviderOutputRejected.point` carries a finite content-free
  `RejectionPoint` code (payload_shape, payload_limits, usage_shape,
  usage_bounds, output_profile, output_items, text_blocks, text_bytes, and
  others); the public message is unchanged. `describe_usage_shape` reports only
  field names, type classes, and the accounting counts.
- The unit contract from the previous repair is unchanged: `max_output_tokens`
  is the SDK and reported-usage token ceiling, `max_output_bytes` the returned
  text ceiling, and the cost reservation remains token-based.

Contract change flagged for review: two accepted tests asserted that unmodeled
top-level or usage metadata (including hostile-looking values) is rejected. The
live evidence shows legitimate responses carry such metadata. They now assert
that bounded metadata is ignored and inert while unbounded metadata still fails
closed. Neither new model has produced a successful live-provider result.

## Live-provider evidence chronology and acceptance (2026-10-27)

Three human-authorized, bounded live exercises were run from outside the
repository; the operator-run scripts and raw artifacts stay external.

1. **First attempt: failed.** Both providers returned
   `ProviderOutputRejected` at `max_output_tokens=64`. The exact rejection
   points were not retained. The output-unit defect (provider tokens vs UTF-8
   bytes) it exposed was repaired; whether it caused those failures was never
   established.
2. **Second attempt: failed**, with sanitized structural diagnostics that
   captured the application validation boundaries: OpenAI at the generic
   payload check for unmodeled top-level response fields, Anthropic at the
   usage handler for unmodeled usage keys. The reasoning-item contract,
   bounded unknown-metadata policy and rejection-point codes were repaired
   and independently reviewed.
3. **Third attempt: succeeded for both providers.** Baseline
   `e1e5e1ac5f931f95a146c85baaace40cc3357230`. The independent review
   disposition is `ACCEPTED — LIVE_PROVIDER EVIDENCE VERIFIED`: evidence hash
   matched, the artifact was unchanged, the worktree was clean, both runs were
   genuinely live with one attempt and no retry, and both responses satisfied
   the reviewed application contract.

Accepted record (repository-owned, typed, in `live_readiness.py`
`ACCEPTED_LIVE_EXERCISES`; no response text, reasoning content, credentials or
raw provider errors are representable):

| Item | OpenAI `gpt-6-luna` | Anthropic `claude-haiku-5-5` |
| --- | --- | --- |
| Status / attempts / retries | success / 1 / 0 | success / 1 / 0 |
| Input / output tokens | 20 / 39 | 35 / 27 |
| Returned text | 27 UTF-8 bytes | 86 UTF-8 bytes |
| Cache creation / read input tokens | n/a | 0 / 0 |
| Live exposure | 0.0000215 USD | 0.0000170 USD |

Bounds: `max_context_tokens=512`, `max_output_tokens=256`,
`max_output_bytes=4096`, `max_cost_usd=0.001` per provider,
`max_provider_attempts=1`, `max_retries_per_action=0`,
`action_timeout_seconds=20`. The sanitizer recorded counts only for fields the
SDK does not model (OpenAI: six unmodeled top-level fields; Anthropic: one
unmodeled usage key), confirming that live responses carry such metadata; their
names were not retained.

External artifact (immutable, stored under the engineering evidence folder, not
in this repository): `module-06-5-third-live-evidence-20261027-002708.json`,
SHA256 `389287FC65C9F51F84850E2D2929C50EC21FDEC4B70BC902FD0CE65100D7FCF4`.
It records no response content and no credential values, and the repository was
unchanged during the run. No deployment was performed.

Classification: the runtime reports `adapter` for itself and cannot promote
itself; the `live_provider` class is applied only by the repository evidence
record, as the outcome of independent review, never by runtime code. The
claim this supports is: the bounded, human-authorized live-provider path was
exercised against both currently supported providers and models under the
reviewed controls. It is not universal provider validation, provider-SLA
validation, billing accuracy beyond this run, deployment validation, or
scale readiness.

Auditability without committing the one-off runner: the actual calls were made
by the repository implementation (`ProviderRuntime`, the vendor adapters, the
authorization and credential seams) at the pinned baseline commit; the artifact
is pinned by SHA256; the parameters, models and outcomes are recorded above;
and the independent review disposition is recorded. The ephemeral external
script was deleted after execution and adds no authority. The repository defines
no maintained live-validation tool, so none was added.

Story 13's live-evidence gate is satisfied. Module 6.5 overall closeout is not
complete: deployment verification, final documentation reconciliation, root
README reconciliation and the closeout post remain.
