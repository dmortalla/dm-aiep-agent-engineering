# Story 8 — Interoperable enterprise workflow

This story implements the frozen architecture with no new dependencies or
protocols. `EnterpriseWorkflow` is application orchestration, independent of
presentation. It returns `WorkflowResult`, serializable with
`model_dump(mode="json")` for Story 9. No Streamlit implementation is included.

## Execute and inspect

From `module-08`, run:

```powershell
uv run pytest tests/test_workflow.py -v
```

The acceptance fixture starts the real enterprise MCP server and deterministic
enterprise HTTP API on loopback, with a seeded SQLite database. Both SDK consumers
use that same MCP URL. No API key or model inference is needed.

For an already running local enterprise MCP server, application code can execute:

```python
from mcp_enterprise_integration.workflow import EnterpriseWorkflow

result = await EnterpriseWorkflow("http://127.0.0.1:8000/mcp").run(
    customer_id="CUST-001",
    principal_role="account_manager",  # supplied by the authenticated application
)
print(result.model_dump_json(indent=2))
```

Use the actual server URL. The workflow does not host services or authenticate
users. The calling application owns authentication and policy configuration;
business input, persisted results, and discovered capabilities cannot supply role
authority. The current path is intentionally limited to loopback HTTP.

## Working results and trust boundaries

1. The genuine OpenAI Agents SDK MCP consumer reads a customer through MCP and
   SQLite. The response envelope and customer contract are validated, bounded,
   and correlated with the requested identity.
2. The genuine Google ADK `McpToolset`/`McpTool` consumer uses that validated
   customer identifier to query the enterprise HTTP API through the same MCP
   server. Its returned account contract is strictly validated and correlated.
3. Application orchestration builds a typed `PolicyRequest` using the validated
   account identifier, customer account state, original requested action, and
   application-supplied role. The OpenAI SDK invokes the internal policy service
   through MCP. Its result is validated and correlated with identity and action.

Each invocation independently checks the same application-owned
`CapabilityPolicy`. Successful discovery or execution by one SDK grants nothing
to the other. Neither SDK calls the other's private implementation. A policy
denial is a valid business result; it is distinct from capability authorization
denial, which raises `AuthorizationError`. Evaluating a proposed action never
executes that action, and returned decisions never grant application privileges.

Results expose the actual customer, account, policy request, policy result, and
three framework/transport/authorization/evidence records. Malformed or missing
data, identity substitution, excessive context, undeclared fields, or invalid
enums stop execution without producing a successful workflow result. Input is
validated before connecting. There are three sequential capability invocations,
no orchestration retries, a 45-second total deadline, an 8192-byte context limit,
bounded strings and case count, and existing SDK request/discovery deadlines.

## MCP versus direct tool calling

`test_direct_versus_mcp_comparison` executes a direct repository lookup and the
MCP workflow, then verifies the same customer record. The direct baseline knows
the Python repository implementation and bypasses MCP discovery and transport.
The workflow's SDK consumers know protocol capability names and typed schemas;
the server owns the enterprise implementations. This demonstrates the coupling
difference underlying traditional vendor-specific direct tool calling. The
baseline is an application-level direct call, not a vendor model tool invocation.
It does not claim comparative performance or that MCP removes all integration
work. Schemas, application authorization, identity correlation, and domain
validation still matter.

## Infrastructure concepts and source traceability

- REQ-INT-001: orchestration, capabilities, context and authority boundaries are
  building blocks relevant to AI operating systems. This module is not an AI
  operating system, scheduler, or resource-management platform.
- REQ-INT-002, REQ-LAB-002, REQ-LAB-003: independently implemented SDK ecosystems
  participate in one typed application workflow using shared MCP capabilities.
  The evidence demonstrates infrastructure interoperability, not autonomous
  agent dialogue or model reasoning.
- REQ-INT-003: independently addressed MCP and enterprise HTTP services with
  client/server boundaries form a small distributed-service demonstration on
  loopback. No multi-host availability or cloud deployment is claimed.
- REQ-INT-004: MCP is the implemented capability/context protocol. A2A is a
  complementary agent-to-agent standard; no A2A implementation is needed for
  this workflow, and none was added.
- REQ-OBJ-001, REQ-MCP-003, REQ-INFRA-002, REQ-DEL-001, REQ-DEL-002: real MCP
  invocation and validated cross-stage context support the existing traceability.
  Final reviewer UI and module requirement closure remain with Stories 9 and 10.

The frozen traceability matrix and architecture remain unchanged.

## Evidence and completion limits

Principal acceptance execution is **local-integration**, with deterministic
seeded data and genuine MCP/OpenAI-SDK/Google-ADK transport participation.
Focused corruption tests are **mocked failure injection** into genuine SDK result
boundaries. Agent configuration is genuine SDK construction; neither agent model
runner executes. No live-provider or deployment evidence is claimed.

Requirements: Story 8 scope implemented; final module closure deferred.
Product experience: structured application results and runnable acceptance
demonstration; Story 9 console pending. Real functionality: SQLite, HTTP API and
internal policy through MCP. Reliability: bounded calls, deadline, strict failure
handling. Security: independent application authorization and validated context.
Cost: zero model execution. Evidence: local integration and labeled corruption
tests. Deployment: not exercised. This story does not establish whole-module
production readiness or release approval.
