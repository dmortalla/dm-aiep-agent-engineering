# Module 10 operational runbooks — Story 10.10

Status: implemented offline-deterministic operational readiness; live
operational exercises remain separately human-authorized. This document
describes the four operational registers, their evidence contracts, the
rollback authority boundary, and the verified limitations. It makes no
deployment, SLA, provenance, or completion claim beyond the accepted
point-in-time records.

## Boundaries that bind every register

- All validators are deterministic, no-key, and offline. They read one
  explicitly supplied minimized JSON evidence file (at most 32768 bytes)
  and never perform network, cloud, subprocess, or privileged operations.
- All evidence content is untrusted data: exact field allowlists, type-strict
  checks, bounded values, fixed sanitized errors, fail-closed on missing,
  malformed, contradictory, or unsupported input. Evidence content can never
  select commands, URLs, paths, or privileges.
- VALIDATED ROLLBACK PLAN != AUTHORIZED EXECUTION. A validated plan is not
  authorized, performed, or successful rollback; execution authority remains
  the accepted `ci/promotion.json` value: an operator-approved protected
  environment. No code in this story executes rollback, modifies deployment
  pointers, invokes cloud APIs, or triggers workflows.
- Registers assert no dollar amounts; the cost register records
  configuration-bounded levers only, never a billing record.
- SLO statements follow the accepted measured/proposed/illustrative label
  discipline (ARCHITECTURE item 21). Labels are reasoning, not SLA claims;
  the validator rejects measured claims without measurements or sources and
  proposed/illustrative claims that carry fabricated measurements.

## 1. Deployment-readiness checklist (C-015)

Command:

```powershell
.venv/Scripts/python.exe scripts/operations_check.py checklist --evidence <checklist.json>
```

The checklist evidence is one minimized JSON document with schema_version 1,
classification `MODULE 10 OPERATIONAL READINESS / OFFLINE DETERMINISTIC`, a
tz-aware `generated_at` timestamp, and exactly one entry per accepted item:

- The eight M2 acceptance gate names (`inventory`, `configuration`,
  `registry_digest`, `revision_health`, `https_health`,
  `deterministic_inference`, `bounded_rejection`, `azure_monitor_receipt`)
  each reading `passed` from the accepted point-in-time M2 record.
- Three carried-open items that must read `open`: `tested_source_provenance`
  (unresolved M2 provenance binding), `rollback_execution` (never verified),
  and `live_slo_attainment` (no live SLO measurement exists).

Outcome `ready` means the checklist is consistent with the accepted
point-in-time evidence — it is not deployment authority. Gate items reading
`failed` yield `not_ready`; a carried-open item reading anything other than
`open` is rejected as `contradictory` (an unsupported claim), so no
carried-open item can be dropped from the report; unknown, missing, or
malformed items fail closed. Each check exits 0 (validated), 1 (rejected), or
2 (usage), and every rejection prints one machine-readable JSON report whose
status token distinguishes `missing` evidence from `malformed` evidence.

## 2. Incident response (C-016)

```powershell
.venv/Scripts/python.exe scripts/operations_check.py incident --evidence <incident.json>
```

Incident evidence carries one accepted scenario and exactly its allowlisted
observations: `health-flap` (readiness outcomes plus a bounded window),
`queue-saturation` (bounded rejected-event count plus window),
`inference-deadline` (bounded timeout count plus window), `telemetry-gap`
(bounded Monitor receipt-row count), and `revision-drift` (expected and
observed revision identities in the accepted revision shape). Unknown
scenarios are `unsupported`, never invented into a class; malformed
observations fail closed.

Classification output is fixed read-only guidance per scenario (worker
lifecycle degradation vs process death; documented backpressure expectation;
deadline/queue-depth inspection before any human scale decision; Monitor
ingestion window before escalation; rollback-plan boundary consultation) plus
a boundary note that no response action is authorized by the report. Live
diagnostics against a deployed app reuse the accepted read-only verifier
surface (`scripts/azure_deployment.py` gates and correlated aggregate KQL);
operators run those commands themselves under the accepted workflow.

## 3. Rollback validation (C-017)

```powershell
.venv/Scripts/python.exe scripts/operations_check.py rollback-plan --evidence <plan.json>
```

A rollback plan is a data-only artifact validated against the accepted
promotion contract (`ci/promotion.json`): one accepted trigger
(`failed_health_verification`, `failed_inference`, `operational_regression`);
exactly the accepted five post-rollback checks in sequence (`liveness`,
`readiness`, `deterministic_inference`, `azure_monitor_receipt`,
`revision_traffic`); the exact accepted execution-authority string;
`deployment_authorized` exactly `false`; and `provenance_precondition`
exactly `unresolved` — the unresolved M2 tested-source-to-cloud-image
binding is carried as an explicit precondition, and a plan claiming it
resolved is rejected as contradictory.

Human rollback execution (activate/redeploy the previous accepted revision)
remains an operator action under the accepted promotion contract, with the
post-rollback checks re-running the accepted verifier contracts. NO rollback
has been executed or verified; the plan validator does not change that.

## 4. SLO register (C-018) and cost register (C-012 share)

```powershell
.venv/Scripts/python.exe scripts/operations_check.py slo --evidence <slo.json>
.venv/Scripts/python.exe scripts/operations_check.py cost --evidence <cost.json>
```

Accepted SLO objectives: `readiness_availability`, `liveness`,
`inference_latency`, `queue_saturation_rate`, `monitor_receipt_presence`,
each with an accepted measurement source (`local-telemetry`,
`azure-monitor-receipt`, `verifier-gates`, `none`). A `measured` label
requires a bounded measurement value and a real source; `proposed` and
`illustrative` must not carry measurements. Today the honest register labels
operational objectives `measured` only where accepted exercise evidence
exists (local deterministic exercises) and `proposed`/`illustrative`
everywhere else; `live_slo_attainment` remains an open checklist item.

Cost entries cover `registry`, `log-analytics`, `container-app`, `identity`,
and `teardown`. A `verified` kind must rest on `observed-configuration`
(the accepted footprint/quota settings); an `assumption` must rest on
`operator-judgment`. An optional bounded `budget_threshold` may be recorded
(recommended: `bounded-by-human-review`). The register asserts no dollar
amount; actual billing review remains the operator's private responsibility
per AZURE_DEPLOYMENT.md cost discipline.

## Exercised demonstration and limitations

The offline demonstration exercised the real CLI against (1) valid readiness
evidence (`ready`, exit 0, eight gates, three open items), (2) invalid and
missing evidence (fixed errors, exit 1), (3) a conforming rollback plan
requiring human authorization (`validated`, `deployment_authorized=false`,
exit 0) plus an authority-claiming plan rejected as `incompatible` (exit 1),
and (4) malformed and oversized evidence files, which are reported with the
`malformed` status token rather than `missing`. Simulated checks are OFFLINE
DETERMINISTIC evidence; they are not live-cloud evidence.

Preserved verified limitations: M2 point-in-time Azure acceptance 8/8;
tested-source/cloud-image provenance UNRESOLVED; actual rollback execution
NOT VERIFIED; C-026/C-027 DEFERRED to Story 10.11; full Module 10 completion
NOT ESTABLISHED; live operational exercises (incident drills against the
deployed app, rollback execution, live SLO attainment) require fresh explicit
human authorization and an existing cloud footprint.
