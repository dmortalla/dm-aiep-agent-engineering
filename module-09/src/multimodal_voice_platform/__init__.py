"""Module 9 multimodal and voice AI platform.

Story 9.1 provides architecture and typed contracts. Story 9.2 adds deterministic, no-key
fixture-playback adapters (``adapters.deterministic``) that perform no inference. Story 9.3 adds
validated image and document ingestion (``ingestion``), local image analysis and document extraction
adapters (``adapters.local``), and the understanding service (``understanding``), with no model
inference. Story 9.4 adds local audio processing (``audio``), a deterministic tone-sequence
text-to-speech adapter (``adapters.speech``), and the speech pipeline (``speech``); its
deterministic STT is fixture playback and its TTS output is not speech. No model-based vision,
semantic document, speech recognition, speech synthesis, cross-modal, voice orchestration,
streaming, live-provider, or UI capability is implemented yet.
See ``module-09/docs/STORIES.md``.
"""
