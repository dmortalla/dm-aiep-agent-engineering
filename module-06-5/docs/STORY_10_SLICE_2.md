# Story 10 Slice 2: usage, fixture exposure, warnings and advisory anomalies

Implemented for independent adversarial review. Story 10 remains IN PROGRESS.
No staging, commit, live spending, real tariff policy, external integration or
dashboard is included. This report does not close Story 10 or Module 6.5.

**Review history:** the initial independent Codex B review returned REJECT with
two blockers, zero non-blockers and zero informational observations. Its focused
gate failed (324 passed, one timing-sensitive late-receipt failure). An isolated
diagnostic pass did not override that failure. The repaired candidate requires
fresh complete gates and Codex B re-review; independent acceptance is not claimed.

## Authority, baseline and isolation

Human-approved authority policy: `b0285bd8b7c913824dfe74b1b016976d76deb3bf`.
Accepted Slice 1 and initial HEAD: `b310fb91baba22751f075ebf8b8c7ed5a670976b`.
Accepted baseline: **1,434 passing tests**. The human reports Slice 1 independent
review accepted with zero blockers/non-blockers and two informational observations.

Before mutation, accepted Slice 1 ancestry passed (exit 0), there were no
intervening commits, Module 6.5 was clean including untracked files, and the
entire index was empty. Foreign root and Module 7 work was protected throughout.
Read AGENTS/CLAUDE, engineering SOP, authoritative source, requirements,
traceability, architecture, implementation plan, ADR 001, authority policy and
accepted Slice 1 report/source/tests. Inspected provider/vendor, configuration,
checkpoint/recovery and approval-journal patterns and accepted provider tests.

Architecture remains frozen. A dedicated application-owned SQLite ledger follows
the existing separate approval-journal pattern; no checkpoint, effect, approval
or recovery schema is changed. No dependency is added or changed. No new ADR or
human pricing decision is needed for the fixture-only implementation.

Files relative to `module-06-5`:

- Added `src/harness_engineering/usage.py`.
- Added `src/harness_engineering/cost_governance.py`.
- Added `src/harness_engineering/anomaly_signals.py`.
- Added `src/harness_engineering/governance_facts.py`.
- Modified `src/harness_engineering/providers.py`.
- Modified `src/harness_engineering/vendor_providers.py`.
- Modified `src/harness_engineering/observability.py`.
- Added `tests/test_cost_governance.py`.
- Added `tests/test_usage_governance.py`.
- Added `tests/test_anomaly_signals.py`.
- Added `docs/STORY_10_SLICE_2.md` (this report).

## Requirements advanced, not closed

| Requirement | Slice 2 evidence / remaining scope |
|---|---|
| REQ-COST-001 | Durable per-step cumulative input/output allocations, exact workflow/action binding, bounded provider attempts and validated numeric usage. Allocations and reported token counts are explicitly distinct. |
| REQ-COST-003 | Workflow/step/attempt attribution, fixture estimates, committed/outstanding exposure and source warning snapshots. Reviewer-visible dashboard/presentation remains deferred. |
| REQ-COST-004 | Deterministic 80%/100% utilization warnings include outstanding reservations, survive reopen and deduplicate crossings. |
| REQ-OBS-001/003 | Closed numeric governance projections and bounded deterministic retry, denial, provider-failure and budget-spike rules. No ML anomaly claim. |
| ENG-002/003 | Provider reports remain data; fixture tariff, identity, limits, evidence and monetary admission remain application-owned. |
| ENG-004/005 | Integer hard exposure, bounded journal/attempts/receipts/rules, concurrency serialization, no paid or hosted deterministic execution. |
| ENG-006/007 | Separate evidence/accounting concepts, adversarial failures/races/recovery tests and accepted regression coverage. |

The frozen architecture's hard exposure enforcement is demonstrated with
fixture policy only. Neither REQ-COST-003's dashboard nor Story 10 completion is
claimed. Slice 1 latency/SLO meanings and critical observer semantics remain.

## Usage contracts and provider boundary

`UsageFacts` is a strict frozen numeric contract: finite `UsageState` plus bounded
integer input/output counts only when REPORTED. Negative, bool, float, nonfinite,
oversized, partial or authority/metadata-shaped facts fail validation. Missing,
malformed, unavailable, timeout, cancellation, late and local states carry no
invented counts. `UsageReceipt` wraps facts with trusted workflow/thread,
application attempt UUID, numeric step ordinal, fixed provider alias and actual
local input UTF-8 byte count. It contains no prompt/output or pricing authority.

`UsageCapture` is a one-shot worker-to-caller channel. Duplicate open-channel
reports fail. Caller finalization freezes the receipt; later reports only flag
the attempt as late. Late observations cannot rewrite receipts, settle again,
refund allocations or reduce outstanding exposure. At most eight receipts and
eight channels are retained per provider runtime.

The installed OpenAI/Anthropic SDK usage field profiles were inspected locally.
Both adapters now normalize bounded primary counts after the accepted complete
SDK-payload structural check and before text/profile/filter acceptance. Supported
SDK detail fields are not exported or interpreted as prices; unknown usage
fields fail closed. All existing response size/type/output rules still apply.
Valid primary usage is captured even when subsequent response validation or
application filtering rejects the content. Malformed SDK payloads become an
explicit malformed observation, without retaining diagnostics.

Primary token counts do not establish cache, reasoning, regional, service-tier
or other invoice charges. Fixture estimates cover only the declared primary
input/output calculation. No full vendor-price calculation is claimed.

The deterministic fake reports LOCAL, not fabricated provider token counts.
Its existing UTF-8-byte bounds remain local conservative resource accounting.
Provider token counts cannot select an SDK method, endpoint, model, tool,
permission, approval, route, retry or evidence class. `ModelResult` still carries
only validated untrusted text; adding `usage` to model output is rejected.
Receipt ordinals preserve the accepted runtime's up-to-100 structural action
bindings; the optional fixture ledger independently enforces its normal frozen
12-step profile. No accepted wider fake-runtime path is narrowed by attribution.

## Four distinct accounting concepts

1. **Local accounting:** input UTF-8 bytes and conservative allocated capacities.
2. **Provider-reported usage:** bounded external numeric claims in `UsageFacts`.
3. **Application estimate/exposure:** integer fixture micro-USD estimates and
   conservative full reserved/committed exposure, recorded separately.
4. **Verified invoice/billing:** absent. `verified_billing_units` is always None.

Validation is structural and does not authenticate a provider claim or prove a
vendor invoice. Receipt possession cannot grant spending authority.

## Token authority

`TokenPolicy` fixes per-call input/output maxima, cumulative per-step allocation
caps, per-step attempt caps and workflow attempt cap. Values cannot exceed
frozen provider bounds (12,000 input, 2,000 output, three attempts per action,
eight per workflow, twelve normal workflow steps). Exact application action
order is bound in durable policy so recovery cannot reinterpret step ordinals.

Before an integrated provider dispatch, `FixtureLedger.reserve` allocates the
full per-call input/output capacities to that step. Provider usage never refunds
these allocations. Repeated calls and rebuilt runtimes share durable history;
exhausted step allocations or attempt capacity deny before adapter invocation.
Different steps have independent cumulative caps. Existing per-call byte/token,
retry, tool/MCP, deadline, off-switch and HITL controls remain authoritative.

A receipt does not increase a limit. Unknown/malformed counts are not zero.
This deliberately conservative policy may deny another call despite a low
reported token count; this slice supplies no provider-driven re-credit policy.

## Monetary authority and settlement

`FixtureTariff` is immutable, explicitly `fixture_only`, bound to finite provider
aliases and `fixture-model`. Rates are bounded integer micro-USD per million
tokens. Integer ceiling arithmetic calculates the conservative reservation from
maximum per-call capacities. One monetary unit is one micro-USD (10^-6 USD).
No authoritative accumulation uses binary float.

Admission atomically checks:

`committed + outstanding + proposed reservation <= trusted hard cap`.

Equality is allowed; exceeding by the smallest unit is denied. Each admission
generates one attempt UUID and durably reserves exposure before dispatch.
Outstanding reservations always count. No fallback tariff or unknown
provider/model mapping exists. Runtime/ledger identity, action order, provider,
model and per-call limits must agree; ledger attempt caps may only tighten the
runtime caps. If the legacy optional `RuntimeBudget.max_cost_usd` is supplied,
its decimal string is converted once to a micro-USD cap with downward rounding;
the fixture cap may not expand it. The legacy float is not an accumulator.

Finalization is exactly once per reservation. A valid report computes a separate
fixture estimate but commits the **full reserved bound**, never the low reported
amount. LOCAL completion also commits the full fixture bound without inventing
tokens/estimated billing. A timeout, cancellation, missing/malformed/unavailable
receipt keeps the full bound outstanding and finalizes its observation once.
An interrupted process can leave an unfinalized outstanding reservation. None
of these paths releases monetary or token authority. Duplicate/unbound settlement
is rejected, including racing calls from different reopened handles.

Settlement-storage failure withholds the caller result and leaves conservative
reservation state. Telemetry failure never releases anything. This is application
exposure accounting, not exactly-once provider execution or billing reconciliation.

## Real monetary admission remains denied

`require_real_monetary_admission` independently rejects missing live enablement,
missing approved policy, fixtures, self-asserted approval objects, unsupported,
stale or ambiguous pricing. There is intentionally **no supported approved live
tariff implementation or live-enablement wiring** in this slice. Even supplying
both an arbitrary policy object and True cannot authorize spending.

The existing SDK authentication/legacy opt-in checks remain, and a new mandatory
real-monetary gate sits immediately before non-mocked SDK request dispatch.
Offline exact MockTransport paths bypass no actual monetary authority because
they cannot issue real requests. Tests supply only isolated dummy configuration
and prove the gate blocks request creation even with legacy live opt-in and
dummy authentication. SDK authentication is not spending authorization.

No actual live provider spending occurred. No prices were fetched, credentials
read from the user's environment, API keys validated, or live service called.
Any future approved live policy support requires separate human authorization.

## Dedicated persistence and recovery

The ledger uses its own database with application ID `0x48363543`, schema version
1, one immutable canonical policy header, a transactionally updated sequence
watermark and a journal of at most sixteen reservation/finalization rows for
eight attempts. Existing Stories 1-9 databases are neither adopted nor migrated.

Creation requires explicit `create=True` and exclusive file creation; it cannot
overwrite an existing file. Reopen uses SQLite `mode=rw` and cannot create a
missing file. Missing, foreign, unsupported, altered, truncated, malformed,
noncanonical or inconsistent state denies admission. Every operation validates
the whole bounded journal against fresh trusted policy. Canonical round trips
reject duplicate JSON keys/coercion; sequence and watermark checks detect
partial-history deletion. SQLite reads bound projected payload lengths.

`BEGIN IMMEDIATE` serializes reads/admission/writes across independent connections.
Reservation, sequence watermark and journal updates commit together. Failures
roll back; database errors produce fixed safe application errors. Reopening
preserves committed exposure, outstanding reservations, finalization identities,
token allocations, cap/tariff binding and warnings. Changing action order or cap
on resume fails reconciliation. Existing checkpoint contents supply no monetary
authority and cannot reconstruct an empty ledger.

This is local trusted-filesystem structural recovery evidence, not authenticated
tamper resistance or protection against wholesale rollback/replacement of a valid
database together with its metadata. Trusted bootstrap must not deliberately
create a new empty ledger to resume an old workflow. Live monetary resume remains
disabled; provider deadlines/effect recovery are not newly reconstructed here.

## Warnings and anomaly source state

Warnings use integer comparisons at 80% and 100% of hard-cap utilization, including
outstanding reservations. Source warning state is derived from durable monotonic
exposure and survives reopen. Each crossing is projected once; finalization does
not re-emit it. No re-arm/refund path exists because exposure never decreases.
Lost projection does not erase the source warning; snapshots retain it.

`AnomalyDetector` implements four advisory rules:

| Rule | Trigger in a rolling 60-second window |
|---|---|
| Retry burst | Two explicit repeated provider invocations. |
| Denial burst | Three provider authority denials. |
| Provider failure burst | Three charged provider invocations that do not return accepted success. |
| Budget spike | One admitted reservation >=25% of the hard cap. |

Provider observations come from trusted runtime boundaries, never error text.
Budget-spike observations come from committed ledger reservations. There are four
finite rule keys, at most 64 timestamps per rule and 64 retained signals. A rule
latches at threshold and re-arms only after its rolling count drops below
threshold. Clocks must be finite/monotonic; counters, dimensions and classifications
are application-owned. Invalid observations create no false signal.

Source observation and telemetry projection are separate. Budget source state is
observed even when cost telemetry fails. Signal state is retained before optional
signal projection. Advisory failures expose fixed counters, not raw diagnostics.
Signals cannot call tools, retry providers, change permissions/HITL, route work,
alter caps or change monetary authority. Compression and unusual tool-frequency
rules are deferred rather than speculatively instrumented. No ML detection is claimed.

Fixture source binding now validates anomaly provenance before initialization or
provider execution. The same shared validator covers direct cost telemetry and
anomaly telemetry: only the existing deterministic/mocked/adapter/local-integration
classes are permitted, with exact workflow/thread and evidence agreement.
`AnomalyDetector.bind_fixture` receives the trusted accounting identity, rejects
foreign ownership or unattributed prior observations, and cannot reassign a
detector to another workflow. Signals retain that accounting identity. No
incompatible classification is silently promoted/demoted. Provider accounting
uses the same binding; callers must supply its actual accounting identity when
an existing detector/telemetry session is already workflow-bound.

## Safe telemetry relationship

Slice 1 receives only a closed `GovernanceFacts` record: finite kind, optional
bounded exposure/cap numbers or bounded rule count. Contradictory warning/count
claims are rejected. Governance events create no latency samples/cohorts and
preserve the <=4 KiB event and 512-record ring bounds. Workflow/evidence binding
remains application-owned; fixture projections cannot use live/deployment evidence.

No prompts, outputs, credentials, headers, arbitrary metadata, tariffs or raw
exceptions enter governance telemetry. Cost transactions commit before optional
projections, and projection failures are counted outside authoritative state.
The ledger never reads telemetry for admission, recovery, finalization or warnings.
No exporter queue, LangSmith, Langfuse, Helicone or hosted SDK is introduced.

## Pre-repair verification (historical, not current acceptance)

Initial Ruff findings were safe import/unused-import fixes and line wrapping;
no unsafe fixes were used. The first focused run had four new nonfinite-data
fixture failures: HTTP response construction rejected NaN/infinity before the
adapter saw them. Corrected these fixtures to send raw malformed JSON bytes,
matching accepted Story 9 practice. No accepted test or security rule was weakened.
The repaired focused run passed 317 tests. Final gate results follow below.

Source review also separated anomaly source observation from telemetry failure,
bound cumulative legacy cost caps conservatively, reconciled usage/telemetry
identity and added contradictory-governance-claim tests before final gates.

Pre-repair focused gate: Ruff PASS; **325 passed in 27.64 seconds**, no warnings,
across the three new Slice 2 test files plus unchanged provider/vendor and
Slice 1 observability/latency tests (92 new cases + 233 accepted focused cases).

Pre-repair full-module fail-fast gates on 2026-10-18, from `module-06-5`:

1. `.venv/Scripts/ruff.exe check .` - PASS.
2. Focused pytest over the three new Slice 2 test files, `test_providers.py`,
   `test_vendor_providers.py`, `test_observability.py` and `test_latency.py`,
   with `-q --tb=short` and parent EVIDENCE basetemp - **325 passed in 27.64 seconds**.
3. `.venv/Scripts/python.exe -B -m pytest -q --tb=short --basetemp
   E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-10-slice-02-full-20261018`
   - **1,526 passed, 6 warnings in 405.38 seconds** (1,434 accepted + 92 new).
4. `.venv/Scripts/python.exe -m compileall -q src tests` - PASS, exit 0.

The six warnings are the accepted Guardrails dependency's Typer/Click
deprecations: `get_binary_stream`, `get_text_stream`, and four warnings about
`is_flag`/`flag_value`. No accepted tests, warnings filters or dependency versions
were changed to hide them. No new focused warnings were reported.

Tests used host Windows event loops/runtime, with dummy-only isolated vendor
configuration and offline transports. Source/tests were fixed before the final
full gate; only this report was completed afterward. No provider/service call
or monetary operation against a real provider was performed.

Temporary pytest artifacts are under parent `TECHADEMY/EVIDENCE`, never committed.
Normal new tests forbid sockets and use dummy-only isolated SDK configuration.

## Bounded repair after independent REJECT

The independent review found two blockers. No other behavior was reopened.

1. **Anomaly provenance bypass:** the direct telemetry constructor checked
   workflow/evidence, but the anomaly constructor binding checked only type.
   This allowed a fixture accounting source to emit stronger evidence or project
   into a different workflow. Extracted the existing permitted-evidence and exact
   identity semantics into `validate_fixture_projection`, applied it to direct
   ledger telemetry and detector binding, and bound signal identity to trusted
   accounting ownership. The adjacent provider anomaly construction path had the
   same bypass and now performs the same validation. Incompatible bindings fail
   explicitly before reservation or invocation; no evidence coercion occurs.
2. **Late-receipt test startup race:** a 0.2-second deadline sometimes expired
   before the genuine Anthropic mock handler started, invalidating the intended
   scenario and its cleanup assumptions. The repaired test uses a separate caller
   future, handler-entry and caller-wait Events, a controlled result-queue `get`
   that raises `Empty` only on the test's explicit timeout signal, and a late
   response-release Event. It keeps the normal production deadline and does not
   modify production timeout code. The genuine SDK/mock worker must enter first;
   the actual caller timeout branch then freezes its receipt; only after the
   caller returns is the mock response/usage released. Assertions verify late
   usage, exact unchanged ledger snapshot/receipt, one attempt/request and worker
   slot/transport completion. All coordination/cleanup waits are bounded at ten
   seconds. This is synchronized timeout failure injection, not elapsed-time
   performance evidence.

Exactly six files changed relative to the independently rejected candidate:

- `src/harness_engineering/anomaly_signals.py`.
- `src/harness_engineering/cost_governance.py` (constructor validation only).
- `src/harness_engineering/providers.py` (adjacent anomaly binding only).
- `tests/test_anomaly_signals.py`.
- `tests/test_usage_governance.py`.
- `docs/STORY_10_SLICE_2.md`.

Fifteen new adversarial cases exercise LIVE_PROVIDER/DEPLOYMENT rejection with
and without telemetry, foreign workflow/thread rejection with unchanged monetary
state, valid same-workflow evidence without promotion/demotion, detector reuse
and unattributed-history rejection, and adjacent provider rejection without
invocation or off-switch changes. Existing bounded-window tests remain intact.

Fresh repaired-candidate gate sequence:

1. Ruff - PASS (only safe import fixes and line wrapping were needed).
2. Focused Slice 2 + accepted provider/Slice 1 tests - **340 passed in 30.28 seconds**.
3. Five separate bounded pytest rounds of the late-receipt scenario across both
   adapters - **10/10 passed**; per-round durations 5.78, 6.19, 6.09, 5.97 and
   5.44 seconds. No retries, skips, flaky markers, sleeps or network calls.
4. Fresh full module pytest - **1,541 passed, 6 warnings in 442.05 seconds**
   (1,434 accepted Slice 1 + 92 original Slice 2 + 15 repair regression cases).
   Command: `.venv/Scripts/python.exe -B -m pytest -q --tb=short --basetemp
   E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/module-06-5-story-10-slice-02-repair-full-20261018`.
5. `.venv/Scripts/python.exe -m compileall -q src tests` - PASS, exit 0.

The six full-suite warnings remain the accepted Typer/Click deprecations noted
above; the repaired focused gate and stability rounds reported no warnings.
Source/tests remained fixed throughout these fresh gates; only this report was
finalized afterward. Story 9 and Slice 1 regression cases remain green. No live
provider, hosted service, real tariff or spending execution occurred.

Fresh artifacts use parent EVIDENCE directories named
`module-06-5-story-10-slice-02-repair-focused-20261018`,
`module-06-5-story-10-slice-02-repair-stability-{1..5}-20261018`, and
`module-06-5-story-10-slice-02-repair-full-20261018`.
No financial journal schema, reservation/settlement method, token allocation,
cap arithmetic, warning, retry, permission, HITL or execution control is changed.
Independent acceptance remains Codex B's decision after re-review.

## Evidence and non-claims

Evidence is deterministic fixture accounting, injected failures/races, genuine
local SQLite integration and installed OpenAI/Anthropic SDK parsing/serialization
over mocked in-memory HTTP. Counters and token claims are not vendor billing.

- No live provider spending occurred.
- No real/current provider pricing is claimed; deterministic tariffs are fixtures only.
- Application hard exposure limits are not guaranteed vendor invoice limits.
- No verified billing or invoice reconciliation exists.
- No hosted observability or live Helicone integration is proven.
- No Story 10 dashboard is complete.
- No deployment, production-grade completion or Story 10 closeout is claimed.

Requirements advanced for Slice 2 only -> reviewer product experience is the
callable API and snapshots, with presentation deferred -> real functionality is
local durable fixture governance and actual offline SDK normalization -> reliability
and security are bounded/tested as recorded -> external cost is zero -> evidence
classes stay distinct -> deployment remains unestablished.

Final repaired-candidate isolation/status: accepted Slice 1 remains an ancestor
(exit 0). Current HEAD is `51b0a14881c433c1a61ba6d475330d8fd6397dde`.
Intervening commits are `0996158` (Module 9 image evidence), `554a75f` (Module 9
release evidence), `518aa2d` (roadmap status) and `51b0a14` (module summaries).
None modifies Module 6.5; the module-filtered intervening log is empty.
The entire index is empty; tracked-content `git diff --check -- module-06-5` passes.
Exactly the eleven owned files listed above are modified/untracked. No accepted
test or foreign concurrent file was modified by this slice.

**The repaired candidate is ready for independent Codex B re-review.** Fresh gates
pass, but independent acceptance remains pending and the initial REJECT is
preserved above. All changes remain unstaged and uncommitted. Slice 3 integrations
and Slice 4 lab/closeout have not begun. Story 10 remains incomplete.

Final `git status --short`, including protected pre-existing foreign work:

```text
 M module-06-5/src/harness_engineering/observability.py
 M module-06-5/src/harness_engineering/providers.py
 M module-06-5/src/harness_engineering/vendor_providers.py
 M module-07/pyproject.toml
 M module-07/tests/test_package_contract.py
 M module-07/uv.lock
 M module-10/src/module10_ai/azure_verification.py
 M module-10/tests/test_azure.py
?? .editorconfig
?? .gitattributes
?? module-06-5/docs/STORY_10_SLICE_2.md
?? module-06-5/src/harness_engineering/anomaly_signals.py
?? module-06-5/src/harness_engineering/cost_governance.py
?? module-06-5/src/harness_engineering/governance_facts.py
?? module-06-5/src/harness_engineering/usage.py
?? module-06-5/tests/test_anomaly_signals.py
?? module-06-5/tests/test_cost_governance.py
?? module-06-5/tests/test_usage_governance.py
?? module-07/docs/STORY-05-IMPLEMENTATION.md
?? module-07/docs/stories/STORY-05-langfuse-integration-boundary.md
?? module-07/src/reliability_safety_observability/langfuse_adapter.py
?? module-07/src/reliability_safety_observability/langfuse_config.py
?? module-07/tests/test_langfuse_adapter.py
?? module-07/tests/test_langfuse_live.py
?? scripts/
```
