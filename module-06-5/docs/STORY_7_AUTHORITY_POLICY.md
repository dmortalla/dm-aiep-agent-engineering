# Story 7 Human Approval Authority Policy

## Status

**APPROVED BY HUMAN REVIEWER - 2026-10-14**

This policy records the human-authorized security and authority semantics required to implement Story 7 - Durable Human Approval and Asynchronous Escalation.

It is additive implementation policy under the frozen Module 6.5 requirements and architecture. It does not amend, weaken, or replace those authorities.

## Governing requirements

- REQ-HITL-001 through REQ-HITL-003
- REQ-DEL-003
- REQ-LAB-005
- ENG-002
- ENG-003
- ENG-007

## Approved authority policy

### Approver authority

Approval authority is application-owned and determined from an explicit trusted allowlist of approver identities.

A requester cannot approve their own pending action.

Unknown, missing, model-generated, agent-generated, untrusted-input-derived, or persisted-only identity does not grant approval authority.

Possession of an approval-shaped record does not itself prove authorization.

### Confidence threshold

The confidence threshold is deterministic and configurable.

The deterministic local demonstration default is 0.80.

Confidence below 0.80 requires human approval under the default demonstration policy.

Confidence at or above the threshold does not bypass approval independently required by consequential-action policy, privileged capability scope, configured risk, or another policy-defined escalation state.

Model or agent output cannot change the threshold or decide that its own privileged action does not require approval.

### Override authority

An override may change an ordinary policy outcome only when performed by a separately authorized override-capable human identity.

Override authority cannot bypass hard safety invariants, including:

- capability or action blocklists;
- cancellation or application off-switch state;
- invalid, forged, stale, replayed, consumed, or mismatched approval binding;
- malformed or untrusted authority information;
- exhausted hard budgets or deadlines;
- deterministic scope or authorization boundaries that policy defines as non-overridable.

Every override must be explicitly identified and auditable.

### Exact-action binding

Every approval decision binds to the exact workflow identity, thread identity, pending-action identity, and pending-action version represented by the trusted application state.

Changed, stale, replayed, forged, mismatched, or already-consumed approvals fail closed.

Approval for one action cannot authorize another action.

### Durable approval state

Pending approval requests and decisions are application-owned durable workflow state.

Durable approval evidence records, at minimum where applicable:

- workflow and thread identity;
- pending-action identity and version;
- requester identity;
- risk classification;
- confidence threshold or escalation reason;
- bounded decision evidence;
- approver identity;
- decision;
- override status and reason;
- deterministic sequence or ordering information;
- audit history sufficient to reconstruct the approval lifecycle.

### Asynchronous suspension and resume

A workflow may suspend while approval is pending and resume asynchronously after an authorized decision.

A persisted approval record does not grant arbitrary execution authority.

Before resumed execution, the application must revalidate current trusted approval policy, approver authority, exact-action binding, cancellation state, and applicable hard safety boundaries.

### Denial

Human denial is terminal for the pending action.

Retry, fallback, recovery, or model output cannot bypass a valid denial.

### Demonstration identity boundary

Story 7 may use deterministic local identities such as requester-1, approver-1, and override-approver-1 for credential-free tests and demonstrations.

These identifiers demonstrate application authorization semantics only. They do not constitute or claim real human authentication, identity-provider integration, or production identity assurance.

## Required adversarial evidence

Story 7 tests and the HITL lab must exercise applicable authority and failure paths, including:

- unauthorized approver rejection;
- requester self-approval rejection;
- forged approval rejection;
- stale or mismatched action binding rejection;
- consumed approval replay rejection;
- unauthorized override rejection;
- attempted override of a hard safety invariant;
- valid approval and asynchronous resume;
- valid denial without retry or fallback bypass;
- recovery of durable pending approval without treating persisted identity as fresh authority.

## Story 7 implementation boundary

Story 7 implements deterministic approval policy, confidence thresholds, durable pending approvals, asynchronous suspension and resume, exact-action binding, denial, bounded override handling, and audit records.

Real external authentication, enterprise identity-provider integration, and production deployment identity assurance are outside Story 7 unless separately implemented, reviewed, and evidenced.

## Human decision

The human reviewer explicitly approved this policy on 2026-10-14 before Story 7 implementation began.
