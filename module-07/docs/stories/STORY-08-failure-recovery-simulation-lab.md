# Story 8 - Failure-Recovery Simulation Lab

## Status

DRAFT — AUTHORED FOR INDEPENDENT CONTRACT REVIEW. Story 8 contract authoring
only; nothing is implemented, staged or committed by this document's authoring
pass. This contract is not accepted until the independent contract review and
human acceptance record supersede this status line.

Accepted Story 7 base for this authoring pass:

- Commit: `fc5084b62bc4e59abe1a98c57fb1edc784f512c7` (ancestor of HEAD, verified).
- Story 7 contract SHA-256 verified intact:
  `43d3350c93e7021bbae6c7c2025472ab9f1c9ab8299db8a178bc9ae7a4212209`.

## Goal

Demonstrate resilience engineering through deterministic, reviewer-reproducible
failure scenarios exercised against the real, accepted Module 7 system.

The Story 8 lab (the "simulation lab") observes, drives and verifies the
already-accepted application-owned boundaries of Stories 1–7 under a fixed,
finite failure taxonomy. It re-proves — never re-implements — retry, fallback,
idempotency, budget, authorization, safety, telemetry, evaluation and gateway
evidence behavior, and it produces reviewer-visible deterministic evidence of
failure recovery paths.

The lab is strictly an evidence and demonstration surface:

- It must NOT become a second application reliability controller.
- It must NOT create an alternate authority, safety, budget, provenance or
  recovery layer.
- It must NOT own any workflow state of record.
- Every reliability claim it makes must transit the real accepted boundaries.

## Authoritative Scope

Derived verbatim from the frozen `docs/IMPLEMENTATION_PLAN.md` Story 8:

- transient provider failure
- permanent provider failure
- timeout
- telemetry failure
- Guardrails rejection and failure
- authorization denial
- replay/idempotency scenario
- malformed response
- budget exhaustion
- recovery evidence

Out of scope for Story 8 (explicit non-goals below): the Streamlit console,
deterministic-vs-live presentation controls, UI-driven lab execution, any new
reliability strategy, any live vendor call, and release/production closure.

## Requirements

Exact assignment from the frozen plan (Story 8 section):

| Requirement | Role in Story 8 |
| --- | --- |
| REQ-LAB-003 | Primary assignment: "simulate failure recovery workflows" — the lab itself. Simulation closure belongs to Story 8; Story 9 additionally presents lab outputs and must not own simulation logic. |
| REQ-REL-001 | Retry strategies re-proven through the real Story 3 controller. |
| REQ-REL-002 | Fallback mechanisms re-proven through the real Story 3 controller (Story 7 already holds its own gateway-routing contribution; Story 8 does not modify it). |
| REQ-REL-003 | Idempotency patterns re-proven through real replay/duplicate scenarios. |
| REQ-REL-004 | Resilience engineering demonstrated across the whole taxonomy with recovery evidence. |
| REQ-ENG-005 | Idempotent operations prevent duplicate side effects — behavioral lab invariant. |
| REQ-ENG-006 | Observability/telemetry/vendor failure never silently grants authority, bypasses safety or corrupts workflow state — behavioral lab invariant. |
| REQ-ENG-007 | Expected failure paths and recovery behavior are tested — the numbered test contract below. |

These six REL/ENG requirements are shared assignments with earlier stories:
Story 3 owns their semantics and implementation; Story 8 owns their
deterministic, reviewer-visible simulation and proof through real boundaries.
Story 8 must not weaken, restate or re-decide any Story 3 semantic; where the
lab's exercise exposes a genuine Story 3 defect, that is reported, not patched
in the lab.

Requirements intentionally left to other stories (no closure here):

- REQ-LAB-001/REQ-LAB-002 (Labs 1–2 with their observability dashboard and
  evaluation pipeline goals) — Story 9 presentation;
- REQ-UI-001..004, REQ-DEL-001/002 presentation and deliverables evidence —
  Stories 9–10;
- all remaining REQ-SEC/REQ-SAFE implementation semantics — Story 2 (this lab
  only re-proves behavior at the real Story 2 boundaries);
- release, prohibition and reconciliation checks — Story 10.

## Assigned ADRs

Binding ADRs constraining this lab:

- ADR-007-003 — Guardrails moderation (real safety boundary; fail-closed).
- ADR-007-004 — reliability strategy (bounded retries/fallback/timeouts/
  idempotency; the controller of record).
- ADR-007-005 — authorization boundary (denial cannot be widened by recovery).
- ADR-007-006 — telemetry redaction (connector data must remain redacted;
  failure telemetry obeys the same rules).
- ADR-007-009 — state recovery (bounded workflow/recovery state semantics).
- ADR-007-012 — cost governance (reservations before work; no refunds outside
  the accepted model; vendor claims never expand budget).

Inherited but not re-implemented (binding through their accepted stories):
ADR-007-001/002 (topology and tool split), ADR-007-008 (CI/live evidence
separation), ADR-007-010 (Streamlit belongs to Story 9), ADR-007-011
(dependency security — no new dependency is authorized for the lab).

## Frozen Architecture Constraints

1. Single controller of record: the Story 3 `ReliabilityController` remains the
   only retry/fallback/timeout/idempotency/budget authority. The lab calls it
   with authorized inputs and reads its results; the injects nothing into its
   internals. Retry, fallback, idempotency and budget decisions observed by the
   lab are always Story 3's.
2. Single safety and authorization boundary of record: Story 2's
   authorization policy, safety pipeline and Guardrails-backed adapter. A
   denied action remains denied regardless of lab pressure (retries, fallback
   attempts, replayed inputs or vendor noise cannot re-open it).
3. Evidence classification of the accepted taxonomy
   (`deterministic_fixture`, `simulated_failure`, `mocked_provider_contract`,
   `live_vendor`, `production_observed`) is used accurately. The lab records
   `simulated_failure` as the recovery evidence class of record for scenario
   outcomes and must never mint `live_vendor` or `production_observed`.
4. Telemetry relations unchanged: Story 4 pipeline remains the neutral
   telemetry surface; Story 5 (Langfuse), Story 6 (LangSmith) and Story 7
   (Helicone) adapters keep their exact accepted behavior. None of their
   script-driven failures may be laundered into application truth.
5. Vendor fallback evidence (Story 7) remains evidence-only; the lab's
   scenarios re-prove that it never drives Story 3 decisions.
6. REDACTION: every lab record obeys Story 4's redaction rules; no API key,
   no bearer token, no provider or vendor message text, no raw untrusted
   content in lab results, summaries, errors or logs. Sanitized fixed reason
   codes only.
7. Determinism: identical lab inputs with identical accepted-module versions
   produce byte-identical scenario results and digests.

## Lab Boundary

The lab is implemented as additive files only:

- `src/reliability_safety_observability/failure_lab.py` — the typed scenario
  models, injection surface, runner and result/summary model.
- `tests/test_failure_lab.py` — the numbered Story 8 contract tests.

No other module changes. No new dependency. No configuration-schema change.
The package `__init__.py` must not export the lab from the deterministic
startup surface beyond what the accepted package contract already permits
(the `__init__` imports no adapter; Story 9 imports the lab explicitly).

The runner exposes one synchronous entry point that executes the finite
scenario matrix sequentially, single-event-loop, returning a typed per-scenario
result list plus one deterministic aggregate summary. It owns no background
thread beyond the accepted bounded-lane machinery already relied on by
Stories 3/6/7 when those boundaries are exercised, and it leaves no thread
running at return.

## Failure Taxonomy

The frozen surfaces and accepted Stories 1–7 ground a finite taxonomy of
twenty lab scenarios, `ScenarioKind` S01–S20. Every scenario defines all
columns below; a scenario without its full row is not implementable.

Legend — Authority owner is the accepted module whose decision is on record
(never the lab). Dispositions reuse the accepted Story 3 classification
labels verbatim (`success`, `attempt_exhausted`, `terminal_exhausted`,
`budget_exhausted`, `authorization_denied`, `safety_denied`,
`time_exhausted`, `timeout_unresolved`, `identity_denied`, `interrupted`,
...) or the accepted adapter outcome labels.

- S01 `transient_retry_recovered` — Trigger: scripted transient failure then
  success on one authorized target. Authority owner: Story 3. Disposition:
  `success` after bounded backoff. Side effects: exactly one. Budget: both
  failed attempt's reservation consumed per accepted accounting. Provenance:
  `simulated_failure` recovery result. Invariant: attempts recorded,
  replayed False, exactly one effect, no budget mutation beyond accepted
  charge, recovery telemetry carries retry classification.
- S02 `terminal_failure_refuses_fallback` — Trigger: scripted permanent
  failure on the primary with a second authorized target registered.
  Authority owner: Story 3. Disposition: `terminal_exhausted`; the fallback
  target is NOT invoked (accepted default `fallback_on` excludes TERMINAL).
  Side effects: zero. Invariant: the second target's operation never fired;
  a policy-fallback_on=TERMINAL variant remains available for demonstration
  as an explicit secondary scenario input, where fallback success reuses S06
  invariants.
- S03 `operation_timeout_unresolved` — Trigger: scripted never-returning
  operation under the per-op timeout (bounded real 0.5s max tick on the
  adapter side, deterministic). Authority owner: Story 3. Disposition:
  `timeout_unresolved` (uncertain effect status; ownership uncertainty is
  recorded, never converted into "stopped successfully"). Side effects:
  reported as uncertain-of-record; follow-up duplicate-suppression behavior
  under S08's rules. Invariant: recovery state honestly marks the attempt
  unresolved; no successful claimed effect without observed completion.
- S04 `whole_run_deadline_exhausted` — Trigger: run deadline reached between
  attempts (virtual clock). Authority owner: Story 3. Disposition:
  `time_exhausted` (accepted label), no new attempt begins after exhaustion.
  Invariant: budget reflects only accepted charges; telemetry records the
  deadline refusal.
- S05 `retry_exhaustion` — Trigger: scripted transient failures equal to the
  policy attempt bound. Authority owner: Story 3. Disposition:
  `attempt_exhausted`. Side effects: zero success effects, one recorded
  reservation per attempt. Invariant: attempts == policy bound; no
  post-bound retry; telemetry correlates the exhaustion.
- S06 `fallback_success` — Trigger: primary scripted exhausted (transient),
  fallback target succeeds. Authority owner: Story 3. Disposition: `success`
  with `fallbacks == 1` and fallback telemetry. Side effects: exactly one
  (on the fallback target). Sandbox invariant: authorization for the fallback
  target was granted before the run and is not fabricated by the lab.
- S07 `fallback_exhaustion` — Trigger: every registered target's scripted
  outcomes exhausted. Authority owner: Story 3. Disposition: the accepted
  exhaustion classification for the configured policy (attempt or fallback
  exhausted), no further target, no authority widening. Side effects: zero.
- S08 `duplicate_replay_suppressed` — Trigger: re-execution of the same
  logical operation identity after a recorded outcome. Authority owner:
  Story 3 (idempotency registry of record). Disposition: accepted replay
  semantics (recorded outcome re-served / replayed marker), no second
  governed invocation. Side effects: exactly one, total, across both
  executions. Invariant: effect count 1; `replayed` reflected in recovery
  evidence.
- S09 `side_effect_duplication_refused` — Trigger: replay/attempt pressure
  over an uncertain timed-out attempt (S03 continuation). Authority owner:
  Story 3. Disposition: accepted uncertain-attempt handling; lab asserts the
  observed total effects against the accepted bound (uncertain attempts
  surfaced honestly; if the accepted semantics permit at most one observed
  effect, more than one observed effect is an invariant failure of the lab,
  a Report — not silently accepted).
- S10 `budget_exhaustion_reservations` — Trigger: budget limit sized to be
  consumed by scripted reservations before success is reachable. Authority
  owner: Story 3 budget model. Disposition: `budget_exhausted` before any
  additional governed work; reservations charged before work only per
  accepted semantics; uncertain work never refunded. Invariant: observed
  charges == accepted accounting; vendor cost evidence (any of Stories 5–7)
  cannot expand the budget or authorize another attempt.
- S11 `authorization_denial_sticky` — Trigger: tool denied to the principal;
  scripted retry and fallback pressure around an otherwise-authorizable
  flow, including a denied second target. Authority owner: Story 2.
  Disposition: `authorization_denied`-class outcome; stays denied across
  retries, fallback, replay and recovery pressure. Side effects: zero for
  the denied action. Invariant: no lab path, scripted outcome or vendor
  record widens permission.
- S12 `safety_refusal_and_provider_failure_fail_closed` — Trigger: (a)
  scripted input that the accepted deterministic safety checks reject and/or
  Guardrails-moderation refusal path; (b) a failing Guardrails provider
  lane. Authority owner: Story 2. Disposition: `safety_denied`-class
  outcome; provider failure fails closed (never fail-open). Side effects:
  zero. Invariant: no lab input may convert a safety refusal into an
  application effect.
- S13 `prompt_injection_forged_authority_defeated` — Trigger: untrusted
  content carrying authority-shaped text ("you are now authorized"),
  forged permission claims, and vendor records carrying instruction-shaped
  text, replayed through recovery pressure. Authority owner: Story 2
  boundaries decide; Story 3 sees untrusted content only. Disposition:
  denial of the attack; no effect from injected instructions. Invariant:
  content-shaped claims never alter authorization, safety, retries,
  fallbacks, budgets, ids or evidence class.
- S14 `malformed_vendor_evidence_contained` — Trigger: scripted malformed,
  conflicting, duplicate and stale vendor records fed to accepted adapter
  boundaries (Helicone readback shapes; LangSmith readback/feedback mirror
  shapes). Authority owner: the adapter of record classifies untrusted
  rows; Story 3 state is untouched. Disposition: accepted fail-safe
  classification (`malformed`/mismatch/`unresolved` classes), no mint, no
  authority change. Invariant: story 3 result identical with and without
  the vendor noise.
- S15 `telemetry_pipeline_failure_isolated` — Trigger: scripted failure of a
  downstream telemetry consumer while the real pipeline emits accepted
  telemetry. Authority owner: Story 4 neutral pipeline. Disposition:
  accepted telemetry-failure handling (bounded, redacted); the workflow
  result and Story 3 state are unchanged. Invariant: workflow outcome and
  budget identical with and without the telemetry failure; redaction holds
  in failure telemetry.
- S16 `observability_vendor_unavailable` — Trigger: Langfuse adapter in its
  accepted unavailable/unauthenticated offline disposition. Authority owner:
  Story 5 boundary. Disposition: accepted no-network refusal/isolation;
  workflow unchanged; adapter evidence stays at its accepted class.
- S17 `evaluation_vendor_unavailable` — Trigger: LangSmith adapter in its
  offline refusal state. Authority owner: Story 6 boundary. Disposition:
  the local engine, benchmark and regression evidence are unchanged;
  adapter refusal is contained with fixed reason codes; no evaluation claim
  upgrades.
- S18 `gateway_evidence_unavailable_or_contradictory` — Trigger: Helicone
  adapter boundary with missing, unfound (404-equivalent), contradictory
  cost/fallback rows or unavailable transport. Authority owner: Story 7
  classification. Disposition: accepted classification states
  (missing/malformed/disagree/unknown), never application authority, and
  Story 3 decisions identical with and without the gateway states.
- S19 `lifecycle_close_failure` — Trigger: scripted failing or interrupted
  close on an observable lane (adapter-level and lane-level). Authority
  owner: accepted adapter/lane close semantics. Disposition:
  accepted close labels (`close_failed`, `close_busy`, fixed refusal);
  send-after-close refused; idempotent close behavior; no background thread
  left; no interpreter-exit reliance.
- S20 `unresolved_ownership_released_only_on_resolution` — Trigger:
  retained ownership past a per-op time bound of a lane-boundary operation,
  followed by genuine resolution. Authority owner: accepted bounded lane
  machinery of record. Disposition: busy refusal while unresolved; close
  reports `close_busy` while unresolved; ownership released only on genuine
  resolution; no duplicate side effect from repeated operations. Invariant:
  evidence never upgraded while unresolved.

## Failure-Injection Boundary

A typed, finite model — no arbitrary execution:

1. `ScenarioKind` — a `StrEnum` enumerating exactly S01–S20 above. Unknown
   kinds refuse at construction with a fixed `ConfigurationError`, naming
   the field, never values.
2. `ScriptedOutcome` — a frozen dataclass with fields bounded to what the
   accepted `AttemptResult` surface can produce from enumerated inputs only:
   `kind` (`success` | `transient` | `terminal` | `timeout`), a bounded
   `cost_usd` (finite, nonnegative, ≤ 1.0 per outcome), an optional
   bounded literal output token string drawn from a fixed allowlist of
   marker tokens (never scenario text, never untrusted). No callable, no
   code object, no `eval`/`exec`, no import machinery, no network address,
   no shell.
3. `FailureScript` — a frozen, finite, non-empty list of `ScriptedOutcome`
   (≤ 16 entries) plus the bounded `ReliabilityPolicy` under which the
   scenario runs. Policy-fixture bounds are Story 8-specific, beyond the
   accepted Story 3 schema validation (whose production ceilings are
   intentionally broader): fixtures may vary only policy fields already
   accepted by Story 3, introduce no new policy semantics, and are
   additionally constrained by the lab-owned deterministic resource bounds
   of this contract — lab attempts ≤ 8 per scenario, real waits ≤ 0.5s
   each and ≤ 1.5s total per scenario. Broader production-valid Story 3
   values remain valid production values but sit outside the deterministic
   lab fixture envelope; these are simulation bounds, never new
   application policy. The lab may not silently widen any bound.
4. Injection point — the ONLY injection surface is the documented adapter
   boundary that `Target` invokes: the lab constructs one real, authorized
   `Target` per declarative plan whose operation adapter consumes the next
   `ScriptedOutcome` from the script, mirrors the accepted deterministic
   test pattern (finite iterator; exhausted iterator raises bounded
   `InvalidScenario`), and forwards real results into the real controller.
   For vendor/telemetry scenarios the injection runs through the accepted
   public offline behaviors of Stories 4–7 (their fakes, seams and offline
   config refusals) — the lab never reaches into vendor client internals,
   never spawns sockets, never fabricates vendor identity.
5. This cannot become an authority or security bypass because: the only
   power the injected adapter has is to return an `AttemptResult`-shaped
   value which the real controller classifies itself; the lab cannot
   authorize, mint, refund, widen, skip safety or inject state — every
   authority-shaped decision remains inside the accepted boundaries of
   record; and the injection surface references no credentials, no network
   and no production configuration.

## Time / Timeout Simulation

Deterministic with the accepted clock injection:

- The controller's accepted `clock` and `sleeper` hooks receive the lab's
  deterministic zero/near-zero-advance clock for backoff and deadline
  scenarios (no real production-duration waits; real sleeps bounded ≤ 0.5s
  per scenario step and only where the accepted boundary itself waits).
- Distinguished precisely, per the accepted model:
  - provider operation timeout (per-op `timeout_seconds`; per-op bounded
    label);
  - whole-run deadline (`deadline_seconds`; `time_exhausted`, refusal of
    new attempts after exhaustion);
  - unresolved timeout ownership (`timeout_unresolved`, uncertain effects,
    retained ownership);
  - close/lifecycle timeout (bounded close lane; `close_busy` on unresolved
    ownership; `close_failed` acceptance).
- Recovery evidence must never imply work stopped when ownership remains
  uncertain: `timeout_unresolved` is surfaced as unresolved in the lab
  result and never counted as a recovered success.

## Idempotency / Side Effects

Pinned from accepted Story 3 semantics and re-proven behaviorally:

- Operations govern through stable idempotency keys owned by `WorkflowState`;
  the same logical replay reaches the same recorded outcome without a second
  governed invocation.
- Maximum expected effect count for governed success variants is exactly one
  recorded effect per logical operation (S09 asserts the accepted bound and
  reports any excess as an invariant failure).
- Duplicate suppression: repeat execution with the same identity is accepted
  replay semantics and never issues fresh authorization or a fresh effect.
- After an uncertain timeout (S03/S09/S20), only the accepted semantics
  decide whether retry/fallback may proceed; the lab never overrides that
  decision and asserts the accepted outcome only.
- Budget charging: reservations occur before governed work per accepted
  semantics; uncertain and failed attempts are never improperly refunded;
  replayed results do not recharge the ledger beyond accepted semantics.

## Budget / Cost Failure

Using Story 3's authoritative budget model only:

- Reservations occur before governed work (accepted pre-charge), verified by
  observed `UsageRecord`/`BudgetState` accounting before and after each
  scenario.
- Exhausted budget prevents additional governed work; the accepted
  `budget_exhausted` classification applies; no scenario may continue past
  refusal through retries/fallbacks the accepted policy would refuse.
- Uncertain work is not refunded (accepted never-refunded semantics; the
  lab observes the accounting and must never mutate it).
- Vendor cost evidence from Stories 5–7, including any simulated gateway
  cost rows, cannot expand authority, refund, authorize more work, or mint
  budget.
- No invented monetary ceilings: all budget values are bounded test-local
  literals well inside accepted schema bounds; no live ceiling is defined
  or claimed.

## Security / Authority Scenarios

Scenarios S11–S13 above; behavioral proofs at the real boundaries:

- Untrusted content cannot grant authority — attacked through recorded
  authorization denials that remain denials after retry/fallback/replay
  pressure (real `AuthorizationPolicy` decisions re-run under lab pressure).
- Prompt injection cannot bypass authorization — the same denial disposition
  holds with injection-shaped untrusted content and with forged identity
  claims.
- Safety validation cannot substitute for authorization — scenarios where
  safety would pass but authorization denies (and vice versa) both refuse
  the governed effect; never an "OR" path.
- Denied tool action remains denied under retry/fallback/recovery pressure —
  the sticky invariant of S11.
- Vendor telemetry/evidence cannot become instructions — S13's vendor-shaped
  records carry instruction text and are asserted inert at every real
  boundary.

## Observability Failure Isolation

Scenarios S14–S18 above preserve the accepted responsibility split:

- Story 4 neutral telemetry: pipeline-local failure containment; record
  redaction in failure paths; no authority transfer.
- Story 5 Langfuse operational observability: unavailable → accepted
  offline refusal; already-accepted adapter behavior re-proven under lab
  conditions; never silent authority.
- Story 6 LangSmith evaluation/regression: offline/unavailable → local
  evaluation evidence unchanged; adapter refusal contained; regression
  baselines never mutated by the lab.
- Story 7 Helicone gateway evidence: missing/contradictory/unavailable →
  accepted classification states; evidence-only forever.

Contract pin: no scenario in this lab may treat a vendor adapter failure as
an authorization, retry, fallback, replay or budget signal.

## Simulation Result Model

`LabScenarioResult` — frozen, bounded, reviewer-visible, evidence-only:

- `scenario_id`: canonical, deterministic scenario identifier of record.
- `kind`: one `ScenarioKind` of record.
- `kind_version`: lab scenario-definition version (a fixed integer bump for
  invariant-affecting changes).
- `trigger`: bounded primitive map (≤ 16 entries, fixed allowed keys: the
  scripted outcome kinds, policy bounds, target names as fixed markers) —
  never raw untrusted text.
- `expected_disposition`: the invariant's fixed expected label(s) of record.
- `observed_disposition`: the real system's actual classification label.
- `attempts`, `fallbacks`, `effect_count`: observed real-controller counts.
- `budget_before_usd`, `budget_after_usd`: observed accounting of record
  (finite, bounded).
- `authority_outcome`: the authorization decision classification observed.
- `safety_outcome`: the safety decision classification observed.
- `telemetry_state`: sanitized telemetry/failure state of record (fixed
  labels; no vendor text).
- `evidence_class`: `simulated_failure` for governed recovery scenarios;
  accepted adapter classes at vendor boundaries (`mocked_provider_contract`
  where accepted); never `live_vendor` or `production_observed`.
- `passed`: strict boolean of record.
- `reason_codes`: a bounded tuple of fixed sanitized reason identifiers
  (accepted refusal/classification ids only; never messages, never secrets,
  never vendor text).

Field-count and value-size rules mirror the accepted evidence-export bounds
(≤ 32 fields; string values ≤ 256 chars; no secret-shaped values). Records
must remain JSON-safe.

## Lab Summary / Reviewer Evidence

`LabSummary` — deterministic aggregate of record, non-authoritative:

- `lab_version`: the lab contract version of record (bump on invariant
  changes).
- `scenario_count`: number of scenarios executed (≤ bound below).
- `passed_count`, `failed_count`: strict pass/fail accounting.
- `invariant_failures`: bounded list (≤ 32) of sanitized invariant failure
  descriptors (`scenario_id`, `reason_code` pairs), empty for a passing run.
- `evidence_counts`: per evidence-class tally of record.
- `digest`: deterministic digest over canonicalized scenario results, using
  the accepted Module 7 `canonical_digest` mechanism (the single digest
  mechanism of record; no alternate Story 8 digest implementation exists).
  Canonical ordering is pinned: scenario results are ordered by ascending
  `scenario_id` before digest input construction; each result serializes as
  the canonical frozen-JSON representation of its primitive map with fixed
  key ordering (the model's declared field order), so identical results
  produce byte-identical digest input and byte-identical digest output.
  If `canonical_digest` is ever proven technically incapable of satisfying
  this frozen contract, STOP rather than silently inventing a replacement.
- The summary is presentation input for Story 9 and integrated verification
  evidence for Story 10 — never authoritative application state; any UI
  change based on the summary remains a Story 9/10 responsibility.

## Evidence Modes

- Governed recovery scenario results: `simulated_failure` (the accepted
  accuracy label for exactly this situation).
- Scaffolding/dataset-side lab fixtures: `deterministic_fixture`.
- Vendor-adapter boundary evidence encountered through accepted fakes/seams
  and offline refusals: `mocked_provider_contract` (and adapter refusal
  evidence per each story's accepted behavior).
- Story 8 never mints `live_vendor` or `production_observed`; no live
  provider or production claim extends from this lab; a simulated recovery
  does NOT prove live-provider, live-vendor or production behavior. The
  frozen plan assigns Story 8 no live requirement; the lab is fully
  deterministic ordinary CI.

## Cost / Resource Bounds

- Maximum scenarios per full run: the 20-kind taxonomy exactly once (a bounded
  runner accepts a finite subset list too, but no ad-hoc scenario
  construction beyond the taxonomy).
- Maximum attempts per scenario: ≤ 8 (Story 8 lab-owned bound; policy
  fixtures vary only Story-3-accepted policy fields, introduce no new
  policy semantics, and are additionally constrained by these lab bounds;
  broader production-valid Story 3 values stay valid production values
  outside the deterministic lab fixture envelope).
- Maximum scripted outcomes per target: ≤ 16.
- Maximum simulated delay representation: virtual clock; real waits
  ≤ 0.5s each and ≤ 1.5s total per scenario (Story 8 lab-owned test bounds,
  not new application policy), sequencing only.
- Result/summary size: ≤ 64 KiB total serialized summary; per-scenario
  records under the accepted evidence bounds.
- Bounded cleanup: each scenario closes/cleanses any lane resources it
  opened before returning; no lab-run thread survives the runner returning;
  no unbounded loops (every loop in the lab has a fixed bound constant).
- Sequential execution only (accepted single-event-loop model); no
  concurrency requirement exists in the frozen Story 8 assignment.

## Required Tests

All in `tests/test_failure_lab.py`; numbered, behavioral, reviewer-attackable.
Source-string or constant-existence assertions never substitute for
behavioral proof. Ordinary CI: credential-free, network-free, bounded.

1. Scenario schema and refusal: every `ScenarioKind` constructs; unknown
   kinds, empty/oversized scripts, ghost-scripted outcomes, non-allowlisted
   tokens, unbounded costs, oversized descriptors and unknown trigger keys
   all refuse construction with fixed safe errors naming fields, never
   values; identical inputs construct identical frozen results.
2. Lab determinism and reproducibility: executing the full default matrix
   twice yields identical per-scenario results, identical `LabSummary`
   counts and an identical digest; the summary's deterministic serialization
   is byte-stable across two runs; execution is finite (bounded wall clock
   under an implicit CI timeout).
3. Real-controller transient recovery (S01): scripted transient failure and
   success through a real authorized Target into the real
   ReliabilityController produces the accepted `success` classification,
   recorded attempts/backoff telemetry and exactly one effect; recovery
   telemetry correlation present; result carries `simulated_failure`.
4. Terminal failure semantics (S02): accepted `terminal_exhausted`, fallback
   target untouched in the default policy; the explicit TERMINAL-fallback
   variant succeeds only with prior authorization and all S06 invariants.
5. Per-op timeout ownership (S03): a real never-returning adapter in a real
   controller run yields the accepted `timeout_unresolved`-family semantic
   with honestly-marked uncertainty; nothing falsely claims completion;
   idle provider threads terminate per accepted bounded-lane behavior.
6. Whole-run deadline (S04): with a virtual clock, deadline exhaustion
   produces the accepted `time_exhausted` label, no new attempt begins after
   exhaustion, and budget reflects only accepted charges.
7. Retry exhaustion (S05): attempts == accepted policy bound under scripted
   transient failures; the accepted exhaustion classification and correlated
   telemetry hold; additional scripted outcomes are never consumed.
8. Fallback success (S06): primary scripted exhaustion, real fallback target
   succeeds with `fallbacks == 1`, exactly one total effect, budget exactly
   the accepted charge pattern, fallback telemetry classified.
9. Retry/fallback exhaustion (S07): all targets exhausted under bounded
   rules; accepted exhaustion classification; neither target fires again.
10. Idempotent replay duplication (S08/S09): same-identity replay re-serves
    the recorded outcome without a second governed invocation; total
    observed effects remain exactly one; `replayed` recorded; any excess
    observed effect is a detected lab invariant failure, not silently
    accepted.
11. Uncertain-attempt continuation (S09/S20 linkage): replay/attempt
    pressure after `timeout_unresolved` follows only the accepted semantics;
    the lab verifies observed effect accounting against the accepted bound
    and reports honestly.
12. Budget exhaustion (S10): reservation-before-work observed; the accepted
    `budget_exhausted` classification; no additional governed work; neither
    proper refund of uncertain work nor any vendor-driven budget expansion;
    lab verifies accounting snapshots before/after.
13. Authorization denial stickiness (S11): real denial stays `denied` under
    scripted retry, fallback and replay pressure; no path, scripted outcome
    or vendor record widens permission; side effects of the denied action
    remain zero.
14. Safety refusal and provider failure, fail closed (S12): real Accepted
    Story 2 boundaries reject under the scripted safety scenario; a failed
    Guardrails provider lane fails closed; no effect ever results from safety
    failure.
15. Prompt-injection and forged authority defeat (S13): authority-shaped and
    vendor-shaped instruction content inside untrusted inputs is inert at
    every real boundary; no effect, no authorization change, no telemetry
    corruption; denied outcomes unchanged.
16. Malformed/contradictory vendor evidence containment (S14/S18): accepted
    adapter classification behavior for malformed/stale/conflicting/duplicate
    records with story-3 workflow results proven identical with and without
    the noise; no mint; no authority change.
17. Telemetry pipeline failure isolation (S15): a real accepted telemetry
    pipeline under a scripted downstream failure leaves workflow outcome and
    budget untouched, with accepted redacted failure telemetry.
18. Vendor unavailable, evaluation vendor offline (S16/S17): accepted
    offline/unavailable dispositions of the Langfuse and LangSmith adapters
    under lab conditions leave workflow, budget and local evaluation/
    regression evidence unchanged and contained.
19. Lifecycle and ownership (S19/S20): failing close reports the accepted
    label, idempotent close holds, send-after-close refuses, close-busy on
    unresolved ownership, ownership releases only on genuine resolution, no
    background thread survives the runner.
20. Result and summary schema, evidence classification: every field of the
    result/summary model under fixed bounds; reason codes sanitized;
    `simulated_failure`/`deterministic_fixture`/`mocked_provider_contract`
    labels given exact accuracy; assert no `live_vendor`/`production_observed`
    mint and a Story 9-consumable deterministic shape. Secret-containment,
    behavioral: configured secret-shaped values, credential-like values,
    raw prompt/provider content and uncontrolled vendor text never appear
    in any `LabScenarioResult`, in `LabSummary`, in the canonical serialized
    representation, in the `canonical_digest` input, or in any sanitized
    reason code — proven by driving scenario fixtures that carry
    recognizably secret-shaped and injection-shaped values through the real
    lab flow and scanning every emitted record/summary/component with the
    lab's redaction rules (accepted secret shapes and configured-value
    redaction); any occurrence is an invariant failure, never silently
    emitted.
21. Resources + zero-network CI: full lab matrix in a subprocess with ambient
    variables present and a connection-refusal socket guard: zero non-loopback
    connect attempts, no vendor SDK import beyond what the accepted
    deterministic surface allows, bounded runtime, sequential execution, and
    no residual thread or session; conclusion in summary only.
22. Cross-suite regression with bounded, recursion-safe selection: the
    Story 8 sweep must prove Stories 1–7 still pass unchanged in ordinary
    CI, without unbounded subprocess nesting. The accepted Story 7 test
    `test_22_cross_suite_regression_stays_green` discovers every
    `tests/test_*.py` except its own current file, so a naive Story 8 sweep
    would recurse Story 7 → Story 8 → Story 7 forever. The Story 8
    cross-suite rule is therefore pinned exactly:
    a. Explicit deterministic selection: the spawned sweep enumerates an
       explicit, ordered, construction-time list of accepted Story 1–7 test
       files (not broad glob discovery), selected deterministically from the
       module test directory.
    b. The Story 8 failure-lab test file itself
       (`tests/test_failure_lab.py`) is excluded from the spawned sweep.
    c. The recursive Story 7 node
       `tests/test_helicone_contract.py::test_22_cross_suite_regression_stays_green`
       is explicitly deselected from the spawned sweep.
    d. All other accepted Story 7 tests (and Stories 1–6 tests) run in the
       spawned sweep; the Story 7 file is not dropped for convenience.
    e. Guarantee by construction: inside the spawned sweep,
       `tests/test_helicone_contract.py` runs with that one node
       deselected, so no subprocess launched by Story 8 test 22 can launch
       another cross-suite-regression subprocess (Story 7 test 22 is absent
       from the sweep's collection).
    f. Global process-tree depth invariant, stated truthfully: the maximum
       cross-suite subprocess nesting depth is AT MOST 2 below the original
       outer pytest process; the only permitted depth-2 path is outer pytest
       → accepted Story 7 test 22 child → Story 8 test 22 bounded child; no
       depth-3 cross-suite subprocess is permitted anywhere. No sentinel is
       introduced merely to force depth 1; depth ≤ 2 is the truthful
       invariant of the immutable accepted Story 7 behavior plus Story 8's
       own bounded child, while retaining a finite mechanical safety bound.
    g. Ordinary outer-suite execution of both Story 7 test 22 and Story 8
       test 22 is preserved unchanged. Both test-22 nodes execute when the
       full suite runs. Accepted Story 7 test 22 legitimately discovers
       `tests/test_failure_lab.py` in its own child (its accepted selection
       globs every `tests/test_*.py` except its own file), so Story 8 test
       22 may execute once inside Story 7's child; that nested Story 8
       invocation may launch its own bounded child; Story 8's child
       explicitly excludes `tests/test_failure_lab.py` and deselects
       Story 7's recursive test-22 node; therefore no further cross-suite
       subprocess can result and the process tree terminates by construction.
    h. Bounded nested cross-suite execution is permitted; unbounded
       recursive subprocess execution is prohibited — these are the pinned,
       distinct terms. Ordinary CI retains complete intended coverage:
       the outer full-suite run remains authoritative; bounded cross-suite
       nesting is finite and globally capped at depth ≤ 2; recursive
       re-entry beyond this bounded process tree is prohibited; no
       unbounded mutual recursion exists anywhere.
    i. Mechanical acceptance invariant (behavioral, self-proven): the test
       must verify — through its deterministic selection construction
       and/or direct process-tree evidence — that Story 8's child
       selection excludes `tests/test_failure_lab.py`, deselects the
       Story 7 recursive node, contains no cross-suite regression node
       capable of launching a depth-3 subprocess, and yields a global
       maximum depth ≤ 2 with the child exiting normally. Failure to
       construct the exact bounded selection fails closed; broad glob
       fallback is forbidden. No modification of Story 7 is required.
    j. Direct Story 8 test-22 execution (depth metric, documented for
       unambiguity): when Story 8 test 22 runs directly in the outer suite
       it produces `direct Story 8 test 22 → one bounded child → STOP`,
       a process tree of depth 1. When it runs inside Story 7's accepted
       child, the tree is `outer pytest → Story 7 child → Story 8 bounded
       child → STOP`, global depth 2. Both cases are within the same ≤ 2
       invariant; the depth metric is always measured below the original
       outer pytest process.
    k. Fail closed: if the bounded explicit selection cannot be constructed
       (a listed file is missing, the deselection target is absent, or the
       selected set would be empty), the test fails closed with a fixed
       safe reason; it never silently degrades to glob discovery or drops
       the whole Story 7 file.
    l. Resource discipline: the accepted Story 7 and Story 8 cross-suite
       tests duplicate some coverage between them; the outer suite remains
       the authoritative full ordinary-CI coverage; Story 8 test 22 is a
       bounded regression proof, never an unbounded suite launcher; no test
       may expand the selection through glob fallback; the controlling
       safety invariant for this story is maximum process-tree depth, not
       the number of duplicated assertions; no new performance claims are
       made.
    No Stories 1–7 file is modified; a deselection is a selection argument,
    not an edit.

## Requirement-to-Acceptance Coverage

| Requirement | Acceptance tests |
| --- | --- |
| REQ-LAB-003 | The lab whole: tests 1-3, 5-14, 16-22 (the entire simulation surface) |
| REQ-REL-001 | tests 3, 5, 7, 12, 13 (retry incl. budget/auth pressure) |
| REQ-REL-002 | tests 4, 6, 8, 9 (fallback success/exhaustion/refusal + deadline) |
| REQ-REL-003 | tests 8, 10, 11 (idempotent replay + duplication) |
| REQ-REL-004 | tests 3-19 (collective resilience findings) · regression sweep test 22 |
| REQ-ENG-005 | tests 8, 10, 11, 16 (duplicate prevention everywhere) |
| REQ-ENG-006 | tests 16, 17, 18, 15 |
| REQ-ENG-007 | tests 3-19 (failure-path suite), attested by 21-22 |

## Prior Accepted Precedent

- Story 6 deterministic no-network subprocess pattern (ambient
  environment, guard socket, full deterministic run) is the accepted basis
  for tests 4/22 shape; Story 7 repeated it. Story 8 reuses the pattern in
  full.
- Story 3's accepted controller-based behavioral style (Operation-recorded
  keys/effects counters) is the accepted basis for scenario target adapters.
- Story 5/6/7 fakes, seams and offline refusals are the ONLY monitoring
  injection surfaces for vendor isolation scenarios. Vendor-import rule,
  pinned unambiguously: `failure_lab.py` must not import vendor SDKs or
  vendor transport packages (for example `langfuse`, `langsmith` or
  `helicone`) directly, and Story 8 introduces no new vendor dependency;
  the lab MAY import and use the accepted Module 7 Story 5/6/7 adapter
  modules' public deterministic/offline/fake/seam surfaces where required
  to exercise accepted failure-isolation behavior; this authorization does
  NOT extend to private transport coupling, adapter-internals coupling, or
  bypassing any accepted adapter boundary; no accepted Story 5/6/7 source
  changes. `requests` therefore stays confined, unchanged, to the two
  accepted adapter modules, and the Story 6 adapter's documented wire-note
  remains accurate after Story 8.
- Noted deliberately, no Story 1–7 file requires amendment: the
  `test_package_contract.py` confinement remains satisfied because the lab
  module imports no vendor SDK or vendor transport package at all.

## Quality Gates

Fail-fast, unchanged:

1. `ruff check .`
2. `pytest -q` (all 607 accepted Stories-suite tests + new Story 8 tests
   must pass, with the three accepted opt-in skips visible)
3. `python -m compileall -q src tests`

A later passing gate never overrides an earlier failure. Bounded repair: fix
and rerun the failed gate, then the whole fail-fast sequence. Never weaken
tests, security, redaction, provenance, budget or acceptance controls to
turn any gate green.

## Isolation

Only Module 7 belongs to this slice. No
sibling implementation, tests, runtime state or story documents are touched.
Concurrent dirty work elsewhere in the repository is preserved. Frozen Module
7 authorities — `docs/REQUIREMENTS.md`, `docs/TRACEABILITY.md`,
`docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN.md`, all `docs/adr/*`,
the accepted Stories 1–7 contract files, and the accepted Story 1–7
application/test surfaces — remain untouched by Story 8 implementation.
Contract-file isolation: Story 8 authoring changes exactly one new doc
under `docs/stories/` and nothing else.

## Non-Goals

- No new reliability strategy, classification or controller; no Story 3
  semantics change.
- No live vendor call, credential protocol, or live evidence requirement
  (there is none assigned to Story 8).
- No Streamlit/console/log UI surface (Story 9).
- No continuous-improvement proposal execution; baselines, proposals and
  release files untied (Story 6/10).
- No prohibited dependency, no prohibited version discussion (Story
  10's dependency gate covers the final audit; Story 8 adds no dependency).
- No re-close of Stories 1–7 acceptance behaviors, except only adversarial
  re-combinations already within their own contracts; the lab does not
  invent new attack surfaces outside the frozen scope.

## Definition of Done

- Contract acceptance: independent review + human acceptance of this
  contract; implementation begins only afterward.
- Implementation closure: additive `failure_lab.py` + `test_failure_lab.py`
  only; quality gates green; staged-only (commit at the human-ordered
  story close, mirroring the accepted Story 7 process).
- Deterministic simulation acceptance: all 22 tests written, numbered and
  pass in ordinary CI; full matrix executes deterministically with visible
  pass counts and zero invariant failures; cross-suite regression passes.
- Live evidence: none required for Story 8; none claimed. If a live run is
  ever desired for lab scenarios, that would be an explicit Story 10 live-
  evidence addition, not a Story 8 obligation.
- Story 9 UI presentation: separate story; the lab only provides the
  deterministic summary shape here; Story 9 owns rendering and controls.
- Story 10 integrated/release closure: full requirement/ADR/test/evidence
  reconciliation, adversarial suite and release evidence remain Story 10.

## Open Human Decisions

- Implementation-blocking HITL: none. The frozen plan, ADRs and accepted
  Stories 1–7 completely determine the lab's authority, boundary, taxonomy
  and evidence responsibilities. This contract can be reviewed and accepted
  without further human input first.
- Future live-run authorization: unchanged — no live call is required or
  allowed by this story; any later live lane remains a Story 10 decision.
- Runtime configuration: none beyond accepted settings; the lab defines no
  new environment reading.
- Story 9/10 decisions: presentation of this lab's summary (Story 9) and
  release reconciliation (Story 10), and any later live evidence ambition.
