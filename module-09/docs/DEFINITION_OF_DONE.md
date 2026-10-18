# Module 9 Definition of Done

Module 9 is done only when every item below has verified evidence of the required class (see
[EVIDENCE_POLICY.md](EVIDENCE_POLICY.md)). Design documentation alone never checks a box except
where the item itself is about documentation or traceability.

Current local evidence is reconciled through Story 9.10 in [RELEASE_READINESS.md](RELEASE_READINESS.md).
Checked items mean established within the documented local scope, not public deployment. The
unchecked audio/document/STT items retain accepted limitations (WAV-only, local extraction only,
and no genuine partial STT). Measured latency is checked only as measurement, not an SLO or closure
of SRC-012. SRC-013 also remains partial because real browser microphone/live UI is unverified.
Module 9 remains incomplete; separate human-controlled release-closeout gates follow this checklist.

- [x] Every authoritative source requirement is traced.
- [x] Vision processing works.
- [ ] Audio processing works.
- [ ] Document understanding works.
- [x] Cross-modal reasoning works.
- [ ] Speech-to-text works.
- [x] Text-to-speech works.
- [x] Voice orchestration works.
- [x] The voice-enabled AI assistant is demonstrable.
- [x] The multimodal workflow is demonstrable.
- [x] Genuine WebSocket streaming works.
- [x] Real-time/low-latency behavior has measured evidence.
- [x] The integrated multimodal AI platform works.
- [x] Deterministic no-key mode is reproducible.
- [x] Live BYOK mode is explicit opt-in and safely bounded.
- [x] Streamlit exposes actual working results.
- [x] The UI includes concise built-in reviewer/user guidance.
- [x] Security and failure paths are tested.
- [x] Structured observability exists without secret leakage.
- [x] Documentation, type, and error-handling standards are satisfied.
- [x] Native quality gates pass.
- [x] Reviewer-visible acceptance evidence exists.
- [x] Architecture, ADRs, requirements, traceability, project status, and README accurately describe the implementation.
- [x] Module 9 remains isolated.
- [x] Only verified functionality is claimed.

## Native quality gates (fail-fast)

Run from `module-09/`:

1. `uv run ruff check .`
2. `uv run pytest`
3. `uv run python -m compileall src tests streamlit_app.py`
4. Project-native integration and acceptance tests (added by Stories 9.2 to 9.10).

A later passing gate never overrides an earlier failure. Ruff safe fixes only; never `--unsafe-fixes`.

## Production-grade review order

Requirements -> Product Experience -> Real Functionality -> Reliability -> Security -> Cost ->
Evidence -> Deployment

## Mandatory release-closeout gates (not performed here)

- Independent Story 9.10 acceptance and separately controlled commit.
- Explicitly authorized publication/push.
- Actual reviewer-facing Streamlit deployment.
- Deployed application and deterministic/demo verification.
- Secure opt-in BYOK/live verification where appropriate and separately authorized.
- Recruiter-facing LinkedIn publication.

No checked local engineering item overrides these gates or the partial requirement statuses.
