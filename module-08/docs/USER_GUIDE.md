# Module 8 User Guide

## MCP & Modern AI Infrastructure — Reviewer Walkthrough

This guide demonstrates how a genuine MCP enterprise capability plane connects OpenAI SDK and Google ADK consumers to shared enterprise services while preserving application-owned execution authority.

The normal reviewer experience is deterministic, credential-free, and supported by real local MCP, SQLite, HTTP, and internal-service execution.

---

## 1. What You Need

### Public reviewer path

Open the verified [Module 8 Streamlit Console](https://dm-aiep-module-08.streamlit.app/).

A browser is sufficient for the deterministic reviewer demonstration. No provider key or paid inference is required.

### Local reviewer path

Install Python 3.12 and uv. From the module-08 directory:

```powershell
uv sync --locked --extra dev
uv run streamlit run src/mcp_enterprise_integration/console.py
```

Dependency installation may require internet access. The demonstration itself uses loopback services and synthetic local data.

### Optional live-provider review

Live Provider Demo is explicitly opt-in. Reviewers supply their own keys through masked form inputs and acknowledge external execution and possible account charges before triggering a bounded run.

Do not substitute sensitive customer records for the synthetic demonstration inputs.

---

## 2. Understand the Evidence Classes

| Evidence class | Establishes | Does not establish |
| --- | --- | --- |
| Deterministic | Fixed-input application behavior and policy decisions | External model inference |
| Mocked | Controlled failure injection or scripted model behavior | Genuine provider execution |
| Adapter | SDK or provider boundary construction and integration | Successful external inference alone |
| Local-integration | Real local MCP, SQLite, HTTP and policy-service execution | Public enterprise production services |
| Live-provider | Completed, bounded, validated real provider execution | SLA, universal model availability or billing accuracy |
| Deployment | Verified hosted reviewer application behavior | Multi-host enterprise production readiness |

Historical Story 10 and Story 11 documents describe earlier acceptance stages. The later Module 8 closeout establishes the completed deployment and controlled live-provider exercise.

---

# Walkthrough 1 — Architecture and Orientation

## Goal

Identify the vendor-neutral MCP enterprise capability plane and application-owned authority boundary.

## Steps

1. Read the architecture and usage guidance in the console.
2. Identify the application controller, OpenAI SDK consumer, Google ADK consumer, MCP client/server, and enterprise services.
3. Locate the scenario selector and evidence records.
4. Confirm that Streamlit displays underlying results instead of implementing authorization policy.

## Expected result

Both SDK consumers share the same MCP service boundary. Capability discovery is separate from permission.

## What this demonstrates

The enterprise integration plane belongs to the application and MCP protocol layer, not to a model vendor.

---

# Walkthrough 2 — Manager Review

## Goal

Exercise the successful deterministic enterprise workflow.

## Steps

1. Select Deterministic Demo.
2. Select Manager review.
3. Click Run enterprise demonstration.
4. Inspect discovered capabilities, customer data, account data, policy request and final decision.
5. Inspect SDK stages, MCP transport and execution evidence.

## Expected result

Three enterprise MCP capabilities are discovered. The customer lookup is allowed. Three validated workflow stages execute: OpenAI SDK, Google ADK and OpenAI SDK.

The viewer capability denial is separate from the authorized enterprise workflow. The internal policy service returns an allow business decision for Manager. No account state is changed, and the deterministic path makes zero external model calls.

## What this demonstrates

Genuine enterprise interoperability can be reviewed without paid model inference.

---

# Walkthrough 3 — Support Review

## Goal

Distinguish viewer capability-authorization denial from the internal enterprise business-policy decision.

## Steps

1. Select Support review.
2. Run the deterministic enterprise demonstration.
3. Inspect the authorized customer read and the viewer capability denial, which also appears in Manager review.
4. Confirm Support is authorized to invoke the internal policy tool, then inspect the separate deny business decision.

## Expected result

Support shows the same viewer-level capability denial as Manager. Support is separately authorized to invoke the internal policy tool. That tool executes and returns a deny business decision; this is not a CapabilityPolicy refusal to invoke the tool.

## What this demonstrates

CapabilityPolicy independently controls whether an MCP tool may be invoked. The authorized internal policy service separately determines the enterprise business outcome.

---

# Walkthrough 4 — MCP Discovery and Transport

## Goal

Inspect genuine MCP protocol behavior.

## Steps

1. Inspect the discovered tool inventory and typed schemas.
2. Inspect Streamable HTTP session and transport evidence.
3. Compare discovery, authorization and invocation records.
4. Review validated output and evidence classification.

## Expected result

The official MCP SDK exposes three real enterprise capabilities through client/server interaction and typed contracts.

## What this demonstrates

MCP is a functioning interoperability protocol rather than a cosmetic wrapper around local Python functions.

---

# Walkthrough 5 — Enterprise Integrations

## Goal

Inspect the distinct enterprise capabilities exposed through MCP.

## Steps

1. Examine the seeded SQLite customer lookup result.
2. Examine the bounded local HTTP account-status response.
3. Examine internal policy-service evaluation and the resulting decision.
4. Review the validated cross-stage context and execution records.

## Expected result

SQLite, HTTP API and internal policy integrations produce genuine local results from synthetic data. Policy evaluation does not perform the proposed account change.

## What this demonstrates

Different enterprise service types can share one discoverable MCP capability plane.

---

# Walkthrough 6 — OpenAI SDK and Google ADK Interoperability

## Goal

Verify heterogeneous SDK consumption of the same MCP enterprise services.

## Steps

1. Inspect the OpenAI SDK customer stage.
2. Inspect the Google ADK account-status stage.
3. Inspect the final OpenAI SDK MCP policy stage.
4. Compare capability identities, context exchange, transport and results.

## Expected result

The three stages exchange validated, bounded, identity-correlated context. The deterministic SDK path does not run paid provider models.

## What this demonstrates

Interoperability does not require an individual SDK framework to own enterprise integration or execution authority.

---

# Walkthrough 7 — MCP Versus Direct Tool Calling

## Goal

Compare direct implementation coupling with discoverable protocol-mediated tools.

## Steps

1. Inspect the direct customer-lookup comparison.
2. Identify the direct Python repository path.
3. Identify the MCP discovery and invocation path.
4. Compare interface and transport responsibilities.

## Expected result

Both paths return the intended customer information; MCP adds typed discovery and a transport boundary.

## What this demonstrates

The exercise establishes an interoperability difference, not a performance or model-quality benchmark.

---

# Walkthrough 8 — Authorization and Failure Handling

## Goal

Review the application-owned CapabilityPolicy and fail-closed execution.

## Steps

1. Inspect reviewer-visible authorization decisions.
2. Compare allowed and denied application-role behavior.
3. Review traceability for malformed context, forged identity and unauthorized tool calls.
4. Inspect the accepted regression evidence for an explicitly empty capability allowlist.

## Expected result

CapabilityPolicy controls authorization independently of MCP discovery. An explicit empty grant map denies all roles, and malformed or unauthorized requests fail closed.

A failed demonstration must not display stale success.

## What this demonstrates

SDK execution and protocol capability metadata cannot replace application-owned security policy.

---

# Walkthrough 9 — Deterministic and Live/BYOK Modes

## Deterministic Demo

This is the accepted default: no API key, no paid model calls, and genuine local enterprise integration.

## Live Provider Demo

To request an optional live execution:

1. Select Live Provider Demo.
2. Select Manager or Support review.
3. Enable OpenAI, Gemini or both.
4. Choose an available allowlisted model.
5. Enter the appropriate key in the masked input.
6. Acknowledge external-provider execution and possible charges.
7. Click Run live provider demonstration.

The backend independently enforces ProviderPolicy and the application-owned CapabilityPolicy. Only the authorized MCP tool is exposed to a selected provider, and application-bound arguments are revalidated before dispatch.

Unselected provider stages remain deterministic. The final enterprise-policy stage never delegates its decision to a model.

## Live-mode bounds

At most two OpenAI and two Gemini model calls per run; 600 output tokens per call; one MCP tool call per stage; no SDK/HTTP retries; 50 seconds per stage; 120 seconds per run; one live run per process.

These are execution bounds, not guarantees about provider billing or service availability. Credentials grant connectivity, not application authority.

---

# Walkthrough 10 — Accepted Live and Deployment Evidence

## Goal

Distinguish current accepted evidence from historical or mocked results.

## Accepted live-provider result

The final deployed acceptance recorded four of four bounded model calls across OpenAI and Google ADK/Gemini stages. Each provider-driven stage completed with live-provider classification.

OpenAI exercised customer lookup, and Gemini exercised account-status lookup. The final internal policy stage remained application-owned local-integration with zero model calls.

## Accepted deployment result

The hosted Streamlit reviewer application was verified with three discovered enterprise MCP capabilities, three workflow stages and zero provider-model calls in the deterministic Manager demonstration. Support review was also accepted.

The deployed environment uses GOOGLE_API_USE_CLIENT_CERTIFICATE=false to avoid an unnecessary Google mTLS credential probe during local MCP discovery.

That setting is loopback transport configuration, not a provider-model credential or authorization grant.

## What this does not prove

The results do not certify multi-host deployment, publicly authenticated MCP services, cloud-managed enterprise infrastructure, production SLA, load capacity, universal model support or guaranteed billing amounts.

---

# Security and Trust Boundaries

- Capability discovery does not grant permission.
- Application-owned policy retains authority over roles and capabilities.
- Model text cannot alter trusted identity, arguments, capabilities or enterprise decisions.
- Malformed, oversized or identity-substituted workflow context is rejected.
- Raw MCP primitives are not an authenticated public network perimeter.
- Manager and Support roles are demonstration fixtures, not real user authentication.
- Optional live mode requires explicit consent and bounded execution.
- Provider credentials never establish permission to execute.
- Model narratives remain untrusted display-only text.
- Streamlit presents real results rather than fabricating execution success.

---

# Common Problems

## No external model calls are reported

Expected in Deterministic Demo. The default path is intentionally no-key.

## Live mode refuses to start

Check selected mode, enabled provider, allowlisted model, masked credential, both acknowledgements and backend policy.

## A discovered capability is denied

Expected when the application-owned role lacks authority. MCP discovery does not override CapabilityPolicy.

## Cloud MCP discovery stalls

Review the documented Google mTLS probe workaround and deployed configuration. Increasing the discovery deadline is not the accepted repair.

## Dependency warnings appear during testing

The accepted Google ADK environment records experimental and deprecation warnings. These were not suppressed solely for cosmetic reasons.

## Historical documents say no live provider was exercised

Those statements belong to the earlier acceptance chronology. Refer to the final Module 8 closeout for later live-provider and deployment verification.

---

# Suggested 15-Minute Reviewer Path

1. Read the architecture and evidence guidance.
2. Run the deterministic Manager scenario.
3. Run the deterministic Support scenario.
4. Examine SQLite, HTTP API and internal policy results.
5. Inspect three-stage OpenAI SDK / Google ADK interoperability.
6. Inspect MCP discovery, Streamable HTTP and typed contracts.
7. Compare direct customer lookup with MCP invocation.
8. Review authorization, denial and failure boundaries.
9. Interpret accepted live-provider and deployment evidence.

---

# What to Look For

A successful review should establish genuine MCP integration, heterogeneous SDK interoperability, application-owned authorization, bounded local execution, accurate evidence classes, a deterministic no-key reviewer experience, and separately classified opt-in live execution.

Do not mistake successful reviewer deployment for an authenticated production enterprise service.

---

# Go Deeper

- [Module 8 README](../README.md)
- [Authoritative Source](AUTHORITATIVE_SOURCE.md)
- [Requirements](REQUIREMENTS.md)
- [Architecture](ARCHITECTURE.md)
- [Traceability](TRACEABILITY.md)
- [Story 10 Verification and Deployment](stories/STORY-10-integrated-verification-release-evidence.md)
- [Story 11 Live Provider and BYOK](stories/STORY-11-opt-in-live-provider-byok.md)
- [Implementation Plan](IMPLEMENTATION_PLAN.md)
- [Portfolio README](../../README.md)
- [Streamlit console](../src/mcp_enterprise_integration/console.py)
- [MCP integration source](../src/mcp_enterprise_integration/)

Module 8 is complete under its accepted final closeout. Historical records remain historical; the final README describes the later deployment, bounded live exercise and LinkedIn publication.
