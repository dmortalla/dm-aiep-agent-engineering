# Story 11 Slice 1: inline invariants, golden set and regression harness

Implemented for independent review; Story 11 remains incomplete. Patch is
unstaged and uncommitted. No architecture, requirements, dependencies, lockfile,
root status, foreign module, accepted Story 1-10 source or test is changed.

## Authority, baseline and scope

Accepted Story 10 baseline and initial HEAD:
`096c96db4c181680d9d22bf52326ae9cc62e9f5c` (no intervening commits).
Accepted pre-Story-11 full suite: 1,644 tests.

Authority read before mutation: AUTHORITATIVE_SOURCE (Evaluation Hooks, Test
Cases & Regression Checks; deliverable "Regression test harness for agent
behaviour"), REQUIREMENTS, TRACEABILITY, frozen ARCHITECTURE ("Evaluation and
Regression Harness", "Streamlit Reviewer UI", latency regression reporting),
ADR 001, IMPLEMENTATION_PLAN Story 11, Story 10 authority policy, root SOP,
AGENTS/CLAUDE and PROJECT_STATUS. No architecture amendment, new ADR or
dependency change is needed for this slice.

Files relative to `module-06-5` (all added):

- `src/harness_engineering/evaluation.py` - inline invariant monitor, golden-set
  contracts, strict loader, exact comparison, typed case/report results.
- `src/harness_engineering/evaluation_probes.py` - trusted probe registry over
  accepted Story 2-10 services and labs.
- `src/harness_engineering/evaluation_golden_set.json` - retained expectations.
- `src/harness_engineering/evaluation_lab.py` - regression runner, latency
  cohort, guided text/JSON CLI.
- `tests/test_evaluation.py`, `tests/test_evaluation_lab.py`.
- `docs/STORY_11_SLICE_1.md` (this report).

## Requirements advanced, not closed

| Requirement | Slice 1 evidence and remaining scope |
|---|---|
| REQ-EVAL-001 | `InlineInvariantMonitor` is a trusted `BoundaryObserver` checking seven invariants (schedule order, attempt bound, attempt accounting, monotonic progress, terminal closure, no attempt after deadline, boundary bound) at every lifecycle boundary; violation aborts the run fail-closed. Used by every lifecycle golden probe. |
| REQ-EVAL-002 | Versioned, bounded golden set of 16 cases covering every architecture-named area (planning, dependency order, context budget, compression, permission denial, MCP validation, retries, circuit breaking, fallback, hard stops, recovery, idempotency, approval, cost controls, output validation, off-switch). |
| REQ-EVAL-003 / REQ-DEL-005 | `run_regression` executes accepted services and compares fresh observations exactly with retained expectations, reporting per-field drift. Reviewer UI presentation remains Slice 2. |
| REQ-COST-002 (architecture regression reporting) | Twenty complete deterministic plan -> lifecycle -> fake-provider workflows measured with the accepted `LatencyWindow` against the frozen p95 <= 5 s SLO. |
| ENG-002/003/007 | Hostile fixture text stays inert and is never echoed; golden data cannot add probes, relabel traceability or promote evidence; failure, drift and defect paths are tested. |
| ENG-004/005/006 | Bounded golden bytes/cases/fields/sequences/samples; no credentials, network or paid calls; evidence derived only from trusted probe classification. |

ENG-001 (Streamlit reviewer UI covering all six labs) and Story 11 closeout are
not claimed by this slice.

## Semantics

- Golden data contains only `case_id` and exact `expected` observations. Area,
  requirement IDs, purpose and evidence class live in the trusted registry.
- Golden case IDs must exactly equal the registry; mismatches, extra fields,
  duplicate JSON keys, floats, nested objects, oversize files (> 64 KiB), > 32
  cases, > 24 fields or > 32 sequence items fail closed before any execution,
  without echoing content.
- Comparison is exact and typed (`True` is not `1`; sequence order matters).
- Expected harness failures inside a probe become an `ERROR` verdict with the
  exception type only; programming defects (e.g. `TypeError`) propagate.
- Verdict, totals and report evidence are derived and revalidated; evidence is
  restricted to `deterministic` and `local_integration`.
- Expectations are retained accepted behavior; the latency SLO is frozen at
  5 seconds. An implementation-local safety bound permits at most 16 nested
  containers (root container is level 1), following the accepted MCP JSON
  convention. It is not a source requirement or user-configurable threshold.
  An iterative guard precedes recursive normalization, including parsed probe
  observations. Decoder and normalization recursion failures become sanitized
  `ContractValidationError`; CLI exit 2 precedes probes and artifact creation.
  Ordinary malformed JSON retains the same sanitized rejection behavior.

## Reviewer invocation

```text
python -m harness_engineering.evaluation_lab --directory <new-path>
python -m harness_engineering.evaluation_lab --directory <new-path> --format json
python -m harness_engineering.evaluation_lab --directory <new-path> --golden <edited-copy>
```

Exit codes: 0 all cases pass; 1 regression or case error; 2 untrusted golden
file, invalid selection or reused directory (details withheld).

## Original candidate gates (before bounded repair)

1. Ruff safe fixes on the new files only (unused `noqa`, import order), then
   `ruff check .`: PASS.
2. Focused `tests/test_evaluation.py tests/test_evaluation_lab.py`: 75 passed.
3. Full Module 6.5 suite: 1,719 passed (1,644 accepted + 75 new), 6 warnings,
   all pre-existing third-party typer/click deprecations from the Guardrails test.
4. `python -m compileall -q src tests`: PASS.

CLI smoke: packaged JSON run exit 0 (16/16 passed, 20 latency samples, SLO met);
edited-golden run exit 1 with the exact `resume` field difference reported.

## Limitations and non-claims

Deterministic fixtures and local integrations only (MCP SDK in-memory transport,
local SQLite). No live provider, paid inference, hosted LangSmith/Langfuse,
Helicone routing, deployment or production claim. Fixture cost units are not
billing. Latency is one local workflow shape, not production traffic. Network
denial in tests counts non-loopback connections; loopback stays available for
the Windows asyncio self-pipe used by the in-process MCP transport.


## Bounded recursion repair (pending independent re-review)

The independent review blocker was an escaping `RecursionError`: JSON decoding
can overflow before validation, and recursive array freezing can overflow even
when decoding succeeds. The loader now translates decoder/validation recursion;
normalization first enforces the iterative 16-container safety bound and narrowly
translates residual recursion with exception chaining. Probe observation validation
also translates recursion. The existing CLI sanitization boundary is unchanged.
No architecture or product requirement threshold is added.

Fresh fail-fast verification: Ruff PASS; focused tests 86 passed (11 added);
adversarial depths 17, 1,200 and 10,000 rejected; CLI smoke exits 0/1/2 for
accepted/drift/malformed input; full suite 1,730 passed with the same six
third-party Typer/Click deprecation warnings; compileall source/tests PASS.
Depth 16 normalization passes; depth 17 fails. Existing packaged observations
remain accepted. Regression tests inject decoder/normalizer recursion to verify
sanitized `ContractValidationError` and causal chaining. CLI sentinels prove no
case or latency workflow starts for malformed input; no output directory is
created and neither traceback nor `RecursionError` is emitted.

Fresh normal smoke: 16/16 cases pass, 20 workflow latency samples,
p95 0.016 seconds against the frozen 5-second SLO. Normal plus valid-drift
smokes counted zero external socket attempts and 22 local loopback attempts;
network denial was active. No live provider, hosted service, credential or
spending activity was performed. Temporary artifacts remain under
`TECHADEMY/EVIDENCE/story11-repair-20261020`.

Only evaluation.py, its two test files, and this report were repaired. All seven
candidate files remain unstaged/uncommitted. Story 11 remains incomplete;
Slice 2 and Story 12 remain unstarted. No independent acceptance, UI completion,
deployment or production-readiness claim is made.
