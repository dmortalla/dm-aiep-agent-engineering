# Module 10 Story 10.9 — Recovery Grants Architecture (R0)

Status: **planned architecture documentation**. Nothing in this document
authorizes operational recovery, changes trust infrastructure, or selects the
open policy decisions: they remain standing human decisions recorded in the
Story 10.9 record (`docs/STORY_10_9.md`, "R0 recovery-grants architecture
baseline" section). The Step 73 design remains
`DesignApproved=false` for operational purposes; these stages are a documented
plan pending independent review and human acceptance.

## 1. Accepted structural validator baseline

`src/module10_ai/recovery_authorization.py` (committed at HEAD
`e321c5f60a7963281654660a60af2328da649ca7`) implements the offline structural
validation contract for the Step 73 signed recovery grant:

- Exact 23 signed payload fields (`schema, issuer_key_id, grant_id,
  experiment_id, subscription_id, resource_group, container_app,
  authorized_action, restore_min_replicas, restore_max_replicas,
  issued_at_utc, expires_at_utc, experiment_deadline_utc, issuer_sid,
  approval_reference, tenant_id, expected_resource_id,
  expected_pre_recovery_state, approval_version, approval_digest,
  not_before_utc, maximum_execution_attempts, recovery_policy_version`)
  with `schema = taie.module10.recovery-grant.v1`,
  action = `restore_azure_container_app_scale`,
  issuer key id = `TAIE-M10-Recovery-Grant-Issuer-v1`,
  scale bounds exactly (0, 2), and a 900-second experiment window.
- Versioned signature envelope `taie.module10.signed-grant-envelope.v1` with
  canonical payload bytes, byte-preserving SHA-256 transport binding, canonical
  base64 transport, and the RSA-3072 384-byte signature length shape.
- Exact duplicate-key/NaN-strict JSON parsing, canonical compact serialized
  byte form, second-precision canonical UTC timestamps, timezone-aware
  evaluation instants, internal consistency of
  `expected_resource_id` with `subscription_id` + `resource_group` +
  `container_app`, and bounded escaped diagnostics.

**Exact limits of that validator.** Structural validation is NOT cryptographic
authentication, NOT human approval, NOT replay protection, and NOT recovery
authorization. A structurally valid grant proves nothing beyond conformance:
signatures are shape-checked only, approval fields are structural strings, and
the returned structure carries no authority tokens. This separation is
architecture, not a limitation of implementation effort.

## 2. Existing protected Windows recovery trust boundary

The existing Step 73 operational trust infrastructure is documented here as a
protected boundary and MUST NOT be read, exported, created, altered or tested
by any implementation stage without separate authorization:

1. A non-exportable RSA-3072 issuer signing identity exists in protected
   Windows key storage. Its private material never leaves that store, never
   enters this repository, and is out of reach for every offline stage.
2. The corresponding public trust anchor lives at a protected trust-anchor
   location owned by the operator's Windows environment. Verification stages
   will ask the host store for verification-service access; no anchoring rank,
   trust-store file, or key blob may be copied into the repository.
3. Issuer identity and recovery execution identity are distinct Windows
   identities by design. Holding the signing identity does not hold the
   recovery-execution privilege, and recovery-execution authority is bound to
   a separate least-privileged recovery account that cannot reach the issuer
   store or the signing flow.
4. The recovery account runs under a least-privilege boundary: it cannot
   register scheduled tasks, change Windows accounts or ACLs, sign content, or
   modify the trust store, and it re-enters authorization per execution.

Module 10 code must only ever reach these boundaries through narrow,
explicitly authorized service calls (public-key verification against the
protected anchor in stage R1; recovery-command execution from the recovery
account in stage R5). Reading signing keys, reading operational trust-store
files, exporting secrets, or replicating trust material in this repository are
outside scope and prohibited absent new human authorization.

## 3. Conceptual pipeline separation

The recovery pipeline is a chain of independent stages; each consumes its
predecessor's structural output and none takes another component's claim as
its own:

| Stage | Owns | Must never do |
|---|---|---|
| S1 Structural validation (done) | parse, schema, bounds, canonical representation, internal consistency | claim authentication, approval, replay restriction, or authority |
| S2 Cryptographic signature verification (planned R1) | RSA-PSS-SHA256 verification against the protected public trust anchor | issue or sign; treat a valid shape as authentic; reflect raw exceptions |
| S3 Independent approval / policy validation (planned R2) | approval-reference, version and digest binding against the human-owned approval store; bounded policy-version mapping | approve or self-attest; create or edit approval artifacts |
| S4 Durable replay prevention (planned R3) | single-use consumption ledger keyed by the canonical `grant_id` | delete, rewrite, or re-consume; consume on any prior-stage failure |
| S5 Recovery planning (planned R4) | derive the concrete recovery step plan from a verified grant plus a fresh read-only Azure observation | mutate cloud state; execute anything |
| S6 Authorized execution (planned R5) | the fixed recovery mutation command under fresh human operator confirmation | broaden scope, retry without reauthorization, echo secrets |
| S7 Independent outcome verification (built) | existing `validate_state`/HTTPS/Monitor contract re-verified after execution | accept stale reads; skip the final drift check |
| S8 Audit and reviewer presentation (planned R5/R6) | append-only audit evidence, durable compute report, Streamlit review display | claim verified recovery beyond recorded evidence |

## 4. Fail-closed authority chain

```
structural validity ≠ authentication
authentication ≠ approval
approval ≠ permission to execute
attempted execution ≠ verified recovery
```

Every arrow is enforced by a separate stage with its own failure mode. A chain
that stops at any arrow produces a fixed failure and zero success evidence. No
runner joins two arrows; no component gathers grant of two different stages'
privileges together.

## 5. Reconciliation with existing Module 10 architecture

The Stage plan inherits and never modifies these accepted boundaries:

- Module isolation (E-001): the recovery-authority components live under
  `src/module10_ai` solely and make no remote or cross-module calls.
- Untrusted-input discipline (E-008, ARCHITECTURE items 8/9): a recovery grant,
  HTTP response, or CLI observation still reaches a stage only through the
  explicit structural/verification gate before any claim.
- Deterministic reviewer path (E-005): all non-execution stages work offline
  with no Azure access; the live-clock is the only external dependency in S1.
- Evidence classification (E-007): only S6/S7 outputs may be labeled
  `live-cloud/authorized recovery`; planning attempts, grants-in-hand, or
  verified signatures do NOT become recovery evidence.
- Cost boundaries (E-010) and the Azure read-only boundary: no recovery stage
  implements a mutable Azure call before R5 and only within a fresh, bounded,
  human-authorized execution window.

## 6. Planned stages R1-R6 (not implemented)

| Stage | Purpose | Gate convention |
|---|---|---|
| R1 | Trust-anchor loader + `verify_grant_signature` via the protected anchor (public material only) | independent review |
| R2 | Approval-store loader + digest/version binding | independent review |
| R3 | Durable replay-prevention ledger | independent review |
| R4 | Recovery planner (derivation from live reads only, no execution) | independent review |
| R5 | Recovery executor with fixed mutation command, operator reconfirmation, telemetry and audit record | independent review + fresh live authorisation |
| R6 | Reviewer presentation + documentation close-out | independent review |

## 7. Accepted architectural curve: what ALREADY exists vs what is built

The pipeline reuses and does not duplicate: `resource_id`/`identifier` grammar,
`VerificationError` + fixed-text diagnostics, cloud-evidence exclusive-create
persistence and git-boundary checks, the R0 CLI child-process isolation model,
telemetry correlation, the Streamlit reviewer display layer, and the existing
final `validate_state` drift check. The only genuinely new components are the
trust-anchor loader, the approval store, the replay-prevention ledger, the
recovery planner, and the bounded recovery executor.
