# Module 6.5 User Guide

## Harness Engineering — Reviewer Walkthrough

This guide provides a practical review path through the Module 6.5 agent-harness reviewer application.

Module 6.5 demonstrates a production-grade, application-governed agent lifecycle covering:

- task planning and dependency scheduling;
- context construction, compression, and memory routing;
- capability discovery separated from authorization;
- bounded tool execution;
- retries, fallbacks, circuit breakers, deadlines, and safe stops;
- SQLite checkpointing, crash recovery, and no-replay re-entry;
- durable human approval and asynchronous resume;
- MCP discovery, trusted binding, and bounded invocation;
- provider-neutral model adapters;
- output validation and guardrails;
- structured observability, latency, token, and cost governance;
- regression evaluation and reviewer-visible evidence;
- deterministic no-key operation plus explicit bounded live-provider execution.

The public reviewer deployment is useful without credentials. Live execution is explicit opt-in and does not grant authority merely because a credential exists.

A focused first review can be completed in roughly 15–20 minutes.

---

## 1. What You Need

### Public reviewer path

For the deployed reviewer application, you need only:

- a modern browser;
- the deployed Streamlit URL.

Open:

**https://dm-aiep-agent-engineering-module-06-5.streamlit.app/**

The deterministic reviewer path requires no provider key and no paid inference.

### Local deterministic review

For local review:

- Python 3.12;
- this repository;
- project dependencies installed through the repository environment.

From the module directory:

```powershell
streamlit run streamlit_app.py
```

### Optional live-provider review

Live-provider execution is optional and requires explicit activation, an allowlisted provider/model, approved credential delivery, human authorization, and fixed application-owned bounds.

Credentials provide connectivity only. They never grant workflow authority.

---

## 2. Understand the Evidence Classes

Module 6.5 deliberately separates evidence types.

### Deterministic

Credential-free application behavior using fixed local inputs and deterministic execution.

This can establish:

- workflow policy;
- planning and dependency behavior;
- context budgeting;
- permission decisions;
- bounded execution;
- evaluation behavior;
- safety denials;
- reviewer-visible application semantics.

It does not establish live provider execution.

### Local integration

Real local integration evidence, including SQLite persistence and local MCP SDK transport.

It does not establish a hosted external service.

### Adapter

A genuine integration adapter verified at its application boundary.

Adapter evidence does not prove that an external provider was exercised live.

### Mocked

The live seam and its controls exercised without external network execution.

This establishes control behavior, not live-provider execution.

### Live provider

A separately human-authorized and independently accepted external provider execution.

Module 6.5 has accepted bounded live-provider evidence for:

- OpenAI `gpt-6-luna`;
- Anthropic `claude-haiku-5-5`.

Each accepted run used one attempt and zero retries.

### Deployment

Evidence that the hosted Streamlit application was deployed and exercised at its documented boundary.

Deployment evidence does not automatically become live-provider evidence.

---

# Walkthrough 1 — Orientation

## Goal

Understand the reviewer posture before running anything.

## Steps

1. Open the public reviewer application.
2. Read the built-in guidance.
3. Identify the deterministic default mode.
4. Locate the sections covering provider readiness, evidence classes, safety boundaries, and limitations.

## Expected result

You should see clear separation between:

- deterministic reviewer operation;
- adapter readiness;
- accepted live-provider evidence;
- deployment evidence;
- provider-level production-readiness non-claims.

## What this demonstrates

The reviewer experience is evidence-aware rather than presenting every implemented integration as if it were currently live.

---

# Walkthrough 2 — Planning and Dependency Control

## Goal

Inspect deterministic task decomposition and dependency scheduling.

## Steps

1. Open the planning demonstration.
2. Use the provided deterministic sample.
3. Run the demonstration.
4. Inspect generated subtasks, dependencies, priorities, and execution order.

## Expected result

The planner should produce bounded typed subtasks and reject invalid dependency structures.

Ready work should execute only after dependencies are satisfied.

## What this demonstrates

Planning is an application-owned deterministic service, not uncontrolled model-directed execution.

---

# Walkthrough 3 — Context Compression and Memory Routing

## Goal

Inspect how context remains bounded before execution.

## Steps

1. Open the context-compression demonstration.
2. Run the provided sample.
3. Inspect token-budget information.
4. Compare retained, compressed, and routed context.

## Expected result

The application should enforce the configured context budget and apply bounded compression or sliding-window behavior where required.

Retrieved or retained memory remains contextual data and does not grant authority.

## What this demonstrates

Context construction and memory routing remain governed application concerns rather than implicit provider behavior.

---

# Walkthrough 4 — Capability Selection and Permission Enforcement

## Goal

Verify that discovering or selecting a capability does not authorize it.

## Steps

1. Open the permissions/tool demonstration.
2. Run an allowed scenario.
3. Run a denied or approval-required scenario.
4. Compare discovery metadata with the authorization result.

## Expected result

Allowed actions execute only after policy authorization.

Denied actions remain inert.

Capability metadata alone must not grant permission.

## What this demonstrates

Selection and authorization are independent security boundaries.

---

# Walkthrough 5 — Bounded Execution and Safe Failure

## Goal

Exercise reliability and safety controls.

## Steps

Review scenarios involving:

- retry limits;
- exponential backoff;
- circuit breaking;
- fallback eligibility;
- deadlines;
- validation failures;
- hard stops;
- the application-owned off-switch.

## Expected result

Retries and fallbacks should remain bounded.

Authorization, safety, budget, human-denial, and validation failures should not be retried into success.

## What this demonstrates

Execution control is application-owned and fail-closed.

---

# Walkthrough 6 — Checkpointing, Recovery, and No Replay

## Goal

Verify durable state recovery without replaying committed effects.

## Steps

1. Open the recovery demonstration.
2. Run the deterministic crash/recovery scenario.
3. Inspect checkpoints and effect state.
4. Review the resumed outcome.

## Expected result

Recovery should reconstruct validated workflow state and resume only from the first safe incomplete boundary.

Previously committed effects should not execute again.

## What this demonstrates

Checkpointing is not merely serialization; recovery revalidates current trusted state and preserves idempotency.

---

# Walkthrough 7 — Human Approval and Asynchronous Resume

## Goal

Inspect durable human-in-the-loop control.

## Steps

1. Open the approval demonstration.
2. Trigger a scenario requiring approval.
3. Inspect the pending action identity and version.
4. Review approval, denial, resume, and replay scenarios.

## Expected result

Approval should bind to the exact pending action.

Unknown, stale, forged, replayed, consumed, or unauthorized approvals should fail closed.

Denial should remain terminal for the bound action.

## What this demonstrates

Human approval is durable workflow authority, not a cosmetic UI confirmation.

---

# Walkthrough 8 — MCP Capability Boundary

## Goal

Verify that MCP discovery does not imply trust or execution authority.

## Steps

1. Open the MCP demonstration.
2. Inspect discovered capabilities.
3. Review the trusted binding step.
4. Exercise an allowed invocation.
5. Review denied or cancelled cases.

## Expected result

Discovery remains inert until trusted binding and current authorization succeed.

Denied, cancelled, unbound, or invalid capabilities should remain non-executable.

## What this demonstrates

MCP provides capability transport and discovery, not application authorization.

---

# Walkthrough 9 — Observability, Cost, and Latency

## Goal

Inspect provider-neutral telemetry and governance evidence.

## Steps

Review:

- structured events;
- workflow and step correlation;
- token accounting;
- cost exposure;
- spend thresholds;
- latency cohorts;
- anomaly signals.

## Expected result

The reviewer surface should distinguish deterministic fixture values from real provider exposure.

Local latency measurements should not be presented as production latency certification.

## What this demonstrates

Observability and cost governance are application-owned and evidence-class aware.

---

# Walkthrough 10 — Evaluation and Regression

## Goal

Verify deterministic regression behavior.

## Steps

1. Open the evaluation/regression demonstration.
2. Run the accepted golden-set path.
3. Inspect invariant results.
4. Review drift or failure behavior where available.

## Expected result

Accepted behavior should compare exactly against retained expectations.

Invariant or regression failures should surface explicitly rather than being silently repaired into a passing state.

## What this demonstrates

The harness includes deterministic verification of agent behavior, not just runtime execution.

---

# Walkthrough 11 — Provider Modes and Live/BYOK

## Goal

Understand the deterministic default and explicit live-provider boundary.

## Deterministic mode

The reviewer path defaults to no-key deterministic execution.

No credential is required.

## Live/BYOK mode

Live execution requires all of the following:

- explicit live-mode selection;
- an allowlisted provider;
- an allowlisted model;
- an approved credential source;
- explicit charge acknowledgement where applicable;
- fresh human authorization;
- fixed token, output, time, attempt, retry, and cost bounds.

## Expected result

A credential by itself must never make the runtime executable.

The runtime must still satisfy application policy and authorization before dispatch.

## What this demonstrates

Connectivity and authority remain independent.

---

# Walkthrough 12 — Interpret the Accepted Live-Provider Evidence

## Goal

Understand exactly what the accepted external-provider evidence proves.

Accepted bounded evidence exists for:

| Provider | Model | Attempts | Retries | Evidence class |
| --- | --- | ---: | ---: | --- |
| OpenAI | `gpt-6-luna` | 1 | 0 | `live_provider` |
| Anthropic | `claude-haiku-5-5` | 1 | 0 | `live_provider` |

## What this proves

The reviewed bounded path successfully executed against those providers and models under the accepted controls.

## What this does not prove

- universal provider support;
- provider SLA;
- production scale;
- general billing accuracy;
- model quality;
- hosted Anthropic execution;
- provider-level production readiness.

---

# Walkthrough 13 — Interpret Hosted Deployment Evidence

## Goal

Separate deployment evidence from live-provider evidence.

The hosted Streamlit application was rebuilt from the accepted repository state and started successfully.

One bounded, explicit OpenAI BYOK call completed through the hosted governed path.

That call remains `adapter`-class evidence within a separate `deployment` record.

It does not create or replace `live_provider` evidence.

Anthropic was not exercised through the hosted application.

## What this demonstrates

Deployment, adapter execution, and live-provider acceptance remain separate evidence categories.

---

# Security and Trust Boundaries

A reviewer should be able to verify that:

- model output is untrusted data;
- user input is untrusted data;
- MCP, tool, provider, and memory content are untrusted data;
- models cannot self-authorize privileged actions;
- capability discovery does not grant permission;
- approval is exact-action bound and durable;
- requester identity does not automatically grant approver authority;
- retries and fallback cannot bypass safety or authorization;
- credentials grant connectivity only;
- deterministic reviewer paths require no paid inference;
- provider evidence classes cannot be promoted by runtime code;
- Streamlit is a presentation layer rather than the authority boundary.

These controls do not establish universal prompt-injection immunity, genuine production authentication, formal compliance certification, hostile-file isolation, or production-scale guarantees.

---

# Evidence and Deployment Boundaries

## Established

- 69 of 69 approved requirements verified;
- 6 of 6 hands-on labs implemented;
- 5 of 5 required deliverables implemented;
- 9 of 9 named technologies represented with explicit roles;
- 2,063 passing tests on the accepted final-integration candidate;
- accepted deterministic and local-integration evidence;
- accepted adapter and mocked live-seam evidence;
- bounded independently accepted OpenAI and Anthropic live-provider evidence;
- verified reviewer-facing Streamlit deployment;
- completed controlled publication and LinkedIn closeout.

## Not established

- provider-level production readiness;
- universal provider/model validation;
- production SLA;
- production capacity or cloud scale;
- formal billing certification;
- production identity/authentication;
- hosted LangSmith or Langfuse verification;
- live Helicone routing;
- hosted Mem0 service;
- authenticated public production MCP service;
- OS/container sandbox isolation.

---

# Common Problems

## Live mode is unavailable

Confirm that live mode was explicitly selected and that the required application-owned policy, authorization, provider/model allowlist, credential source, and bounds are present.

A credential alone is intentionally insufficient.

## A deterministic demonstration makes no provider call

Expected.

The normal reviewer path is designed to prove harness behavior without paid inference.

## A denied action does not retry

Expected.

Authorization, approval, validation, safety, and hard-budget denials are not transient failures.

## A historical record differs from the current session

Treat them as separate evidence.

Recorded evidence must never substitute for a failed or unavailable current action.

## The hosted app does not prove Anthropic deployment execution

Correct.

Anthropic was not exercised through the hosted application.

## The application-level sandbox is not OS isolation

Correct.

The project claims only the bounded application-level isolation that was actually implemented and tested.

---

# Suggested 15-Minute Reviewer Path

1. **Orientation**
   - Read the evidence and authority model.

2. **Planning**
   - Run task planning and inspect dependencies.

3. **Context**
   - Run context compression and inspect budget behavior.

4. **Permissions**
   - Compare selected capability vs authorized capability.

5. **Recovery**
   - Inspect checkpoint/resume and no-replay behavior.

6. **HITL**
   - Review pending approval, exact-action binding, and denial behavior.

7. **MCP**
   - Review inert discovery and trusted binding.

8. **Observability / regression**
   - Inspect evidence classes, cost/latency signals, and regression results.

9. **Provider modes**
   - Review deterministic default, live controls, accepted live-provider evidence, and deployment evidence.

---

# What to Look For

A successful review should make these properties obvious:

- application policy owns authority;
- LangGraph coordinates lifecycle but does not own security policy;
- context and memory remain bounded and untrusted;
- capability discovery and permission are separate;
- committed effects are not replayed after recovery;
- HITL decisions bind to exact pending actions;
- MCP transport never grants authority;
- retries and fallbacks remain bounded;
- cost and latency are explicit runtime concerns;
- provider credentials never imply authorization;
- deterministic, adapter, mocked, live-provider, and deployment evidence remain distinct;
- reviewer-facing deployment is useful without overclaiming production readiness.

---

# Go Deeper

- [Module 6.5 README](../README.md)
- [Authoritative Source](AUTHORITATIVE_SOURCE.md)
- [Architecture](ARCHITECTURE.md)
- [Traceability](TRACEABILITY.md)
- [Release Readiness](RELEASE_READINESS.md)
- [Story 13](STORY_13.md)
- [Implementation Plan](IMPLEMENTATION_PLAN.md)
- [Portfolio README](../../README.md)
- [`streamlit_app.py`](../streamlit_app.py)
- [`src/harness_engineering/`](../src/harness_engineering/)
- [`tests/`](../tests/)

Historical story documents preserve the state and terminology that were accurate when each slice was authored. Current module completion is established by the accepted final publication state and the normalized reviewer documentation.
