# Story 4 — Tool-Permission Registry Lab

Slice 4 implementation candidate for independent acceptance review. This guide records
the runnable lab and its evidence; it does not declare governed Story 4 acceptance,
module completion, production readiness, or deployment. Frozen requirements and
architecture and accepted Slices 1–3 are unchanged.

## Run and inspect working results

From `module-06-5`, using the existing Python 3.12 environment:

```powershell
.\.venv\Scripts\python.exe -m harness_engineering.permission_lab
```

Run all ten cases first. Each prints the action, expected behavior, selected capability,
actual execution/refusal category, actual error reason, handler invocation count,
configured input bound, validated result (if any), and the property demonstrated.
Successful execution returns a document excerpt. Safe refusal returns no result and
shows zero handler calls. A genuine execution failure is reported separately and fails
the expectation check rather than appearing as successful execution or safe refusal.

Inspect individual cases or structured output:

```powershell
.\.venv\Scripts\python.exe -m harness_engineering.permission_lab --scenario allow
.\.venv\Scripts\python.exe -m harness_engineering.permission_lab --scenario scope
.\.venv\Scripts\python.exe -m harness_engineering.permission_lab --scenario self-authorization
.\.venv\Scripts\python.exe -m harness_engineering.permission_lab --json
.\.venv\Scripts\python.exe -m harness_engineering.permission_lab --help
```

The command returns 0 when observed outcome categories and handler counts match the
predefined scenario expectations; 1 for a mismatch; argparse rejects unknown cases
with exit code 2. These checks supplement the more detailed integration tests.

## Scenarios and actual expected evidence

| Scenario | Observation | Handler calls | What to inspect |
| --- | --- | ---: | --- |
| `allow` | Executed; registered output validated | 1 | `doc-a`, `matched=true`, excerpt: `Application-level sandbox bounds tool execution.` |
| `missing-permission` | Authority refused: no matching permission | 0 | The capability is selected despite the absent grant. |
| `scope` | Authority refused: outside policy scope | 0 | Grant includes `doc-c`; application scope includes only `doc-a`. |
| `malformed-input` | Contract rejected: input violates registered schema | 0 | Integer query rejected with otherwise valid application authority. |
| `payload-bound` | Bound refused: payload exceeds configured byte limit | 0 | A schema-valid 100-character query exceeds the executor's 32-byte input limit. |
| `self-authorization` | Contract rejected: invalid invocation proposal | 0 | Generated `approved` and `trust` fields cannot become invocation authority. |
| `context-injection` | Authority refused: no matching permission | 0 | Schema-valid model/credential-looking instructions remain ordinary query text. |
| `blocklist` | Authority refused: action blocked | 0 | Blocklist overrides the matching grant. |
| `approval-required` | Authority refused: human approval required | 0 | Pending approval has no execution authority. |
| `decision-token` | Contract rejected: invalid invocation proposal | 0 | Even a genuine ALLOW decision cannot substitute for an action proposal. |

## Integration and traceability

The service in `src/harness_engineering/permission_lab.py` creates application-owned
local fixture configuration and delegates behavior to the accepted components:

| Requirement/evidence | Authoritative implementation exercised | Integration evidence |
| --- | --- | --- |
| REQ-LAB-003 | Registry → authorizer → bounded executor → local handler → output validation | All ten runnable cases and `tests/test_permission_lab.py` |
| REQ-TOOL-001/002 | `CapabilityRegistry.register`, `select`, and registry contract resolution | Every case selects registered `documents.search`; approval-looking tags grant no authority. |
| REQ-TOOL-003, REQ-SAFE-002/003 | `CapabilityAuthorizer.authorize` at executor invocation boundary | Missing grant, scope, blocklist, approval and contextual-injection cases |
| REQ-TOOL-004 | `BoundedToolExecutor.execute`, registry schemas and `ExecutionContext.checkpoint` | Real local execution, strict input/output validation, deterministic payload-bound refusal |
| ENG-002/003/004/005/006/007 | Real contract/authority boundaries, explicit limits and evidence classification | Forged authority/decision rejection, bounded inputs, credential-free and blocked-network tests |
| ENG-001 (partial) | Guided terminal surface and composable structured results | Reviewer observes instructions, expectations, results, reasons and invocation counts. Final module UI remains later work. |

The lab implements no authorization algorithm. It varies only predefined fixture
policy/grant/input configurations and categorizes actual application exceptions.
Handlers receive the validated input and exact approved resource context, search one
local fixture document, charge one cooperative work unit, and return raw output for
executor validation. No accepted Slice 1–3 code or tests are changed.

`run_permission_lab()` returns immutable structured results; `render_permission_lab()`
and the terminal entry point only project those results. The eventual Story 11 unified
Streamlit UI can consume this service without moving authority into presentation code.
No competing Streamlit application or new dependencies are introduced.

Each scenario uses a fresh bounded fixture workflow: one maximum tool call, one
cooperative work unit, finite action/workflow deadlines, 1,024-byte output limit, and
normally a 1,024-byte input limit (32 bytes in the payload-bound case). Fresh executors
are for independent predefined demonstrations, not a way to reset a real workflow's
consumed budgets. No timers, sleeps, external storage, providers or network are needed
for the scenarios. Invocation counts are measured at handler entry.

## Evidence and limitations

Evidence class: **deterministic**. These are genuine accepted application services and
a genuine local handler operating on synthetic local documents; no live provider,
external integration, credential, paid execution, deployment, or production evidence
is claimed. The accepted Slice 3 timeout tests remain part of the full suite; this lab
demonstrates a payload bound without a presentation-dependent wall-clock test.

The sandbox is an **application-level bounded sandbox/executor**. It supplies no
OS/container/VM/kernel, filesystem, process, network, CPU or memory isolation. Timeout
rejects late results but cannot forcibly stop Python handlers or undo side effects.
Cooperative work charging depends on trusted handler behavior, and payload limits
bound accepted serialized data rather than allocation. See `SLICE_3_EXECUTOR.md` for
the complete accepted limitations. This lab adds no consequential external authority.

Verification: accepted baseline 202 tests; Slice 4 adds 28 integration cases for 230
passing tests. Module-local `ruff check .`, full `pytest`, and `python -m compileall src
tests` pass in fail-fast order. Tests independently instrument real registered handler
calls and authorization/output validation, inspect real ValidationError causes, compare
displayed reasons and JSON with actual service results, exercise the module entry point,
inject an execution failure, and block network connections while removing credentials.

Completion review: Requirements — candidate REQ-LAB-003 and Story 4 exit evidence.
Product Experience — runnable guided terminal lab; unified UI deferred to Story 11.
Real Functionality — real local search through accepted services. Reliability — existing
bounds plus deterministic input-resource demonstration. Security — real accepted policy
and contract enforcement; no authority expansion. Cost — zero paid external calls.
Evidence — deterministic fixtures only. Deployment — not performed.

Repository-wide status and governed Story 4 closeout remain for independent acceptance.
Later lifecycle, recovery, HITL completion, MCP, providers, observability, cost dashboard,
final reviewer UI, module-wide deliverables and deployment remain outside this slice.
