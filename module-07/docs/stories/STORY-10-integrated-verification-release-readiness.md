# Story 10 — Integrated Verification, Live Evidence, and Release Closure

## Status, scope, and authority

DRAFT — CONTRACT REVISION 6. This human-authorized Option 1 architecture
reconciliation strengthens Revision 5; implementation repair and independent
architecture/implementation acceptance remain pending. This step changes only
the necessary architecture documents, requirements, traceability, plan and ADR;
source, tests, configuration, lockfile and accepted Story 1–9 contracts remain
unchanged. Story 10
is the frozen-plan integrated closure, not a new control plane, workflow
service, provider integration, or presentation architecture. Binding ADRs are
ADR-007-001 through ADR-007-013. Story 9 contract SHA-256:
`555522E2C68EB36411E5A0C36AB9AAA9A133076A1643122D2EA9F383572615CD`.

Assigned requirements are exactly REQ-OBJ-001; REQ-CLOSE-001..005;
REQ-DOD-001..010; REQ-QG-001..006; and REQ-EVD-001..007. A status cell never closes a prior
requirement: Story 10 must bind accepted Story 1–9 implementation, test, and
evidence references.

## Revision 6 immutable evidence authority

[ADR-007-013](../adr/ADR-007-013-immutable-evidence-records.md) and the
[architecture amendment](../ARCHITECTURE.md#human-approved-option-1-amendment--immutable-evidence)
are binding, including producer seams, persistence/atomicity/concurrency,
retention, path safety, integrity, classification and gate lifecycle rules.
Revision 6 retains every following Revision 5 obligation and the exact 20-test
inventory. Additional adversarial cases belong within those conceptual tests.

Only authorized producer execution seams may record eligible evidence; raw
constructible models and caller mappings/labels are insufficient. Existing
engine/loader, failure-lab, policy/security/telemetry and session authorities
retain semantic ownership. Typed adapters preserve actual validated output and
its provenance, minimizing/redacting before immutable persistence and artifact
construction. Story 10 has no new workflow/session/provider authority.

Each immutable envelope MUST bind producer/schema, source identity and payload,
provenance, derived class and applicable exact candidate/contract digests. Its
content/integrity-bound trusted reference cannot be rebound. Retrieval grants
no authorization. Read-only reload MUST independently verify origin, integrity,
schema and freshness, then rederive source/provenance, class, projection, exact
RFC 8785 JCS UTF-8 bytes and SHA-256. Unknown, malformed, corrupt, stale,
producer/candidate/contract mismatches and classification promotion fail closed.
Changed evidence creates a new reference; identical recording is idempotent.

All eight artifacts MUST retain verifiable references/bindings/freshness and
derive from reloaded authoritative evidence. Traceability reads the frozen source
relationships independently; lab links need actual lab/deliverable support;
budget verification consumes stable accepted policy outcomes separately from
raw numeric telemetry. Missing evidence stays open/unsatisfied, never verified
by a constant label. The ledger reconciles S5 Langfuse, S6 LangSmith and S7
Helicone wrapper lanes; absent qualifying live evidence remains open. Capability
to record live data does not establish live evidence or authorize execution.

The final gate recorder derives candidate identity from actual candidate files
and approved contract, observes actual Ruff -> pytest -> compileall execution,
and records results/order/timestamps/output integrity and repair history only
after completion, outside candidate content. Read-only reload independently
checks current bindings and freshness. Failure stops the attempt; retain it,
apply bounded repair, rerun the failed gate and the full formal sequence on the
newly frozen candidate. Unresolved failures forbid success. Candidate/contract
mutation invalidates readiness. Tests 17–18 use synthetic execution evidence;
they cannot mint their own final pytest success.

Reviewer storage MUST be configurable, ignored, runtime-local and excluded from
candidate identity, with no machine path or TECHADEMY/EVIDENCE dependency.
Production adapters enforce the same durable immutable/read-only contract;
deployment/live evidence is absent until actually authorized and exercised.
LLM/tool/retrieval/provider content cannot grant itself evidence authority;
credentials grant connectivity only. Prompt injection cannot change class or
provenance. Secrets are excluded/minimized before persistence, references,
projections and artifacts, using accepted redaction facilities.

### Prior independent findings

All six findings are **ARCHITECTURALLY ADDRESSED — IMPLEMENTATION REPAIR PENDING**:

| Finding | Required architecture and test repair |
| --- | --- |
| Forged run/live provenance | Producer seams, trusted reload and anti-promotion; Tests 1, 11, 20 |
| Placeholder artifacts | All eight artifacts derive from reloadable evidence; Tests 2–16, 20 |
| Fabricated traceability/lab/budget | Independent frozen-source reconciliation and actual policy outcomes; Tests 2, 3, 10 |
| Fabricated gate success | Actual executor provenance and post-sequence recording; Tests 17–18 |
| Optional redaction | Mandatory pre-persistence/construction minimization; Tests 1, 14 |
| Shallow tests | Exactly 20 integrated behavioral/adversarial tests, including fixed independent RFC vector and DNS/socket guarded integrated execution; Tests 1–20 |

## Frozen evidence taxonomy

The complete captured-result taxonomy is exactly:

1. `deterministic_fixture`
2. `simulated_failure`
3. `mocked_provider_contract`
4. `live_vendor`
5. `live_model`

No other value is a captured-result class. `production_observed` is neither a
substitute for `live_model` nor a sixth class; if a frozen authority uses it,
it is only a separate provenance/observation claim concept. Validation rejects
unknown or relabelled classes and deterministic/mock evidence presented as live.

## Authoritative three-lab and tool linkage

There are exactly three labs: (1) implement observability dashboards (Stories
5/7 and Story 9 observability surface; observability platform), (2) build
automated evaluation pipelines (Story 6 and Story 9 evaluation surface;
evaluation pipeline), and (3) simulate failure recovery workflows (Story 8 and
Story 9 failure-lab surface; one or both deliverables only where actual
reconciliation supports it).

REQ-CLOSE-003 requires every lab to contribute to **at least one** deliverable
and permits both deliverables when each asserted link has accepted
implementation, test, and evidence support. Unsupported or fabricated links
fail, including an asserted link to either or both deliverables when that
specific link lacks accepted evidence. REQ-CLOSE-004 permits each tool to
contribute to actual requirements, labs, and/or deliverables, including
multiple legitimate links; only missing required, stale, contradictory, or
fabricated links fail validation.

## Requirement -> ADR -> story -> test -> evidence

The authoritative row is:

`requirement_id -> adr_ids[] -> story_ids[] -> implementation_reference[] ->
test_reference[] -> evidence_reference[] -> captured_result_class -> status`.

`adr_ids` retains every applicable ADR as an ascending duplicate-free list.
Where frozen authority establishes none it is explicit `[]`, not an invented
ADR. Other lists have deterministic identifier order. Evidence references carry
artifact, class, candidate binding, and freshness. Status is `open`,
`qualified_historical`, `verified`, or `rejected`; only matching accepted
evidence may verify a row.

Validation rejects unknown, missing, duplicate, stale, contradictory, or
unsorted rows; omitted applicable ADRs; invented ADRs; unsupported classes;
unrouted requirements; and closed/live rows without matching evidence.

## Actual evidence and canonical deterministic projection

Actual evidence retains workflow, trace, idempotency, and span IDs; the actual
result/evidence source; timing and elapsed data; bounded cost/usage; and
classification. It is never normalized or falsified. For every recorded run,
the Integrated Deterministic Acceptance Record binds candidate identity,
contract identity, genuine run provenance, the immutable recorded result
reference/digest, stored canonical projection, canonical serialized bytes, and
SHA-256 of those exact bytes.

The deterministic projection contains only semantic fields: terminal,
authorization, and safety results; retry/fallback/replay facts; reason codes;
dataset/version/evaluator/verdict/regression fields; lab IDs/dispositions; and
redacted telemetry classifications. Projected version integers are exactly
`RunIdentity.dataset_version`, `evaluator_suite_version`,
`threshold_policy_version`, and `target_version`; applicable
`BaselineRecord.baseline_schema_version`, `dataset_version`,
`evaluator_suite_version`, `threshold_policy_version`, and `target_version`;
the values in `BaselineRecord.evaluator_versions`; and
`ScenarioEvaluation.evaluator_version` only when a scenario-evaluation row is
otherwise included. It excludes run ordinal/IDs, timestamps, elapsed values,
opaque tokens, raw provider telemetry, and raw numeric cost/usage.

The accepted deterministic structures do not establish that raw numeric
cost/usage is a cross-run semantic invariant, so this contract deliberately
uses Option B: projection-digest equality does **not** claim equivalence of
cost, usage, or budget semantics. Candidate-bound separate verification records
the stable policy outcomes exposed by the accepted run (including terminal and
recovery classification, retry/fallback/replay outcome, and any budget/cost
limit refusal) and rejects a meaningful mismatch. Test 10 owns that path; no
deterministic numeric cost/token value is invented or normalized away.

The canonical projection domain is deliberately narrow: recursively nested JSON
objects and arrays plus strings, booleans, and null. Every accepted semantic
version integer is represented in the projection by exactly one reserved tagged
object, `{"$integer":"<canonical-decimal>"}`, rather than a JCS number. This
losslessly adapts the authoritative source `int`; it does not change that source
type or admit arbitrary numerics. The tag is valid only at a projection-schema
field declared semantic-integer; an ordinary object containing `$integer` is
never inferred to be one, and a semantic integer cannot collide with an
ordinary projected string such as `"1"`.

Story 10 consumes accepted evidence, not raw constructible models: evaluation
versions come from the `RunIdentity` constructed by `EvaluationEngine.run`,
whose `dataset_version`, `evaluator_suite_version`, `threshold_policy_version`,
and `target_version` are validated `int` values with `ge=1` and no maximum.
Applicable baseline values come only from `load_committed_baseline`, which
validates schema/digest/dataset/target facts and requires every
`evaluator_versions` value to equal the committed evaluator-suite version;
raw `BaselineRecord` construction is not evidence. A projected
`ScenarioEvaluation.evaluator_version` comes from an accepted engine row and
is an `int` with `ge=1`; raw evaluator objects are not the evidence boundary.
The committed `ThresholdPolicy` is materialized into that accepted
`RunIdentity`; its raw dataclass annotation alone is not the Story 10 boundary.

The tagged payload is generated only from the accepted source `int`, explicitly
excluding `bool`, and is never accepted from user/display text. Its grammar is
ASCII decimal: zero is `"0"`; positive values are `[1-9][0-9]*`; a negative
value, only if an authoritative accepted-evidence boundary actually permits
one, is `-` plus that positive magnitude. `-0`, plus signs, leading zeros,
decimal points, exponents, whitespace, Unicode digits, and base prefixes are
invalid. Current projected accepted-evidence version fields are `ge=1`, so
negative tagged forms are rejected at those boundaries rather than invented as
new source semantics. Float, Decimal, Fraction, custom numeric, numeric-string,
bool-as-int, NaN, infinities, binary, date/time, set, UUID, enum/object
instance, and every other unsupported value are rejected. Raw numeric
cost/usage/timing remains outside projection equality as defined above.

Canonical bytes MUST use RFC 8785, JSON Canonicalization Scheme (JCS), exactly;
the SHA-256 input is exactly the resulting JCS UTF-8 byte sequence. This is a
conforming JCS subset, not a "JCS-like" serializer. At every nesting depth, JCS
sorts object member names by UTF-16 code-unit order. Arrays preserve their
semantic sequence order; a collection intentionally modelling a set is first
normalized into its contract-defined source-identifier order, then serialized
as an array. Incidental language dictionary/set iteration is forbidden.

JCS determines Unicode and escaping: strings retain their input Unicode code
points without added Unicode normalization; malformed Unicode is rejected; and
implementations must use JCS's mandated JSON escaping rather than choosing
literal non-ASCII versus arbitrary `\\u` escapes. JCS also determines control
character, quote, and reverse-solidus escaping. No whitespace is emitted
outside strings. Boolean and null use the JCS literals. The tagged integer is a
JCS object whose value is a JCS string; RFC 8785/JCS does not serialize the
source integer as a JSON number. SHA-256 still receives the complete JCS UTF-8
projection bytes, never the decimal payload alone.

Independent verification loads the recorded genuine result, rederives its
projection by these rules, JCS-canonicalizes it, recomputes SHA-256, and
compares rederived projection, canonical bytes, and digest with their stored
counterparts and with the candidate/contract/run binding. It rejects
run-A/projection-B or run-A/digest-B pairs, cross-candidate or cross-contract
copies, altered results with stale projections, altered projections with stale
digests, post-record candidate edits, and a projection that cannot be
deterministically rederived from its claimed run.

Equal projection digests prove equality **only** of the explicitly projected
deterministic semantic fields, including accepted source integer version values
through their tagged form, for the candidate-bound runs. They do not prove
equality of excluded identity, timestamps, elapsed timing, raw provider
telemetry, cost/usage/budget semantics, live-provider behavior, production
behavior, or raw runs.

## Existing bounded presentation path

No UI authority is added. The existing Story 9 path is:

`ConsoleBoundary.run_workflow()` -> `WorkflowEvidence` ->
`recovery_projection()` / redacted telemetry; `run_benchmark()` ->
`BenchmarkEvidence`; `run_full_lab()` -> `LabSummary` / `lab_projection()`;
then existing Workflow, Evaluation, and Failure-recovery console tabs.

Story 10 exercises and reconciles this bounded path only. It supplies no
provider execution or new presentation state. The console shows actual
provenance and deterministic component views; the candidate-bound filesystem
record makes its run-to-projection derivation, canonical bytes/digest, and
separate cost/budget verification inspectable. This path is credential-free,
network-free, and secret-free.

## Eight release-readiness artifacts

All are generator-owned, generated after inputs complete, redacted/key-free,
candidate- and contract-bound, fresh, and deterministically verified by
recomputing schema/order/input/output digests. Each rejects stale, forged,
contradictory, incomplete, or secret-bearing evidence.

| Artifact | Owner/source of truth | Required contents |
| --- | --- | --- |
| Integrated Deterministic Acceptance Record | Story 10 runner / accepted interfaces | actual provenance/result reference, stored projection/bytes/digest rederivable from that run, candidate/contract binding, class tally, time/order |
| Reconciliation Table | reconciler / frozen requirements, ADRs, Stories 1–9 evidence | complete ordered requirement→ADR→story→test→evidence rows |
| Failure-Path Record | runner / Story 8 `LabSummary` | actual summary, redacted scenario facts, digest |
| Adversarial Security Record | runner / accepted S2/S3 boundaries | checks, outcomes, test references, class |
| Quality-Gate Record | final gate recorder | binding, ordered commands/results, timestamps, repair/rerun history |
| Dependency & Prohibited-Version Record | dependency verifier | declaration, lock/source, prohibited check, Streamlit 1.66.1 |
| Documentation & UI Claim Audit | claim auditor | claim/reference pairs and reviewed-source digest |
| Live-Claim Ledger | ledger generator / accepted S5/S6/S7 records | lane, contract/evidence reference, status; no secret/payload |

## Live-claim ledger

Rows originate only from accepted S5/S6/S7 wrapper contract/execution records,
not user input or deterministic output. A row has claim ID, lane,
contract/candidate binding, status (`open`, `verified`, `qualified_historical`,
or `rejected`), and matching live evidence reference for `verified`. Otherwise
it is `open`. Fixture, simulated, and mocked evidence cannot prove
`live_vendor` or `live_model`. Story 10 makes no live call; live execution is
accepted-wrapper-only, explicit opt-in, and HITL-authorized.

## Gate mechanism and gate-of-record

Tests exercise a **synthetic** gate-record mechanism, never pretend final
acceptance has already occurred. The real final flow is Ruff -> pytest ->
compileall -> create final candidate-bound Quality-Gate Record -> independently
verify that record against the unchanged reviewed candidate.

Every gate entry has branch/worktree when applicable, commit or immutable
candidate digest, contract SHA, ordered gate/command/result, start/end time,
output digest, class, and repair/rerun history. Earlier failure stops later
gates. Authorized bounded repair reruns the failed gate and then the complete
sequence; unsafe fixes and weakened/deleted rules are forbidden. Validation
rejects stale/different-candidate/missing/reordered gates, post-gate candidate
edits, forged/contradictory results, and later passes after an earlier failure
without required repair and full rerun.

The independent historical `656 passed, 3 skipped, 1 failed` Helicone
cross-suite child/Story 8 lab result is retained as `qualified_historical`.
Its failed invariant was not captured: it is neither green evidence, S19
attribution, nor proof of a current defect. Only a fresh candidate-bound
gate-of-record may supersede it explicitly.

## Exact 20-test inventory

All tests are deterministic unless stated otherwise; none mints live evidence.
Tests 17–18 use synthetic records and complete before a final gate exists.

| # | Mechanism and requirement mapping | Class |
| --- | --- | --- |
| 1 | Equivalent runs have equal projections only for projected fields; each stored projection/bytes/digest is rederived from its own recorded run and candidate/contract binding. Reject run/projection or run/digest cross-pairs, stale result/projection/digest, candidate/contract mismatch, and nonrederivable projection. Verify RFC 8785/JCS canonical bytes and SHA-256 for differently inserted nested objects, ordered nested arrays/source-ID collections, non-ASCII text, JSON-escaped control/quote/reverse-solidus characters, booleans/null, and unsupported values. Re-derive accepted version values from source `int` to the reserved tagged form: verify lossless `9007199254740991`, accepted `9007199254740992`, and a representative accepted value above `2^53`; same source integer gives same tag/bytes/digest and a changed value changes all three. Reject source numeric-string, float, bool, unsupported numeric object, malformed decimal forms, and tag/string or arbitrary-object collisions; prove unique decimal grammar and rederivation from recorded integer rather than display text. If a negative version reaches accepted evidence, cover it; otherwise verify rejection at that governing boundary. Use an RFC 8785 known canonical-byte/digest vector so two copies of an incorrect serializer cannot agree. Cost/usage/budget semantics use test 10's separate record. OBJ-001, CLOSE-001/-005, DOD-005/-010 | deterministic_fixture |
| 2 | Requirement→ADR→story→test→evidence completeness; all ADRs and invalid-row rejection. CLOSE-002, DOD-001/-002/-009 | deterministic_fixture |
| 3 | Three-lab/tool linkage permits either or both deliverables when each link is accepted-evidence-supported; unsupported/fabricated links to either or both fail. CLOSE-003/-004, DOD-010 | deterministic_fixture |
| 4 | Existing observability console path shows redacted workflow/provenance. DOD-005/-006 | deterministic_fixture |
| 5 | Existing evaluation path shows benchmark/regression. DOD-005/-006 | deterministic_fixture |
| 6 | Exact Streamlit 1.66.1 support; other version/malformed shape fails closed. DOD-006 | deterministic_fixture |
| 7 | Story 8 lab summary/projection reconciliation. DOD-003, CLOSE-005 | simulated_failure |
| 8 | Injection, forged-authority, denial, safety fail-closed re-anchoring. QG-004 | deterministic_fixture |
| 9 | End-to-end replay/effect-count anchor. CLOSE-005 | deterministic_fixture |
| 10 | Bounded budget/cost semantics. ADR-007-012 | deterministic_fixture |
| 11 | Ledger taxonomy/live honesty; mock-as-live and relabel rejection. DOD-004/-009 | deterministic_fixture |
| 12 | Credential-free/no-ambient-activation path. DOD-004 | deterministic_fixture |
| 13 | Socket-guarded zero-network path. QG-004 | deterministic_fixture |
| 14 | Artifact/display redaction canary containment. DOD-008 | deterministic_fixture |
| 15 | Dependency/prohibited-version/registry verification, including pin. QG-005 | deterministic_fixture |
| 16 | Documentation/UI claim audit and candidate binding. DOD-008 | deterministic_fixture |
| 17 | Synthetic gate schema/order/candidate/freshness/forgery rejection. QG-001..006 | deterministic_fixture |
| 18 | Synthetic repair state: stop, authorized repair, failed-gate rerun, full sequence. QG-001..006 | simulated_failure |
| 19 | Story 9 ownership preservation: real 1.66.1 guard, rerun identity, A/B separation, copied boundary/receipt rejection; distinct from test 6. DOD-006 | deterministic_fixture |
| 20 | Live-lane HITL/no-auto-execution and open-ledger boundary. DOD-004 | mocked_provider_contract |

## Failure, HITL, and Definition of Done

Ordinary CI is zero-credential, zero-external-network, bounded, and preserves
accepted redaction/authority controls. Gaps are `open` or `rejected`, never
relabelled. Reproducible accepted-story defects stop for diagnosis; Story 10
does not silently repair Stories 1–9.

Option 1 supplies the human-approved evidence architecture decision for this
revision; no additional undecided architecture choice is required. Independent
architecture acceptance must precede implementation repair. HITL is required if
implementation needs a new workflow service, frozen-authority change, new
provider/presentation authority, or consequential live execution. Push, merge,
release, deployment, publication, and real provider calls remain outside scope.

Done requires independent contract acceptance, all 20 tests, all eight fresh
candidate-bound redacted artifacts, a passing final ordered gate-of-record,
honest live rows, and reviewer access to both deliverables and exactly three
labs through the existing bounded path.

## Isolation

Revision 6 changes only the authorized coordinated architecture authority set.
No implementation, staging, commit, push, merge, deployment, external evidence
write or provider call occurs during this architecture reconciliation.
