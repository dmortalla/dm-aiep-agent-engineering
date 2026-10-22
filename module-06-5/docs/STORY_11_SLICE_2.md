# Story 11 Slice 2 — local Streamlit reviewer

Builder candidate over independently accepted Slice 1 commit
`fa7d24872826ffa835d24976a4c92d1f84fdc709`. Story 11 remains incomplete;
Slice 3 closeout and Story 12 are outside this slice. Independent acceptance,
deployment and production readiness are not claimed.

## Run and review

From `module-06-5`, with the locked UI, orchestration and MCP extras available:

```powershell
uv run --no-sync streamlit run streamlit_app.py
```

Open the loopback URL shown in the terminal. Select a demonstration, read its
action/expectation/safety/evidence/limitations, press **Run local demonstration**,
then inspect observed metrics and literal results. Each session retains one
result per choice; navigation does not rerun it. A new session can run a fresh
demonstration. No API key, input document, approval handle or provider selection
is needed. No privileged action is authorized by clicking the button.

The module-local Streamlit configuration binds `127.0.0.1`, disables usage
statistics, file watching and run-on-save, and hides framework error details.
Run from the module directory so these defaults are discovered. This is a local
reviewer interface, not a production authentication or multi-user service.

## Architecture and traceability

`streamlit_app.py` renders instructions, accepts a finite demo selection and
requests `reviewer_service.run_demo`. That service composes the **unchanged**
accepted labs and Slice 1 harness, then projects bounded inert display data.
Planning, permission, approval, recovery, accounting, safety and regression
decisions remain in the accepted domain/application services. No architecture
amendment is required by this presentation slice (ENG-001, ENG-006, ENG-007).

| Source lab / capability | Accepted service and visible evidence |
| --- | --- |
| REQ-LAB-001 task planning | `run_planning_lab`: decomposition fixture, ready queues, dependencies and priority order |
| REQ-LAB-002 context compression | `run_context_lab`: constructed prompt budget, compression/provenance, sliding window and memory routes |
| REQ-LAB-003 permissions | `run_permission_lab` / accepted renderer: ten allow/deny/input/scope/injection/boundary scenarios with handler-call counts |
| REQ-LAB-004 recovery | `run_recovery_lab`: real local SQLite checkpoints/effect, injected interruption, three fresh recoveries, one commit and no replay |
| REQ-LAB-005 HITL | `run_approval_lab`: durable suspension and escalation, fixture approval/denial, forged/stale/self approval refusal and off-switch scenarios |
| REQ-LAB-006 / REQ-DEL-004 observability | `run_observability_lab` / `render_report`: correlated traces, structured logs, token/cost attribution, spend warnings, cap denial, recovery and advisory anomalies |
| MCP boundary | `run_mcp_lab`: genuine in-process SDK transport, discovery without authority, allowlisting, validation, bounded calls and resource closure |
| REQ-EVAL-001/002/003 / REQ-DEL-005 | `run_regression` / accepted renderer: all 16 cases, inline invariants, exact mismatch/verdict semantics and 20-workflow latency cohort, including safety and off-switch behavior |

## Safety, resource and evidence boundaries

- Selection accepts exact application-owned enum members only. No free-form
  service names, paths, uploads, prompts, identity/approval/budget fields,
  credentials, evidence labels or live switches reach an application service.
- Fixture approvals run only in the accepted lab with its own principals and
  exact-action handles. Session state contains display data, never durable
  checkpoint/approval/cost authority.
- One nonblocking execution slot per application process prevents simultaneous
  demo initialization. The UI creates no worker threads/processes itself;
  accepted service deadlines and finite matrices remain in force.
- One bounded view per choice per session, at most eight views; details are
  limited to 65,536 characters with an explicit truncation notice. This is a
  presentation safety limit, not an application budget. No rerun loop or global
  cross-session result cache is introduced.
- Every run gets an OS temporary workspace that is cleaned on success or
  exception. Persisted lab files do not survive the demo. Recovery file paths
  are excluded from its display projection. Use accepted CLIs when retained
  inspection artifacts or full reports are required.
- Result content renders as literal code/text, never executable HTML/Markdown.
  A final UI exception boundary shows fixed, actionable guidance without raw
  exception text or traceback; service defects still propagate to service callers.
- Approval results project every scenario and its durable status/audit outcomes
  without dumping action bindings or authority handles into the reviewer surface.
- Deterministic fixtures and local integration are explicitly distinguished.
  Observability uses deterministic accounting fixtures with local SQLite;
  MCP uses an in-memory SDK transport. Windows self-pipes may use loopback.
- No optional live provider, hosted telemetry, live Mem0, Helicone routing,
  genuine human identity service or verified billing is exercised. Fixture
  micro-USD is not provider pricing. One observability workflow cannot assess
  p95; the regression harness separately uses its accepted 20-workflow cohort.
- No credential presence can enable live operations through this interface.

## Builder validation

`tests/test_reviewer_ui.py` uses the installed Streamlit 1.65.0
`streamlit.testing.v1.AppTest` against the real entry point. Coverage includes
startup with no execution; every real local demo; instructions and evidence;
rerun reuse; fixed choices; sanitized defects and busy feedback; literal hostile
content; bounded display; temp cleanup; slot release; and local/privacy defaults.
Socket guards count/deny external connections and classify loopback separately.
AppTest is headless and does not bind a web server.

Builder verification on 2026-10-21 (host Windows, OS temporary artifacts):

1. `ruff check . --no-cache`: PASS. Overlong-line diagnostics during development
   were corrected without changing lint policy; formal gates restarted.
2. Focused UI tests: **21 passed in 25.11 seconds**.
3. Separate cold headless AppTest smoke: **8/8 demos rendered**, all results
   untruncated, eight retained session views, no server bound; **zero external
   socket attempts**, **40 loopback attempts** counted separately. Regression
   reported 16 passed, zero regressed/errors and 20 workflow samples.
4. Full Module 6.5 suite: **1,751 passed, 6 warnings in 191.64 seconds**.
   Warnings are the existing third-party Typer/Click deprecations from Guardrails.
   The accepted fresh-process Guardrails test passed with its timeout unchanged.
5. `python -m compileall -q src tests streamlit_app.py`: PASS; bytecode directed
   to OS temporary storage.

The headless smoke emitted Streamlit's benign bare-mode missing-context warning.
Dependency installation emitted a hardlink-to-copy fallback warning. Neither was
suppressed or required dependency/test changes.

Streamlit **1.65.0** and its locked transitive UI dependencies were installed using
`uv sync --extra ui --inexact`; `--inexact` preserved the pre-existing accepted
optional/runtime/test packages. Pre/post dependency-file SHA-256 values match:

```text
pyproject.toml
A62336F9A0FE9C1974F9CE9EA950808EA6AE7D09DBE8A00769B95C23577BD132
uv.lock
4AA0C6FE580C11FB017BACF4B5443FD8102E8413E372872A126F1A5401A3339C
```

Only five new module-local files comprise this slice: `streamlit_app.py`,
`.streamlit/config.toml`, `src/harness_engineering/reviewer_service.py`,
`tests/test_reviewer_ui.py`, and this report. No accepted Module 6.5 file or
Slice 1 behavior is changed. Work remains unstaged/uncommitted. No independent
acceptance or Story 11 completion is implied by Builder gates.
