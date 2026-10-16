# Story 4 implementation boundary

Implementation is ready for independent review, not independently accepted.
Import the API from `reliability_safety_observability.telemetry`. No earlier
source/test interface or frozen authority is changed. Story 5 remains blocked
until independent acceptance and lifecycle recording/controlled commit.

## Neutral model and use

`Observation` is an immutable typed envelope around the unchanged foundation
`TelemetryRecord`. It adds the original UUID action key, event, component,
availability/provenance, recovery facts, and an optional evaluation join UUID.
It holds no issuer, executable policy, permission set or workflow/controller
reference. `from_recovery(result)` projects an accepted Story 3 `RecoveryResult`
without touching execution. Its default evidence is deterministic_fixture with
the original upstream evidence retained separately, including simulated_failure.
Fake neutral exchanges may explicitly use mocked_provider_contract. Live evidence
labels are rejected; credential presence has no effect.

Create observations from application-owned facts, then `await pipeline.emit(obs)`
inside the caller's event loop. `pipeline.records` returns immutable local JSON
records; an optional `NeutralSink.send(record)` receives one minimized JSON string.
No vendor is configured or imported. Sinks are trusted cooperative async adapters:
they must yield, bound I/O and support cancellation. Synchronous/blocking callbacks,
forceful cancellation of remote effects, and automatic live activation are not
supported. Sink replies are discarded, including authority-shaped replies.

Raw operation names, status/error messages and event text are not exported.
Fixed `Event`, `Component` and `Code` labels describe the application operation,
stage and outcome. The application-owned Story 3 classifications
`transient_exhausted`, `terminal_exhausted`, `timeout_exhausted` and
`unknown_exhausted` are preserved verbatim in status/error classification;
they remain distinct from the separate `unknown` outcome for an adapter exception
whose effect cannot be inferred. Unrecognized classification text is minimized
to `unknown`; no raw error text is exported. Action UUIDs retain
the distinction between operations without exporting secret-bearing names.
Workflow and trace UUIDs remain stable through retry/fallback/recovery/replay;
span UUIDs distinguish observations. Attempt history is projected as recorded,
not fabricated as timed per-attempt spans. Replay retains historical usage and
sets new_cost_usd to zero; zero-attempt denials/pending results remain zero.
The optional evaluation UUID joins future records without inventing scores.

## Sensitive-key watchpoint and minimization

Story 1 `logging.py`, including `_is_sensitive_key`, is unchanged. It still redacts
input_tokens, output_tokens, token_count, session_id and authorization_decision.
The new projection maps **typed numeric token counts** to usage.input_units and
usage.output_units, with unit=model_tokens. Typed observed decisions use
permission_outcome and safety_outcome. These are descriptive schema fields, not
aliases for credentials. No arbitrary dictionary is unpacked into this projection.
The projected fields also pass through the unchanged generic redactor, and tests
verify both its broad legacy behavior and useful new logging output.

All new event labels and metadata keys are fixed application vocabulary. Raw
prompts, outputs (even safety-approved), provider errors, exception objects,
policy issuance state and payloads are never projected. Optional metadata uses
`minimize`: every free-text string and unknown key is omitted, sensitive keys and
SecretStr values are redacted, unsupported/non-string keys and objects use the
accepted unsupported marker. Fixed details/nested/items/count/safe/value keys
can retain bounded numeric, boolean and UUID diagnostics. Key length is bounded
before classification. This is deliberate minimization, not universal secret
detection. Exceptions are never rendered via str/repr, chained into observation
errors or sent to a downstream vendor for sanitization.

## Timing and accounting

The foundation duration_ms is finite nonnegative milliseconds. `elapsed_ms`
supports an injected monotonic clock and rejects backward/non-finite intervals.
Recovery elapsed_seconds is converted to whole-execution milliseconds; it does
not change Story 3 timeouts or imply per-attempt/production latency.

CostBasis defaults to unknown: monetary values remain null rather than claiming
the UsageRecord zero defaults are actual pricing. Explicit fixture or trusted
supported_usage provenance exposes supported token and USD values. Independently
known token counts may be exposed with usage_available=True while cost stays null.
Budget limits/used values are observation snapshots. Recovery actual cost,
overage and remaining resources remain distinct from the saturated BudgetState.
Reservations/conservative budget consumption are not called measured provider
invoices. Callers must supply truthful provenance; telemetry cannot establish
unknown pricing. There is no accounting authority or aggregate charging engine
here. Repeated snapshots are not additive accounting entries.

## Bounds and failures

Defaults: 256 observation admissions, 16,384 bytes per JSON record (including
reserved local-status overhead), 128 metadata traversal nodes, depth 6 and
0.1 seconds per cooperative sink call. Configurable hard ceilings are 4,096
events, 65,536 bytes, 1,024 nodes, depth 16 and 5 seconds. Invalid limits are
rejected. History is limited to 1,000 entries; excessive serialized records are
refused. Cyclic/deep/large metadata is truncated without arbitrary iteration or
unsafe fallback. Full pipelines refuse new observations instead of evicting
evidence; create a new pipeline deliberately for a new retention scope.

Each admitted observation has at most one export and one independent local send,
without retries. Concurrent/reentrant emission is refused. A timed-out sink is
cancelled without awaiting cancellation; unresolved work prevents new admission,
so ignoring cancellation cannot accumulate tasks. Late errors are consumed
without retaining their text. Caller cancellation propagates and cancels the sink.
These bounds assume cooperative adapters, as does Story 3's operation boundary.

Export failure returns export_failed and writes correlated minimal local evidence
in pipeline.records, independently of the exporter. Even if the optional local
sink also fails, this bounded in-process evidence survives. No recursive logging
occurs. Local sink failure cannot confer authority or change execution; no durable
delivery guarantee is claimed. Invalid/redaction/serialization failure returns
invalid_observation, exports nothing and consumes an admission slot. Such input
is never sent raw as an error diagnostic. Delivery statuses are observation
results, not authoritative workflow results.

## Verification traceability

`tests/test_telemetry.py` covers the contract's twelve test groups:

| Contract groups | Evidence |
| --- | --- |
| 1, 6 | Fixed structured records, legacy classifier collisions, legitimate typed usage/decisions, nested credential families |
| 2, 5 | Recovery identity/history, zero-attempt outcomes, real timeout/fallback and replay, distinct actions and evaluation join |
| 3, 4 | Controlled timing, invalid/non-finite values, unknown cost versus known counts, genuine fixture zero, budget saturation/actual overage |
| 6, 7 | Unsupported objects/keys, exceptions, cycles, depth/node/byte bounds, redaction failure and forged invalid models |
| 8, 9 | Real controller remains unchanged under untrusted source metadata and sink failure; local failure evidence, timeout, reentrancy, capacity, unresolved sinks |
| 10, 11 | Fake neutral JSON exchanges, ignored malformed/authority replies, no credential activation, no external socket connection, no live labels |
| 12 | Complete unchanged Stories 1-3 suite, including real local Guardrails execution and security/reliability regression |

REQ-OBS-001/002/005 and ADR-007-001/006 reach neutral correlation, logging,
safe debugging, pre-export minimization and independent failure evidence.
REQ-OBS-003 reaches controlled timing. REQ-OBS-004, REQ-COST-002 and ADR-007-012
reach faithful available/unknown usage and budget projection without billable
ordinary tests. REQ-SEC-007/008 reach minimization and non-authoritative isolation.

Implementation evidence is deterministic_fixture and mocked_provider_contract;
observed upstream simulated_failure remains separate. No live telemetry, vendor
SDK integration, dashboard, external trace, provider-backed billing, deployment,
production monitoring or production readiness is claimed. The existing UI/labs,
evaluation, Langfuse, LangSmith, Helicone and release closure remain later scope.

Requirements have local implementation/verification evidence pending independent
review. Product Experience remains a library/reviewer-test surface until Story 9;
Real Functionality is local neutral emission, not vendor integration. Reliability,
Security and Cost are tested within the stated cooperative/in-process limits.
Evidence is local/mocked; Deployment and production-grade module completion remain
unverified later work. Passing gates does not constitute independent acceptance.

## Implementation gate result

On 2026-10-15, using the existing Module 7 Python 3.12.14 environment, the final
ordered sequence passed: `ruff check .`, full `pytest` (277 passed: 48 new Story 4
cases and 229 unchanged earlier cases), and `python -m compileall -q src tests`.
Six upstream Typer/Click deprecation warnings remain non-blocking. Pytest used
the accepted Windows asyncio loopback workaround outside the restricted sandbox;
no external vendor/model operation or credential was required. The initial
sandbox test run was interrupted at the known local socket-pair restriction.
Earlier new-file line-length/test-setup/cancellation-cleanup failures were repaired
before rerunning the complete ordered sequence. Final inspection also added
sink-self-cancellation isolation and safe revalidation without serializer warnings;
the full sequence above includes those fixes. Independent acceptance is pending.

## B-1 bounded repair

The independent implementation review rejected the original implementation for
collapsing four Story 3 exhaustion outcomes to `unknown`. The neutral Code
allowlist now includes those four application-authored outcomes directly, without
changing Story 3 or interpreting provider error text. A five-case real-controller
regression verifies status, error classification and history through projection,
fake export and local records, including the separate exception-driven `unknown`.
On 2026-10-15 the repair passed the full ordered Ruff -> pytest (282 passed,
six upstream deprecation warnings) -> compileall src tests sequence. Evidence
remains deterministic_fixture / mocked_provider_contract; upstream simulation
labels remain separate. Independent re-review is required before acceptance.
NB-1 cost-delta behavior is unchanged and remains open; NB-3's broader all-outcome
test coverage is not implemented by this bounded five-case regression.
