# Story 9 Slice 3: additive Guardrails AI validation

Implemented for independent review. Story 9 is not formally closed. No broader
project/release status, approved architecture, dependency declarations or lock
state is changed.

## Baseline and scope

Accepted baseline and initial HEAD:
`0a678c470970ef8b3f6edd17faff37017fb80806` (1,307 accepted tests).
Before edits, `git merge-base --is-ancestor` returned 0, the module-filtered
intervening commit log was empty, the entire index was empty, and Module 6.5
had no tracked or untracked changes. Foreign root/Module 7/8/9 work was
protected throughout. No staging, commit, checkout, reset, revert or clean
operation was performed.

Read the controlling source, requirements, traceability, frozen architecture,
ADR 001, implementation plan, Slice 1/2 reports, accepted provider source/tests,
AGENTS.md, CLAUDE.md and engineering SOP. This implements the already-approved
additive guardrail boundary; it introduces no architecture or authority change.

Files relative to `module-06-5`:

- Modified `src/harness_engineering/providers.py`.
- Added `src/harness_engineering/guardrails_adapter.py`.
- Added `tests/test_guardrails_adapter.py`.
- Added `docs/STORY_9_SLICE_3.md` (this report).

## Actual dependency and API

The optional dependency was initially absent. Used the existing mechanism:
`uv sync --frozen --inexact --extra guardrails`. Installed the existing locked
Guardrails AI **0.11.0** and its locked dependencies without removing existing
packages or changing pyproject/uv.lock. Download/install traffic is dependency
setup, not validation, model inference, or external-service evidence.

Inspected installed package source (including Guard, Validator, settings, RC
and schema validator) and exercised these installed signatures:

```python
validate_payload(payload: Any, json_schema: Dict[str, Any], *,
                 validate_subschema: Optional[bool] = False)
SchemaValidationError(*args: object, fields: Dict[str, List[str]])
```

The actual implementation is `guardrails.schema.validator.validate_payload`.
It builds a local JSON Schema Draft 2020-12 validator and local resource
registry, calls `validate_against_schema`, returns `None` on success, and
raises `SchemaValidationError` for rejected payloads. The adapter verifies
exact version 0.11.0 and the required callable/error API at bootstrap. Future
versions require deliberate compatibility review rather than silent acceptance.

This uses a genuine low-level Guardrails AI validation path, not `Guard.parse`,
`Guard.__call__`, a hub validator, remote inference, or a fabricated SDK outcome.
The full Guard/Validator paths support configuration, telemetry and inference;
those execution paths are unnecessary for this narrow role and are not used.

## Role and authority boundary

`GuardrailsTextValidator.validate(text) -> None` validates a disposable
`{"text": text}` payload against a fixed application-owned local schema:
only a required string field, no additional properties, 1..2,000 characters,
and at least one non-whitespace character. Direct adapter input also enforces
the frozen 2,000 UTF-8-byte ceiling. No arbitrary schema, URI reference,
validator plugin, callback, model identifier or generated configuration is
accepted. This adds an explicit nonblank-output check, not semantic moderation.

Trusted bootstrap opts in with:

```python
from harness_engineering.guardrails_adapter import GuardrailsTextValidator
from harness_engineering.providers import ProviderRuntime

runtime = ProviderRuntime(guardrails=GuardrailsTextValidator())
result = runtime.generate({"prompt": "Summarize this local fixture."})
assert result.trust == "untrusted_model" and not result.grants_authority
```

`ProviderRuntime()` still uses only the deterministic fake and does not import
Guardrails AI. Optional construction happens before runtime deadlines start;
framework cold import is not a provider action or deadline-controlled work.

Inside the existing single worker, application schema/profile checks, tighter
runtime UTF-8 output bounds and OutputFilter execute before the additive layer.
The framework receives only disposable data/schema, never context, off-switch,
routing, capabilities, tools, approval, permission, counters or budget objects.
No framework-returned text is used. Even payload/schema mutation cannot replace
the original immutable application response. Only `None` means validation
success; any returned object, bool, string or authority-shaped data fails closed.
The runtime separately rejects a non-None adapter result.

Existing checkpoints bracket validation. Timeout rejects late results and
retains the busy worker slot until completion; cancellation remains one-way.
Each started provider action consumes its existing attempt even when guardrail
validation fails. No retry, repair, re-ask, fallback inference, budget reset,
approval or routing transition is created. Output remains untrusted text in a
fresh application ModelResult. All existing capability/permission/blocklist/HITL
controls remain application-owned and unchanged.

## Failure semantics and confidentiality

Missing package metadata or the missing top-level optional `guardrails` module
raises fixed `GuardrailsConfigurationError`, with an actionable locked-extra
instruction. Unsupported version/API also fails closed at bootstrap.
Missing transitive modules and unexpected programming/import defects propagate;
they are not disguised as optional absence or successful validation.

Known `SchemaValidationError` becomes fixed `ProviderOutputRejected` outside
the framework exception scope. Its raw fields, payload, text, message and
exception chain are not retained by the public application exception.
Malformed outcomes are also rejected with fixed diagnostics. Unexpected
RuntimeError, TypeError and ValueError propagate unchanged and are recorded
as DEFECT by the accepted worker bridge. Raw defects are not sanitized evidence
and should not be rendered/logged as such. Audit remains finite enums/counters.

Guardrails package import itself initializes its settings and may read the
user's `.guardrailsrc`; the selected validation function does not consult that
profile or instantiate telemetry. Tests deny that profile read and replace the
environment with only Windows SYSTEMROOT, without reading/copying credentials.
The application does not alter global framework settings, environment, user
profiles or logging. Arbitrary installed Python package/import behavior is a
trusted-code boundary, not an OS security sandbox. External framework debug
logging is not sanitized application evidence.

## Requirements and adversarial evidence

| Requirement advanced/preserved | Evidence |
| --- | --- |
| REQ-TECH-006 | Actual locked Guardrails AI schema validator executes locally with an explicit additive output-validation role. |
| REQ-SAFE-001 | Nonblank schema validation added after authoritative application OutputFilter/profile/size checks. |
| ENG-002 / ENG-003 | Disposable untrusted text only; malformed/authority-shaped framework results rejected; payload rewrites ignored; hostile text remains inert through real LangGraph routes. |
| ENG-004 | Existing workflow/per-action attempt accounting, tighter size limits, active worker slot, deadline and cancellation remain authoritative. |
| ENG-005 | Credential-free socket/DNS-denied tests, including fresh-process import and genuine validation; fake remains default. |
| ENG-006 / ENG-007 | Explicit local-framework versus injected-fault evidence; expected failures and unexpected defects tested. |
| REQ-TECH-008 / REQ-TECH-009 | Accepted OpenAI/Anthropic source and tests unchanged; full-suite regression result below. |

37 added tests cover genuine valid/rejected text; malformed outcomes;
authority-shaped outputs and hostile text; fixed lifecycle routes and safe stop;
disposable payload/schema mutation; filter and character/UTF-8 bounds before
framework invocation; attempts/retry exhaustion; before/during cancellation;
action timeout/busy slot; workflow deadline; optional absence versus broken
transitive import; unsupported version/API/binding; sanitized known errors;
unchanged programming defects; no Guard/inference/provider execution by
validation; and credential-free, profile-free, network-denied cold imports.

Self-review checked that the adapter cannot widen accepted limits, receive
control-plane references, replace output, retain raw framework failure chains,
or introduce hidden model execution. Accepted tests and quality rules were
not weakened or deleted.

## Verification

Focused final run: Ruff PASS, then **37 passed, 6 warnings in 6.84 seconds**.
Warnings are installed Typer/Click deprecations (binary/text stream helpers and
flag parameters); none were suppressed or repaired by changing dependency state.
Initial development exposed a forward-annotation NameError and a cold Windows
subprocess missing SYSTEMROOT. Fixed the annotation and minimal OS fixture,
then reran focused gates successfully. No accepted policy/check was bypassed.

Final full-module fail-fast gates on 2026-10-17, from `module-06-5`:

1. `.venv/Scripts/ruff.exe check .` - PASS.
2. `.venv/Scripts/python.exe -m pytest -q --tb=short --basetemp
   E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-09-slice-03-final-20261017`
   - **1,344 passed, 6 warnings in 455.83 seconds** (1,307 accepted + 37 new).
3. `.venv/Scripts/python.exe -m compileall src tests` - PASS, exit 0.

The six full-suite warnings are the same Typer/Click deprecations described
above. The accepted OpenAI/Anthropic and Story 9 security tests remain green.
Tests used host Windows Python/event loops; cold sandbox imports can stall.
This did not authorize live/provider execution. Temporary pytest artifacts
remain under parent TECHADEMY/EVIDENCE. Source/tests were unchanged after
final gates began; only this report was completed afterward.

Final repository checks: accepted ancestry still passes; HEAD remains
`0a678c470970ef8b3f6edd17faff37017fb80806`; no intervening module commits;
entire index empty; exactly the four intended module files above are dirty
or untracked; tracked-content `git diff --check -- module-06-5` passes.
Foreign concurrent work remains outside the patch. No dependency/lockfile,
accepted test, architecture, requirement, release/status or foreign file edit
is included. All Slice 3 changes remain unstaged and uncommitted.

## Evidence classification, limitations and review disposition

Evidence is deterministic fake/injected failures plus **genuine local
adapter/framework schema validation**, with accepted local LangGraph integration
and accepted vendor SDKs over mocked HTTP in the full regression suite.
It does not establish live-provider/external-service behavior, paid inference,
authentication or billing validity, deployment, or production readiness.
No real key or model is necessary for this slice.

This is deliberately a narrow structural/nonblank validator. It does not prove
semantic safety completeness, prompt-injection prevention, secret detection,
moderation completeness or production content safety. The lower-level schema
API is version-specific and intentionally fenced to 0.11.0. No hub/model-based
validators or configurable remote references are supported.

Existing limits remain: no forced termination of synchronous Python, atomic
revocation, OS isolation, crash-safe provider effects, durable provider counter
recovery or vendor token/billing accuracy is claimed. Story 10 governance and
Story 11 reviewer UI remain outside this slice.

Completion evaluation: requirements advance as above; product experience is
the runnable API/tests/report with UI deferred; real functionality is actual
local schema validation; reliability/security preserve deterministic controls;
validation incurs zero model spend; evidence classes remain distinct;
deployment/production readiness are unestablished. With all gates passing,
Story 9 appears technically ready for independent closeout review of the
accepted provider slices plus this additive framework slice. Formal Story 9
completion and broader project/release status remain unchanged.
