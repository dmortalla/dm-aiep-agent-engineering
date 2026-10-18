"""Story 9.9 deterministic UI and genuine socket acceptance; zero external provider calls."""

import asyncio
import socket
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.ui.reviewer import (
    MAX_UPLOAD_BYTES,
    Reviewer,
    ReviewerInputError,
    Upload,
    authorize_live,
    safe_display,
)
from multimodal_voice_platform.ui.socket_demo import stream_demo

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
CANARY = "sk-test-ui-canary-not-a-real-key-123456789"


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Permit only loopback sockets, including Windows asyncio's socket pair."""
    connected: list[str] = []
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def guard(address: Any) -> None:
        host = address[0]
        assert host in {"127.0.0.1", "::1"}, "external network is forbidden in UI acceptance"
        connected.append(host)

    def checked(self: socket.socket, address: Any) -> Any:
        guard(address)
        return original(self, address)

    def checked_ex(self: socket.socket, address: Any) -> Any:
        guard(address)
        return original_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", checked)
    monkeypatch.setattr(socket.socket, "connect_ex", checked_ex)
    return connected


def app(route: str = "Multimodal workflow") -> AppTest:
    """Return an initialized headless application on the requested route."""
    test = AppTest.from_file(str(APP), default_timeout=20).run()
    test.radio(key="route").set_value(route).run()
    assert not test.exception
    return test


def submit(test: AppTest) -> AppTest:
    """Submit exactly one operation and fail on unhandled UI exceptions."""
    test.button[0].click().run()
    assert not test.exception
    return test


def test_launch_is_no_key_default_and_rerender_never_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(Reviewer, "multimodal", lambda *args: calls.append(args))
    test = app()
    test.run()
    assert test.radio(key="mode").value == "Deterministic demo"
    assert not test.text_input
    assert not calls
    assert "result" not in test.session_state
    assert "Story 9.10" in " ".join(c.value for c in test.caption)


def test_multimodal_sample_renders_authoritative_observations_and_evidence() -> None:
    test = submit(app())
    result = test.session_state.result
    assert result["status"] == "succeeded"
    assert len(result["observations"]) == 4
    assert result["evidence"]["evidence_class"] == "deterministic_demo"
    assert not result["evidence"]["live_provider_executed"]
    assert any(f["kind"] == "corroborated" for f in result["findings"])
    assert any("corroborated" in text.value for text in test.text)
    assert test.json


def test_voice_remember_recall_audio_and_session_reset() -> None:
    test = submit(app("Voice assistant"))
    assert test.session_state.result["committed"]
    assert test.session_state.result["transcript"]["text"]
    assert test.session_state.audio_result.startswith(b"RIFF")
    test.selectbox(key="voice_fixture").set_value("voice-recall")
    submit(test)
    assert "falcon" in test.session_state.result["reply"]["reply"]
    assert test.session_state.result["sequence"] == 2
    test.button[1].click().run()
    assert "result" not in test.session_state
    assert "audio_result" not in test.session_state
    assert test.session_state.reviewer.turn == 0


@pytest.mark.parametrize("modality", ["image", "document"])
def test_local_understanding_rendered_without_model_claims(modality: str) -> None:
    test = app("Document & vision")
    test.selectbox(key="analysis_modality").set_value(modality)
    submit(test)
    result = test.session_state.result
    assert result["status"] == "succeeded"
    assert not result["model_inference_performed"]
    assert result["evidence"]["evidence_class"] == "deterministic_demo"
    assert test.json


def test_live_render_rerun_and_missing_ack_never_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(Reviewer, "multimodal", lambda *args: calls.append(args))
    test = app()
    test.radio(key="mode").set_value("Live / BYOK").run()
    test.run()
    assert not calls
    test.text_input(key="credential").set_value(CANARY)
    submit(test)
    assert not calls
    assert test.error
    assert test.text_input(key="credential").value == ""
    assert CANARY not in str([e.value for e in test.error])


def test_explicit_live_submission_scrubs_password_and_exception_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def failure(self: Reviewer, inputs: Any, key: Any) -> Any:
        calls.append(key.get_secret_value())
        raise RuntimeError(f"private path C:/internal {CANARY}")

    monkeypatch.setattr(Reviewer, "multimodal", failure)
    test = app()
    test.radio(key="mode").set_value("Live / BYOK").run()
    test.text_input(key="credential").set_value(CANARY)
    test.checkbox(key="acknowledged").check()
    submit(test)
    assert calls == [CANARY]
    assert test.text_input(key="credential").value == ""
    assert not test.checkbox(key="acknowledged").value
    assert CANARY not in str([e.value for e in test.error])
    assert "internal" not in str([e.value for e in test.error])
    test.run()
    assert len(calls) == 1
    assert "result" not in test.session_state


def test_socket_ui_renders_received_history_and_real_incremental_fragments() -> None:
    test = submit(app("WebSocket streaming"))
    result = test.session_state.result
    assert result["transport"] == "real loopback WebSocket"
    assert result["evidence_class"] == "deterministic_demo"
    events = result["events"]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session_started"
    assert kinds.index("response_delta") < kinds.index("response_complete")
    assert kinds[-1] == "session_complete"
    assert sum(e["type"] == "turn_complete" for e in events) == 2
    assert test.metric and test.dataframe


@pytest.mark.parametrize("cancel", [False, True])
def test_socket_receipt_callback_precedes_final_result_and_cleanup(
    cancel: bool,
    no_external_network: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from multimodal_voice_platform.ui import socket_demo

    coordinator = socket_demo.StreamingVoiceCoordinator()
    monkeypatch.setattr(socket_demo, "StreamingVoiceCoordinator", lambda: coordinator)
    seen = []

    def receive(item: Any) -> None:
        # Callback is invoked during receipt, not replayed from a completed result.
        if item.event["type"] == "response_delta":
            assert not any(e.event["type"] == "response_complete" for e in seen)
        seen.append(item)

    # For the full two-turn run, only compare within each turn.
    def per_turn(item: Any) -> None:
        if item.event["type"] == "turn_accepted":
            seen.clear()
        receive(item)

    events = asyncio.run(stream_demo(per_turn, cancel_after_first=cancel))
    assert no_external_network
    assert coordinator.voice.store.active_sessions == 0
    assert any(e.event["type"] == "response_delta" for e in events)
    if cancel:
        assert not any(e.event["type"] == "turn_complete" for e in events)
    else:
        assert events[-1].event["type"] == "session_complete"
    assert all(e.event.get("evidence_class") != "live_integration" for e in events)


@pytest.mark.parametrize("data", [b"", b"x" * (MAX_UPLOAD_BYTES + 1)], ids=["empty", "oversized"])
def test_empty_and_oversized_uploads_fail_before_service(data: bytes) -> None:
    with pytest.raises(ReviewerInputError, match="2 MiB"):
        Upload("sample.wav", "audio/wav", data)


def test_malformed_unsupported_content_and_injection_are_inert() -> None:
    reviewer = Reviewer()
    record = reviewer.understand(Modality.IMAGE, Upload("bad.png", "image/png", b"garbage"))
    assert record.status.value == "rejected"
    record = reviewer.speak(upload=Upload("clip.mp3", "audio/mpeg", b"garbage"))
    assert not record.committed
    record = reviewer.speak("voice-injection")
    assert record.evidence.evidence_class.value == "deterministic_demo"
    assert not record.live_provider_called
    assert safe_display(CANARY) == "[REDACTED]"


def test_ui_contains_no_unsafe_html_cache_secrets_or_environment_key_read() -> None:
    source = (APP.parent / "src/multimodal_voice_platform/ui/app.py").read_text("utf-8")
    for forbidden in ("unsafe_allow_html", "st.html", "st.cache", "st.secrets", "os.environ"):
        assert forbidden not in source
    assert 'type="password"' in source
    assert 'pop("credential"' in source
    assert authorize_live(False, True, CANARY) is None
    with pytest.raises(ReviewerInputError):
        authorize_live(True, False, CANARY)
    with pytest.raises(ReviewerInputError):
        authorize_live(True, True, "")


def test_fake_live_binding_is_refused_instead_of_claiming_live_or_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from live_builders import FakeOpenAI

    from multimodal_voice_platform.adapters import openai

    fake = FakeOpenAI()
    monkeypatch.setattr(openai, "openai_bindings", fake.bindings)
    test = app()
    test.radio(key="mode").set_value("Live / BYOK").run()
    test.text_input(key="credential").set_value(CANARY)
    test.checkbox(key="acknowledged").check()
    submit(test)
    assert test.error
    assert fake.requests == []
    assert "result" not in test.session_state
    assert test.text_input(key="credential").value == ""


def test_ui_upload_checks_precede_read_and_unsupported_extensions_are_safe() -> None:
    from multimodal_voice_platform.ui.app import _uploaded

    class Incoming:
        size = MAX_UPLOAD_BYTES + 1
        name = "secret-path.exe"

        def getvalue(self) -> bytes:
            pytest.fail("Oversized or unsupported input must never be read")

    with pytest.raises(ReviewerInputError, match="2 MiB"):
        _uploaded(Incoming())
    Incoming.size = 1
    with pytest.raises(ReviewerInputError, match="PCM WAV"):
        _uploaded(Incoming())


def test_browser_sessions_do_not_share_conversation_results() -> None:
    first = submit(app("Voice assistant"))
    second = app("Voice assistant")
    assert "result" not in second.session_state
    assert first.session_state.reviewer.session_id != second.session_state.reviewer.session_id
    second.selectbox(key="voice_fixture").set_value("voice-recall")
    submit(second)
    assert second.session_state.result["sequence"] == 1
    assert "falcon" not in second.session_state.result["reply"]["reply"]


def test_ui_keeps_mocked_result_classification_even_when_live_was_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from multimodal_voice_platform.contracts.evidence import EvidenceClass
    from multimodal_voice_platform.contracts.session import SessionConfig
    from multimodal_voice_platform.crossmodal.service import CrossModalWorkflow

    reviewer = Reviewer()
    record = asyncio.run(
        CrossModalWorkflow(reviewer.catalog).run(
            SessionConfig(session_id="sess-ui-test"),
            reviewer.sample(),
            evidence_class=EvidenceClass.AUTOMATED_TEST,
        )
    )
    monkeypatch.setattr(Reviewer, "multimodal", lambda *args: record)
    test = app()
    test.radio(key="mode").set_value("Live / BYOK").run()
    test.text_input(key="credential").set_value(CANARY)
    test.checkbox(key="acknowledged").check()
    submit(test)
    assert test.session_state.result["evidence"]["evidence_class"] == "automated_test"
    assert not test.session_state.result["evidence"]["live_provider_executed"]
    assert any("automated_test" in item.value for item in test.text)
    assert test.text_input(key="credential").value == ""
