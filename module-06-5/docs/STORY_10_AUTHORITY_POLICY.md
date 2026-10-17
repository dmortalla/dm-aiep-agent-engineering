# Story 10 Authority Policy

**Status:** HUMAN APPROVED

**Approval date:** 2026-10-17

This policy records the consequential human decisions required before implementing Module 6.5 Story 10 - Observability, Cost Governance, and Latency SLO.

It implements the already-frozen architecture. It does not amend the authoritative source, requirements baseline, or architecture.

## 1. Monetary Exposure Authority

Story 10 may implement and deterministically demonstrate an application-owned reservation and settlement ledger, spend warnings, hard budgets, concurrency controls, persistence and recovery behavior, and deterministic tariff fixtures.

Real billable admission is disabled by default and fails closed unless separately trusted application configuration explicitly supplies an approved provider/model tariff policy and enables live monetary execution.

The following rules are mandatory:

1. Missing, stale, unsupported, ambiguous, model-generated, provider-generated, or otherwise untrusted pricing grants no spending authority.
2. Credentials, API keys, SDK configuration, environment variables, or provider availability never grant spending authority.
3. Application monetary authority remains separate from provider authentication.
4. A conservative maximum exposure must be reserved before billable dispatch.
5. Outstanding reservations count toward the application exposure limit.
6. Uncertain billable attempts retain conservative reserved exposure rather than being assumed free.
7. Settlement is application-owned and exactly once per application attempt.
8. Monetary accumulation must avoid floating-point authority decisions; use integer monetary units or Decimal with conservative rounding.
9. Telemetry, exporters, model output, provider output, tool output, MCP output, retrieved data, and agent output cannot increase or reset spending authority.
10. Exporter or observability failure cannot release monetary reservations or bypass a hard budget.
11. Reconstruction or resume cannot reset consumed or reserved exposure.
12. Without durable validated monetary-ledger recovery, billable resume fails closed.
13. Deterministic fixture tariffs may prove enforcement mechanics but do not establish real provider prices.
14. Application cost estimates must remain distinct from provider-reported usage and independently verified billing.
15. An application hard exposure limit must not be claimed to guarantee the final vendor invoice.

Any future live monetary execution still requires the applicable trusted configuration and human authorization boundaries. This policy does not authorize a live provider request or paid inference.

## 2. Helicone Authority Boundary

Story 10 shall give Helicone an explicit source-faithful role through an offline gateway configuration and header integration boundary with deterministic serialization, validation, privacy, and security tests.

Story 10 is not authorized to reroute actual provider inference traffic through Helicone.

The following rules are mandatory:

1. Do not invent or require a Helicone Python dependency when the approved architecture does not require one.
2. Do not change accepted provider endpoints merely to demonstrate Helicone.
3. Do not send prompts, model outputs, credentials, authorization headers, or inference traffic to Helicone during deterministic Story 10 work.
4. Helicone configuration or headers cannot alter application permissions, approvals, routing authority, retry accounting, cost authority, evidence class, or safety controls.
5. Offline adapter or serialization evidence must never be classified as live-provider, live-Helicone, deployment, or production evidence.
6. Gateway retries, caching, fallbacks, or transformations must never be assumed safe merely because Helicone supports them.
7. Any future live Helicone gateway binding requires separate human authorization because it changes provider transport and privacy boundaries.

## 3. Evidence Classification

Story 10 must continue to distinguish deterministic, mocked, adapter, local-integration, live-provider, and deployment evidence.

Local accounting, provider-reported usage, estimated monetary cost, and independently verified billing are distinct evidence concepts and must not be conflated.

No Story 10 deterministic or offline integration evidence establishes:

- live provider behavior;
- real provider pricing;
- actual vendor billing;
- live Helicone gateway behavior;
- hosted observability availability;
- deployment readiness; or
- production-grade completion.

## 4. Security and Authority Invariants

Existing application-owned permissions, approval gates, capability scope, blocklists, budgets, retries, deadlines, off-switch behavior, persistence semantics, and Story 9 provider security remain authoritative.

Telemetry and observability are projections of application behavior, not authority sources.

Correlation identifiers, trace context, exporter metadata, provider usage receipts, model output, and external observability responses cannot grant application authority.

## 5. Implementation Authorization

With this policy recorded, deterministic Story 10 implementation may proceed under the frozen architecture without a new ADR.

The approved implementation sequence is:

1. application-owned telemetry, correlation, latency, and safe projections;
2. usage receipts, cost governance, warnings, and deterministic anomaly signals;
3. optional sanitized observability integration adapters and the offline Helicone boundary;
4. runnable observability lab, regression evidence, and Story 10 closeout.

A new human decision is required before any live monetary execution or live Helicone gateway routing.
