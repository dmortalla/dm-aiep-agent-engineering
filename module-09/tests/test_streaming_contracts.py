"""Tests for the typed streaming protocol contracts."""

import json
import typing

import pytest

from multimodal_voice_platform.contracts.errors import ErrorCode, SafeError, StreamProtocolError
from multimodal_voice_platform.contracts.limits import LatencyStage
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.contracts.streaming import (
    MAX_EVENT_BYTES,
    Metric,
    ResponseDelta,
    SessionStarted,
    StreamError,
    StreamEvent,
    StreamEventType,
    parse_stream_event,
    serialize_stream_event,
)


def _union_types() -> set[str]:
    union = typing.get_args(StreamEvent)[0]
    return {member.model_fields["type"].default for member in typing.get_args(union)}


def test_protocol_covers_every_required_event_type() -> None:
    required = {
        "session_started",
        "transcript_partial",
        "transcript_final",
        "response_delta",
        "response_complete",
        "audio_ready",
        "metric",
        "error",
        "session_complete",
    }
    assert {event.value for event in StreamEventType} == required
    assert _union_types() == required


def test_events_round_trip_through_json() -> None:
    events = [
        SessionStarted(session_id="sess-1", sequence=0, mode=ExecutionMode.DETERMINISTIC),
        ResponseDelta(session_id="sess-1", sequence=1, index=0, text="Hel"),
        Metric(
            session_id="sess-1", sequence=2, stage=LatencyStage.FIRST_RESPONSE, duration_ms=12.5
        ),
        StreamError(
            session_id="sess-1",
            sequence=3,
            error=SafeError(code=ErrorCode.PROVIDER_TIMEOUT, message="Timed out", retryable=True),
        ),
    ]
    for event in events:
        assert parse_stream_event(serialize_stream_event(event)) == event


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"type": "shell_command", "session_id": "sess-1", "sequence": 0}),
        json.dumps({"type": "response_delta", "session_id": "sess-1", "sequence": 0}),
        json.dumps(
            {
                "type": "response_delta",
                "session_id": "sess-1",
                "sequence": -1,
                "index": 0,
                "text": "x",
            }
        ),
        json.dumps(
            {
                "type": "response_delta",
                "session_id": "sess-1",
                "sequence": 0,
                "index": 0,
                "text": "x",
                "grant_admin": True,
            }
        ),
        json.dumps(
            {
                "type": "audio_ready",
                "session_id": "sess-1",
                "sequence": 0,
                "audio_ref": "ref-a",
                "media_type": "text/html",
                "duration_ms": 10,
            }
        ),
        json.dumps(
            {
                "type": "session_started",
                "session_id": "sess-1",
                "sequence": 0,
                "mode": "deterministic",
                "protocol_version": 2,
            }
        ),
    ],
)
def test_malformed_or_unknown_events_are_rejected(payload: str) -> None:
    with pytest.raises(StreamProtocolError) as excinfo:
        parse_stream_event(payload)
    assert excinfo.value.code is ErrorCode.PROTOCOL_ERROR
    assert excinfo.value.to_safe_error().code is ErrorCode.PROTOCOL_ERROR


def test_validation_failures_are_chained() -> None:
    with pytest.raises(StreamProtocolError) as excinfo:
        parse_stream_event("{}")
    assert excinfo.value.__cause__ is not None


def test_oversized_messages_are_rejected_before_parsing() -> None:
    with pytest.raises(StreamProtocolError, match="maximum size"):
        parse_stream_event("x" * (MAX_EVENT_BYTES + 1))


def test_safe_error_message_is_bounded() -> None:
    with pytest.raises(ValueError):
        SafeError(code=ErrorCode.INTERNAL_ERROR, message="x" * 301)
