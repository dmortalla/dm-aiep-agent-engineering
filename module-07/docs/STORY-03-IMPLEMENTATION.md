# Story 3 implementation boundary

Import the API from `reliability_safety_observability.reliability`. Frozen
authorities and earlier story interfaces remain unchanged.

## Trust and execution boundary

Principal, policy, target bindings, cost bounds and adapter usage/repeat-safety
attestations are trusted application inputs. Never unpack provider/model/request
payloads into these types. Principal is an identity representation, not a grant.
Each target requires its own exact Story 2 issued authorization decision;
forged, copied, mismatched or evicted decisions fail closed. Input and returned
output pass the existing safety pipeline. Safety denial is terminal.

Operations are async callables receiving the original UUID action key and
untrusted content. They must yield, use bounded I/O and support cancellation.
The caller owns the event loop. Blocking Python callbacks and forcibly stopping
remote effects are unsupported. `asyncio.wait` enforces bounded waiting; an
unresolved timeout cancels without awaiting cancellation, retains protection,
and never recovers into another invocation. Late output/errors cannot overwrite
the terminal result. An adapter-resolved timeout may recover only with explicit
timeout policy and a trusted repeat-safety attestation. Controller cancellation
also retains the action's protection.

## Limits and counting

Defaults: three global invocations including initial/retry/fallback calls, two
per target, one fallback, one-second operation timeout, five-second overall
monotonic deadline, constant zero-second backoff, 256 retained actions. Global
attempts are configurable up to 1,000 and capacity up to 4,096. Time units are
seconds; cost units are USD. Invalid/non-finite critical policy is rejected.

Targets are distinct, ordered and visited once; no recursive recovery is used.
Only transient failure recovers by default. Policy can explicitly admit timeout
recovery or terminal operational fallback; unknown/security failures cannot
recover, and terminal operational failures cannot retry. All repeat execution
also requires trusted adapter attestation that no effect occurred or the same
action is deduplicated across every candidate. Provider payloads cannot supply
that promise. Every invocation rechecks current authority and safety, including
after backoff. No wait or candidate transition renews resources.

One action runs per controller. Nested new keys and new work while timeout
cancellation remains unresolved are refused. Pending duplicate keys return
zero-attempt pending evidence. Capacity has no eviction/expiry: all completed,
failed, pending and uncertain entries retain protection; full storage refuses
new keys while retained keys still replay. Recreating a controller is a deliberate
application retention boundary and loses protection. There is no restart,
cross-process, distributed exactly-once or indefinite retention guarantee.

## Identity, accounting and evidence

The UUID key binds a SHA-256 digest of principal, operation, effectful content,
source and target plan. Changed identity with a reused key is refused. Retries
and fallback retain that key. Completed replay rechecks authority and safety,
returns the recorded outcome/identity/usage with `replayed`, and causes no new
invocation, effect or charge. Terminal failures replay rather than renewing
limits. Before-effect failures may retry within their original execution.

Every target requires an explicit finite nonnegative reservation. Zero supports
explicitly free fixtures; unknown exposure must not be represented as zero.
Reservations are consumed before calls and never refunded. Actual supported
usage is accumulated separately; cost above reservation increases consumption.
Actual over-budget usage fails as `budget_exhausted`, with no released output or
further calls. BudgetState remains valid by saturating used cost at its original
limit; separate actual cost and overage fields expose overrun. Unknown or
unfinished usage is conservatively charged at reservation. Late unknown remote
cost cannot be priced locally: adapter exposure bounds are a precondition, not
a billing guarantee. Tokens accumulate as usage evidence, without an invented
token quota; overflow/non-finite accounting fails safely.

RecoveryResult retains foundation workflow fields, decisions, key, terminal
state, attempts/retries/fallbacks, safe classification history, elapsed/remaining
time, remaining attempts, usage/cost and recovery status. Zero-invocation outcomes
have no fabricated ReliabilityResult. Raw operation exceptions are discarded;
request bodies are digested and only safety-approved output is retained. No new
observation hook exists. The existing logging sink isolates exceptions so sink
failure cannot change authorization, safety or core state.

## Verification and remaining scope

`tests/test_reliability.py` covers contract test groups 1–9: classification,
backoff, fallback, enforced and attested timeout, replay/pending/effect counters,
capacity, reservations/overage/accounting, composition/global limits, authority,
safety/moderation/provider failure, untrusted inputs, secret-safe failures and
logging failure. Unchanged Story 1/2 tests supply regression group 10, including
real local Guardrails validation.

Evidence is deterministic_fixture or simulated_failure, selected by trusted
initial state. No credential, billable call or external network is needed.
Windows asyncio initializes a local socket pair; sandbox restrictions can stall
that OS operation before controller execution. Running these deterministic tests
outside that sandbox adds no external-service call.

This library slice awaits independent implementation acceptance. Requirements
and reliability/security/cost behavior have local evidence; product experience,
full module functionality, live integrations and deployment remain later work.
No production or deployment claim is made. Story 4 has not started.
