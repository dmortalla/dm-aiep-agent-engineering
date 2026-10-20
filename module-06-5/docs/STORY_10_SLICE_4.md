# Story 10 Slice 4: observability lab and implementation closeout

**Story 10 is implementation-complete, pending independent acceptance.**
Candidate for independent cross-model adversarial review. Story 10 is not
independently accepted by this report. Story 11/12, the final Streamlit reviewer
interface, module release, deployment and public closeout are outside this slice.

## Baseline, chronology and ownership

Accepted Slice 3: `fb2b6073801a2fda528aafbd202e3f443625dc0b`, with independently
verified **1,607 passing tests**. The human records independent Slice 3 acceptance
with zero blockers, two non-blockers and seven informational findings.
At Slice 4 start, this commit was HEAD, ancestry passed, no intervening commits
existed, Module 6.5 was clean including untracked files, and the entire index was
empty. Protected pre-existing foreign work consisted of `.editorconfig`,
`.gitattributes` and `scripts/`, all untracked.

Current chronology includes `61816fb` (Slice 2), `788b2dc` (Module 10-only Azure
ordering fix), `1cf6eb0` (Module 7 integration), then `fb2b607` (accepted Slice 3).
These foreign commits do not alter Slice 3 acceptance. **N1:** the accepted Slice
3 report is historical evidence and is deliberately preserved byte-for-byte;
its old working-tree snapshot is not represented as current repository status.

Read root AGENTS/CLAUDE/SOP/status, authoritative source, approved requirements,
traceability, frozen architecture, implementation plan, ADR 001, approved Story
10 authority policy, accepted slice reports and relevant lifecycle, context,
provider, recovery, telemetry, ledger, anomaly, SDK and lab code/tests.
No architecture/policy/dependency/lockfile amendment is made. Root status editing
is separately authorized only after successful implementation gates and closeout
reconciliation; unrelated root/module work remains protected.

## Runnable lab and presentation

From `module-06-5`, with the accepted Python environment:

```powershell
.venv/Scripts/python.exe -B -m harness_engineering.observability_lab --directory E:/ONEDRIVE-PERSONAL/TECHADEMY/EVIDENCE/story10-review-unique
```

Use a **new** directory; the lab never overwrites or resets an existing one.
The returned report is also available through `run_observability_lab(Path(...))`.
`--format json` selects the same closed facts as structured JSON; default text
renders a readable cost dashboard followed by structured events/receipts/cohorts.
`--samples 20` explicitly executes twenty whole local workflows; default is one.
`--offline-sdk` explicitly demonstrates both accepted offline SDK workers once
for the detailed workflow. It cannot enable hosted export. SDK packages are
optional; their absence is advisory unavailable health, not workflow failure.

No Streamlit/server is introduced. The frozen implementation plan assigns the
observability lab to Story 10 and the final cross-lab Streamlit UI to Story 11.
This CLI dashboard is the smallest intermediate reviewer presentation; it does
not replace or claim completion of that later interface.

Architecture:

```text
Strict finite LabConfig -> fresh local fixture directory
  -> accepted LangGraph LifecycleRuntime
     -> observe_workflow / observe_step / ProviderRuntime(FakeProvider)
        -> accepted FixtureLedger + TelemetrySession + AnomalyDetector
  -> read-only immutable ObservabilityReport
     -> separate text/JSON renderer
     -> optional existing process-isolated offline SDK projections
```

The renderer has no ledger/runtime/admission/execution handle and no callbacks.
It revalidates the closed report, aggregates source snapshot numbers for display
only, and cannot reserve, settle, retry, refund, approve, authorize or reroute.
No business rule, percentile algorithm or admission calculation is recreated in
presentation code. Strict options accept only 1..20 samples and an offline SDK
boolean; identity/content/credentials/permissions/budgets/evidence are not options.

## Real local composition and visible facts

Each workflow runs a genuine two-step LangGraph lifecycle. Step 1 invokes the
accepted local fake provider twice; step 2 invokes it once. Provider output is
validated by the accepted boundary and discarded from the report. Action and
provider spans are nested under the generated workflow trace, with numeric step
ordinals rather than arbitrary work labels. Structured event schemas and the
strict inert traceparent hook are unchanged. External trace context grants no
authority and cannot replace the application's trace root.

Application fixture limits: input/output per call **8/32**, cumulative per step
**24/96**, at most **5** workflow reservations, at most **3** per step. The fixed
tariff of one fixture micro-USD per allocated token reserves **40** per attempt
against a cap of **160**. These are deterministic fixtures, not real prices.
Three local completed calls commit **120**. An explicit simulated uncertain
attempt reserves/finalizes TIMEOUT, keeping **40 outstanding**. It sends no
inference request. A fifth reservation is refused by the accepted hard exposure
cap. Reopen preserves the exact ledger snapshot, token allocations and warnings.
No lower provider report can refund the conservative bounds.

The dashboard presents per-step local call/receipt counts, reservation counts,
allocated input/output tokens, token caps, provider-reported counts if present,
attributed committed/outstanding fixture exposure, cap/utilization, 80%/100%
warning state, hard-cap denial and recovery preservation. Local fake receipts
correctly report LOCAL with no invented provider token counts or usage-based
estimate. Local input bytes remain separate numeric accounting facts. Verified
billing remains None. Per-step committed/outstanding values are read-only sums
of accepted attempt accounts, not independent settlement or pricing logic.

Warnings include outstanding exposure and persist through reopen. With four
equal 25% reservations, the final 75%-to-100% crossing legitimately emits both
80% and 100% warnings at that reservation. Existing lower-level regressions also
cover separate threshold crossings, deduplication and durable reconstruction.

## Latency, cohorts and SLO meaning

Accepted monotonic measurements cover the local lifecycle invocation, its actions
and providers, including their real ledger work. Optional exports, subsequent
uncertain-attempt demonstration and rendering are outside the completed workflow
measurement. They are not included in a fabricated end-to-end timing claim.
The report contains per-workflow cohorts and a separate bounded cross-workflow
successful deterministic monotonic cohort. A one-sample report remains explicitly
**insufficient_samples**, even if p95 is below five seconds.

The optional twenty-sample demonstration creates twenty fresh complete workflows,
not twenty copies of one duration. Each accepted single-run duration is added to
the accepted LatencyWindow; its nearest-rank p50/p95/sufficiency/SLO assessment is
used unchanged. Only one workflow's detailed history is presented. UUIDs and
monotonic timings intentionally vary; costs, categories, bounds and availability
states are semantically equivalent. The SLO remains **p95 <=5 seconds** and the
workflow deadline remains a separate **180-second** safety limit. Neither this
fixture nor a passing cohort establishes representative production latency.
Accepted suspension/resume tests retain their distinct segment/HITL wait semantics.

## Anomaly pipeline and the remaining frozen categories

Accepted bounded advisory rules are reused. Budget-spike source observations come
from real fixture ledger reservations (40 is 25% of the cap). Retry-burst,
denial-burst, provider-failure and tool-frequency examples use **explicit bounded
event-stream fixtures**, not a claim that those failures/retries/tool executions
occurred in the successful local workflow.

The architecture also requires excessive compression and tool-frequency support,
which Slice 2 explicitly deferred. Slice 4 adds two finite GovernanceKind values
and extends the existing detector rather than creating another anomaly engine:

- Excessive compression: an accepted ContextCompressor result supplies only
  source/compressed token estimates; >=90% removal emits an advisory signal.
- Tool frequency: ten trusted call observations in the existing rolling 60-second
  window emit an advisory signal. The lab feeds ten labeled fixture observations.

These are documented engineering signal defaults, not new privileged policy,
execution budgets, semantic quality guarantees or ML anomaly detection. They do
not automatically block tools or approve any action. Source rules retain 64
timestamps per finite category and 64 signals, window expiration, deduplication
and rearm behavior. Compression counts are bounded strict integers <=12,000;
content and provenance text do not enter the anomaly payload.
Lab advisory observation failures are counted without retaining diagnostics;
persisted monetary state and previously recorded anomaly source state survive.

## Optional integrations and N2 disposition

LangSmith retains its accepted genuine Client create/update/flush/close seam over
the controlled offline Session. Langfuse retains genuine observations/OTel export
through a private provider and offline exporter. Production adapter/worker
behavior is unchanged. Helicone remains the accepted strict disabled header and
configuration boundary with no transport, key field or provider target binding.
Its headers do not establish safe future retries/caching/fallback/transformation;
any live gateway integration still requires separate human authorization.

**N2 independent investigation:** installed Langfuse 4.17.0 resource-manager source
keys instances by public key and returns an existing instance. Shutdown stops its
consumers but does not remove that registry entry. A fresh-process regression
probe demonstrates first projection succeeds and repeat direct in-process
initialization fails at flush. No vendor registry reset or undocumented global
mutation is used to force a different lifecycle.

All genuine SDK seam and SDK phase-failure tests now run in fresh test processes,
matching the supported production flush lifecycle. Each probe counts socket/DNS
attempts and asserts zero. Existing payload/privacy/correlation/error-chain
assertions remain; the production subprocess tests and a repeated-fresh-process
regression demonstrate independent successful lifecycles. Test order no longer
supplies a hidden Langfuse registry precondition. Direct repeated in-process use
is explicitly unsupported; it is not a new public integration API.

## Privacy, authority, resource and failure boundaries

Only closed accepted facts reach the report: workflow/thread/trace/span/attempt
IDs, finite categories, numeric steps/counts/timing, token allocations/availability,
fixture exposure/warnings, and finite exporter health. Unknown metadata, prompts,
model/tool/MCP/document content, secrets, auth headers, arbitrary errors/repr or
URLs cannot be added to configuration/report contracts. Renderer errors are fixed
safe PresentationError messages and leave the source report/ledger intact.
Presentation values remain data and cannot grant monetary or other authority.

Default lab tests count socket connect/connect_ex/create_connection/getaddrinfo
attempts and require **zero**, even with hostile credential-looking environment
sentinels. Optional SDK probes independently count zero attempts in child
processes. SDK fixtures use only dummy values and controlled transports. Neither
credential presence, fixture tariff, usage claim, telemetry, anomalies, external
trace IDs nor report/exporter/Helicone state can enable real monetary admission.
Accepted permission/HITL/off-switch/routing/provider protections remain unchanged.

Bounds: <=20 complete workflows, <=3 actual local provider calls per workflow,
one detailed report, <=512 events, <=36 per-workflow latency cohorts, <=8 usage
receipts/attempt accounts, <=64 anomaly signals, six finite rule windows and no
dashboard history registry. At most two optional vendor drains per lab, regardless
of sample count. Accepted queue capacity 64, saturating counters, one process-wide
drain slot, ten-second subprocess timeout and no-export-retry semantics remain.
Integration health is captured before immediate adapter close; no persistent
client remains. SDK absence/failure/timeout is advisory, and real admission remains
disabled. Local SQLite remains trusted-filesystem evidence, not authenticated
rollback/tamper resistance or provider invoice reconciliation.

## Verification and requirement reconciliation

Strict gate order: Ruff -> focused Story 10 suite -> full module pytest -> compileall.
Initial Ruff findings were line lengths, unused import and import ordering;
repaired with manual wrapping plus safe import fixes only. No unsafe fixes used.

- Ruff: PASS.
- Focused tests: **300 passed in 100.00 seconds**, no warnings/skips reported.
- Full module pytest: **1,644 passed, 6 warnings in 502.77 seconds (8:22)**.
  Accepted 1,607 baseline plus 37 additions; no failures or skips.
- Compileall: **PASS**, exit 0, `python -m compileall -q src tests`, after pytest.
- Actual CLI invocation: **PASS**, default text output and explicit offline-SDK
  JSON output. Both SDK worker health snapshots reported 28 projected events,
  zero drops/failures; no hosted delivery claim. Output/SQLite artifacts are under
  parent `TECHADEMY/EVIDENCE/module-06-5-story-10-slice-04-cli-20261019*` and
  `module-06-5-story-10-slice-04-sdk-cli-20261019*`, outside the repository.
- Explicit twenty-workflow CLI JSON artifact:
  `TECHADEMY/EVIDENCE/module-06-5-story-10-slice-04-twenty-cli-20261019.json`.
  Actual monotonic successful deterministic cohort: **n=20, p50=0.984s,
  p95=1.593s, SLO target=5.0s, slo_met=True**, no evictions. This is one bounded
  fixture cohort, not representative production performance. Default CLI n=1
  measured 0.328s and correctly reported insufficient samples, not compliance.

Integrated tests cover zero network attempts; real trace/step/provider nesting;
read-only cost rendering; source evidence/provenance; one/twenty sample states;
bounded semantically repeatable fixtures; invalid configuration before side
effects; report injection; telemetry/anomaly projection failures; missing SDK,
construction failure and timeout normalization; unchanged accounting on exporter
failure; uncertain exposure/reopen; duplicate/late usage; renderer serialization
failure; and added anomaly thresholds/validation. Accepted Story 10 tests retain
queue-full/saturation/single-slot/no-retry bounds, malformed receipts, fail-closed
corrupt recovery, spend warnings, permission denial and suspension coverage.

After all four green gates, implementation evidence was appended to TRACEABILITY.md
without changing approved requirement wording. Current root PROJECT_STATUS.md
bytes were re-read before a narrow Module 6.5-only status update, explicitly
pending independent acceptance. No other module status was overwritten.
Requirement implementation assessment (all listed implementation criteria met):

| Requirement | Implementation / reviewer-visible evidence |
|---|---|
| REQ-OBS-001 | TelemetrySession/TelemetryEvent, nested real lifecycle lab, structured event presentation and regressions. |
| REQ-OBS-002 | Strict inert traceparent, generated app identity, provider-worker context and offline SDK correlation tests. |
| REQ-OBS-003 | Bounded six-category advisory detector, accepted source hooks and explicit fixture pipeline examples. |
| REQ-COST-001 | Accepted TokenPolicy/FixtureLedger/ProviderRuntime allocations and per-step visible accounting. |
| REQ-COST-002 | Monotonic cohorts, accepted nearest-rank percentiles, explicit insufficiency and bounded twenty-run option. |
| REQ-COST-003 | Runnable text/JSON per-step fixture attribution dashboard from read-only source accounts. |
| REQ-COST-004 | Durable warning thresholds including outstanding exposure, displayed states and accepted threshold regressions. |
| REQ-TECH-004 | Genuine LangSmith offline projection/serialization/failure probes; optional, no authority. |
| REQ-TECH-005 | Genuine Langfuse/OTel offline seam and supported fresh-process lifecycle regression. |
| REQ-TECH-007 | Source-faithful strict disabled offline header/configuration boundary, no routing. |
| REQ-LAB-006 | Runnable observability lab exposes actual trace capture, structured logs and cost dashboard. |
| REQ-DEL-004 | Story 10 CLI observability/cost dashboard; final combined Streamlit experience remains Story 11. |
| ENG-002..007 | Closed untrusted-data boundaries, unchanged authority, bounded/free execution, evidence labels and adversarial/full regression gates. |

## Completion evaluation and non-claims

Requirements: the matrix above has complete successful gates; independent review
is pending and this is not a formal acceptance decision. Product experience: runnable
self-explanatory CLI dashboard with JSON facts. Real functionality: accepted
LangGraph/provider/SQLite/telemetry composition, with explicitly labeled fixtures.
Reliability: bounded execution, recovery, uncertainty, exporter/presentation loss
and regression evidence. Security: strict content/provenance/evidence boundaries
and no authority feedback. Cost: deterministic fixture-only accounting, no spend.
Evidence: deterministic application behavior, local SQLite integration and genuine
SDK behavior over controlled offline boundaries remain distinct. Deployment: none.

No hosted LangSmith/Langfuse traffic, Helicone provider/inference traffic, live
gateway binding, provider endpoint rerouting, live provider execution, real
credentials, real monetary execution, current provider prices, verified billing,
hosted delivery, deployment or production observability is claimed. Guardrails AI
remains Story 9 additive validation and is not relabeled as observability.
No Story 11 evaluation/golden-set/UI or Story 12/module release is claimed.

Warnings are the six accepted Typer/Click stream/flag-parameter deprecations in
guardrail coverage. No new Slice 4 test warnings occurred. Verified environment:
Python 3.12.14, LangSmith 0.14.7, Langfuse 4.17.0, OpenTelemetry SDK 1.45.1.
No installation or dependency-file change was needed.

## Exact candidate inventory and final review boundary

Module 6.5 added:

- `src/harness_engineering/observability_lab.py`
- `src/harness_engineering/observability_report.py`
- `src/harness_engineering/observability_presentation.py`
- `tests/observability_sdk_probe.py`
- `tests/test_observability_lab.py`
- `docs/STORY_10_SLICE_4.md`

Module 6.5 modified:

- `src/harness_engineering/anomaly_signals.py`
- `src/harness_engineering/governance_facts.py`
- `tests/test_observability_adapters.py`
- `docs/TRACEABILITY.md`

Separately authorized root modification: `docs/PROJECT_STATUS.md`, limited to
Module 6.5 status/evidence/next review. No accepted slice report, architecture,
authority policy, requirement wording, monetary/provider implementation,
dependency declaration or lockfile changed.

All 12 Story 10 requirement implementation criteria and applicable ENG-002–007
evidence are satisfied at the authorized deterministic/offline scope. The no-key,
zero-attempt lab path, reviewer-visible results, safe SDK seams and regression
gates are present. Story 10 is implementation-complete **pending independent
acceptance**, and the candidate is ready for independent cross-model adversarial
review. No independent acceptance or release is declared. Nothing is staged or
committed; protected foreign work is preserved.

Final ancestry verification passed again with no intervening commits after
`fb2b607`. `git diff --check` passes. Git reported CRLF-to-LF advisory warnings
for the edited PROJECT_STATUS/TRACEABILITY documents; no foreign line-ending
configuration was modified. The entire index is empty.

Complete final `git status --short`:

```text
 M docs/PROJECT_STATUS.md
 M module-06-5/docs/TRACEABILITY.md
 M module-06-5/src/harness_engineering/anomaly_signals.py
 M module-06-5/src/harness_engineering/governance_facts.py
 M module-06-5/tests/test_observability_adapters.py
?? .editorconfig
?? .gitattributes
?? module-06-5/docs/STORY_10_SLICE_4.md
?? module-06-5/src/harness_engineering/observability_lab.py
?? module-06-5/src/harness_engineering/observability_presentation.py
?? module-06-5/src/harness_engineering/observability_report.py
?? module-06-5/tests/observability_sdk_probe.py
?? module-06-5/tests/test_observability_lab.py
?? scripts/
```
