"""Tests for the deterministic adapters and the deterministic foundation (Story 9.2)."""

import asyncio
import inspect
from collections.abc import Coroutine
from typing import Any

import pytest
from pydantic import ValidationError

from multimodal_voice_platform.adapters.deterministic import (
    ContentNotFoundError,
    DeterministicFoundation,
    DeterministicInputError,
    DeterministicRunRecord,
    FixtureBudgetError,
    UnknownFixtureError,
)
from multimodal_voice_platform.contracts import providers
from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import (
    InputSource,
    Modality,
    ModalityInput,
    TrustLevel,
)
from multimodal_voice_platform.contracts.providers import (
    DocumentRequest,
    DocumentResult,
    ProviderPort,
    TranscriptionRequest,
    TranscriptSegment,
    VisionRequest,
    VisionResult,
)
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig

FIXTURES = ("text-brief", "image-quadrants", "audio-tone", "document-brief")


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture
def foundation() -> DeterministicFoundation:
    return DeterministicFoundation()


@pytest.fixture
def session() -> SessionConfig:
    return SessionConfig(session_id="sess-9-2")


async def _transcribe(foundation: DeterministicFoundation, item: ModalityInput) -> list[Any]:
    request = TranscriptionRequest(audio=item)
    return [segment async for segment in foundation.speech_to_text.transcribe(request)]


@pytest.mark.parametrize(
    ("adapter", "port_name", "method"),
    [
        ("vision", "VisionPort", "analyze"),
        ("document", "DocumentUnderstandingPort", "understand"),
        ("speech_to_text", "SpeechToTextPort", "transcribe"),
    ],
)
def test_adapters_conform_to_their_ports(
    foundation: DeterministicFoundation, adapter: str, port_name: str, method: str
) -> None:
    implementation = getattr(foundation, adapter)
    port = getattr(providers, port_name)
    port_method = getattr(port, method)
    impl_method = getattr(type(implementation), method)
    assert list(inspect.signature(impl_method).parameters) == list(
        inspect.signature(port_method).parameters
    )
    if method == "transcribe":
        assert inspect.isasyncgenfunction(impl_method)
    else:
        assert inspect.iscoroutinefunction(impl_method)
    descriptor = implementation.descriptor
    assert descriptor.mode is ExecutionMode.DETERMINISTIC
    assert descriptor.provider_id.startswith("deterministic-")
    assert (
        descriptor.port
        is {
            "vision": ProviderPort.VISION,
            "document": ProviderPort.DOCUMENT_UNDERSTANDING,
            "speech_to_text": ProviderPort.SPEECH_TO_TEXT,
        }[adapter]
    )


@pytest.mark.parametrize("fixture_id", FIXTURES)
def test_every_fixture_runs_to_a_typed_deterministic_record(
    foundation: DeterministicFoundation, session: SessionConfig, fixture_id: str
) -> None:
    record = _run(foundation.run(session, fixture_id))
    assert isinstance(record, DeterministicRunRecord)
    assert record.fixture_id == fixture_id
    assert record.fixture_sha256 == foundation.catalog.get(fixture_id).sha256
    assert record.input.source is InputSource.DETERMINISTIC_FIXTURE
    assert record.input.trust is TrustLevel.UNTRUSTED_EXTERNAL
    assert record.live_provider_called is False
    assert record.evidence.evidence_class is EvidenceClass.DETERMINISTIC_DEMO
    assert record.evidence.execution_mode is ExecutionMode.DETERMINISTIC
    assert record.evidence.live_provider_executed is False
    assert record.evidence.story == "9.2"
    assert "No model, live provider, network, or credential was used." in record.evidence.summary
    if record.modality is Modality.TEXT:
        assert record.provider is None
        assert record.input.text is not None
        assert record.input.content_ref is None
    else:
        assert record.provider is not None
        assert record.provider.mode is ExecutionMode.DETERMINISTIC
        assert record.input.content_ref is not None


def test_outputs_are_typed_scripted_and_untrusted(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    image = _run(foundation.run(session, "image-quadrants"))
    document = _run(foundation.run(session, "document-brief"))
    audio = _run(foundation.run(session, "audio-tone"))
    assert isinstance(image.vision, VisionResult)
    assert image.vision.description.startswith("Deterministic fixture annotation:")
    assert image.vision.observations[-1].endswith("No vision model ran.")
    assert isinstance(document.document, DocumentResult)
    assert document.document.title == "Module 9 Deterministic Document Fixture"
    assert all(isinstance(segment, TranscriptSegment) for segment in audio.transcript)
    assert [segment.is_final for segment in audio.transcript] == [False, True]
    assert audio.transcript[-1].end_ms <= (audio.input.duration_ms or 0)
    assert "No speech-to-text model ran." in audio.transcript[-1].text
    for result in (image.vision, document.document, *audio.transcript):
        assert result.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT


def test_identical_input_produces_identical_output(session: SessionConfig) -> None:
    first = [_run(DeterministicFoundation().run(session, fid)).model_dump() for fid in FIXTURES]
    second = [_run(DeterministicFoundation().run(session, fid)).model_dump() for fid in FIXTURES]
    assert first == second


def test_records_serialize_for_a_reviewer_layer(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    record = _run(foundation.run(session, "image-quadrants"))
    restored = DeterministicRunRecord.model_validate_json(record.model_dump_json())
    assert restored == record
    dumped = record.model_dump(mode="json")
    assert dumped["provider"]["mode"] == "deterministic"
    assert dumped["evidence"]["evidence_class"] == "deterministic_demo"
    assert dumped["live_provider_called"] is False


def test_automated_test_evidence_class_is_supported(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    record = _run(
        foundation.run(session, "audio-tone", evidence_class=EvidenceClass.AUTOMATED_TEST)
    )
    assert record.evidence.evidence_class is EvidenceClass.AUTOMATED_TEST


@pytest.mark.parametrize(
    "evidence_class",
    [
        EvidenceClass.LIVE_INTEGRATION,
        EvidenceClass.DESIGN_DOCUMENTATION,
        EvidenceClass.DEPLOYMENT_RELEASE,
    ],
)
def test_runs_cannot_claim_non_deterministic_evidence(
    foundation: DeterministicFoundation, session: SessionConfig, evidence_class: EvidenceClass
) -> None:
    with pytest.raises(DeterministicInputError, match="deterministic evidence"):
        _run(foundation.run(session, "image-quadrants", evidence_class=evidence_class))


def test_record_rejects_contradictory_claims(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    data = _run(foundation.run(session, "image-quadrants")).model_dump()
    with pytest.raises(ValidationError, match="deterministic provider"):
        DeterministicRunRecord.model_validate(
            {**data, "provider": {**data["provider"], "mode": "live"}}
        )
    with pytest.raises(ValidationError):
        DeterministicRunRecord.model_validate({**data, "live_provider_called": True})
    with pytest.raises(ValidationError, match="wrong outputs"):
        DeterministicRunRecord.model_validate({**data, "vision": None})
    with pytest.raises(ValidationError, match="port"):
        DeterministicRunRecord.model_validate({**data, "provider": None})
    text = _run(foundation.run(session, "text-brief")).model_dump()
    with pytest.raises(ValidationError, match="port"):
        DeterministicRunRecord.model_validate({**text, "provider": data["provider"]})


def test_unknown_fixture_fails_with_a_safe_error(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    with pytest.raises(UnknownFixtureError) as excinfo:
        _run(foundation.run(session, "../../secrets"))
    safe = excinfo.value.to_safe_error()
    assert safe.code is ErrorCode.INPUT_REJECTED
    assert "secrets" not in safe.message


@pytest.mark.parametrize(
    ("budget", "fixture_id", "message"),
    [
        (ResourceBudget(max_image_bytes=10), "image-quadrants", "byte budget"),
        (ResourceBudget(max_audio_bytes=100), "audio-tone", "byte budget"),
        (ResourceBudget(max_audio_duration_ms=100), "audio-tone", "duration budget"),
        (ResourceBudget(max_document_bytes=100), "document-brief", "byte budget"),
    ],
)
def test_fixtures_respect_the_session_budget(
    foundation: DeterministicFoundation, budget: ResourceBudget, fixture_id: str, message: str
) -> None:
    session = SessionConfig(session_id="sess-small", budget=budget)
    with pytest.raises(FixtureBudgetError, match=message) as excinfo:
        foundation.stage(session, fixture_id)
    assert excinfo.value.code is ErrorCode.LIMIT_EXCEEDED
    assert foundation.store.reference_count("sess-small") == 0


def _forged(item: ModalityInput, **overrides: Any) -> ModalityInput:
    return ModalityInput.model_validate({**item.model_dump(), **overrides})


def test_adapters_reject_content_that_is_not_a_committed_fixture(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    item = foundation.stage(session, "image-quadrants")
    ref = foundation.store.put(session.session_id, "forged", b"\x89PNG not the fixture")
    with pytest.raises(DeterministicInputError, match="does not match"):
        _run(foundation.vision.analyze(VisionRequest(image=_forged(item, content_ref=ref))))
    with pytest.raises(DeterministicInputError, match="metadata"):
        _run(
            foundation.vision.analyze(
                VisionRequest(image=_forged(item, media_type="image/webp", display_name=None))
            )
        )
    with pytest.raises(DeterministicInputError, match="metadata"):
        _run(foundation.vision.analyze(VisionRequest(image=_forged(item, size_bytes=81))))


def test_adapters_reject_content_staged_as_another_modality(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    image = foundation.stage(session, "image-quadrants")
    document = foundation.stage(session, "document-brief")
    as_document = _forged(document, content_ref=image.content_ref)
    with pytest.raises(DeterministicInputError, match="does not match"):
        _run(foundation.document.understand(DocumentRequest(document=as_document)))


def test_speech_to_text_rejects_before_yielding(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    audio = foundation.stage(session, "audio-tone")
    ref = foundation.store.put(session.session_id, "noise", b"RIFF not the fixture")
    with pytest.raises(DeterministicInputError):
        _run(_transcribe(foundation, _forged(audio, content_ref=ref)))


def test_content_is_session_scoped_and_released(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    item = foundation.stage(session, "image-quadrants")
    assert foundation.stage(session, "image-quadrants").content_ref == item.content_ref
    with pytest.raises(ContentNotFoundError):
        _run(foundation.vision.analyze(VisionRequest(image=_forged(item, session_id="other"))))
    foundation.stage(session, "audio-tone")
    assert foundation.release(session.session_id) == 2
    assert foundation.store.reference_count(session.session_id) == 0
    with pytest.raises(ContentNotFoundError, match="unknown"):
        _run(foundation.vision.analyze(VisionRequest(image=item)))


def test_failures_are_specific_module9_errors_with_safe_messages(
    foundation: DeterministicFoundation, session: SessionConfig
) -> None:
    item = foundation.stage(session, "image-quadrants")
    foundation.release(session.session_id)
    with pytest.raises(Module9Error) as excinfo:
        _run(foundation.vision.analyze(VisionRequest(image=item)))
    assert isinstance(excinfo.value.__cause__, KeyError)
    safe = excinfo.value.to_safe_error()
    assert safe.code is ErrorCode.INPUT_REJECTED
    assert "/" not in safe.message and "\\" not in safe.message
