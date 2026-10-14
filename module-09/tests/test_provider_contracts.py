"""Tests for provider port request and result contracts."""

from typing import Any, Protocol

import pytest
from pydantic import ValidationError

from multimodal_voice_platform.contracts import providers
from multimodal_voice_platform.contracts.limits import MAX_OUTPUT_TOKENS, MAX_REASONING_PARTS
from multimodal_voice_platform.contracts.modality import (
    InputSource,
    Modality,
    ModalityInput,
    TrustLevel,
)
from multimodal_voice_platform.contracts.providers import (
    DocumentRequest,
    ProviderDescriptor,
    ProviderPort,
    ReasoningPart,
    ReasoningRequest,
    SynthesizedAudio,
    TranscriptionRequest,
    TranscriptSegment,
    VisionRequest,
    VisionResult,
)
from multimodal_voice_platform.contracts.session import ExecutionMode

DESCRIPTOR = ProviderDescriptor(
    provider_id="deterministic-vision", port=ProviderPort.VISION, mode=ExecutionMode.DETERMINISTIC
)


def _image() -> ModalityInput:
    return ModalityInput(
        input_id="img-1",
        session_id="sess-1",
        modality=Modality.IMAGE,
        media_type="image/png",
        source=InputSource.USER_UPLOAD,
        size_bytes=10,
        content_ref="ref-img-1",
    )


def _part(**overrides: Any) -> ReasoningPart:
    fields: dict[str, Any] = {
        "modality": Modality.IMAGE,
        "source_input_id": "img-1",
        "content": "a chart",
        "trust": TrustLevel.UNTRUSTED_MODEL_OUTPUT,
    }
    fields.update(overrides)
    return ReasoningPart(**fields)


def test_requests_require_matching_modality() -> None:
    VisionRequest(image=_image())
    with pytest.raises(ValidationError, match="expected audio"):
        TranscriptionRequest(audio=_image())
    with pytest.raises(ValidationError, match="expected document"):
        DocumentRequest(document=_image())


def test_provider_results_are_always_untrusted_model_output() -> None:
    result = VisionResult(provider=DESCRIPTOR, description="a chart")
    assert result.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    with pytest.raises(ValidationError, match="untrusted_model_output"):
        VisionResult(provider=DESCRIPTOR, description="x", trust=TrustLevel.APPLICATION)


def test_transcript_span_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="start_ms"):
        TranscriptSegment(provider=DESCRIPTOR, text="hi", is_final=True, start_ms=10, end_ms=5)


def test_synthesized_audio_media_type_is_allowlisted() -> None:
    with pytest.raises(ValidationError, match="media type"):
        SynthesizedAudio(
            provider=DESCRIPTOR, audio_ref="ref-a", media_type="video/mp4", duration_ms=10
        )


def test_reasoning_parts_cannot_claim_application_trust() -> None:
    with pytest.raises(ValidationError, match="untrusted"):
        _part(trust=TrustLevel.APPLICATION)


def test_reasoning_request_is_bounded() -> None:
    ReasoningRequest(session_id="sess-1", task="describe", parts=(_part(),), max_output_tokens=10)
    with pytest.raises(ValidationError):
        ReasoningRequest(session_id="sess-1", task="describe", parts=(), max_output_tokens=10)
    with pytest.raises(ValidationError):
        ReasoningRequest(
            session_id="sess-1",
            task="describe",
            parts=(_part(),) * (MAX_REASONING_PARTS + 1),
            max_output_tokens=10,
        )
    with pytest.raises(ValidationError):
        ReasoningRequest(
            session_id="sess-1",
            task="describe",
            parts=(_part(),),
            max_output_tokens=MAX_OUTPUT_TOKENS + 1,
        )


@pytest.mark.parametrize(
    "port_name",
    [
        "SpeechToTextPort",
        "TextToSpeechPort",
        "VisionPort",
        "DocumentUnderstandingPort",
        "ReasoningPort",
    ],
)
def test_each_provider_capability_has_a_protocol_port(port_name: str) -> None:
    port = getattr(providers, port_name)
    assert Protocol in port.__mro__
    assert "descriptor" in dir(port)


def test_provider_port_vocabulary_covers_five_capabilities() -> None:
    assert {port.value for port in ProviderPort} == {
        "speech_to_text",
        "text_to_speech",
        "vision",
        "document_understanding",
        "reasoning",
    }
