# Module 9 Evidence Policy

## Evidence classes

| Class | Runtime executed | Live provider | What it proves |
|---|---|---|---|
| `design_documentation` | No | No | Architecture, contracts, and plans exist. Design intent only. |
| `automated_test` | Yes | No | Code paths behave as tested, using deterministic inputs. |
| `deterministic_demo` | Yes | No | A reviewer ran the workflow with deterministic adapters and no key. |
| `live_integration` | Yes | Yes | The workflow ran against a real provider with opt-in credentials. |
| `deployment_release` | Yes | No | A packaged, deployed, or released artifact was exercised in its target environment. |

Rules, enforced by `EvidenceRecord` in `contracts/evidence.py`:

- `design_documentation` cannot claim runtime or live execution.
- `automated_test`, `deterministic_demo`, and `deployment_release` require runtime execution.
- Only `live_integration` may record live-provider execution, and it must.
- Deterministic-mode results can never be labeled `live_integration`. Live-mode results can never
  be labeled `deterministic_demo`.

## Deterministic versus live execution

| | Deterministic mode | Live mode |
|---|---|---|
| Default | Yes | No |
| Activation | Always available | `live_opt_in=True` plus a user-supplied credential |
| Network | None | Allowlisted providers only |
| Cost | None | Bounded by `ResourceBudget` |
| Evidence | `automated_test`, `deterministic_demo` | `live_integration` |

## Reviewer-visible results invariant

Every material capability must ultimately show its real output in the Streamlit UI, labeled with
its execution mode and evidence class, next to concise guidance on how to run it and what the
result demonstrates (ADR-009-009). A capability without reviewer-visible evidence is not done.

## Story 9.1 classification

Story 9.1 evidence is **`design_documentation` only**. It is not deterministic runtime evidence,
not automated functional capability evidence, not live integration evidence, and not proof that any
multimodal, voice, streaming, provider, or UI functionality works.

The Story 9.1 automated tests check contract and governance consistency (for example, that a
contract rejects an oversized file). They do not exercise any multimodal capability, so they do
not count as functional capability evidence for any SRC requirement.

## Story 9.2 classification

Story 9.2 evidence is **`automated_test`**: the test suite runs every committed fixture through the
deterministic adapters with sockets blocked and no credentials. `DeterministicRunRecord` can also
emit `deterministic_demo` records for reviewer runs. It rejects every other class, so deterministic
runs can never be labeled `live_integration`.

This evidence proves that the deterministic, no-key path runs reproducibly through the provider
ports. It does not prove vision, document understanding, speech-to-text, or any other SRC
capability: the adapters replay scripted output for committed fixtures and perform no inference.

## Story 9.3 classification

Story 9.3 evidence is **`automated_test`**: the suite runs generated PNG, JPEG, WebP, PDF, Markdown,
and text inputs through validated ingestion and the local vision and document adapters, with
sockets blocked and no credentials. `UnderstandingRecord` can emit `deterministic_demo` records for
reviewer runs and rejects every other class.

Story 9.3 performs local extraction and structural analysis with no model inference. Its records
name their processing kinds (`local_extraction`, `local_structural_analysis`) and reject
`fixture_playback` and `model_inference`. This evidence partially supports SRC-002, SRC-004, and
ENG-006. It is not evidence of model-based vision, semantic document understanding, live
integration, or reviewer-visible results. See [UNDERSTANDING.md](UNDERSTANDING.md).
