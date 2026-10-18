"""Story 9.8 live mode: explicit selection, credentials, evidence ladder, workflows, streaming.

Every test runs the real application services, the real OpenAI SDK, and the real adapters against
an in-process fake API (``live_builders.FakeOpenAI``). No real provider is called, no key is needed,
and every live-mode run is ``automated_test`` evidence.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from live_builders import (
    FAKE_KEY,
    FakeOpenAI,
    act,
    fragments,
    run,
    secrets_absent,
    session,
    split_after_first,
)
from pydantic import SecretStr
from stream_builders import AsgiWebSocket, fixture_turn, voice_turn
from voice_builders import CATALOG, TONE_WAV
from voice_builders import request as voice_request

from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.live import (
    LiveCall,
    LiveCapability,
    check_live_evidence,
    live_evidence,
)
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.providers import ProviderPort
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.crossmodal import (
    CrossModalStatus,
    CrossModalWorkflow,
    ModalitySubmission,
)
from multimodal_voice_platform.interface import GatewaySettings, create_app
from multimodal_voice_platform.live import acceptance
from multimodal_voice_platform.live.bindings import LiveBinding
from multimodal_voice_platform.live.credentials import (
    credential_from_environment,
    live_session,
    session_credential,
)
from multimodal_voice_platform.live.errors import LiveConfigurationError, LiveCredentialError
from multimodal_voice_platform.live.json_stream import ArrayElementScanner, StreamedJsonError
from multimodal_voice_platform.live.redaction import RedactingFilter, redact
from multimodal_voice_platform.speech import SpeechService, SpeechStatus
from multimodal_voice_platform.streaming import (
    ResponseCompletedUpdate,
    ResponseFragmentUpdate,
    StreamingVoiceCoordinator,
    TurnFinished,
)
from multimodal_voice_platform.understanding.service import UnderstandingService
from multimodal_voice_platform.voice import TurnStatus, VoiceAssistant, VoiceStage

TEST = EvidenceClass.AUTOMATED_TEST
MODULE = Path(__file__).resolve().parents[1]
NEVER_WRITTEN = MODULE / "tests" / "__acceptance_never_written__.json"
"""Refused or failed acceptance runs must not create this file."""
REMEMBER = act(
    "remembered",
    "obs-1-s1",
    "remember that the project code word is falcon",
    "Noted: the project code word is falcon.",
    slot="project code word",
    value="falcon",
)


def _voice(fake: FakeOpenAI) -> VoiceAssistant:
    bindings = fake.bindings()
    return VoiceAssistant(
        CATALOG,
        speech=SpeechService(CATALOG, live=bindings.speech),
        live_reasoning=bindings.conversation,
    )


def _coordinator(fake: FakeOpenAI) -> StreamingVoiceCoordinator:
    return StreamingVoiceCoordinator(
        _voice(fake),
        live_reply=fake.bindings().conversation,
        live_credential=lambda: SecretStr(FAKE_KEY),
    )


# --- Mode selection -------------------------------------------------------------------------------


def test_deterministic_mode_never_reaches_a_live_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    fake = FakeOpenAI()
    service = SpeechService(CATALOG, live=fake.bindings().speech)
    record = run(service.transcribe_fixture(SessionConfig(session_id="sess-det"), "voice-remember"))
    assert record.status is SpeechStatus.SUCCEEDED and fake.requests == []
    assert record.provider_processing.value == "fixture_playback"
    assert record.evidence.story == "9.4" and record.live_calls == ()


def test_live_session_without_live_adapters_is_refused_not_downgraded() -> None:
    record = run(
        SpeechService(CATALOG).transcribe_upload(
            session(), media_type="audio/wav", display_name="t.wav", data=TONE_WAV
        )
    )
    assert record.status is SpeechStatus.REJECTED
    assert record.error is not None and record.error.code is ErrorCode.LIVE_MODE_NOT_AUTHORIZED
    with pytest.raises(Exception, match="live voice providers are not available"):
        VoiceAssistant(CATALOG).start_session(session())


def test_live_failure_is_never_replaced_by_deterministic_output() -> None:
    fake = FakeOpenAI()
    fake.failure = (500, {"error": {"message": "down"}})
    voice = _voice(fake)
    voice.start_session(session())
    record = run(
        voice.run_turn(
            voice_request("turn-1", TONE_WAV, session_id="sess-live"), evidence_class=TEST
        )
    )
    assert record.status is TurnStatus.FAILED and not record.committed
    assert record.failed_stage is VoiceStage.SPEECH_TO_TEXT
    assert record.transcript is None and record.reply is None
    assert record.transcription is not None
    assert record.transcription.provider.mode is ExecutionMode.LIVE


def test_importing_module_9_does_not_load_or_initialize_a_provider_sdk() -> None:
    code = (
        "import sys, multimodal_voice_platform.voice, multimodal_voice_platform.streaming, "
        "multimodal_voice_platform.crossmodal, multimodal_voice_platform.interface, "
        "multimodal_voice_platform.live.credentials; print('openai' in sys.modules)"
    )
    env = {k: v for k, v in os.environ.items() if "KEY" not in k.upper()}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    assert result.stdout.strip() == "False"


# --- Credentials and redaction --------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "short", "sk-has space inside the key 123", "sk-é" * 10])
def test_missing_or_malformed_keys_fail_closed_without_echo(bad: str) -> None:
    with pytest.raises(LiveCredentialError) as raised:
        live_session("sess-x", bad)
    assert raised.value.code is ErrorCode.LIVE_MODE_NOT_AUTHORIZED
    if bad:
        assert bad not in str(raised.value)


def test_live_session_holds_the_key_ephemerally_and_never_serializes_it() -> None:
    config = session()
    assert config.mode is ExecutionMode.LIVE and config.live_opt_in
    assert config.allowed_live_providers == frozenset({"openai"})
    assert secrets_absent(config.model_dump_json(), repr(config), str(config.model_dump()))
    assert session_credential(config).get_secret_value() == FAKE_KEY
    with pytest.raises(LiveCredentialError):
        session_credential(SessionConfig(session_id="sess-det"))


def test_environment_key_is_read_only_when_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("M9_TEST_KEY", raising=False)
    with pytest.raises(LiveCredentialError) as raised:
        credential_from_environment("M9_TEST_KEY")
    assert "M9_TEST_KEY is not set" in str(raised.value)
    monkeypatch.setenv("M9_TEST_KEY", FAKE_KEY)
    assert credential_from_environment("M9_TEST_KEY").get_secret_value() == FAKE_KEY


def test_redaction_removes_known_and_key_shaped_secrets(caplog: pytest.LogCaptureFixture) -> None:
    text = f"key={FAKE_KEY} header Bearer abcdefghijklmnop sk-another-secret-value-123"
    assert secrets_absent(redact(text, [FAKE_KEY]))
    assert "abcdefghijklmnop" not in redact(text) and "sk-another" not in redact(text)
    logger = logging.getLogger("m9.redaction.test")
    logger.addFilter(RedactingFilter([FAKE_KEY]))
    with caplog.at_level(logging.INFO, logger="m9.redaction.test"):
        logger.info("provider said %s", FAKE_KEY)
    assert secrets_absent(caplog.text) and "[REDACTED]" in caplog.text


def test_live_runs_leave_no_secret_in_records_logs_or_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = fragments(REMEMBER)
    voice = _voice(fake)
    voice.start_session(session())
    with caplog.at_level(logging.DEBUG):
        record = run(
            voice.run_turn(
                voice_request("turn-1", TONE_WAV, session_id="sess-live"), evidence_class=TEST
            )
        )
    assert record.committed
    assert secrets_absent(record.model_dump_json(), repr(record), caplog.text)


# --- Evidence ladder ------------------------------------------------------------------------------


def _call(real: bool) -> LiveCall:
    return LiveCall(
        provider_family="openai",
        capability=LiveCapability.REASONING,
        model="gpt-test",
        real_endpoint=real,
        outcome="succeeded",
        latency_ms=1.0,
    )


def test_evidence_ladder_classifies_by_what_actually_ran() -> None:
    common = {"evidence_id": "ev-x", "requirement_ids": ("SRC-005",), "summary": "s"}
    real = live_evidence(requested=EvidenceClass.LIVE_INTEGRATION, calls=[_call(True)], **common)
    assert real.evidence_class is EvidenceClass.LIVE_INTEGRATION and real.live_provider_executed
    mocked = live_evidence(requested=TEST, calls=[_call(False)], **common)
    assert mocked.evidence_class is TEST and mocked.execution_mode is ExecutionMode.LIVE
    none = live_evidence(requested=EvidenceClass.LIVE_INTEGRATION, calls=[], **common)
    assert none.evidence_class is EvidenceClass.DETERMINISTIC_DEMO
    assert none.execution_mode is ExecutionMode.DETERMINISTIC
    with pytest.raises(ValueError):
        check_live_evidence(real, [_call(False)])
    with pytest.raises(ValueError):
        check_live_evidence(mocked, [_call(True)])
    forged = EvidenceRecord(
        evidence_id="ev-y",
        evidence_class=EvidenceClass.LIVE_INTEGRATION,
        story="9.8",
        requirement_ids=("SRC-005",),
        summary="s",
        runtime_executed=True,
        live_provider_executed=True,
        execution_mode=ExecutionMode.LIVE,
    )
    with pytest.raises(ValueError):
        check_live_evidence(forged, [])


def test_mocked_transport_can_never_be_recorded_as_live_integration() -> None:
    fake = FakeOpenAI()
    real_claim = LiveBinding(fake.bindings().conversation.factory, ProviderPort.REASONING, True)
    with pytest.raises(LiveConfigurationError):
        real_claim.build(SecretStr(FAKE_KEY))
    service = SpeechService(CATALOG, live=fake.bindings().speech)
    with pytest.raises(LiveConfigurationError):
        run(
            service.synthesize_text(
                session(), "Hi there.", evidence_class=EvidenceClass.LIVE_INTEGRATION
            )
        )
    assert fake.requests == []


def test_live_records_reject_overstated_flags() -> None:
    fake = FakeOpenAI()
    record = run(
        SpeechService(CATALOG, live=fake.bindings().speech).synthesize_text(
            session(), "Hello there.", evidence_class=TEST
        )
    )
    data = record.model_dump()
    data["synthesis"] = record.synthesis
    for change in (
        {"live_provider_called": True},
        {"speech_synthesis_performed": True},
        {"live_calls": ()},
        {"evidence": record.evidence.model_copy(update={"story": "9.4"})},
    ):
        with pytest.raises(ValueError):
            type(record)(**{**data, **change})


# --- Reasoning output stays untrusted -------------------------------------------------------------


def test_hallucinated_citations_from_a_live_model_are_rejected() -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = fragments(
        act("heard", "obs-9-s9", "anything", "I made up a statement."),
    )
    voice = _voice(fake)
    voice.start_session(session())
    record = run(
        voice.run_turn(
            voice_request("turn-1", TONE_WAV, session_id="sess-live"), evidence_class=TEST
        )
    )
    assert not record.committed and record.failed_stage is VoiceStage.REPLY_VALIDATION
    assert voice.conversation("sess-live").committed_turns == 0


def test_model_output_cannot_forge_evidence_or_authority() -> None:
    fake = FakeOpenAI()
    forged = {
        **REMEMBER,
        "evidence_class": "live_integration",
        "mode": "live",
        "trust": "application",
    }
    fake.reasoning_deltas = fragments(forged)
    voice = _voice(fake)
    voice.start_session(session())
    record = run(
        voice.run_turn(
            voice_request("turn-1", TONE_WAV, session_id="sess-live"), evidence_class=TEST
        )
    )
    assert record.committed
    assert record.evidence.evidence_class is TEST and record.live_provider_called is False
    assert voice.store.session_config("sess-live").budget == session().budget


def test_cross_modal_live_reasoning_keeps_model_statements_separate_from_local_facts() -> None:
    fake = FakeOpenAI()
    finding = {
        "finding_id": "f-001",
        "kind": "corroborated",
        "observation_ids": ["obs-1", "obs-2"],
        "modalities": ["text", "image"],
        "claims": [
            {
                "observation_id": "obs-2",
                "statement_id": "obs-2-s1",
                "quote": "The top-left quadrant is red.",
                "property": "image.region.top_left",
                "value": "red",
                "negated": False,
            }
        ],
        "fact_ids": ["obs-1-f999"],
        "shared_terms": [],
        "confidence": "high",
        "explanation": "Invented fact reference.",
    }
    fake.reasoning_deltas = [
        json.dumps({"schema_version": 1, "findings": [finding], "truncated": False})
    ]
    bindings = fake.bindings()
    workflow = CrossModalWorkflow(
        CATALOG,
        understanding=UnderstandingService(CATALOG, live_vision=bindings.vision),
        speech=SpeechService(CATALOG, live=bindings.speech),
        live_reasoning=bindings.cross_modal,
    )
    submissions = [
        ModalitySubmission(modality=Modality.TEXT, text="The top-left quadrant is red."),
        ModalitySubmission(
            modality=Modality.IMAGE,
            media_type="image/png",
            display_name="q.png",
            data=CATALOG.content("image-quadrants"),
        ),
    ]
    record = run(workflow.run(session(), submissions, evidence_class=TEST))
    assert record.status is CrossModalStatus.FAILED, "an invented fact ID is rejected"
    image = next(o for o in record.observations if o.view.modality is Modality.IMAGE)
    assert all(f.origin.value == "local_measurement" for f in image.view.facts)
    assert {s.origin.value for s in image.view.statements} == {"provider_contract_test_double"}
    assert len(record.all_live_calls()) == 2
    fake.reasoning_deltas = [json.dumps({"schema_version": 1, "findings": [], "truncated": False})]
    ok = run(workflow.run(session(), submissions, evidence_class=TEST))
    assert ok.status is CrossModalStatus.SUCCEEDED and ok.evidence.story == "9.8"


# --- Provider streaming through the coordinator and the WebSocket gateway -------------------------


def test_provider_deltas_become_application_events_before_completion() -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = split_after_first(REMEMBER, act("heard", "obs-1-s1", "falcon", "Okay."))
    fake.gate = asyncio.Event()
    coordinator = _coordinator(fake)
    session_id = coordinator.open_session().session_id
    assert coordinator.voice.conversation(session_id).mode is ExecutionMode.LIVE

    async def body() -> None:
        stream = coordinator.stream_turn(
            voice_request("turn-1", TONE_WAV, session_id=session_id), evidence_class=TEST
        )
        seen: list[Any] = []
        async for update in stream:
            seen.append(update)
            if isinstance(update, ResponseFragmentUpdate):
                break
        assert not any(isinstance(u, ResponseCompletedUpdate | TurnFinished) for u in seen)
        assert coordinator.voice.conversation(session_id).committed_turns == 0
        fake.gate.set()
        rest = [u async for u in stream]
        record = rest[-1].record
        assert record.committed and record.fragments_streamed == 2
        assert record.turn.reasoning_kind.value == "provider_contract_test_double"
        assert record.turn.evidence.story == "9.8" and record.turn.evidence.evidence_class is TEST

    run(body())


def test_cancelling_a_live_turn_closes_the_provider_stream_and_commits_nothing() -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = split_after_first(REMEMBER, act("heard", "obs-1-s1", "falcon", "Okay."))
    fake.gate = asyncio.Event()
    coordinator = _coordinator(fake)
    session_id = coordinator.open_session().session_id

    async def body() -> None:
        stream = coordinator.stream_turn(
            voice_request("turn-1", TONE_WAV, session_id=session_id), evidence_class=TEST
        )
        async for update in stream:
            if isinstance(update, ResponseFragmentUpdate):
                break
        await stream.aclose()

    run(body())
    assert coordinator.active_turns == 0
    assert coordinator.voice.conversation(session_id).committed_turns == 0


def test_live_turn_over_the_websocket_gateway_emits_only_typed_events() -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = fragments(REMEMBER)
    coordinator = _coordinator(fake)
    app = create_app(coordinator, settings=GatewaySettings(evidence_class=TEST))

    async def body() -> list[dict[str, Any]]:
        client = await AsgiWebSocket(app).connect()
        started = await client.event()
        assert started["mode"] == "live"
        await client.event()
        await client.send(voice_turn("turn-1", TONE_WAV))
        events = await client.until("turn_complete")
        await client.disconnect()
        return [started, *events]

    events = run(body())
    types = [e["type"] for e in events if e["type"] != "metric"]
    assert types == [
        "session_started",
        "turn_accepted",
        "transcript_final",
        "response_delta",
        "response_complete",
        "audio_ready",
        "turn_complete",
    ]
    done = events[-1]
    assert done["committed"] and done["execution_mode"] == "live"
    assert done["evidence_class"] == "automated_test"
    assert done["stt_processing"] == "provider_contract_test_double"
    wire = json.dumps(events)
    assert secrets_absent(wire)
    assert "response.output_text.delta" not in wire and "sequence_number" not in wire


def test_client_messages_cannot_carry_a_key_or_select_live_mode() -> None:
    fake = FakeOpenAI()
    app = create_app(
        StreamingVoiceCoordinator(_voice(fake)), settings=GatewaySettings(evidence_class=TEST)
    )

    async def body() -> list[dict[str, Any]]:
        client = await AsgiWebSocket(app).connect()
        started = await client.event()
        assert started["mode"] == "deterministic"
        await client.event()
        await client.send(fixture_turn("turn-1", "voice-remember", api_key=FAKE_KEY, mode="live"))
        error = await client.event()
        await client.disconnect()
        return [error]

    (error,) = run(body())
    assert error["error"]["code"] == "protocol_error" and fake.requests == []
    assert secrets_absent(json.dumps(error))


# --- Streamed JSON scanning -----------------------------------------------------------------------


def test_array_scanner_releases_elements_only_when_closed() -> None:
    scanner = ArrayElementScanner()
    assert scanner.feed('{"fragments":[{"a":"}"') == []
    assert scanner.feed(',"b":[1,{"c":2}]}') == ['{"a":"}","b":[1,{"c":2}]}']
    assert scanner.feed(',{"d":"x\\"y"}]}') == ['{"d":"x\\"y"}']
    scanner.close()
    with pytest.raises(StreamedJsonError):
        ArrayElementScanner(max_chars=5).feed("x" * 6)
    broken = ArrayElementScanner()
    broken.feed('{"fragments":[{"a":1}')
    with pytest.raises(StreamedJsonError):
        broken.close()


# --- Separately invoked live acceptance -----------------------------------------------------------


def test_acceptance_runner_refuses_without_explicit_paid_call_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert acceptance.main(["--out", str(NEVER_WRITTEN)]) == 2
    out = capsys.readouterr().out
    assert "real, paid OpenAI API calls" in out and "--confirm-paid-call" in out
    assert not NEVER_WRITTEN.exists()


def test_acceptance_runner_rejects_a_bad_key_without_echoing_it(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M9_ACCEPT_KEY", "zq-bad-key")
    code = acceptance.main(
        ["--confirm-paid-call", "--key-env", "M9_ACCEPT_KEY", "--out", str(NEVER_WRITTEN)]
    )
    assert code == 2 and "zq-bad-key" not in capsys.readouterr().out


def test_acceptance_runner_cannot_be_satisfied_by_a_mocked_transport(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeOpenAI()
    monkeypatch.setattr(acceptance, "openai_bindings", lambda config: fake.bindings(config))
    monkeypatch.setenv("M9_ACCEPT_KEY", FAKE_KEY)
    code = acceptance.main(
        ["--confirm-paid-call", "--key-env", "M9_ACCEPT_KEY", "--out", str(NEVER_WRITTEN)]
    )
    out = capsys.readouterr().out
    assert code == 1 and "LiveConfigurationError" in out
    assert fake.requests == [] and not NEVER_WRITTEN.exists()
    assert secrets_absent(out)


def test_tests_never_name_the_real_endpoint_or_read_a_real_key() -> None:
    endpoint = "api." + "openai.com"
    for path in (MODULE / "tests").glob("*.py"):
        text = path.read_text("utf-8")
        assert endpoint not in text, path
        assert "credential_from_" + "environment(\"OPENAI" not in text, path
