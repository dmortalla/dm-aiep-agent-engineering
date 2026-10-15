# Module 9 Definition of Done

Module 9 is done only when every item below has verified evidence of the required class (see
[EVIDENCE_POLICY.md](EVIDENCE_POLICY.md)). Design documentation alone never checks a box except
where the item itself is about documentation or traceability.

Current state: Story 9.1 complete (design only), Story 9.2 complete (deterministic foundation),
Story 9.3 complete (local document and vision understanding, no model inference), and Story 9.4
complete (audio and speech pipeline; no speech recognition or synthesis). No item below is
satisfied yet. Story 9.4 contributes automated evidence toward "Audio processing works",
"Speech-to-text works", and "Text-to-speech works"; all three stay unchecked because only PCM WAV
is decodable, the STT adapter is fixture playback, the TTS adapter generates tones, and
reviewer-visible results (9.9) do not exist yet. Story 9.3 contributes automated evidence toward "Vision processing works" and
"Document understanding works"; both stay unchecked until model-based vision (9.8) and
reviewer-visible results (9.9) exist. Item 1 is traced at the design level and still needs implementation
evidence before it can be checked. Story 9.2 contributes deterministic foundation evidence toward
"Deterministic no-key mode is reproducible", which stays unchecked until every essential workflow
runs deterministically (Story 9.9).

- [ ] Every authoritative source requirement is traced.
- [ ] Vision processing works.
- [ ] Audio processing works.
- [ ] Document understanding works.
- [ ] Cross-modal reasoning works.
- [ ] Speech-to-text works.
- [ ] Text-to-speech works.
- [ ] Voice orchestration works.
- [ ] The voice-enabled AI assistant is demonstrable.
- [ ] The multimodal workflow is demonstrable.
- [ ] Genuine WebSocket streaming works.
- [ ] Real-time/low-latency behavior has measured evidence.
- [ ] The integrated multimodal AI platform works.
- [ ] Deterministic no-key mode is reproducible.
- [ ] Live BYOK mode is explicit opt-in and safely bounded.
- [ ] Streamlit exposes actual working results.
- [ ] The UI includes concise built-in reviewer/user guidance.
- [ ] Security and failure paths are tested.
- [ ] Structured observability exists without secret leakage.
- [ ] Documentation, type, and error-handling standards are satisfied.
- [ ] Native quality gates pass.
- [ ] Reviewer-visible acceptance evidence exists.
- [ ] Architecture, ADRs, requirements, traceability, project status, and README accurately describe the implementation.
- [ ] Module 9 remains isolated.
- [ ] Only verified functionality is claimed.

## Native quality gates (fail-fast)

Run from `module-09/`:

1. `uv run ruff check .`
2. `uv run pytest`
3. `uv run python -m compileall -q src tests`
4. Project-native integration and acceptance tests (added by Stories 9.2 to 9.10).

A later passing gate never overrides an earlier failure. Ruff safe fixes only; never `--unsafe-fixes`.

## Production-grade review order

Requirements -> Product Experience -> Real Functionality -> Reliability -> Security -> Cost ->
Evidence -> Deployment
