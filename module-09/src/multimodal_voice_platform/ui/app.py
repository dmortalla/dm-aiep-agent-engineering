"""Unified Streamlit presentation. Only explicit submitted actions execute services."""

import asyncio
import json
from typing import Any

import streamlit as st
from pydantic import ValidationError

from multimodal_voice_platform.contracts.errors import Module9Error
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.crossmodal.service import ModalitySubmission
from multimodal_voice_platform.live.errors import LiveProviderError
from multimodal_voice_platform.live.redaction import redact_json
from multimodal_voice_platform.ui.reviewer import (
    MAX_UPLOAD_BYTES,
    Reviewer,
    ReviewerInputError,
    Upload,
    authorize_live,
    safe_display,
)
from multimodal_voice_platform.ui.socket_demo import ReceivedEvent, stream_demo

ROUTES = ("Multimodal workflow", "Voice assistant", "Document & vision", "WebSocket streaming")
MODES = ("Deterministic demo", "Live / BYOK")
MEDIA = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "txt": "text/plain",
    "wav": "audio/wav",
}


def _uploaded(value: Any) -> Upload | None:
    if value is None:
        return None
    if value.size > MAX_UPLOAD_BYTES:
        raise ReviewerInputError("Choose a file no larger than 2 MiB.")
    suffix = value.name.rsplit(".", 1)[-1].lower()
    if suffix not in MEDIA:
        raise ReviewerInputError("Use PNG/JPEG/WebP, PDF/Markdown/text, or PCM WAV.")
    return Upload(value.name, MEDIA[suffix], value.getvalue())


def _submit() -> None:
    """Execute one explicitly submitted operation and retain only redacted results."""
    # Runs before the script rerenders; deletion is permitted before widget creation.
    raw_key = st.session_state.pop("credential", "")
    st.session_state.pop("result", None)
    st.session_state.pop("audio_result", None)
    st.session_state.pop("safe_error", None)
    key = None
    try:
        reviewer: Reviewer = st.session_state.reviewer
        route = st.session_state.route
        live = st.session_state.mode == MODES[1] and route != ROUTES[3]
        key = authorize_live(live, st.session_state.get("acknowledged", False), raw_key)
        raw_key = ""
        if route == ROUTES[0]:
            if st.session_state.get("samples", True):
                submissions = reviewer.sample()
            else:
                items = []
                text = st.session_state.get("claim", "").strip()
                if text:
                    items.append(ModalitySubmission(modality=Modality.TEXT, text=text))
                for name, modality in (
                    ("image", Modality.IMAGE),
                    ("document", Modality.DOCUMENT),
                    ("audio", Modality.AUDIO),
                ):
                    upload = _uploaded(st.session_state.get(name))
                    if upload:
                        items.append(
                            ModalitySubmission(
                                modality=modality,
                                media_type=upload.media_type,
                                display_name=upload.name,
                                data=upload.data,
                                transcribe=modality is Modality.AUDIO,
                            )
                        )
                submissions = tuple(items)
            record = reviewer.multimodal(submissions, key)
        elif route == ROUTES[1]:
            upload = _uploaded(st.session_state.get("microphone")) or _uploaded(
                st.session_state.get("voice_upload")
            )
            record = reviewer.speak(
                st.session_state.get("voice_fixture", "voice-remember"), upload, key
            )
            if record.output_audio:
                st.session_state.audio_result = record.output_audio.wav_bytes
        elif route == ROUTES[2]:
            modality = Modality(st.session_state.analysis_modality)
            upload = _uploaded(st.session_state.get("analysis_upload"))
            if upload is None:
                fixture_id = "image-quadrants" if modality is Modality.IMAGE else "document-brief"
                spec = reviewer.catalog.get(fixture_id)
                upload = Upload(
                    spec.display_name, spec.media_type, reviewer.catalog.content(fixture_id)
                )
            record = reviewer.understand(modality, upload, key)
        else:
            slot = st.empty()
            history: list[dict[str, Any]] = []

            def received(event: ReceivedEvent) -> None:
                history.append({"elapsed_ms": round(event.elapsed_ms, 3), **event.event})
                slot.text(safe_display(json.dumps(history[-1], ensure_ascii=False)))

            asyncio.run(stream_demo(received, cancel_after_first=st.session_state.cancel_stream))
            st.session_state.result = {
                "transport": "real loopback WebSocket",
                "evidence_class": "deterministic_demo",
                "execution_mode": "deterministic",
                "events": history,
                "client_disconnected_after_first_fragment": st.session_state.cancel_stream,
            }
            return
        # Never retain credential-bearing sessions/services or raw provider failures.
        st.session_state.result = json.loads(
            redact_json(record.model_dump_json(), [key] if key else ())
        )
    except ReviewerInputError as exc:
        st.session_state.safe_error = str(exc)  # Only fixed, application-owned messages.
    except (ValidationError, Module9Error, LiveProviderError):
        st.session_state.safe_error = (
            "The input or operation was rejected. Check file type, size, supported PCM WAV audio, "
            "and live acknowledgement. No deterministic fallback was performed."
        )
    except Exception:  # Final UI boundary: never show/log raw exceptions or payloads.
        st.session_state.safe_error = (
            "The operation could not finish safely. Reset the reviewer session and try a sample."
        )
    finally:
        raw_key = ""
        key = None
        st.session_state.pop("credential", None)
        st.session_state.pop("acknowledged", None)


def _reset() -> None:
    st.session_state.reviewer.reset()
    for name in (
        "result",
        "audio_result",
        "safe_error",
        "credential",
        "microphone",
        "voice_upload",
        "image",
        "document",
        "audio",
        "analysis_upload",
    ):
        st.session_state.pop(name, None)


def _show_result(result: dict[str, Any]) -> None:
    evidence = result.get("evidence", result)
    st.subheader("Execution evidence")
    st.text(
        f"Mode: {evidence.get('execution_mode', 'unknown')} | "
        f"Evidence: {evidence.get('evidence_class', 'unknown')} | "
        f"Status: {result.get('status', result.get('transport', 'unknown'))}"
    )
    if result.get("error"):
        st.warning("The authoritative service rejected or failed this operation.")
    if result.get("transcript"):
        st.subheader("Transcript")
        st.text(result["transcript"]["text"])
    if result.get("reply"):
        st.subheader("Assistant response")
        st.text(result["reply"]["reply"])
    if "findings" in result:
        st.subheader("Cross-modal findings")
        for finding in result["findings"]:
            st.text(f"{finding['kind']}: {finding['explanation']}")
        if not result["findings"]:
            st.info("No supported relationship was found in the supplied observations.")
        with st.expander("Normalized observations and citations"):
            st.json(result.get("observations", []))
    if result.get("vision"):
        st.subheader("Image analysis")
        st.text(result["vision"]["description"])
        for observation in result["vision"].get("observations", []):
            st.text(observation)
    if result.get("model_vision"):
        st.subheader("Live model interpretation  |  untrusted")
        st.text(result["model_vision"]["description"])
    if result.get("document"):
        st.subheader("Locally extracted document")
        for section in result["document"]["sections"]:
            if section.get("heading"):
                st.text(section["heading"])
            st.text(section["text"])
    if "events" in result:
        events = result["events"]
        st.metric("Received WebSocket events", len(events))
        first = next((e["elapsed_ms"] for e in events if e["type"] == "response_delta"), None)
        if first is not None:
            st.metric("Client time to first response (ms)", first)
        st.caption("Events were rendered on receipt. This table is the received event history.")
        st.dataframe(events, alt="Validated WebSocket events in receipt order")
        fragments = [e["text"] for e in events if e["type"] == "response_delta"]
        for fragment in fragments:
            st.text(fragment)
        if result.get("client_disconnected_after_first_fragment"):
            st.info(
                "Client disconnected after the first fragment; gateway cancels the active turn."
            )
    if "audio_result" in st.session_state:
        st.audio(st.session_state.audio_result, format="audio/wav", alt="Validated assistant audio")
    if result.get("timings"):
        st.subheader("Measured stage latency")
        st.dataframe(result["timings"], alt="Measured stage latency in milliseconds")
    if result.get("live_calls"):
        st.subheader("Recorded provider calls and usage")
        st.json(result["live_calls"])
    with st.expander("Authoritative result, providers, processing kinds and timings"):
        st.json(result)


def render() -> None:
    """Render the reviewer app; all execution is gated by explicit form submission."""
    st.set_page_config(
        page_title="Module 9  |  Multimodal and Voice",
        page_icon=":material/graphic_eq:",
        layout="wide",
    )
    st.title("Multimodal and Voice Studio")
    st.caption("Module 9  |  A working reviewer experience  |  Local preview")
    if "reviewer" not in st.session_state:
        st.session_state.reviewer = Reviewer()
    with st.sidebar:
        st.radio("Workflow", ROUTES, key="route")
        st.radio("Execution mode", MODES, key="mode")
        st.button("Reset session and clear results", on_click=_reset, type="primary")
        st.caption(
            "Module 9 is incomplete. Story 9.10 local acceptance is ready for independent review. "
            "Deployment verification and LinkedIn publication remain outstanding."
        )
    route = st.session_state.route
    live = st.session_state.mode == MODES[1] and route != ROUTES[3]
    st.info(
        "Live mode: explicit submitted requests may incur provider usage. No automatic fallback."
        if live
        else "Deterministic demo  |  No key, provider network call or payment required."
    )
    st.caption(
        "All uploaded and model-produced content is untrusted data. Local/demo latency is "
        "measurement, not a production SLO. Results are scoped to this browser session."
    )
    with st.form("execution", clear_on_submit=True):
        if route == ROUTES[0]:
            st.subheader("Relate evidence across modalities")
            st.write(
                "Run the four-modality sample first. Then try a text claim and an image or "
                "document. Inspect measured facts, quoted statements and cited findings."
            )
            st.checkbox("Use repository-owned samples", value=True, key="samples")
            st.text_area("Text claim (custom inputs)", max_chars=20000, key="claim")
            st.file_uploader("Image", type=["png", "jpg", "jpeg", "webp"], key="image")
            st.file_uploader("Document", type=["md", "txt", "pdf"], key="document")
            st.file_uploader("Audio", type=["wav"], key="audio")
            st.caption(
                "Custom workflow needs at least two modalities. Deterministic reasoning uses "
                "a closed vocabulary; fixture STT does not recognize arbitrary speech."
            )
        elif route == ROUTES[1]:
            st.subheader("Listen, reason and respond")
            st.write(
                "Try voice-remember, then voice-recall to demonstrate bounded conversation "
                "state. Deterministic fixtures replay transcripts and generate tones, not speech."
            )
            st.selectbox(
                "Sample utterance",
                ["voice-remember", "voice-recall", "voice-injection"],
                key="voice_fixture",
            )
            st.audio_input("Record a spoken turn", sample_rate=16000, key="microphone")
            st.file_uploader("Or upload PCM WAV", type=["wav"], key="voice_upload")
            st.caption(
                "Microphone/upload takes precedence over the sample. Arbitrary speech needs "
                "live STT. Live voice uses a fresh one-turn session; no live recall is claimed."
            )
        elif route == ROUTES[2]:
            st.subheader("Inspect an image or document")
            st.write(
                "Leave upload empty to use a safe sample. Image analysis measures pixels; "
                "document processing extracts local text and structure. No OCR is provided."
            )
            st.selectbox("Modality", ["image", "document"], key="analysis_modality")
            st.file_uploader(
                "Image or document",
                type=["png", "jpg", "jpeg", "webp", "md", "txt", "pdf"],
                key="analysis_upload",
            )
            st.caption(
                "Documents always use local extraction. Live vision adds an untrusted model "
                "interpretation separate from measured facts."
            )
        else:
            st.subheader("Observe a real WebSocket conversation")
            st.write(
                "This deterministic demonstration starts an ephemeral loopback gateway, sends "
                "remember and recall fixture turns, and renders typed events as they arrive. "
                "Response fragments are produced incrementally; no artificial typing delay."
            )
            st.checkbox(
                "Disconnect after first response fragment (cancellation demo)", key="cancel_stream"
            )
            st.caption(
                "Streaming uses deterministic adapters regardless of the mode selector. "
                "The protocol exposes audio references; use Voice assistant for playback."
            )
        if live:
            st.text_input(
                "Provider API key for this execution only", type="password", key="credential"
            )
            st.checkbox(
                "I acknowledge this execution may incur provider usage/cost", key="acknowledged"
            )
            st.caption(
                "The password is cleared on submit. It is never cached, saved, or included in "
                "evidence. A new key entry and acknowledgement are required for another call."
            )
        st.form_submit_button("Run selected workflow", type="primary", on_click=_submit)
    if "safe_error" in st.session_state:
        st.error(st.session_state.safe_error)
    if "result" in st.session_state:
        _show_result(st.session_state.result)

    st.divider()
    st.caption(
        "Developed from Techademy AI Engineering program requirements. Independent "
        "implementation, engineering enhancements, and deployment."
    )
