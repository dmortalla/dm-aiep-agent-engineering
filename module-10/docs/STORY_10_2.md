# Story 10.2 implementation evidence

## Baseline and scope

Starting HEAD: `5b1c6076347cb32751161eba49882da2a279d996`.
Accepted architecture checkpoint:
`d0e42d6f7f3cd978f79e50ef33e5887c43488d52` (`docs: establish module 10 production architecture`).
The checkpoint is an ancestor of starting HEAD and Module 10 documents have no
changes between those commits. All five governing documents and nine accepted
ADRs were read. The frozen architecture remains unchanged.

Only Module 10 files are part of this story. Existing Module 6.5 modifications,
untracked `.editorconfig`, `.gitattributes`, Module 6.5 files, Module 7, and scripts
were recorded before editing and left untouched. Additional concurrent Module 9
work appeared during execution and was left untouched.

## Implemented architecture

`contracts.py` supplies strict immutable requests/results and execution evidence.
`config.py` permits bounded deterministic execution only. `runtime.py` implements
the asynchronous provider protocol and deterministic lexical fixture.
`service.py` owns input/output validation and expected failure translation.
`errors.py` supplies specific public exceptions. `__init__.py` exports the usable
package contract. No HTTP, UI, queue, cache, cloud, or model SDK code is present.

Python support is `>=3.12,<3.13`, aligned with repository declarations rather than
the globally selected Python 3.14. Verification uses the dedicated Module 10
environment with CPython 3.12.14. There are no runtime dependencies; Hatchling is
the build backend, and Ruff/pytest are development dependencies recorded by
`uv.lock`. Standard-library validation avoids an unnecessary framework dependency.

## Verification

The suite contains 58 deterministic tests covering valid inference,
reproducibility, inclusive bounds, Unicode and punctuation, input/config/result
validation, expected provider failures, invalid output, provenance mismatch,
cancellation, defect propagation, immutable values, prompt-as-data behavior,
no-key operation, network denial during inference, credential-presence safety,
repr/error/log protection, installed imports, and framework isolation.

Native fail-fast results are recorded after the final implementation:

- Ruff: `All checks passed!` (exit 0).
- Pytest: 58 passed (exit 0), Python 3.12.14 / pytest 8.4.2.
- `python -m compileall src tests`: exit 0.

Initial Ruff diagnosed two E501 line-length errors; both received bounded
formatting repairs without unsafe fixes or rule changes. Sandboxed pytest stalled
inside Windows asyncio's local socketpair initialization, before inference.
The diagnostic run was interrupted. Execution outside the sandbox allows normal
Windows event-loop plumbing; provider network denial remains tested. No external
AI service or paid operation is used.

Targeted checks verify UTF-8 without BOM, absence of credential/config artifacts
among story files, no other-module or web-framework imports/dependencies, and
unchanged hashes of all initially recorded foreign working files. Only intended
Module 10 files are staged for the focused local commit; nothing is pushed.

## Completion assessment

Requirements: Story 10.2 contracts and failure boundaries are implemented;
full course requirements remain planned or partial.
Product Experience: README supplies a runnable package example; final reviewer UI
belongs to Story 10.7.
Real Functionality: actual deterministic lexical execution only, accurately
classified; no model-runtime, live-provider, or deployment claims.
Reliability: strict bounds, one execution attempt, output revalidation, and
cancellation propagation; HTTP deadlines and async queue controls remain deferred.
Security: no credential loading/persistence/logging or privileged output authority;
payloads are data, errors are generic, and exception causes stay internal.
Cost: zero provider calls and no billable operations.
Evidence: deterministic tests and native local quality gates only.
Deployment: package installation/import verified; Docker, CI/CD, Azure, scaling,
production readiness, and release acceptance remain unproven.

Story 10.3 has not begun. The full-module Definition of Done remains unchanged.
