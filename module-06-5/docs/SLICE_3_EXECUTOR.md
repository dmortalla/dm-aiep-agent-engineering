# Story 4 Slice 3 — Application-Level Bounded Sandbox Executor

Implementation candidate for independent acceptance review; architecture and requirements remain frozen.

## Requirement and architecture mapping

REQ-TOOL-004 is implemented by `src/harness_engineering/execution.py`, with deterministic
credential-free evidence in `tests/test_execution.py`. Accepted REQ-TOOL-003,
REQ-SAFE-002, and REQ-SAFE-003 enforcement is reused directly from `CapabilityAuthorizer`.
ENG-002/003/004/005/007 are supported through validation, application-owned authority,
explicit bounds, zero external calls, and adversarial failure tests. This slice does not
complete REQ-LAB-003 or Story 4's reviewer integration; those remain Slice 4 work.

The design preserves ADR 001 decisions 5, 16–20, 24–25. Capability discovery metadata
is unchanged. No approved architecture, requirement, or Slice 1/2 policy is amended.

## Bootstrap and invocation contract

Trusted application bootstrap creates one executor per workflow, using that workflow's
accepted authorizer, the same capability registry, local synchronous handler bindings,
per-capability limits, and RuntimeBudget. Bootstrap is the authority boundary; do not
construct or reset executors from generated/contextual content. Recreating executors
resets local counters, so application orchestration must retain the workflow instance.

Bindings and limits are snapshotted, capped at 100, and resolved through the registry.
Handlers receive only a fresh validated input model and invocation context. The context
contains the exact approved action/resource, cooperative deadline checks, and work-unit
charging. Local handlers must use this target when accessing resources; scope checks
cannot constrain arbitrary Python code that ignores the context. Register only trusted
application code with bounded schemas and bounded I/O, never generated Python.

`execute(proposal, inputs)` accepts no principal, grants, approvals, decisions, trust,
credentials, handler, or budget overrides. It revalidates the proposal and registry input
contract, acquires a single execution slot, checks the workflow call budget/deadline,
and starts a daemon worker. Immediately before the handler invocation, the worker calls
the accepted authorizer; only ALLOW proceeds. DENY and APPROVAL_REQUIRED raise
AuthorityViolationError and invoke no handler. No approval completion workflow exists.

Input/output are JSON object snapshots validated strictly against registered schemas.
Model instances are serialized then revalidated, preventing model_construct/model_copy
validation bypasses. Schema and JSON failures raise ContractValidationError. Handler
exceptions raise ToolExecutionError with causal chaining. The worker transports thread
exit exceptions too; failures cannot silently become successful results.

## Bounds and accurate sandbox semantics

- One active worker per executor; concurrent requests fail immediately. No queue or retries.
- Workflow calls use RuntimeBudget.max_tool_calls, including authorized failed/time-out calls.
- Effective invocation deadline is the earliest of capability timeout, action timeout, and
  workflow deadline. Workflow deadline starts at executor construction.
- Input/output default to 16,384 serialized UTF-8 JSON bytes each, configurable up to 1 MiB.
- Cooperative work defaults to 100 units per invocation, configurable up to 100,000. Handlers
  charge before work. Invalid/exhausted charges latch failure even if the handler catches it.
- Result validation occurs inside the timed worker; completion after the deadline fails closed.
- Timeout signals cooperative cancellation and rejects the result. An active timed-out worker
  retains the only slot until it exits; no replacement workers accumulate.

This is application-level execution bounding, **not OS/container/VM/kernel isolation**.
There is no filesystem, process, network, CPU, or memory isolation. Python threads cannot
forcibly terminate handlers or undo side effects. An uncooperative stuck handler may run
indefinitely and render its executor unavailable; daemon threads do not ensure cleanup
on process exit. Work units require handler cooperation. Payload size limits constrain
accepted serialized data, not allocation during serialization or handler execution.
Input validation runs synchronously before the action timeout; trusted schema validators
must themselves terminate and avoid external operations. No temporary storage is created
because this slice's handlers need none. Storage-requiring handlers need dedicated bounded
storage provisioned by trusted application code before use.

This executor supplies no billing authorization, token metering, provider calls, deployment,
recovery, HITL resume, or lifecycle integration. Credentials have no role. Any future paid
handler requires separately authorized and bounded application integration.

## Evidence and completion limits

Tests cover exactly-once authorized invocation, missing grants, deny, pending approval,
blocklists, risk, scope, unknown/unbound capabilities, malformed inputs/outputs, forged
metadata, discovery/tag non-authority, direct decision rejection, constructed model
revalidation, causal exceptions, thread exits, timeout quarantine, workflow expiry,
call count, payload bytes, and latched cooperative work exhaustion.

Evidence class: deterministic local handler tests only. No paid or live provider calls.

Definition-of-Done evaluation for this slice:
Requirements: REQ-TOOL-004 candidate coverage. Product Experience: reviewer lab deferred
to Slice 4. Real Functionality: genuine local Python handlers. Reliability: bounded calls,
concurrency, results and cooperative work; timeout limitations above. Security: accepted
authorization enforced at invocation, contracts validated; no isolation against hostile
Python. Cost: zero external execution in tests. Evidence: deterministic only. Deployment:
not performed. This is not a module release or production-readiness declaration.
