"""Story 9.7 protocol contracts: client messages, turn events, metrics, and streaming limits."""

import base64
import json
from typing import Any

import pytest
from pydantic import ValidationError

from multimodal_voice_platform.contracts.errors import ErrorCode, StreamProtocolError
from multimodal_voice_platform.contracts.limits import LatencyStage
from multimodal_voice_platform.contracts.streaming import (
    MAX_CLIENT_MESSAGE_BYTES,
    MAX_EVENT_BYTES,
    ClientMessageTooLargeError,
    EndSession,
    FixtureTurnMessage,
    Metric,
    TranscriptFinal,
    TurnAccepted,
    TurnComplete,
    VoiceTurnMessage,
    parse_client_message,
    parse_stream_event,
    serialize_stream_event,
)
from multimodal_voice_platform.streaming import StreamingLimits

AUDIO = base64.b64encode(b"RIFF" + bytes(40)).decode("ascii")


def _voice(**fields: Any) -> str:
    message = {
        "type": "voice_turn",
        "turn_id": "turn-1",
        "media_type": "audio/wav",
        "display_name": "turn.wav",
        "audio_base64": AUDIO,
    }
    message.update(fields)
    return json.dumps(message)


def test_client_messages_parse_into_typed_models() -> None:
    assert isinstance(parse_client_message(_voice()), VoiceTurnMessage)
    fixture = parse_client_message(
        json.dumps({"type": "fixture_turn", "turn_id": "t-2", "fixture_id": "voice-recall"})
    )
    assert isinstance(fixture, FixtureTurnMessage) and fixture.fixture_id == "voice-recall"
    assert isinstance(parse_client_message('{"type": "end_session"}'), EndSession)


@pytest.mark.parametrize(
    "field",
    [
        {"session_id": "ws-other"},
        {"evidence_class": "live_integration"},
        {"live_provider_executed": True},
        {"mode": "live"},
        {"budget": {"max_provider_calls_per_session": 200}},
        {"provider_id": "openai"},
        {"trust": "application"},
        {"api_key": "sk-test-0123456789"},
        {"sequence": 0},
    ],
)
def test_client_messages_cannot_carry_authority_or_server_fields(field: dict[str, Any]) -> None:
    with pytest.raises(StreamProtocolError) as excinfo:
        parse_client_message(_voice(**field))
    assert excinfo.value.code is ErrorCode.PROTOCOL_ERROR
    assert excinfo.value.__cause__ is not None


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "[]",
        '{"type": "voice_turn"}',
        '{"type": "unknown"}',
        _voice(turn_id="Turn 1"),
        _voice(turn_id="../x"),
        _voice(media_type=""),
        _voice(audio_base64=""),
        _voice(protocol_version=2),
    ],
)
def test_malformed_client_messages_are_rejected(payload: str) -> None:
    with pytest.raises(StreamProtocolError):
        parse_client_message(payload)


def test_client_message_size_is_checked_before_parsing() -> None:
    with pytest.raises(ClientMessageTooLargeError):
        parse_client_message("{" + " " * 100, max_bytes=50)
    with pytest.raises(ClientMessageTooLargeError):
        parse_client_message(b"x" * (MAX_CLIENT_MESSAGE_BYTES + 1), max_bytes=10**9)


def test_audio_payload_decodes_strictly_within_its_bound() -> None:
    message = parse_client_message(_voice())
    assert isinstance(message, VoiceTurnMessage)
    assert message.audio_bytes(1024) == b"RIFF" + bytes(40)
    with pytest.raises(StreamProtocolError, match="maximum size"):
        message.audio_bytes(16)
    for bad in ("####" + AUDIO[4:], AUDIO + "\n", AUDIO[:-1]):
        broken = parse_client_message(_voice(audio_base64=bad))
        assert isinstance(broken, VoiceTurnMessage)
        with pytest.raises(StreamProtocolError):
            broken.audio_bytes(1024)
    assert "audio_base64" not in repr(message)


def test_turn_events_round_trip_and_carry_turn_correlation() -> None:
    events = [
        TurnAccepted(session_id="ws-1", sequence=2, turn_id="turn-1"),
        TranscriptFinal(session_id="ws-1", sequence=3, turn_id="turn-1", text="hello"),
        Metric(
            session_id="ws-1",
            sequence=4,
            turn_id="turn-1",
            stage=LatencyStage.FIRST_RESPONSE,
            duration_ms=1.25,
            measure="since_turn_received",
        ),
        TurnComplete(
            session_id="ws-1",
            sequence=5,
            turn_id="turn-1",
            status="committed",
            committed=True,
            conversation_sequence=1,
            delta_count=2,
            evidence_class="automated_test",
        ),
    ]
    for event in events:
        assert parse_stream_event(serialize_stream_event(event)) == event


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "committed", "committed": False},
        {"status": "rejected", "committed": True, "conversation_sequence": 1},
        {"status": "committed", "committed": True},
        {"status": "failed", "committed": False},
        {"status": "rejected", "committed": False, "failed_stage": "a", "conversation_sequence": 1},
        {
            "status": "committed",
            "committed": True,
            "conversation_sequence": 1,
            "evidence_class": "live_integration",
        },
        {"status": "cancelled", "committed": False, "execution_mode": "live", "extra": 1},
    ],
)
def test_turn_complete_rejects_contradictory_outcomes(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TurnComplete(session_id="ws-1", sequence=0, turn_id="t", delta_count=0, **fields)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_metrics_must_be_finite_and_non_negative(value: float) -> None:
    with pytest.raises(ValidationError):
        Metric(session_id="ws-1", sequence=0, stage=LatencyStage.END_TO_END, duration_ms=value)


def test_serializer_refuses_oversized_events() -> None:
    event = TranscriptFinal(session_id="ws-1", sequence=0, text="x" * 20_000)
    assert len(serialize_stream_event(event)) < MAX_EVENT_BYTES
    huge = TranscriptFinal.model_construct(
        session_id="ws-1", sequence=0, text="x" * (MAX_EVENT_BYTES + 1)
    )
    with pytest.raises(StreamProtocolError):
        serialize_stream_event(huge)


def test_streaming_limits_have_ceilings_and_stay_consistent() -> None:
    limits = StreamingLimits()
    assert limits.max_audio_bytes * 4 // 3 < limits.max_inbound_message_bytes
    for field in (
        {"max_inbound_message_bytes": MAX_CLIENT_MESSAGE_BYTES + 1},
        {"max_audio_bytes": 3 * 1024 * 1024},
        {"max_events_per_turn": 10_000},
        {"max_reply_fragments": 9},
        {"send_timeout_s": 0},
        {"turn_timeout_s": 1_000},
        {"max_connections": 0},
        {"max_inbound_message_bytes": 64 * 1024, "max_audio_bytes": 64 * 1024},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            StreamingLimits(**field)
