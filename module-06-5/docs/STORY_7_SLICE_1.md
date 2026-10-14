# Story 7 Slice 1 — Approval domain and deterministic policy

Authority: the human-approved `STORY_7_AUTHORITY_POLICY.md` at
`8e3702c17a2c8b8ada20d6720745a516137fbf25`, subordinate to the frozen requirements
and architecture. Starting HEAD equals that commit; ancestry passed, with no
intervening commits, tracked Module 6.5 edits, or staged content. Protected
background work was present and is outside this patch.

This slice adds only `src/harness_engineering/approvals.py`,
`tests/test_approvals.py`, and this document. No accepted implementation,
persistence schema, dependency, frozen policy, architecture, requirements,
traceability, implementation plan, ADR, PROJECT_STATUS, or other module changes.

## Domain and trust boundaries

Application bootstrap constructs one `ApprovalPolicyEvaluator` for one immutable
`ApprovalRequest`. The request contains requester, capability/action, risk,
consequential/privileged flags, escalation state/reason, and a required exact
workflow/thread/pending-action/version binding. It is application-owned metadata;
do not build it from model or persisted authority claims. Any change to action
inputs or scope must change the trusted action version before later approval use.

Public observation data contains only finite confidence in [0, 1] and bounded
evidence. Decision data contains exact binding, a finite approve/deny/override kind,
evidence, and override reason. Neither contract accepts approver authority,
threshold changes, tool permissions, callbacks, graph routing, or safety controls.
Evidence is inert text. No API executes work or accepts an assessment as authority.

Contracts are frozen, reject extra fields, recursively revalidate bypass-copied
models, and bound identifiers, text, versions, configured risks, and allowlists.
Configuration/evaluation boundaries require explicit domain objects rather than
automatically converting dictionaries into trusted configuration. Structural
validation alone does not establish provenance.

## Approved policy enforcement

| Authority rule | Slice 1 enforcement |
| --- | --- |
| Application owns approval requirement | Bootstrap pins request and policy; untrusted observation cannot supply them. |
| Default confidence threshold exactly 0.80 | Configurable finite threshold in [0, 1]; approval required strictly below it. Equality does not independently trigger approval. |
| Independent triggers | Consequential action, privileged scope, configured risk, and explicit application escalation each require approval regardless of confidence. All active reasons are retained in stable order. Default configured risks match existing medium/high conventions; trusted configuration may select risks explicitly. |
| Approver allowlist | Only the original local `HumanIdentity` object installed in the ordinary allowlist is accepted. Unknown/missing/string/dictionary/copied/deserialized identities and self-asserted trust labels grant no authority. |
| No self-approval | Installed requester cannot approve or override their own action. An independently allowlisted requester may deny; denial does not grant execution authority. |
| Separate override authority | Override uses its own allowlist; ordinary authority does not imply override. The same handle may be explicitly installed in both. Override-only authority does not implicitly grant ordinary approval/denial. |
| Explicit auditable override | Override kind is distinct, requires a nonblank reason, and remains explicit in the decision assessment with actor, binding, policy reasons, request metadata, and bounded evidence. No durable audit trail is claimed. |
| Hard safety invariants | Current action/capability blocklist, cancellation, invalid authority/binding, hard-budget/deadline exhaustion, denied scope, and prior human denial prevent approval and override. No hard stop can be cleared by decision data. |
| Exact-action binding | Each decision must equal the trusted workflow, thread, pending action, and version. Any dimension mismatch fails closed. |
| Terminal denial | A valid denial reports `terminal_for_action=True`; no retry/fallback permission is produced. Reported prior denial becomes a non-overridable hard stop. |

`ApprovalSafetyState` has no safe defaults. Every current safety fact must be
explicitly supplied by trusted application code. Binding status models current,
invalid, stale, forged, replayed, consumed, and mismatched cases. This policy rejects
every non-current classification; it does not detect replay, store consumption,
latch denial, authenticate a database, inspect clocks/budgets, or read the real
off-switch itself. Later integration must derive facts from current application
sources and retain denial. Passing a fabricated CURRENT/safe state is outside this
trusted boundary and provides no evidence of durable freshness.

Malformed inputs raise `ContractValidationError` with validation causes preserved;
authority/binding/hard-stop rejection raises `AuthorityViolationError`. Those are
terminal policy failures, not retry/fallback instructions. Approval-policy
eligibility never replaces independent capability authorization or safety checks
at the eventual execution boundary.

Local handles demonstrate application authorization semantics only. Bootstrap is
trusted; it must not install model/input-derived identities. Name matching and
possession of decision-shaped data do not issue a handle. This is no real human
authentication, identity provider, credential system, or sandbox against malicious
Python inside trusted application code. After serialization, identity text requires
fresh application authorization; it cannot reconstruct an installed handle.

## Evidence and deferred work

Run the established gates from `module-06-5` using the Python 3.12 environment:
Ruff check `.`, `python -m pytest`, then `python -m compileall src tests`.
For the known Windows temporary-directory problem, select a fresh `--basetemp`
under parent `TECHADEMY/EVIDENCE`; no test/application workaround is needed.

Verification on 2026-10-14 with Python 3.12.14: Ruff passed, pytest **750 passed,
0 failed** (616 accepted cases plus 134 new approval cases), and compileall of
`src` and `tests` passed. The complete fail-fast run used fresh temporary storage
at parent `EVIDENCE/module-06-5-story-7-slice-1/pytest-20261014-1` and took 128.62
seconds for pytest. Repairs after the initial Ruff failure were formatting and a
manually reviewed Python 3.12 generic-function syntax update. No unsafe automatic
fixes, weakened tests/rules, dependencies, or environment configuration changes.

Focused cases cover threshold boundaries/configuration, each independent trigger,
stable reasons, ordinary and separately configured override authority, missing and
matching-but-untrusted identities, self-approval, exact binding mismatches, every
hard stop, malformed/forged/nested contracts, injection text, explicit override
evidence, and terminal denial. These are deterministic policy/domain tests with
no network, credentials, external services, paid calls, or other-module imports.

Persistence, durable requests/decisions/audit, replay/consumption mechanics,
asynchronous suspension/resume, LangGraph interruption, lifecycle integration,
HITL lab/final UI, identity-provider integration, and deployment are deferred.
No Story 7 completion, real authentication, durable enforcement, live-provider,
deployment, or production-readiness claim is made.

Requirements: Slice 1 foundation for REQ-HITL-001 through 003 and later
REQ-DEL-003/REQ-LAB-005. Product Experience: focused runnable tests; final lab/UI
deferred. Real Functionality: actual deterministic policy. Reliability: bounded
contracts and fail-closed rejection; lifecycle/storage deferred. Security: separate
authority, exact binding, hard stops, and inert data boundaries. Cost: zero paid
calls. Evidence: deterministic only for the new approval behavior. Deployment:
none. No frozen-architecture or approved-authority conflict was discovered.
