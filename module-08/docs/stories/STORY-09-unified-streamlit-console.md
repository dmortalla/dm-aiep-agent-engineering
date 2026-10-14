# Story 9 — Unified Streamlit infrastructure console

## Run

From `module-08`:

```powershell
uv run streamlit run src/mcp_enterprise_integration/console.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

No API key is required. Select **Manager review** or **Support review**, then
**Run enterprise demonstration**. These are fixed demonstration identities,
not real authentication. The customer is bounded to seeded `CUST-001`. Neither
scenario executes an account change. Do not expose this local reviewer console
as an authenticated production application.

## Presentation/application boundary

`console.py` collects a scenario, invokes `run_reviewer_demo`, stores one result
per Streamlit session and renders structured tables, metrics, alerts and evidence.
It contains no MCP implementation, capability grants, business rules or SDK
orchestration. A failed execution clears stale success and renders a safe error.

`reviewer.py` starts isolated, ephemeral loopback enterprise HTTP and MCP services
with the accepted `create_enterprise_mcp_server`. The HTTP fixture supplies
deterministic account data, not business policy. SQLite and enterprise policy
remain in their existing services. Ports are OS-assigned; startup has a five-second
bound, execution a sixty-second deadline, workflow its accepted forty-five-second
deadline, and shutdown bounded joins. There are no retries or provider clients.
Each execution owns and cleans up its services/database. Runtime temporary data
is not retained as engineering evidence.
The application permits at most two concurrent demonstrations per process;
additional requests fail safely without queueing services. Streamlit usage
telemetry is disabled and the console binds to loopback in `.streamlit/config.toml`.

The service uses the accepted `EnterpriseMcpClient` for real initialization,
capability discovery, an authorized viewer customer read and a viewer policy
request denied by the existing `CapabilityPolicy` before remote invocation.
It fails review if the expected denial is absent. It calls the unchanged Story 8
`EnterpriseWorkflow` for OpenAI SDK customer lookup, Google ADK account lookup,
and OpenAI SDK internal policy evaluation. All context validation and independent
capability checks remain in that workflow. The service also executes the accepted
repository directly and compares the customer with MCP/workflow results.

## Reviewer-visible results and traceability

- Discovery/authority: negotiated server/protocol metadata, discovered inventory,
  actual allow evidence and expected denial (REQ-MCP-001/002, REQ-INFRA-001/003/004,
  ENG-003/004).
- Enterprise: validated SQLite customer, HTTP account and internal policy results
  (REQ-ENT-001/002/003).
- Workflow: three actual framework, transport, capability, authorization and
  evidence records; validated policy request and final decision
  (REQ-INFRA-002, REQ-TECH-002/003, REQ-LAB-002/003, REQ-DEL-001/002).
- Comparison: executed direct repository call and matching MCP result, with no
  model-tool or performance claim (REQ-MCP-003).
- Guidance: capability plane, server/client roles, independent SDK consumers,
  reviewer steps, expected outcomes and interpretation. AI operating-system
  building blocks and distributed loopback services are explained; A2A is
  complementary and not implemented (REQ-INT-001/002/003/004, ENG-001).
- Evidence: deterministic seeded fixtures with **local-integration** execution;
  real Streamable HTTP, SDK tools and validated results. Neither SDK model runner
  executes. No live-provider or deployment evidence is claimed (ENG-006/007).

The frozen requirements, architecture and traceability matrix are unchanged.
These mappings add Story 9 execution evidence; they do not close all 33 module
requirements or begin Story 10.

## Verification and completion limits

`tests/test_reviewer.py` exercises actual services through Streamlit AppTest for
both scenarios, genuine discovery, denial before invocation, direct comparison,
SDK stages, evidence preservation and rendered output. Model runners and external
network connections are guarded, and provider keys are removed for these tests.
Other tests verify invalid input before startup, unexpected-error redaction with
exception chaining, concurrency rejection, and stale-success removal after an
injected backend failure.
Failure injection is **mocked**, distinct from the real local-integration tests.

Final Story 9 verification (2026-10-14): `uv run ruff check .` passed;
`uv run pytest --basetemp <TECHADEMY/EVIDENCE/module08-story09-20261014-final>`
passed **112 tests** with 159 Google ADK experimental/deprecation warnings;
`uv run python -m compileall -q src tests` passed. Six focused reviewer tests
were added. AppTest verifies presentation and real execution headlessly; a manual
browser visual review and deployment verification were not performed.

No optional live-provider mode is added: it is unnecessary for the reviewer
capabilities and would introduce additional authority/cost concerns.

Requirements: Story 9 bounded presentation scope; final reconciliation deferred.
Product experience: unified runnable self-explaining console, headless verification.
Real functionality: accepted SQLite/HTTP/policy backend and both SDK MCP consumers.
Reliability: bounded local service lifecycles and safe errors.
Security: fixed demo identities, existing policy, validated workflow context.
Cost: zero model/provider/paid calls in deterministic execution.
Evidence: local integration and explicitly mocked failures.
Deployment: unverified. Story 9 does not declare whole-module production readiness
or authorize release; Story 10 remains untouched.
