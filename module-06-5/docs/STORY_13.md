# Story 13: secure dual-mode provider completion (ENG-008, ADR 002)

Builder candidate record. Story 13 implements the secure opt-in live-provider
seam and the deterministic verification proving it is technically ready for a
separately authorized live exercise. No live provider call was made, no real
credential was accessed or requested, no cost was incurred, and nothing was
staged, committed, pushed, or deployed. Live-provider evidence remains none.

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

## Outstanding (human-authorized gate)

- Choose and confirm the model catalog and tariff upper bounds for the first
  live exercise (current catalog: `gpt-4.1-mini`, `gpt-4.1-nano`,
  `claude-haiku-4-5`, `claude-haiku-5-5`).
- Provision credentials in the server environment or secret store, outside
  the repository and the reviewer UI.
- Issue a `LiveExecutionAuthorization`, run the bounded live exercise, and
  record independently reviewed live-provider evidence.

Until then no live OpenAI or Anthropic execution, live-provider evidence, or
provider-level production readiness is claimed, and the ENG-008
Definition-of-Done item stays open.
