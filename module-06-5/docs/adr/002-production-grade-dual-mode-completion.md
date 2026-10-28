# ADR 002 - Production-Grade Dual-Mode Provider Completion

## Status

ACCEPTED - human-authorized corrective contract repair, 2026-10-23. This is a
restoration of the already-authoritative repository production-grade
invariant; it is not a new architecture decision and does not reopen the
frozen architecture or the approved 69-requirement baseline.

## Context

Repository governance requires production-grade engineering unless a module is
explicitly declared DEMO-ONLY. Module 6.5 has never been declared DEMO-ONLY.
The established production-grade invariant requires deterministic/no-key
reviewer operation by default, securely activatable opt-in live-provider
execution where genuine provider adapters exist, secrets supplied through an
approved credential source (a session-scoped, never-persisted BYOK key and/or
trusted server-side/environment/secret-store mechanisms; server-side
credentials may supplement but never replace BYOK), explicit provider/model allowlists, bounded retries/token/
output/latency/cost exposure, credentials that grant connectivity but never
authority, explicitly distinct evidence classes, and provider-level
production-readiness claims only after the live path is implemented, securely
configured, explicitly authorized for execution, exercised, and independently
evidenced.

The defect (propagation gap): ADR 001 decision 11 and the Story 9
implementation plan described OpenAI and Anthropic as optional live-provider
adapters, and the release-reconciliation contract (Story 12) accepted
adapter-only closure. Repository-level production-grade governance was never
propagated into the Module 6.5 acceptance contract, allowing release
reconciliation with live-provider evidence = none.

Substantial supporting machinery already exists and is unchanged by this
decision: `HarnessConfig` (`deterministic_mode=True` and
`allow_live_providers=False` defaults with a fail-closed mutual-exclusion
validator; `config.py`), `EvidenceClass.LIVE_PROVIDER`, the vendor adapters
(`vendor_providers.py` `OpenAIProvider`/`AnthropicProvider` behind the
provider-neutral boundary, gated on explicit `allow_live_providers` plus a
finite `max_cost_usd` budget), cost-governance boundaries, and committed tests
establishing that credentials alone do not authorize live execution.

## Decision

1. Add additive engineering requirement ENG-008 (production-grade dual-mode
   provider operation, wording in `docs/REQUIREMENTS.md`, provenance recorded
   in its freeze-rule note). The 69 approved baseline requirements are
   preserved exactly.
2. Determine implementation completion through a dedicated, bounded
   implementation story (Story 13 in `docs/IMPLEMENTATION_PLAN.md`), which
   includes the provider/model allowlist enforcement and trusted-secret
   mechanism work that the acceptance contract now requires, all remaining
   credential-free on the deterministic path.
3. Live-provider execution remains a separate later human-authorized
   cost/credential boundary. No live provider call is made or authorized by
   this decision.
4. The approved evidence taxonomy is unchanged. Adapter evidence may not be
   presented as live-provider evidence, and no provider-level
   production-readiness claim is made while the live path remains unexercised.

## Consequences

Story 12's release reconciliation remains valid for the approved 69-requirement
baseline; ENG-008 completion is now an explicit outstanding gate before any
provider-level production-readiness claim. Deterministic/no-key mode remains
the default reviewer mode, free of paid execution. Structural contract tests
(`tests/test_dual_mode_contract.py`) prevent future acceptance documents from
again permitting adapter-only evidence to satisfy provider-level readiness.

## Verification Basis

- Orchestrated repository governance (AGENTS.md/ENGINEERING_SOP.md):
  production-grade by default; no DEMO-ONLY declaration for Module 6.5.
- Accepted machinery and tests enumerated above, present at
  `d4d2fd0`/`7ce1bd8` in module-06-5.
- Human-authorized corrective directive (2026-10-23).
