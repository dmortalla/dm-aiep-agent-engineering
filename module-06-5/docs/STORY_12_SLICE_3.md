# Story 12 Slice 3: production-grade dual-mode contract reconciliation (corrective)

Corrective contract repair under the already-authoritative repository
production-grade invariant. This is not a new architecture decision, not a
requirements-baseline amendment of the approved 69, and not an implementation
of a live path. No live provider call is made, no real credential is accessed
or requested, nothing is staged or committed, and foreign concurrent work is
untouched.

## Accepted baseline and chronology

Story 12 Slice 1 accepted at `1666e99`; the module-wide release reconciliation
was accepted and committed at `d4d2fd0` with the reviewer-UI reconciliation
`7ce1bd8` ("fix(module-06-5): reconcile deployed reviewer UI"). At mutation
time, `1666e99` was verified an ancestor of HEAD; intervening commits
(`d4d2fd0`, `7ce1bd8` module-06-5 accepted work; `c648b41`, `ed7c86d`
module-10 foreign) were inspected for path ownership only; the index holds
staged foreign module-07 files belonging to the protected parallel workstream
and nothing of this candidate; the module-06-5 working tree was clean before
this repair.

## Root cause (diagnosed)

Repository governance (AGENTS.md, ENGINEERING_SOP.md) requires production-grade
engineering by default unless a module is explicitly declared DEMO-ONLY;
Module 6.5 was never declared DEMO-ONLY. The acceptance contract never
propagated that invariant to the module level: ADR 001 decision 11 scoped
OpenAI/Anthropic as optional live-provider adapters, IMPLEMENTATION_PLAN
Story 9 scoped only "optional" adapter implementation, the Story 12 Definition
of Done contained no dual-mode completion item, TRACEABILITY closed
REQ-TECH-008/REQ-TECH-009 and ENG-* with adapter-only evidence, and the
release-readiness contract therefore reconciled with live-provider evidence =
none. The supporting machinery already existed (and is unchanged):
`HarnessConfig` (`deterministic_mode=True`, `allow_live_providers=False`,
fail-closed mutual-exclusion validator), `EvidenceClass.LIVE_PROVIDER`
(`domain.py`), the live-adapter gate on explicit `allow_live_providers` plus a
finite `max_cost_usd` (`vendor_providers.py`), credential-free adapter tests
plus `test_credentials_or_claimed_locality_do_not_authorize_live_provider`,
and cost-governance boundaries. The defect was a missing additive contract
requirement and its propagation, not missing architecture.

## Corrective contract (additive only)

- **ENG-008 — production-grade dual-mode provider operation**
  (`docs/REQUIREMENTS.md`, exact wording there; provenance recorded in the
  freeze-rule note): deterministic, credential-free operation remains the
  default reviewer mode; live OpenAI/Anthropic execution is opt-in, only
  through explicit validated configuration and a documented provider/model
  allowlist; credentials arrive via trusted server-side/environment/
  secret-store mechanisms and never as public browser input; credentials grant
  connectivity only, never authority; retries/token/output/latency/cost stay
  bounded; evidence classes remain explicitly distinct; provider-level
  production readiness may be claimed only when the live path is implemented,
  securely configured, explicitly human-authorized for execution, exercised,
  and independently evidenced. All 69 approved requirements are preserved
  exactly; nothing weakened, omitted, renumbered, or reinterpreted.
- **ADR 002** (`docs/adr/002-production-grade-dual-mode-completion.md`) —
  corrective decision record: root cause, decision, consequences; ADR 001
  received a non-amending addendum cross-reference.
- **Story 13** (`docs/IMPLEMENTATION_PLAN.md`) — the bounded implementation
  story that will finish dual-mode completion safely (trusted-secret plumbing,
  provider/model allowlist enforcement in the live seam, bounded live-path
  semantic), with exit evidence and an explicit Definition-of-Done item.
- **TRACEABILITY** — corrective section (root cause, contract, implemented
  evidence, outstanding items) plus release-status reconciliation.
- **RELEASE_READINESS.md** — status reconciled to the accepted chronology and
  an explicit outstanding gate: adapter evidence may never substitute for
  live-provider evidence; live-path exercising requires a separate explicit
  human-authorized cost/credential/execution boundary with its own recorded
  live-provider evidence.
- **README (root)** — Module 6.5 boundaries now carry the provider-level
  non-claim and the outstanding dual-mode gate truthfully.
- **PROJECT_STATUS (root)** — module rows reconciled: Story 12 accepted,
  ENG-008 adopted, Story 13 outstanding, deployment not complete.
- **Reviewer UI expectations** — the accepted UI already keeps the
  deterministic/no-key default and requests no credentials; no UI behavior
  change is made. The invariant is pinned by tests (below). Live-provider
  operation is explicitly not part of the reviewer UI surface.

## Tests added (invariant preservation)

`tests/test_dual_mode_contract.py` (10 tests, all deterministic, repository-
structural):

1. ENG-008 exists exactly once with every invariant clause (default mode,
   opt-in, allowlist, trusted secret mechanisms, no public browser input,
   connectivity-only credentials, bounded retries/token/output/latency/cost,
   distinct evidence classes, implement+authorize+exercise+evidence gate).
2. Approved baseline numbering untouched (exact single occurrences preserved).
3. ADR 002 + ADR 001 addendum carry the contract; freeze respected.
4. IMPLEMENTATION_PLAN Story 13 + DoD item; TRACEABILITY section present and
   honest about outstanding completion.
5. RELEASE_READINESS carries the outstanding dual-mode gate and the
   adapter≠live-provider substitution prohibition.
6. Evidence-elevation guard: no RELEASE_READINESS/TRACEABILITY sentence
   asserts live-provider, live provider, or deployment facts without an
   explicit negation/requirement qualifier — the same discipline the
   reconciliation suite's negation-context guard enforces (that guard is
   unchanged and remains intact).
7. Implemented seam defaults are structural: `HarnessConfig()` deterministic
   with every live path disabled; `deterministic_mode+allow_live_providers`
   fails closed.
8. `EvidenceClass` retains all six approved classes with LIVE_PROVIDER distinct.
9. Vendor adapters still gate on explicit allow_live_providers + cost budget
   and the credentials-do-not-authorize tests remain in the accepted suite.
10. Reviewer default path stays credential-free (no key prompt, no input
    widgets accepting secrets, no-key default wording pinned).

`tests/test_release_reconciliation.py` was updated coherently: the
approved-baseline verification is anchored independently of the candidate
document (an explicit immutable tuple of the 69 approved identifiers plus a
SHA-256 digest over the canonical approved requirement lines, captured once
from the independently reviewer-verified baseline state), proving the
candidate holds the approved baseline byte-exact with exactly one corrective
additive identifier (ENG-008); adversarial mutation tests prove deletion,
wording weakening, invention, and unauthorized additive additions each fail;
chronology
phrases updated to the accepted state (accepted commits `1666e99`/`d4d2fd0`,
ENG-008 outstanding, deployment verification separate).

## Notes on adjacent truthfulness (while editing those exact locations)

- RELEASE_READINESS status header now matches the accepted chronology
  (engineering release reconciliation accepted at `d4d2fd0`; deployment
  verification and provider-level production readiness not claimed) instead of
  the stale candidate-only wording.
- README Module 6.5 exact-state bullet now reflects Story 12 accepted and the
  ENG-008 outstanding gate (test count 1,767 refreshed; suite count updated
  again at final gates below).
- The historical slice records (including `STORY_12_SLICE_2.md`) are unchanged
  accepted history; this record is the corrective successor.

## Quality gates

1. `ruff check .` — PASS.
2. Focused tests — 43 passed at the original Slice 3 closeout
   (`test_dual_mode_contract.py` 10, `test_release_reconciliation.py` 10,
   `test_reviewer_ui.py` 23).
3. Full module pytest — 1,778 passed at the original closeout (6 pre-existing
   third-party Typer/Click deprecation warnings); after the B-1/B-2 repair,
   see the addendum below for the final verified numbers.
4. `python -m compileall src tests streamlit_app.py` — PASS.

## B-1/B-2 repair addendum (targeted reviewer re-review scope)

The Reviewer rejected the Slice 3 candidate on two blockers, repaired here
without redesign or scope creep:

- **B-1 — self-referential baseline guard.** The original helper derived the
  approved set from the candidate `REQUIREMENTS.md` itself, so deleting or
  weakening a baseline requirement escaped detection. Repaired: the guard is
  now anchored independently — an explicit immutable tuple of the 69 approved
  identifiers and a SHA-256 digest over the canonical approved requirement
  lines (`f9b938dce21e553025de89249d508f1aac66ea8ff0a2af6085c139ca1113646c`),
  captured once from the independently reviewer-verified preservation state;
  the guard asserts the candidate contains exactly the approved 69
  (byte-exact, unique) plus exactly ENG-008, and fails on removal, wording
  mutation, invented requirements, or unauthorized additive ENG requirements.
  Four adversarial mutation tests (delete REQ-SAFE-002; weaken REQ-SAFE-004;
  insert invented REQ-HITL-009; insert unauthorized ENG-009) prove each
  rejection. The Slice 3 record's earlier drift claim was correspondingly
  corrected to match the protection actually implemented.
- **B-2 — RELEASE_READINESS false statements.** "What remains" now truthfully
  records: engineering release reconciliation independently accepted at
  `d4d2fd0`; reviewer-UI reconciliation accepted at `7ce1bd8` with the hosted
  Streamlit reviewer experience existing and published; final live deployment
  verification still outstanding; Story 13 live-provider completion still
  outstanding; final module closeout outstanding; no live-provider evidence
  claimed yet. No runtime behavior was altered.
- Directly related cleanup performed inside the candidate: the DoD now
  clarifies the 69-approved baseline versus the corrective additive ENG-008;
  the traceability propagation gap statement was reworded neutrally; the
  root PROJECT_STATUS "Remote" row was corrected to the configured origin URL
  after Git evidence confirmed it; the README test count was kept consistent
  with the verified suite (updated again at gate closeout below); gate results
  placeholders in this record were filled with the actual verified numbers.

## Non-claims

No live network/provider call is executed or authorized by this repair; no real
credentials are accessed or requested; no secret handling code changes are
made in this slice; no provider-level production-readiness, deployment, or
hosted-service claim is made; live-provider evidence remains none and adapter
evidence must not be represented as live-provider evidence; the approved
evidence taxonomy is unchanged.

## What remains (Story 13, then gates)

Story 13 implements the trusted-secret seam and provider/model allowlist
enforcement, keeps the deterministic default green and credential-free, and
calls live providers only inside a separate human-authorized
cost/credential/execution gate with recorded live-provider evidence. Provider-
level production readiness may then be claimed only with that evidence.

READY FOR INDEPENDENT REVIEW.


## B-1/B-2 repair gate results (verified, final)

Fail-fast sequence after the targeted repair:

1. `ruff check .` — PASS.
2. Focused `test_release_reconciliation.py` — 15 passed (10 structural + 1
   independent-baseline anchor test + 4 adversarial mutation tests).
3. Focused `test_dual_mode_contract.py` — 10 passed (phrases updated to the
   corrected RELEASE_READINESS wording; guard unchanged in substance).
4. Focused `test_reviewer_ui.py` — 23 passed in 23.02 s; no AppTest timing
   anomaly; the accepted 30-second deadline is unchanged.
5. Full module pytest — **1,783 passed, 6 pre-existing third-party Typer/Click
   deprecation warnings, zero failures** (1,778 + 1 baseline-anchor test + 4
   adversarial mutation tests).
6. `python -m compileall src tests streamlit_app.py` — PASS.

READY FOR TARGETED INDEPENDENT RE-REVIEW.
