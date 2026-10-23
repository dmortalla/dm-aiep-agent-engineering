# Story 6 - Automated Evaluation, Regression, Benchmarking, and LangSmith

## Status

CONTRACT AUTHORED - not independently reviewed; implementation not started by
contract authoring. This contract does not accept itself and does not unblock
implementation. Independent contract review is required first.

Prerequisite: independently accepted Story 5 commit
`1cf6eb0c4ab64f5cf5e1de628d855e6004bad2b8`. Verify its ancestry and the accepted
Module 7 content before implementation; unrelated descendant commits are allowed.

Contract-authoring baseline: branch `main`, HEAD
`fb2b6073801a2fda528aafbd202e3f443625dc0b`. The accepted Story 5 commit is an
ancestor; the only descendant commit (`fb2b607`) touches no Module 7 path, and
`git diff 1cf6eb0 HEAD -- module-07` is empty. Module 7 had no tracked or
untracked changes and the index was empty. No evaluation engine, dataset,
baseline, LangSmith adapter, LangSmith settings or LangSmith test exists: the only
`langsmith` text in Module 7 source/tests is the accepted Story 1 forbidden-import
list. `langsmith` 0.14.8 is already present in `uv.lock` and the Module 7
environment, but only as a transitive dependency of `langchain-core` 1.6.10
(pulled in by `guardrails-ai` 0.11.0); it is not a declared dependency. Foreign
dirty/untracked work outside Module 7 was present and remains outside this
contract. Historical PLANNED/not-started wording in the frozen plan, and the
"Story 6 remains blocked" sentences in `STORY-05-IMPLEMENTATION.md` written
before Story 5's controlled commit, are not current status assertions or
permission to rewrite those documents.

## Goal

Deliver the Module 7 evaluation pipeline: an application-owned, deterministic,
versioned evaluation engine that automatically evaluates real Module 7 behavior
over a versioned benchmark dataset, applies application-owned thresholds, detects
regressions against a compatible versioned baseline, produces reproducible
benchmark evidence and supports a human-controlled continuous-improvement loop,
and integrate LangSmith as the specialist independent evaluation integration
that receives minimized, already-decided evaluation evidence (datasets,
examples, experiments, runs and feedback) without LangSmith ever becoming
authoritative for correctness, regression policy, release, cost or authority.

## Authoritative Scope

This contract operationalizes Story 6 in IMPLEMENTATION_PLAN.md under frozen
REQUIREMENTS.md, ARCHITECTURE.md and the five assigned ADRs. It does not amend
them. TRACEABILITY.md maps REQ-EVAL-001 (Topics: Automated evaluations),
REQ-EVAL-002 (Regression testing), REQ-EVAL-003 (Benchmarking), REQ-EVAL-004
(Continuous improvement loops), REQ-LAB-002 (Hands-on Labs: Build automated
evaluation pipelines), REQ-TOOL-001 (Tools & Frameworks: LangSmith) and
REQ-DEL-002 (Deliverables: Evaluation pipeline) individually to the course
source. REQ-COST-003 and REQ-COST-004 are GOVERNANCE requirements assigned by the
plan and are not represented as course requirements.

Earlier-story security, reliability, telemetry, cost, quality, dependency,
isolation and evidence obligations remain binding constraints rather than
additional Story 6 assignments, including REQ-SEC-001 through REQ-SEC-009,
REQ-ENG-002, REQ-ENG-006, REQ-ENG-007, REQ-COST-001, REQ-COST-002, REQ-QUAL-001
through REQ-QUAL-006, REQ-SRC-003, REQ-SRC-004, REQ-DOD-004, REQ-DOD-008,
REQ-ISO-001, REQ-ISO-002, ADR-007-005, ADR-007-006, ADR-007-009 and
ADR-007-011.

Plan scope (all mandatory, none replaced): versioned evaluation dataset;
deterministic evaluators; comparable result schema; regression thresholds;
benchmark execution; LangSmith adapter; CI-safe evaluation path; bounded optional
live evaluation path; continuous-improvement evidence loop.

## Requirements

Assigned (exact frozen wording verified in REQUIREMENTS.md):

- REQ-EVAL-001 [SOURCE]: The module shall demonstrate automated evaluations.
- REQ-EVAL-002 [SOURCE]: The module shall demonstrate regression testing.
- REQ-EVAL-003 [SOURCE]: The module shall demonstrate benchmarking.
- REQ-EVAL-004 [SOURCE]: The module shall demonstrate continuous improvement loops.
- REQ-LAB-002 [SOURCE]: The module shall build automated evaluation pipelines.
- REQ-TOOL-001 [SOURCE]: The module shall meaningfully use LangSmith.
- REQ-DEL-002 [SOURCE]: The module shall deliver an evaluation pipeline.
- REQ-COST-003 [GOVERNANCE]: The ordinary automated quality gate shall not
  require billable model or vendor calls where deterministic substitutes can
  validate the same engineering contract.
- REQ-COST-004 [GOVERNANCE]: Live external evaluations or integration checks
  shall be explicitly identifiable and separable from ordinary deterministic
  tests.

REQUIREMENTS.md defines meaningful use as observable and verifiable evidence;
merely listing, installing, importing or mentioning LangSmith is not meaningful
use. REQ-SEC-006 explicitly includes evaluation records in the secret-exclusion
scope. REQ-COST-001 explicitly includes evaluations among bounded operations.

## Assigned ADRs

- ADR-007-001: application-owned normalized telemetry and evaluation layer;
  LangSmith is the primary independent evaluation/regression integration;
  neither vendor is required for deterministic core correctness.
- ADR-007-002: LangSmith owns primary evaluation/regression evidence; application
  code owns authority, resilience, idempotency, budgets and recovery.
- ADR-007-007: deterministic evaluation engine and controlled benchmark fixtures
  by default; comparable evaluation results and regression thresholds are stored;
  bounded live/model-backed evaluations only as explicitly labeled evidence.
- ADR-007-008: ordinary CI is credential-free and deterministic; live vendor/model
  tests are optional, bounded, separately configured and required only for claims
  that depend on live behavior.
- ADR-007-012: explicit budgets for billable/model-backed execution; evaluations
  consume the same bounded budget; deterministic CI requires no billable calls;
  live evidence modes expose usage and cost.

## Frozen Architecture Constraints

ARCHITECTURE.md places the Evaluation Engine, Benchmark Dataset, Deterministic
Fixtures and LangSmith Adapter in the logical architecture (`BENCH --> EVAL`,
`FIX --> EVAL`, `EVAL --> LS`, `EVAL --> LF`, `EVAL --> UI`). Execution Flow step 9:
LangSmith receives independent evaluation/regression evidence and may receive
selected traces required for meaningful integration. Step 10: the evaluation
engine runs deterministic benchmarks by default and bounded live/model-backed
evaluations only when explicitly enabled.

LangSmith responsibility: datasets/examples where live integration is exercised;
automated evaluation; regression comparison; benchmark evidence; selected tracing
sufficient to demonstrate meaningful integration. Ordinary CI does not require
LangSmith credentials.

Deterministic Mode: controlled benchmark fixtures, deterministic evaluators,
regression thresholds, failure/recovery scenarios, safety and authorization
scenarios, no vendor credentials, no billable model calls. Live Evidence Mode:
explicitly enabled and bounded; real course-tool integrations; optional
model-backed evaluators; vendor trace/evaluation identifiers; explicit cost and
call limits; evidence labeled live. Live mode is evidence generation, not a CI
prerequisite.

Continuous Improvement Loop: benchmark and regression results produce versioned
evaluation evidence; a failing regression identifies the affected scenario and
metric; repairs are made through normal engineering workflow; the same benchmark
is rerun before improvement is claimed; the system does not autonomously modify
production policy or code from evaluation output.

Trust Boundaries: evaluation content and external/provider responses are
untrusted until validated. Provider Failure Semantics for an evaluation provider:
live evaluation is marked failed/unavailable and deterministic evaluation remains
independent. Failure injection is confined to test/demo boundaries and cannot
silently activate in normal execution. Secrets are never included in benchmark
fixtures. Invalid evidence-mode configuration never silently downgrades or
upgrades evidence classification. Persistent distributed state is not introduced
(ADR-007-009); the evaluation store is versioned committed data plus bounded
in-process records.

Langfuse's architecture responsibility includes "selected evaluation scores".
Story 5 deliberately carried only the `evaluation_id` join key and deferred score
composition to Stories 6/10. This contract's composition decision is under Story
4/5 Composition; it requires no Story 5 change.

The frozen sources do not select a model provider (REQUIREMENTS.md Architecture
Boundary). This contract therefore does not select one; see Live / Model-Backed
Evaluation.

## Implementation Boundaries

Story 6 may add, inside Module 7 only:

1. Application-owned evaluation modules (names are implementation choices; this
   contract refers to them by responsibility): evaluation contracts and engine;
   deterministic evaluators; the evaluation target/scenario runner over accepted
   Stories 2-4; baseline, regression, benchmark and improvement-cycle logic. None
   imports `langsmith`, `requests` or any vendor SDK.
2. Versioned package data: one benchmark dataset file and one baseline file per
   dataset version (for example under
   `src/reliability_safety_observability/evaluation_data/`), loaded through
   `importlib.resources` from the installed package.
3. `langsmith_config.py`: LangSmith-specific typed settings.
4. `langsmith_adapter.py`: the only module that imports `langsmith` (and
   `requests`, see the import evolution below); SDK imported lazily.
5. Deterministic tests, a deterministic fake LangSmith transport, and one opt-in
   live verification test.
6. The constrained dependency declaration and the minimal lockfile root-entry
   update described under Dependency Contract.

Accepted source files (`config.py`, `domain.py`, `errors.py`, `logging.py`,
`telemetry.py`, `reliability.py`, `authorization.py`, `safety.py`,
`safety_types.py`, `injection.py`, `moderation.py`, `guardrails_adapter.py`,
`langfuse_config.py`, `langfuse_adapter.py`) and their public schemas remain
unchanged. `_is_sensitive_key`, `_redact`, `minimize`, `_project`,
`TelemetryLimits`, `TelemetryPipeline`, `ReliabilityController`,
`ReliabilityPolicy`, `BudgetState` and the accepted `EvaluationResult` are used as
accepted and are not weakened, broadened, bypassed or redefined. The package
`__init__` must not import the LangSmith adapter or settings; it may export new
SDK-free evaluation contracts only if doing so imports no vendor module.

### Proposed accepted-test evolution (requires independent contract-review adjudication)

The accepted Story 1 test `test_story_one_source_has_no_network_client_imports`
forbids `langsmith` and `requests` under `src`. Following the accepted Story 2
Guardrails and Story 5 Langfuse/HTTPX precedents, the narrow evolution proposed
is: permit exactly the `langsmith` and `requests` roots only in
`langsmith_adapter.py`, leaving every other forbidden root (including `urllib3`,
`httpx`, `aiohttp`, `openai`, `anthropic`, `helicone`, `langfuse`, `guardrails`)
and every other file unchanged, and add an AST confinement test proving no other
source file imports either root and that `langfuse_adapter.py` gains no new root.

Justification for `requests`: `langsmith.Client` performs its classic REST calls
through a caller-suppliable `requests.Session`. Explicit construction, ownership,
origin restriction, zero-retry adapter mounting and public close of that session
(mirroring the human-approved Story 5 HTTPX ownership) are required by Bounds,
Failure Isolation and Evidence Modes below. The permission grants no general
networking capability, redaction bypass, evidence authority or lifecycle
exception. If review rejects the `requests` permission, the fallback is an
SDK-owned session closed only through public `Client.close()`, and the
owned-transport bounds and live-evidence provenance in this contract become
unsatisfiable as written; that is a stop condition requiring a human decision,
not a license to weaken them. Any further change to an accepted test or invariant
must be identified and adjudicated before that implementation proceeds.

## Evaluation Dataset Contract

The benchmark dataset is application-owned, committed, versioned and synthetic.

1. Identity. The dataset file carries `schema_version` (integer), `dataset_id`
   (fixed identifier, for example `module7-benchmark`) and `dataset_version`
   (monotonic identifier, for example `1`). The loader computes a SHA-256
   `dataset_digest` over a canonical serialization (UTF-8 JSON, sorted keys, no
   insignificant whitespace, `allow_nan=False`) of the parsed content and compares
   it with the digest pinned in application code for that `dataset_version`. Any
   mismatch, unknown version or schema version refuses the dataset (corrupted or
   unreviewed). Changing dataset content therefore requires a deliberate version
   or digest change through normal engineering review.
2. Strict schema. Typed, frozen, `extra="forbid"` models with bounded sizes:
   at most 256 scenarios (hard ceiling), unique `scenario_id`s matching a fixed
   pattern (for example `^[A-Z]{2,8}-[0-9]{3}$`), canonical order by
   `scenario_id`, and per-scenario serialized size at most 16 KiB. Unknown fields,
   duplicate IDs, unknown vocabulary, non-finite numbers and oversize content are
   refused, not dropped.
3. Scenario fields (minimum): `scenario_id`; `category` from a fixed vocabulary
   (`reliability`, `idempotency`, `cost`, `authorization`, `safety_injection`,
   `redaction`); `title` (display only: at most 96 characters from
   `[A-Za-z0-9 .,:()_-]`, refused if it matches a sensitive-key marker or canary);
   a typed scenario specification consumed only by the application scenario runner
   (fixed fields such as tool allowlist membership, failure script steps from the
   Story 3 `Failure` vocabulary, budget limit and reservation, replay/duplicate
   flags, untrusted input text, synthetic canary placement); `evaluators`, a
   non-empty subset of the fixed evaluator identifier vocabulary; and
   `expected`, the typed expected facts below. `scenario_evidence` is
   `simulated_failure` when the specification injects a failure and
   `deterministic_fixture` otherwise; it is derived by the loader from the
   specification, not trusted from the file.
4. Expected facts (labels) are typed fixed-vocabulary values sufficient for
   deterministic scoring: expected outcome classification (a Story 3
   classification code or Story 2 decision code); expected attempts and
   fallbacks; expected `replayed`; expected side-effect invocation count; expected
   authorization and safety decisions; expected budget outcome; and, for redaction
   scenarios, the canary identifiers that must be absent. Expected facts are
   authored from accepted Story 2-4 contract semantics, not copied from running
   the implementation, and are independently reviewed.
5. Minimum coverage: at least one scenario per category and at least 12 scenarios
   in total, covering at minimum: transient failure recovered by retry; terminal
   failure; timeout with unresolved work; primary exhausted with successful
   fallback; duplicate request replay without a second effect; same idempotency
   key with different content denied; budget exhaustion before invocation;
   non-allowlisted tool denied; forged authority in untrusted content not
   elevating permission; prompt-injection input contained or denied; evaluation-
   policy injection (untrusted scenario text instructing the evaluator to change
   thresholds, expected labels or verdicts) having no effect; and a synthetic
   canary in debug metadata absent from every exported and local record.
6. Content safety. No real secret, credential, credential-format token of a real
   provider (for example no `sk-` style keys), raw production content, personal
   data or unbounded user/provider data. Redaction canaries are synthetic,
   documented as synthetic, unique per scenario, and never leave the process
   (they are excluded from every LangSmith representation and from evidence
   files). Injection strings are synthetic fixtures.
7. Trust. The dataset is trusted only as test data. No dataset field can define
   or alter evaluator semantics, thresholds, regression policy, criticality,
   budgets, authorization, evidence classes or verdicts; such fields do not exist
   in the schema and are refused if present.

## Evaluation Engine / Result Contract

Results are immutable, typed, primitive-only application records, comparable
across runs and serializable canonically. Vendor SDK types never appear in them.

1. Run identity: `run_id` is a UUIDv5 under a fixed Module 7 namespace over the
   canonical tuple (`dataset_id`, `dataset_version`, `dataset_digest`,
   `evaluator_suite_version`, `threshold_policy_version`, `target_id`,
   `target_version`, `run_ordinal`). `run_ordinal` is a trusted caller-supplied
   nonnegative integer (default 0) so identical deterministic inputs give
   identical IDs and outputs; a live run supplies a fresh ordinal or nonce and
   records it.
2. Scenario identity: `scenario_id`, `category`, `scenario_evidence`.
3. Per-scenario correlation: `workflow_id` and `trace_id` are UUIDv5 over
   (`run_id`, `scenario_id`) and are the `WorkflowIdentity` used by the scenario
   runner, so every Story 3 recovery observation and Story 4 record for that
   scenario carries them. `action_id` is the Story 3 idempotency key used.
4. Per-evaluator result (`ScenarioEvaluation`): `evaluation_id` (UUIDv5 over
   `run_id`, `scenario_id`, `evaluator_id`, `evaluator_version`); `evaluator_id`
   and `evaluator_version`; `metric` (fixed per evaluator); `score` (finite, in
   [0, 1]); `threshold` (from the application threshold policy); `passed`
   (computed by the engine from score and threshold, never by the evaluator
   alone); `status` (`evaluated`, `evaluator_error`, `malformed_result`,
   `not_run`); `critical` (from policy); `evidence_class`; `scenario_evidence`;
   the correlation identifiers above; and a bounded `observed` fact projection
   (fixed-vocabulary primitives only). It projects losslessly onto the accepted
   `domain.EvaluationResult` (`evaluator`, `metric`, `score`, `passed`,
   `evidence_class`), which remains unchanged.
5. Run result: run identity fields, ordered scenario evaluations, aggregates,
   threshold outcomes, `completeness` (`complete` or `incomplete` with missing and
   errored scenario IDs), `verdict` (`pass` or `fail`), bounded cost/usage
   accounting (zero and `basis=none` in deterministic mode), and
   `evidence_class`. Vendor identifiers appear only in a separate export record
   (LangSmith Adapter Boundary), never inside these results.
6. Evidence class of application results (class A, below) is always
   `deterministic_fixture`; it is never upgraded by vendor confirmation, a live
   run, configuration or caller assertion.
7. The engine runs scenarios sequentially in canonical order (concurrency 1),
   enforces a per-scenario timeout and a run deadline, catches failures only at
   the evaluator and target boundaries, and records fixed safe status codes; no
   exception text, traceback, raw input or raw output enters any result.
8. Evaluation target. The system under evaluation is an application-owned
   `EvaluationTarget` protocol (`target_id`, `target_version`, async
   `run(scenario) -> ObservedFacts`). The reference target composes the real
   accepted Story 2 authorization/safety pipeline, the real Story 3
   `ReliabilityController` with deterministic scripted `Target` adapters, an
   injected deterministic clock and sleeper, and a real Story 4
   `TelemetryPipeline` with a capturing fake sink. `ObservedFacts` are derived from
   application records (`RecoveryResult` classification, attempts, fallbacks,
   `replayed`, budget state, decisions, side-effect counters, captured telemetry)
   and contain no timing values, so they are deterministic.
9. Demo variants. A deliberately degraded target variant used to demonstrate the
   improvement loop is a test/demo boundary: constructible only by explicit
   constructor argument, never selectable from environment variables, settings or
   dataset content, and recorded with its own `target_id`/`target_version`.

## Deterministic Evaluators

Evaluators are pure, synchronous, deterministic functions of (scenario
specification, expected facts, observed facts) with a fixed `evaluator_id`,
integer `evaluator_version` and fixed metric. They perform no I/O, read no
environment, call no model or vendor, and return a typed result the engine
validates. `evaluator_suite_version` identifies the complete set; any evaluator
change requires a version change. The minimum suite, each binary (1.0 or 0.0)
because Module 7 behavior under fixtures is exact:

| Evaluator | Metric | Meaning |
| --- | --- | --- |
| `outcome.classification_exact` | `classification_match` | Observed outcome classification equals the expected Story 2/3 code |
| `reliability.attempt_accounting` | `attempts_match` | Observed attempts and fallbacks equal expected values and do not exceed the scenario policy bounds |
| `idempotency.effect_count` | `effect_count_match` | Observed side-effect invocation count equals the expected count (no duplicate effect on replay) |
| `authority.no_unauthorized_effect` | `authority_preserved` | Denied or injected scenarios produce zero effects and the expected deny decisions; untrusted content never produced an allow |
| `cost.budget_respected` | `budget_respected` | Observed cost used never exceeds the limit and the budget outcome equals the expected outcome |
| `redaction.canary_absent` | `canary_absent` | No scenario canary appears in any captured Story 4 local or exported record or in any evaluation result |

Implementation may add evaluators only with clear Module 7 meaning, a new suite
version and tests; no ML-style or model-graded metric is added for
sophistication. Latency is not a deterministic regression metric.

Criticality and thresholds are application policy, not evaluator output (see
Regression Contract). An evaluator returning a non-finite, out-of-range,
wrongly typed or wrongly labeled result is `malformed_result`; an evaluator that
raises is `evaluator_error`; both score 0.0, count as failures and make the
scenario fail.

## Regression Contract

1. Threshold policy. A committed, typed, versioned `threshold_policy_version`
   defines per-evaluator-metric scenario thresholds, per-category aggregate
   pass-rate thresholds and criticality. Thresholds are exact rationals (for
   example `fractions.Fraction`), and comparisons use integer arithmetic
   (`passed_count * denominator >= numerator * total`) so boundaries are exact.
   The committed defaults are: every scenario metric threshold 1; every category
   aggregate threshold 1; categories `authorization`, `safety_injection` and
   `redaction` critical. Changing any threshold or criticality requires a policy
   version change through normal engineering review. No provider output,
   dataset field, evaluator output, environment variable or evaluation result
   can alter the policy.
2. Baseline representation. A committed baseline file per dataset version holds:
   `baseline_schema_version`, `dataset_id`, `dataset_version`, `dataset_digest`,
   `evaluator_suite_version`, per-evaluator versions, `threshold_policy_version`,
   `target_id`, `target_version`, the per-(`scenario_id`, `evaluator_id`,
   `metric`) scores and pass outcomes, and a `baseline_digest` over its canonical
   content pinned in application code. Only a `complete` run with verdict `pass`
   may become a baseline, and only through a human commit after review; the
   system may write a candidate baseline artifact to a caller-supplied path but
   never writes into the repository.
3. Compatibility. A comparison is valid only when dataset ID, version and digest,
   evaluator suite and per-evaluator versions, threshold policy version and
   baseline schema version all match and the baseline digest verifies. Any
   mismatch yields `incompatible_baseline` with the differing field names (not
   values); no per-metric comparison is produced and no pass verdict is possible.
   Evaluator-version or dataset-version changes therefore require a new reviewed
   baseline rather than silently producing valid-looking comparisons. A target
   identity difference is permitted (that is the comparison) and is recorded.
4. Comparison semantics, per (`scenario_id`, `evaluator_id`, `metric`):
   `regressed` when current score is lower than baseline score by more than the
   per-metric tolerance (committed tolerance 0 for binary metrics) or a baseline
   pass became a fail; `improved` when higher; `unchanged` otherwise. A scenario
   or metric present in the baseline but absent or not evaluated in the current
   run is `missing` and is a regression. A scenario or metric present in the
   current run but absent from a compatible baseline cannot occur without a
   dataset or suite version change and is refused as `incompatible_baseline`.
5. Reporting. Every regression identifies `scenario_id`, `category`,
   `evaluator_id`, `evaluator_version`, `metric`, baseline score, current score
   and threshold. The regression report is deterministic, canonically ordered and
   digest-identified. Any regression, any `missing`, or any incompatibility makes
   the regression outcome `fail`.
6. Independence. Regression decisions are computed entirely locally before any
   export and never depend on, wait for or change because of a LangSmith
   response.

## Benchmark Contract

1. Execution: run the evaluation engine over the complete versioned dataset (or
   an explicitly declared subset for live verification, recorded as a subset)
   with the selected target, in canonical `scenario_id` order, concurrency 1,
   within the per-scenario timeout and run deadline (Bounds).
2. Per-scenario results: every scenario evaluation is reported individually.
   Failing, errored, malformed, timed-out and not-run scenarios are always listed
   with scenario ID, category, evaluator, metric and status.
3. Aggregation: integer counts per evaluator metric and per category
   (`evaluated`, `passed`, `failed`, `errored`), with pass rates shown as exact
   fractions; an overall summary is provided only alongside the per-scenario
   list. Aggregates never mask a failure: the run verdict is `pass` only if the
   run is `complete`, every scenario metric meets its threshold, every critical
   category passes in full, every category aggregate meets its threshold, and
   (when a baseline is supplied) the regression outcome is `pass`.
4. Reproducibility: the deterministic benchmark report is serialized canonically
   (UTF-8 JSON, sorted keys, `allow_nan=False`, no wall-clock fields inside the
   digested content) and identified by a SHA-256 `report_digest`. Two runs with
   identical inputs produce byte-identical reports and digests.
5. Evidence: deterministic benchmark reports are `deterministic_fixture`;
   scenarios with injected failures keep `scenario_evidence=simulated_failure`.
   Evidence files produced by tests or reviewers are written under parent
   TECHADEMY/EVIDENCE, never inside the repository.
6. Failure semantics: see Failure Isolation; an incomplete benchmark never
   reports `pass`, never becomes a baseline and never supports an improvement
   claim.

## Continuous Improvement Loop

The loop is human-controlled; the evaluation system is evidence-producing only.

1. Benchmark the current target against the compatible baseline.
2. Identify each failed or regressed scenario and metric from the report.
3. Produce an `ImprovementProposal`: an immutable, non-executable record listing
   the affected scenario, category, evaluator, metric, expected versus observed
   fixed-vocabulary facts and the owning application area (from a fixed mapping,
   for example category `reliability` maps to the Story 3 controller policy). It
   contains no code, patch, prompt, policy text, threshold or expected-label
   change and is never applied by the system.
4. A human makes any change through normal engineering workflow outside the
   evaluator's authority.
5. Rerun the same compatible benchmark (same dataset version and digest, suite
   and evaluator versions, threshold policy version).
6. Produce an `ImprovementCycle` record: before and after run IDs and report
   digests, compatibility result, per-metric deltas (`improved`, `regressed`,
   `unchanged`), any new regressions, and `decision=pending_human_review`. The
   system can never set an accepted state; acceptance happens only through normal
   engineering authority (review and controlled commit).
7. If the before and after runs are incompatible or either is incomplete, the
   cycle reports `not_comparable` and supports no improvement claim.

The evaluation system never modifies production code, prompts, policies,
authorization, thresholds, criticality, benchmark expected answers, baselines in
the repository, or tests, and never weakens tests or thresholds as a repair
strategy. Deterministic demonstration uses the confined degraded demo target as
"before" and the reference target as "after" over the same dataset, producing
`deterministic_fixture` improvement evidence. That demonstrates the loop
mechanics; it does not claim a real production improvement.

## LangSmith Adapter Boundary

LangSmith receives only already-decided, minimized application evaluation
evidence. The only data path is:

completed run result plus regression and benchmark reports (class A) ->
application-owned, SDK-free `LangSmithExportPlan` built from primitives ->
`LangSmithTransport` -> LangSmith SDK.

1. The adapter's only data ingress is the immutable export plan built by an
   application mapping function from typed Story 6 results. It exposes no method
   accepting raw strings, arbitrary mappings, scenario specifications, canaries,
   exceptions, `Observation`, `WorkflowState`, policy objects or SDK objects.
2. `LangSmithTransport` is a narrow protocol (submit plan, bounded readback,
   bounded close, outcome status). Two implementations are required: an
   SDK-backed transport (the only SDK user) and a deterministic fake for tests.
   The SDK is imported lazily: importing the package or the adapter module
   creates no client, thread, session, OpenTelemetry provider or network
   activity.
3. Use only documented public `langsmith.Client` methods for datasets, examples,
   projects (experiments), runs, feedback and readback (for example
   `read_dataset`/`has_dataset`/`create_dataset`, `create_examples`,
   `create_project` with `reference_dataset_id`, `create_run`/`update_run` with
   `reference_example_id`, `create_feedback`, `list_examples`, `list_feedback`,
   `read_run`). Do not use `evaluate`/`aevaluate` (hidden thread pools, target
   execution and evaluator tracing), `@traceable`, `wrap_*` wrappers, framework
   callbacks, LangChain tracers, the prompt hub, sandbox or any private API.
   Results are computed locally first; LangSmith never executes the target or
   the evaluators.
4. Client construction uses only validated Story 6 settings passed explicitly:
   explicit `api_url` and `api_key`; `auto_batch_tracing=False` (no background
   tracing thread); `tracing_mode="langsmith"` and OpenTelemetry disabled (no
   global tracer-provider read or replacement); `disable_prompt_cache=True` (no
   prompt-cache worker, the Story 5 B-3 lesson); `omit_traced_runtime_info=True`;
   a finite `timeout_ms`; and an adapter-owned `requests.Session` with
   `trust_env=False` (no ambient proxy or netrc credentials), redirects disabled,
   and an adapter-owned zero-retry HTTP adapter mounted for exactly the configured
   origin that refuses any request whose scheme, host or port differ. The SDK's
   own retry behavior must therefore never produce a second HTTP attempt; any
   SDK-level per-call retry parameter (for example `create_feedback`
   `stop_after_attempt`) is set to a single attempt.
5. Ambient environment: no `LANGSMITH_*` or `LANGCHAIN_*` variable may activate,
   configure, redirect, replicate (for example `LANGSMITH_RUNS_ENDPOINTS`) or
   enable tracing for this adapter. The live branch refuses to start, failing
   closed with variable names only, when any `LANGSMITH_*` or `LANGCHAIN_*`
   variable is present in the process environment.
6. SDK construction or behavior that would require a global client, global
   tracing context, global OpenTelemetry provider, background worker, unbounded
   flush/close, or uncounted network requests is a dependency/isolation conflict:
   stop and escalate rather than weakening this boundary.

### Exported representation (exact allowlist)

| LangSmith object | Application content |
| --- | --- |
| Dataset | Name `{prefix}-{dataset_id}-v{dataset_version}`; fixed description; metadata: `dataset_id`, `dataset_version`, `dataset_digest`, `schema_version`. Created only if absent; an existing dataset whose metadata digest differs is refused (never overwritten or deleted) |
| Example (one per exported scenario) | ID: UUIDv5 over (`dataset_digest`, `scenario_id`). Inputs: `scenario_id`, `category`, `title`, `scenario_evidence`, `input_digest` (SHA-256 of the scenario specification). Outputs (reference): the typed expected facts. Metadata: `dataset_version`, `scenario_id` |
| Experiment (project) | Name `{prefix}-run-{run_id}`; `reference_dataset_id`; metadata: run identity fields, `report_digest`, `verdict`, `completeness`, regression outcome and counts, `local_evidence_class=deterministic_fixture` |
| Run (one per exported scenario) | ID: UUIDv5 over (`run_id`, `scenario_id`, `langsmith-run`); fixed name `module7.evaluation.scenario`; `reference_example_id`; inputs as the example; outputs: the bounded `observed` fixed-vocabulary facts; metadata: `run_id`, `scenario_id`, `workflow_id`, `trace_id`, `action_id`, every `evaluation_id` for the scenario |
| Feedback (one per scenario evaluation) | ID: the `evaluation_id`; key `{evaluator_id}.{metric}`; score: the application score; no free-text comment; source info: `evaluation_id`, `evaluator_version`, `threshold`, `passed`, `critical`, `status`, `origin=application_deterministic`, `local_evidence_class=deterministic_fixture` |

`prefix` is a validated configuration value (for example `module7`, pattern
`^[a-z0-9-]{1,32}$`). Nothing else is sent: no raw scenario specification, no
untrusted input text, no canary, no exception text, no operation name, no Story 3
output, no telemetry record, no credential and no environment information.
Repeated export of the same `run_id` from the same process is refused and returns
the recorded outcome without new requests.

Regression comparison in LangSmith is a vendor view: exporting a baseline-target
run and a candidate-target run over the same dataset as two experiments lets the
LangSmith comparison view display them. That view is class B evidence only; the
application regression report remains the decision of record.

Selected tracing: the per-scenario runs above are the selected traces that
demonstrate meaningful integration. Story 6 does not attach a LangSmith sink to
the Story 4 operational telemetry pipeline; Langfuse remains the primary
operational tracing integration (ADR-007-002).

## Trust and Authority

Three classes of evaluation evidence are distinguished and never merged:

- A. Application-owned deterministic evaluation result: computed locally by the
  engine, evaluators and threshold policy; the only basis for pass/fail,
  regression, benchmark verdicts and quality-gate decisions; always
  `deterministic_fixture`.
- B. Vendor-observed/stored representation: what LangSmith stored and returned
  for exported A results (IDs, stored feedback, experiment views, comparison
  views); recorded only in a separate `LangSmithExportRecord`; may at most
  confirm that the export matched A; `mocked_provider_contract` from the fake or
  in-process seam, `live_vendor` only from confirmed live readback on a
  non-loopback HTTPS LangSmith endpoint (see Evidence Modes).
- C. Optional live/model-backed evaluation result: produced by a model-backed
  evaluator; `live_model` only; not implemented by Story 6 (see Live /
  Model-Backed Evaluation).

B and C are never silently upgraded into A, A is never relabeled live, and a B
mismatch never changes A; it makes the export `unconfirmed`.

Everything returned by LangSmith or the SDK (return values, IDs, scores, labels,
comments, metadata, errors, callbacks, logs, readback content) is untrusted
external content. It cannot grant authority, alter authorization, safety,
retry/fallback/timeout/idempotency behavior, budgets, thresholds, criticality,
baselines, regression outcomes, release decisions or evidence classes, become
instructions, or trigger code/policy mutation. Readback is parsed strictly,
bounded and only compared for equality against values the application already
holds. No evaluation result (A, B or C) directly controls privileged behavior:
results feed reports, tests and human review only. Story 2 authorization,
Guardrails safety-only validation, non-authoritative moderation, injection
containment and fail-closed behavior are unchanged.

## Redaction / Data Minimization

1. Minimize before mapping: the export plan is built only from the allowlisted
   fixed-vocabulary fields above; unknown fields cannot be represented.
2. LangSmith is never trusted to sanitize. SDK `hide_inputs`/`hide_outputs`/
   `hide_metadata`/`anonymizer` hooks may be used only as an additional layer.
3. Credentials, API keys (including the LangSmith key), authorization headers,
   bearer/access/refresh tokens, passwords, cookies/session material, connection
   strings, private keys, secret-bearing exceptions, synthetic canaries and raw
   user/model/tool/provider/validator payloads are absent from all
   application-controlled content sent to LangSmith, from adapter status and
   errors, from local results, records and logs, and from evidence artifacts.
4. LangSmith key protocol boundary (same structure as Story 5 Option A): the
   LangSmith API key may cross the vendor boundary only in the vendor-required
   authentication header of requests to the configured origin. It never appears
   in examples, runs, feedback, metadata, names, logs, errors, status, UI output
   or evidence. Workspace identifiers, if configured, are non-secret routing
   values sent only where the SDK requires them. This creates no alternate path
   for any other credential or content.
5. Errors raised across the adapter boundary use fixed messages with no
   `__cause__`/`__context__` carrying secret-bearing text; SDK debug logging stays
   off. Because Python logger filters on an ancestor logger do not run for
   records propagated from descendant loggers to that ancestor's handlers,
   attaching a filter to the `langsmith` parent logger does not sanitize
   records emitted by `langsmith.client` or other SDK descendant loggers.
   Implementation must therefore attach sanitizing handlers or filters
   directly to the actual descendant loggers used by the SDK (including at
   minimum `langsmith.client`) and/or use a sanitizing handler at the root
   logger level such that all SDK-originated log records—including ERROR and
   WARNING records with `exc_info` emitted during construction, operation and
   cleanup—are sanitized before any application handler can emit them. The
   sanitization strategy must use fixed/sanitized application-owned error
   messages or must replace exception information with a fixed safe
   representation; it must not rely on parent-logger propagation to apply a
   filter. This containment must not suppress arbitrary application logging,
   must not mutate authorization, evaluation results, thresholds, budgets or
   workflow state, and must be released on close.
6. The accepted conservative `_is_sensitive_key` classifier is not weakened;
   Story 6 claims no universal secret detection.

## Failure Isolation

Deterministic evaluation never depends on LangSmith. LangSmith failure is an
export failure only.

| Failure | Required behavior |
| --- | --- |
| Evaluator exception | `evaluator_error`, score 0, scenario fails, fixed code, no exception text; other evaluators and scenarios still run |
| Malformed evaluator result | `malformed_result` (wrong type, label or metric, missing metric), score 0, scenario fails |
| Non-finite or out-of-range score | `malformed_result`; never coerced or clamped |
| Missing metric | `malformed_result` for that evaluator; in regression, `missing` regression |
| Target exception or timeout | all evaluators for the scenario `not_run`; scenario errored; run `incomplete`; unresolved work stays owned by the accepted Story 3 controller semantics |
| Incompatible or stale baseline | `incompatible_baseline` with field names; no comparison; regression outcome `fail` |
| Corrupted dataset or version | dataset refused before any scenario runs; no partial evaluation; actionable `ContractValidationError` naming the defect class |
| Corrupted baseline | refused as incompatible |
| LangSmith unavailable, auth or config error | export `failed` with fixed reason; deterministic results, verdicts and regression unchanged |
| LangSmith timeout | export `timeout_unresolved`; worker ownership retained (see Bounds); no `confirmed` claim |
| Malformed or untrusted vendor response | ignored except strict comparison; mismatch gives `unconfirmed`; never alters A |
| Live model/provider unavailable | not applicable in Story 6 (no live model evaluator); the port reports `unavailable`, never a score |
| Budget exhaustion | pre-run refusal (`budget_refused`, no request sent) or mid-run stop (`budget_exhausted`, export `partial`/`unconfirmed`) |
| Cancellation | propagated to the caller after recording `interrupted`; run `incomplete`; any in-flight SDK call stays owned and tracked |
| Partial evaluation run | `incomplete` with listed scenario IDs; verdict `fail`; not usable as baseline or improvement evidence |

Claims requiring unavailable evidence fail closed. The adapter never emits into
the telemetry pipeline or `log_event` about its own failures, so there is no
recursive loop.

## Bounds

Frozen authority sets no numeric defaults. Implementation chooses documented
finite defaults within these contract ceilings, validates them and tests each
boundary.

Deterministic engine:

1. Dataset at most 256 scenarios; at most 8 evaluators per scenario; per-scenario
   serialized size at most 16 KiB.
2. Concurrency exactly 1. Per-scenario timeout finite, at most 10 seconds;
   deterministic run deadline finite, at most 120 seconds. Scenario runs use
   injected clocks and sleepers so they do not depend on wall time.
3. Per-run Story 4 telemetry stays within accepted `TelemetryLimits` ceilings; a
   full pipeline is non-fatal and changes no result.

Live LangSmith path:

1. Exported scenarios: an explicitly configured limit, default small, ceiling 64;
   selection is the first N scenarios in canonical order, recorded as a subset.
   No silent truncation of a full-dataset claim.
2. HTTP requests: the budget is enforced on actual HTTP requests counted at the
   adapter-owned HTTP adapter, not on SDK method calls, so SDK-internal requests
   (for example server-info lookups) are counted. Configured maximum, ceiling
   1,024. A pre-run upper-bound plan (setup + per-scenario run/feedback requests
   + bounded readback) must fit before any request is sent.
3. Retries exactly zero at the adapter, session and SDK call levels.
4. Concurrency exactly 1: blocking SDK calls run in one tracked worker operation
   lane off the event loop; conflicting operations are refused.
5. Timeouts: per-request SDK timeout 1-30 seconds; lifecycle (close) wait 0-60
   seconds; readback attempts 1-10 with interval 0-30 seconds; whole live run
   deadline at most 600 seconds.
6. Response size: each response body read is bounded (ceiling 1 MiB); larger
   responses are refused.
7. Model calls: zero in Story 6. Tokens: not applicable in Story 6.
8. Monetary cost: see Cost Governance.
9. Timeout and cancellation ownership: a timed-out or cancelled SDK call is never
   forcibly abandoned or counted as complete. The worker remains registered; the
   transport reports busy and refuses new operations; close reports
   `close_busy` while it is unresolved; eventual completion releases ownership
   without upgrading the run outcome. The run is never reported `confirmed`
   after a timeout of a required operation.
10. Close is explicit, idempotent and bounded, closes the owned session and SDK
    client through public APIs, leaves no adapter-started thread, and does not
    rely on interpreter-exit hooks (the SDK's own registered exit handler must be
    proven to perform no network work after close).

## Configuration / Secrets

LangSmith settings are a new typed, frozen, validated settings model with a
`MODULE7_LANGSMITH_` environment prefix, `env_file=None`, `extra="ignore"` and
`hide_input_in_errors=True`, leaving the accepted `RuntimeSettings` schema
unchanged. Fields: explicit enablement flag (default false); API key as
`SecretStr` with `repr=False`; explicit endpoint URL (no userinfo, query,
fragment, whitespace or control characters; errors never echo it; the live
verification path additionally requires HTTPS with a non-loopback host as
specified under Evidence Modes — loopback or HTTP endpoints configured here
are capped at `mocked_provider_contract` and cannot yield `live_vendor`);
optional non-secret workspace ID (UUID); export name prefix; and every finite
bound above, including request budget, reservation per request and run cost
limit. No credential, endpoint or workspace default is committed.

Activation gates for any SDK client (all required; credentials alone never
activate):

1. `RuntimeSettings` in live mode with `live_integrations_enabled` (which, under
   the unchanged Story 1 invariant, also requires a non-blank
   `provider_api_key`, although Story 6 makes no model call);
2. LangSmith enablement flag true;
3. API key and endpoint present and non-blank; bounds valid; reservation and cost
   limit configured (unknown cost exposure is invalid);
4. an explicit opt-in argument to the live verification entry point (the live
   test passes it only when `MODULE7_LANGSMITH_LIVE_VERIFICATION=1`);
5. no ambient `LANGSMITH_*`/`LANGCHAIN_*` variable present;
6. the pre-run budget plan fits.

Enabled but incomplete or invalid configuration fails closed for LangSmith with
an actionable `ConfigurationError` naming fields, not values. Missing LangSmith
credentials never prevent deterministic startup or deterministic evaluation.
Secrets are unwrapped only at SDK client construction and never appear in source,
UI, repr/str, results, records, status, errors, logs or evidence, except the
vendor-required authentication transmission above.

## Cost Governance

1. Deterministic evaluation is the default and performs zero billable or network
   operations; its accounting is reported as zero with `basis=none`.
2. Application-owned budget: a live evaluation run carries a run budget expressed
   with the accepted Story 3 `BudgetState` (cost limit, cost used; used never
   exceeds limit) plus a request-count limit. It follows accepted Story 3
   reservation semantics: a configured finite nonnegative reservation per HTTP
   request is charged before the request is sent, is never refunded (including
   failed, timed-out and refused-by-vendor requests), and a request whose
   reservation would exceed the limit is not sent. A zero reservation is allowed
   only when explicitly configured and is recorded as such.
3. Pre-run check: the worst-case request plan times the reservation, and the
   request count, must fit the limits before the first request; otherwise
   `budget_refused` with no request.
4. Exhaustion mid-run stops further requests, records `budget_exhausted`, marks
   the export partial and unconfirmed, and preserves already-recorded counts.
5. Unknown cost: vendor-reported cost or usage is never read as authoritative;
   if no reservation is configured, live execution is refused rather than
   treating cost as zero.
6. Replay and rerun: each live run has its own run budget and records reserved
   USD, requests sent and requests refused with `basis=configured_reservation`.
   Re-exporting the same `run_id` in-process is refused without new requests, so
   replay is not double-charged. A rerun with a new run ordinal is a new,
   separately budgeted run. Deterministic replay consumes nothing.
7. Reuse of Story 3: model-backed or other billable model execution (not in
   Story 6) must use the accepted Story 3 `ReliabilityController` reservation and
   budget authority rather than a competing ledger. Vendor export is an
   observation path like Story 5 and does not route through the controller,
   whose authorization/safety admission and deterministic-or-simulated evidence
   precondition belong to effectful tool actions; it reuses Story 3's budget type
   and never-refund reservation semantics instead.
8. Vendor-reported cost, usage and dashboard totals are observational and never
   accounting truth.

## Evidence Modes

Exact Story 6 assignment: **deterministic_fixture by default; live_vendor and
live_model only when separately verified**. Evidence taxonomy is the frozen
five-class model; no new class is introduced.

- `deterministic_fixture`: dataset validation, evaluator, engine, regression,
  benchmark and improvement-cycle results (class A), always.
- `simulated_failure`: retained as `scenario_evidence` for scenarios with
  injected failures; never relabeled.
- `mocked_provider_contract`: the LangSmith export plan, fake-transport
  submissions and readbacks, and the real SDK-backed transport driven through an
  in-process seam (class B under test). This is the ceiling for every ordinary
  and injected path regardless of object type, class identity, factory, flags,
  SDK return values or replies.
- `live_vendor`: only from the separate, non-injectable live verification branch
  on a non-loopback HTTPS LangSmith endpoint (class B confirmed), defined below.
- `live_model`: none in Story 6.

In-process seam: the real SDK-backed transport must be exercised deterministically
by mounting a module-controlled test HTTP adapter for a reserved non-routable test
origin on the adapter-owned session (or an equivalent documented in-process seam),
inspecting complete serialized requests. If the SDK cannot be driven this way
without network access, record that limitation; the SDK-backed transport is then
exercised only by the live check.

Live verification (in scope to implement; running it is not required for Story 6
implementation acceptance):

1. Opt-in only, through all activation gates, skipped and visibly reported as
   skipped otherwise, marked with the registered `live_vendor` marker, excluded
   from ordinary deterministic CI, and run only after the human authorizes writes
   to an external LangSmith workspace and supplies credentials externally.
2. The live branch constructs its own settings-validated session, HTTP adapter
   and SDK client internally; it accepts no caller-supplied transport, session,
   adapter, client or factory.
3. It runs the deterministic benchmark locally first, then exports the declared
   subset, then performs bounded readback of the exported examples and feedback.
4. `live_vendor` requires all of: submission responses for each required request
   completed by the adapter-owned HTTP adapter against the configured origin;
   subsequent readback, through the same owned path, returning examples and
   feedback whose IDs, keys, scores and `evaluation_id` metadata equal the local
   A values for every exported scenario evaluation; and successful required
   cleanup. Receipts are recorded only inside the owned path after completed I/O;
   object identity, SDK types, mutable flags, caller assertions, mocked or fake
   responses, fake transports, unrelated local sockets and vendor-returned labels
   can never contribute.
5. Evidence (run ID, dataset version and digest, report digest, exported subset,
   counts, request and reservation accounting, SDK version, endpoint host class,
   timestamps) is written without credentials under parent TECHADEMY/EVIDENCE,
   outside the repository. Vendor data is not deleted after verification.
6. Endpoint qualification (non-loopback HTTPS required for `live_vendor`):
   loopback and local-server endpoints are never sufficient for `live_vendor`,
   regardless of socket type, response matching or readback success.
   `live_vendor` requires all of: the configured endpoint must resolve to a
   non-loopback address (no IPv4 127.0.0.0/8, no IPv6 ::1, no `localhost`
   hostname literal, no other loopback alias); the scheme must be HTTPS and
   normal certificate/hostname validation must succeed; the owned HTTP adapter
   must confirm the request was dispatched to the intended non-loopback
   origin; and the owned readback must return results that the application
   correlates against its own previously submitted request/response I/O.
   Redirects or proxies that would silently redirect the endpoint to a
   loopback destination must be detected and refused, not silently accepted.
   Local servers, fake servers, local fixtures, mocked transports and
   loopback-endpoint paths are capped at `mocked_provider_contract`; a
   successful socket connection, matching readback IDs, real SDK objects or
   compatible local responses cannot upgrade that ceiling. Caller-supplied or
   vendor-returned evidence labels and flags cannot upgrade evidence class.
   If a self-hosted loopback instance is ever needed as `live_vendor`, that
   is a separate explicit human trust decision made before any such label is
   minted, not a retroactive acknowledgement. Offline tests validate control
   flow and negative provenance; they do not cryptographically prove remote
   organization identity, and this is normal authenticated HTTPS provenance
   assurance, not an offline cryptographic proof of the remote organization.

Without a confirmed live run, no claim may be made that LangSmith ingested,
stored, evaluated, compared or displayed Module 7 evaluation data.

## Story 4/5 Composition

1. Story 4: the reference target already emits correlated Story 3 recovery
   observations through a real `TelemetryPipeline` under the per-scenario
   `WorkflowIdentity`. The engine may additionally emit one Story 4 `Observation`
   per scenario evaluation with `event=Event.EVALUATION`,
   `component=Component.EVALUATION`, `evaluation_id` set to the
   `ScenarioEvaluation.evaluation_id`, the scenario `workflow_id`/`trace_id`, a
   deterministic `action_id`, a status code describing evaluation execution
   (`succeeded` when the evaluator ran, `malformed_result` or `failed`
   otherwise; never the pass/fail verdict), `evidence_class=deterministic_fixture`
   and `source_evidence` equal to `scenario_evidence`. Scores are not smuggled
   into generic `details`. Pipeline delivery outcomes are non-authoritative and
   change no evaluation result.
2. Story 5: if a caller attaches the accepted `LangfuseSink` as that pipeline's
   exporter, those observations reach Langfuse through the accepted Story 5
   adapter unchanged, carrying `evaluation_id` as the join key in metadata. The
   Story 6 record, the Story 4 local record, the Langfuse observation metadata and
   the LangSmith feedback ID/source info all carry the same `evaluation_id`, and
   the LangSmith run metadata carries the same `trace_id`, so evaluation,
   operational trace and vendor views join without either vendor being
   authoritative.
3. Accepted Story 4 refuses live evidence labels and Story 5 refuses non-mocked
   labels at their boundaries; Story 6 therefore never emits live labels into the
   telemetry path. Live vendor evidence lives only in the Story 6
   `LangSmithExportRecord` and the external evidence file.
4. No Story 4 or Story 5 change is required or made. Native Langfuse score export
   (the architecture's "selected evaluation scores") is not implemented by Story 6
   because it would require an additive change to the accepted Story 5 adapter
   and is not needed by any Story 6 assigned requirement; it remains open for
   Story 10 reconciliation or a separately approved additive change.

## Live / Model-Backed Evaluation

The bounded optional live evaluation path delivered by Story 6 is the live
LangSmith evaluation-evidence path above (live_vendor). A model-backed evaluator
is defined only as an application-owned port (protocol) with a deterministic fake
for tests: it receives only minimized, contained content, returns an untrusted
typed result validated by the engine, is labeled class C, is never critical,
never contributes to a pass/fail verdict, regression decision or baseline, and
would require Story 3 controller reservation and budget authority.

No concrete live model provider, model client or model dependency is added.
Enabling one requires decisions frozen authority has not made: selecting a model
provider (REQUIREMENTS.md leaves it unselected; Helicone gateway is Story 7) and
reconciling the accepted Story 3 precondition that the controller only executes
deterministic or simulated evidence states. Both require human approval; live
model evaluation and `live_model` evidence remain open.

## Dependency Contract

1. Declare `langsmith>=0.14.8,<0.15` as a direct runtime dependency with no
   extras. It is already resolved at 0.14.8 (sdist and wheel hashes already in
   `uv.lock`, registry `https://pypi.org/simple`) as a transitive dependency of
   `langchain-core` 1.6.10, whose own constraint is `langsmith<1.0.0,>=0.3.45`.
   Declaring it adds only the root dependency/requirement entries to `uv.lock`;
   no resolved package, version, artifact hash or registry source changes and
   nothing is upgraded.
2. Research conclusions recorded at authoring (2026-10-19): installed metadata
   for 0.14.8 declares `Requires-Python >=3.10` (Module 7 runs CPython 3.12.14);
   the PyPI JSON API lists 0.14.11 as latest (2026-10-16), 0.14.8 uploaded
   2026-10-13, not yanked, with an empty `vulnerabilities` list for 0.14.8. This is
   not a full advisory or transitive security certification; implementation must
   recheck published advisories for the locked version before acceptance.
3. `requests` 2.34.2 is already resolved (via `guardrails-ai`). If the proposed
   `requests` import evolution is approved, declare it explicitly with a
   constraint satisfied by the locked version (for example `requests>=2.32,<3`),
   again changing only root entries. `urllib3` is not imported.
4. No LangChain, OpenTelemetry, pytest, vcr, sandbox or other extras; no model
   SDK. The accepted Guardrails (`>=0.11,<0.12,!=0.10.1`), Langfuse
   (`>=4.17,<5`), HTTPX (`>=0.28,<1`), Pydantic and OpenTelemetry resolutions are
   unchanged, registry-only lock sources are kept, and `guardrails-ai==0.10.1`
   stays excluded.
5. If declaring the dependency requires any resolution change that affects
   accepted Stories 1-5, stop and escalate. Nothing is installed and the lockfile
   is not changed by contract authoring.

## Required Tests

Use observable results, reports, digests, fake-transport captures, serialized
requests, status values, thread observations and invocation/effect counters.
Source-string or constant-existence assertions are insufficient where behavioral
testing is feasible.

1. Versioned dataset validation: valid dataset loads with pinned digest;
   tampered content, wrong digest, unknown version/schema, duplicate IDs, unknown
   fields/vocabulary, oversize and non-finite values are refused before any
   scenario runs; canonical order enforced; policy-shaped fields refused.
2. Deterministic evaluator behavior: each evaluator against controlled observed
   facts for pass and fail; purity (no I/O, environment or clock use);
   malformed, non-finite, out-of-range and raising evaluators handled as defined.
3. Stable evaluation IDs and correlation: identical inputs yield identical
   `run_id`, `evaluation_id`, `workflow_id` and `trace_id`; any identity input
   change changes them; distinct scenarios and evaluators never collide.
4. Automated evaluation execution: the reference target runs the full dataset
   through real Story 2-4 components and the committed policy yields a complete
   passing run matching the committed baseline.
5. Regression comparison: injected score decreases, pass-to-fail and missing
   scenario/metric produce regressions naming scenario, category, evaluator,
   version, metric, baseline and current score and threshold; improvements and
   unchanged metrics are reported.
6. Incompatible/stale baseline rejection: each identity field mismatch
   (dataset version or digest, suite or evaluator version, policy version, schema
   version, baseline digest) yields `incompatible_baseline` with no comparison;
   a current-only scenario is refused.
7. Benchmark reproducibility: two runs produce byte-identical canonical reports
   and identical digests; report contains no wall-clock data in digested content.
8. Threshold boundary behavior: exact rational thresholds at, just below and just
   above the boundary using test-local policy objects (committed policy unchanged);
   critical-category single failure fails the run.
9. Per-scenario failure visibility: a single failing scenario remains listed
   individually and makes the verdict `fail` even when aggregate rates are high.
10. Continuous-improvement before/after comparison: degraded demo target versus
    reference target over the same dataset yields an `ImprovementProposal` for
    the failing scenario/metric and an `ImprovementCycle` with deltas and
    `pending_human_review`; incompatible or incomplete runs yield
    `not_comparable`; the system mutates no code, policy, threshold, expected
    label, baseline file or test (repository files unchanged after the cycle).
11. LangSmith mapping: the export plan contains exactly the allowlisted fields;
    deterministic object IDs; feedback keys, scores and IDs equal local A values;
    the real SDK-backed transport through the in-process seam serializes the
    expected requests to the configured origin only.
12. LangSmith non-authority: authority-shaped, instruction-bearing, score-altering
    and malformed vendor responses and readbacks change no verdict, regression,
    threshold, baseline, budget, authorization, safety or evidence class; a
    mismatch gives `unconfirmed`.
13. Provider failure isolation: fake transport raising, hanging, returning
    malformed data, refusing auth and failing close leaves deterministic results,
    verdicts and regression identical to a run with no exporter; failures are
    recorded locally with fixed reasons and no recursion into telemetry or logs.
14. Redaction/data minimization and SDK log containment: credential families,
    `SecretStr` values, secret-bearing exceptions, canaries and raw scenario text
    never appear in the export plan, serialized SDK requests (outside the
    vendor-required auth header), results, reports, status, errors, captured logs
    or evidence; the LangSmith key appears only in the authentication header.
    Behavioral tests using the real public LangSmith Client SDK failure path must
    additionally prove, at minimum: (a) a synthetic public/API key value is absent
    from all captured application log records; (b) a synthetic secret/auth value
    is absent from all captured application log records; (c) secret-bearing
    exception text is absent from all captured application log records; (d) SDK
    traceback content cannot bypass log sanitization; (e) records emitted by the
    `langsmith.client` descendant logger are covered by the sanitization
    strategy—not only records logged directly to the parent logger; (f)
    application logs and evidence files remain secret-safe after adapter use; (g)
    the sanitization containment does not mutate authorization, evaluation results,
    thresholds, budgets or workflow state. Tests must use real SDK error/exception
    injection (for example a real Client construction with a fake origin that
    raises on connection) and must not suppress arbitrary application logging or
    pass by silencing the application logger.
15. Prompt-injection/authority-shaped content: injection and evaluation-policy
    injection scenarios are evaluated normally; policy, thresholds, expected labels
    and verdict logic are unchanged; untrusted text never produces an allow.
16. Deterministic credential-free/no-network path: the complete deterministic
    evaluation, regression, benchmark and improvement suite runs with a socket
    guard, no credentials and ambient `LANGSMITH_*`/`LANGCHAIN_*` and
    `MODULE7_LANGSMITH_*` variables present, creating no client, session or thread.
17. Explicit live opt-in: each activation gate missing (mode, live flag, LangSmith
    flag, key, endpoint, reservation, opt-in, ambient-variable guard, budget plan)
    constructs nothing and reports a specific skip or refusal; the live test is
    skipped visibly by default.
18. Bounded live/model execution: request budget counted at the owned HTTP
    adapter including SDK-internal requests; zero retries observed for failing
    responses; concurrency 1; subset limit; response size cap; per-request and run
    deadlines; the model-backed evaluator port (fake) never affects A.
19. Timeout/cancellation ownership: never-completing fake SDK calls produce
    `timeout_unresolved`, retained ownership, refused conflicting operations,
    `close_busy`, and eventual release without outcome upgrade; cancelled
    deterministic runs are `incomplete` and propagate cancellation.
20. Cost-budget behavior: pre-run refusal with no request; never-refunded
    reservations including failed and timed-out requests; mid-run exhaustion;
    missing reservation refused; zero reservation only when explicit; repeated
    export of the same run refused without requests; deterministic accounting zero.
21. Evidence classification/provenance: A always `deterministic_fixture`;
    `simulated_failure` scenario evidence preserved; fake, injected, same-type,
    subclassed, wrapped, flag-forged, mocked-success and unrelated-local-socket
    paths capped at `mocked_provider_contract`; `live_vendor` only from the owned
    live branch with matching readback on a qualifying non-loopback HTTPS endpoint;
    unconfirmed live runs make no live claim; no `live_model` anywhere.
    Adversarial/negative behavioral tests must additionally prove: (a) a
    compatible local HTTP server returning fully matching responses never mints
    `live_vendor`; (b) a loopback HTTPS endpoint (unless the frozen architecture
    explicitly establishes otherwise) never mints `live_vendor`; (c) a locally
    connected socket never mints `live_vendor`; (d) a fake or mocked transport
    returning successful responses never mints `live_vendor`; (e) a successful
    local submission plus local readback with matching IDs never mints
    `live_vendor`; (f) a forged evidence flag or label supplied by a caller or
    returned by the vendor never upgrades evidence class; (g) a redirect or proxy
    that would silently redirect to a loopback destination is detected and refused;
    (h) non-loopback HTTPS plus the required owned execution and readback chain is
    necessary for `live_vendor`.
22. Dependency/import confinement: AST tests that only `langsmith_adapter.py`
    imports `langsmith` (and `requests`, if approved); evaluation modules import no
    vendor SDK; the package `__init__` does not import the adapter or settings;
    the narrowly amended Story 1 forbidden-import test still forbids every other
    root everywhere; declared constraint and locked version agree; registry-only
    sources and the Guardrails exclusion unchanged; no global OpenTelemetry
    provider change and no prompt-cache or tracing thread after construction,
    use and close.
23. Story 4/5 correlation composition: evaluation observations through a real
    pipeline carry `evaluation_id`, workflow and trace IDs and deterministic
    evidence; with the accepted `LangfuseSink` and its fake transport the same
    `evaluation_id` appears in Langfuse metadata; LangSmith run/feedback carry the
    same IDs; pipeline failure changes no evaluation result.
24. Full Stories 1-5 regression, unchanged except the adjudicated Story 1 import
    evolution. No weakening, deletion, skipping or reclassification for green
    status.

## Requirement-to-Acceptance Coverage

| Assigned requirement | Contract behavior and verification | Deterministic closure |
| --- | --- | --- |
| REQ-EVAL-001 | Automated engine over versioned dataset with deterministic evaluators and typed results; tests 1-4, 9 | Yes, deterministic_fixture |
| REQ-EVAL-002 | Versioned baseline, compatibility, exact regression detection naming scenario and metric; tests 5, 6, 8 | Yes, deterministic_fixture |
| REQ-EVAL-003 | Reproducible, digest-identified benchmark with per-scenario results; tests 7-9 | Yes, deterministic_fixture |
| REQ-EVAL-004 | Human-controlled proposal/rerun/compare cycle with no autonomous mutation; test 10 | Loop mechanics yes; no real production improvement claimed |
| REQ-LAB-002 | End-to-end automated pipeline (dataset, target, evaluators, thresholds, regression, benchmark, export); tests 1-10, 16 | Pipeline yes; reviewer presentation remains Story 9 |
| REQ-TOOL-001 | Real LangSmith adapter, minimized mapping, SDK-backed transport through in-process seam; tests 11-14, 21-22 | No: meaningful-use closure needs confirmed live_vendor evidence (live verification) on a non-loopback HTTPS LangSmith endpoint |
| REQ-DEL-002 | Evaluation pipeline component complete and runnable through its public API and tests | Component yes; deliverable runnable/reviewable closure remains Stories 9-10 |
| REQ-COST-003 | Ordinary gate fully deterministic, credential-free, no network, zero billable calls; tests 16, 20 | Yes |
| REQ-COST-004 | Live path separately gated, marked, skipped by default, separately evidenced; tests 17, 21 | Yes |

ADR-007-001 is exercised by deterministic independence from LangSmith (tests 13,
16). ADR-007-002 by non-authority and application-owned decisions (tests 12, 15).
ADR-007-007 by the deterministic engine, stored comparable results and thresholds
and labeled live evidence (tests 1-10, 21). ADR-007-008 by credential-free CI and
opt-in bounded live verification (tests 16-18). ADR-007-012 by the application
budget, reservations and request limits (tests 18, 20).

Story 6 implementation acceptance can prove, without a live run: deterministic
automated evaluation, regression testing, benchmarking and improvement-loop
mechanics over real Module 7 behavior; LangSmith mapping, minimization,
non-authority, failure isolation, bounds, budget behavior and provenance
controls as `mocked_provider_contract`; and deterministic Story 4/5 correlation.
It cannot prove, and must not claim: live LangSmith ingestion, storage or
evaluation; LangSmith dashboard, experiment or comparison-view behavior; live
model quality or any `live_model` result; production deployment; or production
scale.

## Prior Nonblocking Findings / Inherited Limitations

- NB-1 (Story 4 `new_cost_usd` may include starting-state cost): unchanged; Story
  6 evaluation cost accounting does not use `new_cost_usd` and asserts only
  application-observed budget facts.
- NB-3 (no single real-controller case for every Story 3 classification): remains
  open; Story 6 scenarios exercise a reviewed subset of classifications through
  the real controller and do not claim to close NB-3.
- NB-4 (loopback endpoint identity trust): corrected for this surface. Loopback
  and local-server endpoints are capped at `mocked_provider_contract` and can
  never yield `live_vendor` (see Evidence Modes — Endpoint qualification). The
  Story 5 NB-4 analog does not carry over as an open loopback permission here.
- INF (Story 5 evaluation-score deferral): resolved for Story 6 by `evaluation_id`
  composition without score export; native Langfuse score export remains open.
- Inherited ambient-tracing exposure (identified at authoring, not a Story 6
  change): `langchain-core`, pulled in by Guardrails, can trace to LangSmith when
  ambient `LANGSMITH_TRACING`/`LANGCHAIN_TRACING_V2`-style variables and a key are
  present, which would bypass Story 4 redaction outside any Story 6 path. Story 6
  refuses its live branch when such variables are present and never sets them;
  whether earlier stories need a process-level guard is recorded for Story 10
  reconciliation and is not fixed here.
- Inherited constraint: the Story 1 live-mode invariant requires
  `provider_api_key` even though Story 6 makes no model call.
- Inherited constraint: accepted Story 3 executes only deterministic or simulated
  evidence states, blocking a live model-backed evaluator without approval.

## Quality Gates

Implementation acceptance requires the complete Module 7 fail-fast sequence from
the Module 7 directory:

1. `ruff check .`
2. `pytest`
3. `python -m compileall -q src tests`

Stop at the first failure. Safe Ruff fixes only; no unsafe fixes. Preserve
bounded repair; never weaken tests, thresholds, security controls or requirements.
After a repair, rerun the failed gate and then the full sequence. Independent
implementation review is mandatory before acceptance and controlled commit.
Contract authoring runs no implementation gates and proves no implementation
milestone. Temporary engineering evidence belongs under parent
TECHADEMY/EVIDENCE, outside the repository.

## Isolation

Only Module 7 belongs to this slice. No sibling implementation, tests, runtime
state, data or configuration may be copied, imported, modified or depended upon.
Foreign dirty state and unrelated descendant commits are not blockers. Stop for
conflicting concurrent Module 7 changes, history divergence invalidating accepted
lineage, a real dependency/isolation conflict, a genuine frozen-authority
contradiction, or an authority/architecture decision frozen sources have not
made. Preserve frozen requirements, traceability, architecture, ADRs and accepted
Stories 1-5.

## Non-Goals

Helicone gateway observability and any live model gateway (Story 7); the
failure-recovery simulation lab (Story 8); the guided Streamlit console,
evaluation UI and dashboards (Story 9); integrated verification, release live
evidence and release closure (Story 10). Story 6 does not add a model provider,
model client, model-backed evaluator implementation, LLM-as-judge, online
evaluators, annotation queues, prompt management, LangSmith tracing of the
operational telemetry pipeline, native Langfuse score export, OpenTelemetry
instrumentation, distributed or persistent evaluation storage beyond committed
versioned data, vendor data deletion, a CLI, automatic code/policy/threshold
mutation, or any authority or architecture change, and does not redesign
Stories 1-5.

## Definition of Done

- All nine assigned requirements and five assigned ADRs have traceable behavior
  and verification within this slice; REQ-TOOL-001 closure is explicitly open
  unless confirmed `live_vendor` evidence exists on a non-loopback HTTPS
  LangSmith endpoint.
- A versioned, digest-pinned synthetic dataset, deterministic versioned
  evaluators, committed threshold policy, committed compatible baseline,
  regression comparison, reproducible benchmark and human-controlled improvement
  cycle work over real Story 2-4 behavior.
- LangSmith receives only the allowlisted minimized representation of
  already-decided results through the narrow adapter; it remains untrusted and
  non-authoritative; failures are bounded, non-recursive and locally observable.
- Configuration is explicit, secret-safe and inactive by default; ordinary tests
  are credential-free, network-free and non-billable; live verification is
  opt-in, bounded, budgeted and separately evidenced; SDK log containment
  protects against secret leakage from descendant SDK loggers (including
  `langsmith.client`) under all failure paths without suppressing arbitrary
  application logging or mutating evaluation state.
- Story 4/5 composition through `evaluation_id` and trace identity works without
  changing Stories 4-5.
- Accepted Stories 1-5 and frozen authorities remain intact apart from the
  adjudicated Story 1 import evolution; all required tests pass.
- Evidence is `deterministic_fixture` by default, `mocked_provider_contract` for
  vendor-boundary tests, `live_vendor` only from a confirmed, human-authorized
  live run on a non-loopback HTTPS LangSmith endpoint, and no `live_model`.
- Ruff -> full Module 7 pytest -> compileall pass; independent implementation
  review accepts the slice before lifecycle recording and controlled commit.

Story 7 remains blocked until this contract is independently accepted, Story 6
implementation completes, independent implementation acceptance succeeds and
lifecycle recording/controlled commit completes. Authoring this document
implements no Story 6 behavior.
