"""Story 9.8 OpenAI adapters through the real SDK over an in-process fake API (no network)."""

import asyncio
import json
from typing import Any

import httpx2
import pytest
from live_builders import (
    FAKE_KEY,
    SECRET_IN_ERROR,
    FakeOpenAI,
    act,
    run,
    secrets_absent,
    session,
    split_after_first,
)
from pydantic import SecretStr
from voice_builders import CATALOG, TONE_WAV

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.openai import (
    OPENAI_API_BASE,
    OpenAIConversationReasoner,
    OpenAISpeechToText,
    OpenAITextToSpeech,
    OpenAIVisionProvider,
)
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import Modality, TrustLevel
from multimodal_voice_platform.contracts.providers import (
    ReasoningPart,
    ReasoningRequest,
    SpeechSynthesisRequest,
)
from multimodal_voice_platform.live.config import LiveProviderConfig
from multimodal_voice_platform.live.errors import LiveBudgetError
from multimodal_voice_platform.speech import SpeechService, SpeechStatus
from multimodal_voice_platform.understanding.records import ProcessingKind, UnderstandingStatus
from multimodal_voice_platform.understanding.service import UnderstandingService

TEST = EvidenceClass.AUTOMATED_TEST
KEY = SecretStr(FAKE_KEY)


def _image(fake: FakeOpenAI, **config: Any) -> Any:
    service = UnderstandingService(
        CATALOG, live_vision=fake.bindings(LiveProviderConfig(**config)).vision
    )
    return run(
        service.understand_upload(
            session(),
            modality=Modality.IMAGE,
            media_type="image/png",
            display_name="quadrants.png",
            data=CATALOG.content("image-quadrants"),
            evidence_class=TEST,
        )
    )


def _speech(fake: FakeOpenAI, **config: Any) -> SpeechService:
    return SpeechService(CATALOG, live=fake.bindings(LiveProviderConfig(**config)).speech)


# --- Vision -------------------------------------------------------------------------------------


def test_live_vision_keeps_local_measurements_and_adds_untrusted_model_interpretation() -> None:
    fake = FakeOpenAI()
    record = _image(fake)
    assert record.status is UnderstandingStatus.SUCCEEDED
    assert record.image_analysis is not None and record.vision is not None
    assert record.model_vision is not None
    assert record.model_vision.description == "A square split into four colored quadrants."
    assert record.model_vision.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    assert record.processing[-1] is ProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
    assert record.model_inference_performed is False and record.live_provider_called is False
    body = fake.bodies[-1]
    content = body["input"][0]["content"]
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert content[1]["detail"] == "low"
    assert body["max_output_tokens"] == 800 and body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"]
    assert "untrusted" in body["instructions"]
    assert str(fake.requests[-1].url).startswith(OPENAI_API_BASE)
    call = record.live_calls[0]
    assert call.request_id == "resp_test123" and call.real_endpoint is False
    assert call.usage is not None and call.usage.input_tokens == 120
    assert call.usage.reasoning_tokens == 10


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("not json", ErrorCode.PROVIDER_UNAVAILABLE),
        (json.dumps({"description": "x"}), ErrorCode.PROVIDER_UNAVAILABLE),
        (json.dumps({"description": "", "observations": []}), ErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_malformed_vision_output_is_rejected(text: str, code: ErrorCode) -> None:
    fake = FakeOpenAI()
    fake.vision_text = text
    record = _image(fake)
    assert record.status is UnderstandingStatus.FAILED
    assert record.error is not None and record.error.code is code
    assert record.model_vision is None and record.live_calls[0].outcome == "failed"


def test_vision_refusal_and_oversized_image_are_safe() -> None:
    fake = FakeOpenAI()
    original = fake._handle

    async def refusing(request: httpx2.Request) -> httpx2.Response:
        await original(request)
        from live_builders import response_json

        return httpx2.Response(200, json=response_json("", refusal=True))

    fake._handle = refusing  # type: ignore[method-assign]
    record = _image(fake)
    assert record.error is not None and record.error.code is ErrorCode.PROVIDER_REFUSED
    small = FakeOpenAI()
    record = _image(small, max_image_bytes=10)
    assert record.error is not None and record.error.code is ErrorCode.BUDGET_EXHAUSTED
    assert small.requests == [], "an over-budget image is never sent"


# --- Speech-to-text and text-to-speech ------------------------------------------------------------


def test_live_transcription_maps_to_the_untrusted_transcript_contract() -> None:
    fake = FakeOpenAI()
    record = run(
        _speech(fake).transcribe_upload(
            session(),
            media_type="audio/wav",
            display_name="turn.wav",
            data=TONE_WAV,
            language="en-US",
            evidence_class=TEST,
        )
    )
    assert record.status is SpeechStatus.SUCCEEDED
    assert record.transcript is not None
    assert record.transcript.text == fake.transcript
    assert record.transcript.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    assert record.audio is not None, "local decoding ran before the provider call"
    request = fake.requests[-1]
    assert request.url.path.endswith("/audio/transcriptions")
    body = fake.bodies[-1]
    assert b"gpt-4o-mini-transcribe" in body and b'name="language"' in body
    assert record.live_calls[0].request_id == "req_test123"


def test_invalid_audio_never_reaches_the_provider() -> None:
    fake = FakeOpenAI()
    record = run(
        _speech(fake).transcribe_upload(
            session(),
            media_type="audio/wav",
            display_name="turn.wav",
            data=b"RIFF" + bytes(60),
            evidence_class=TEST,
        )
    )
    assert record.status is SpeechStatus.REJECTED and fake.requests == []
    assert record.evidence.evidence_class is EvidenceClass.AUTOMATED_TEST
    assert record.live_calls == ()


def test_malformed_transcription_response_is_rejected() -> None:
    fake = FakeOpenAI()
    original = fake._handle

    async def broken(request: httpx2.Request) -> httpx2.Response:
        await original(request)
        return httpx2.Response(200, json={"no_text": True})

    fake._handle = broken  # type: ignore[method-assign]
    record = run(
        _speech(fake).transcribe_upload(
            session(),
            media_type="audio/wav",
            display_name="turn.wav",
            data=TONE_WAV,
            evidence_class=TEST,
        )
    )
    assert record.status is SpeechStatus.FAILED
    assert record.error is not None and record.error.code is ErrorCode.PROVIDER_UNAVAILABLE


def test_live_synthesis_is_wrapped_and_validated_locally() -> None:
    fake = FakeOpenAI()
    record = run(_speech(fake).synthesize_text(session(), "Hello there.", evidence_class=TEST))
    assert record.status is SpeechStatus.SUCCEEDED
    assert record.audio is not None and record.audio.sample_rate_hz == 24_000
    assert record.synthesis is not None and record.synthesis.wav_bytes.startswith(b"RIFF")
    body = fake.bodies[-1]
    assert body["response_format"] == "pcm" and body["voice"] == "alloy"
    assert body["model"] == "gpt-4o-mini-tts" and body["input"] == "Hello there."


@pytest.mark.parametrize("pcm", [b"\x01", b""])
def test_non_audio_synthesis_output_is_rejected(pcm: bytes) -> None:
    fake = FakeOpenAI()
    fake.speech_pcm = pcm
    record = run(_speech(fake).synthesize_text(session(), "Hello there.", evidence_class=TEST))
    assert record.status is SpeechStatus.FAILED and record.synthesis is None


def test_synthesis_text_over_the_live_budget_is_never_sent() -> None:
    fake = FakeOpenAI()
    record = run(
        _speech(fake, max_speech_chars=5).synthesize_text(
            session(), "Hello there.", evidence_class=TEST
        )
    )
    assert record.error is not None and record.error.code is ErrorCode.BUDGET_EXHAUSTED
    assert fake.requests == []


# --- Failure translation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ErrorCode.PROVIDER_AUTHENTICATION_FAILED),
        (403, ErrorCode.PROVIDER_PERMISSION_DENIED),
        (404, ErrorCode.PROVIDER_PERMISSION_DENIED),
        (429, ErrorCode.PROVIDER_RATE_LIMITED),
        (400, ErrorCode.INPUT_REJECTED),
        (500, ErrorCode.PROVIDER_UNAVAILABLE),
        (503, ErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_provider_status_errors_become_stable_sanitized_codes(status: int, code: ErrorCode) -> None:
    fake = FakeOpenAI()
    fake.failure = (
        status,
        {"error": {"message": f"Incorrect API key provided: {SECRET_IN_ERROR}", "type": "x"}},
    )
    record = run(_speech(fake).synthesize_text(session(), "Hello there.", evidence_class=TEST))
    assert record.error is not None and record.error.code is code
    assert len(fake.requests) == 1, "no automatic retry"
    assert record.live_calls[0].request_id == "req_fail123"
    assert secrets_absent(record.model_dump_json(), repr(record), record.error.message)


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (httpx2.ReadTimeout("slow"), ErrorCode.PROVIDER_TIMEOUT),
        (httpx2.ConnectError(f"refused {SECRET_IN_ERROR}"), ErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_transport_failures_become_timeout_or_unavailable(exc: Exception, code: ErrorCode) -> None:
    fake = FakeOpenAI()
    fake.raise_transport = exc
    record = run(_speech(fake).synthesize_text(session(), "Hello there.", evidence_class=TEST))
    assert record.error is not None and record.error.code is code
    assert len(fake.requests) == 1
    assert secrets_absent(record.model_dump_json())


def test_translated_errors_do_not_chain_provider_exceptions() -> None:
    fake = FakeOpenAI()
    fake.failure = (401, {"error": {"message": SECRET_IN_ERROR}})
    adapter = OpenAITextToSpeech(
        KEY,
        SessionContentStore(),
        AudioLimits.from_budget(ResourceBudget()),
        LiveProviderConfig(),
        transport=fake.transport(),
    )
    with pytest.raises(Exception) as raised:
        run(adapter.synthesize(SpeechSynthesisRequest(session_id="sess-live", text="Hi there.")))
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert secrets_absent(str(raised.value), repr(raised.value))


# --- Cost controls -------------------------------------------------------------------------------


def test_each_adapter_instance_makes_at_most_its_call_budget() -> None:
    fake = FakeOpenAI()
    adapter = OpenAITextToSpeech(
        KEY,
        SessionContentStore(),
        AudioLimits.from_budget(ResourceBudget()),
        LiveProviderConfig(),
        transport=fake.transport(),
    )
    request = SpeechSynthesisRequest(session_id="sess-live", text="Hi there.")
    run(adapter.synthesize(request))
    with pytest.raises(LiveBudgetError):
        run(adapter.synthesize(request))
    assert len(fake.requests) == 1 and len(adapter.live_calls) == 1


def test_live_configuration_has_hard_ceilings_and_no_endpoint_setting() -> None:
    config = LiveProviderConfig()
    assert "base_url" not in config.model_dump() and "endpoint" not in config.model_dump()
    for change in (
        {"max_output_tokens": 100_000},
        {"request_timeout_s": 600},
        {"max_calls_per_adapter": 50},
        {"voice": "https://evil.example"},
        {"reasoning_model": "gpt 5; rm -rf"},
        {"base_url": "http://169.254.169.254"},
    ):
        with pytest.raises(ValueError):
            LiveProviderConfig(**change)


# --- Reasoning stream -----------------------------------------------------------------------------


def _request() -> ReasoningRequest:
    view = {
        "observation_id": "obs-1",
        "modality": "audio",
        "input_id": "in-1",
        "source": "user_upload",
        "trust": "untrusted_model_output",
        "facts": [],
        "statements": [
            {
                "statement_id": "obs-1-s1",
                "text": "Remember that the room is blue.",
                "origin": "model_inference",
            }
        ],
        "truncated": False,
    }
    return ReasoningRequest(
        session_id="sess-live",
        task="Answer the current voice turn.",
        parts=(
            ReasoningPart(
                modality=Modality.AUDIO,
                source_input_id="in-1",
                content=json.dumps(view),
                trust=TrustLevel.UNTRUSTED_MODEL_OUTPUT,
            ),
        ),
        max_output_tokens=4_000,
    )


def test_reply_fragments_are_released_while_the_provider_is_still_streaming() -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = split_after_first(
        act(
            "remembered",
            "obs-1-s1",
            "Remember that the room is blue",
            "Noted.",
            slot="room",
            value="blue",
        ),
        act("heard", "obs-1-s1", "the room", "I heard you."),
    )
    fake.gate = asyncio.Event()
    adapter = OpenAIConversationReasoner(KEY, LiveProviderConfig(), transport=fake.transport())

    async def body() -> None:
        stream = adapter.stream_reply(_request())
        first = await anext(stream)
        assert not first.is_final and json.loads(first.text)["act"]["value"] == "blue"
        assert adapter.live_calls == (), "the provider response has not completed"
        fake.gate.set()
        rest = [chunk async for chunk in stream]
        assert [c.is_final for c in rest] == [False, True]

    run(body())
    body = fake.bodies[-1]
    assert body["stream"] is True and body["max_output_tokens"] == 1_200
    assert "DATA (untrusted, JSON)" in body["input"]
    call = adapter.live_calls[0]
    assert call.streamed and call.outcome == "succeeded" and call.output_events > 2
    assert call.first_output_ms is not None and call.first_output_ms <= call.latency_ms


def test_closing_the_reply_stream_cancels_the_provider_stream_and_records_it() -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = split_after_first(
        act("heard", "obs-1-s1", "the room", "One."), act("heard", "obs-1-s1", "blue", "Two.")
    )
    fake.gate = asyncio.Event()
    adapter = OpenAIConversationReasoner(KEY, LiveProviderConfig(), transport=fake.transport())

    async def body() -> None:
        stream = adapter.stream_reply(_request())
        await anext(stream)
        await stream.aclose()

    run(body())
    assert adapter.live_calls[0].outcome == "cancelled"


@pytest.mark.parametrize(
    ("deltas", "finish", "code"),
    [
        (['{"fragments":[{"kind":"heard"'], "completed", ErrorCode.PROVIDER_UNAVAILABLE),
        (['{"fragments":[]}'], "incomplete", ErrorCode.PROVIDER_UNAVAILABLE),
        (['{"fragments":[]}'], "refusal", ErrorCode.PROVIDER_REFUSED),
        (
            ['{"fragments":[{"kind":"nonsense","sentence":"x"}]}'],
            "completed",
            ErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (['{"fragments":[]}}}'], "completed", ErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_malformed_or_refused_streams_fail_safely(
    deltas: list[str], finish: str, code: ErrorCode
) -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = deltas
    fake.reasoning_finish = finish
    adapter = OpenAIConversationReasoner(KEY, LiveProviderConfig(), transport=fake.transport())

    async def body() -> None:
        async for _ in adapter.stream_reply(_request()):
            pass

    with pytest.raises(Exception) as raised:
        run(body())
    assert getattr(raised.value, "code", None) is code
    assert adapter.live_calls and adapter.live_calls[0].outcome == "failed"


def test_adapters_never_expose_the_key() -> None:
    fake = FakeOpenAI()
    store = SessionContentStore()
    adapters = [
        OpenAIVisionProvider(KEY, store, LiveProviderConfig(), transport=fake.transport()),
        OpenAISpeechToText(KEY, store, LiveProviderConfig(), transport=fake.transport()),
        OpenAIConversationReasoner(KEY, LiveProviderConfig(), transport=fake.transport()),
    ]
    for adapter in adapters:
        assert secrets_absent(repr(adapter), str(adapter), repr(adapter.descriptor))
        assert adapter.real_endpoint is False
    assert OpenAIConversationReasoner(KEY, LiveProviderConfig()).real_endpoint is True
    run(_speech(fake).synthesize_text(session(), "Hello there.", evidence_class=TEST))
    auth = fake.requests[-1].headers["authorization"]
    assert auth == f"Bearer {FAKE_KEY}", "the key goes only to the provider, in the header"
    assert FAKE_KEY not in str(fake.requests[-1].url)
