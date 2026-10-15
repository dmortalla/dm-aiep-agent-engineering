"""Builders for Story 9.5 cross-modal tests. Every input is generated in-process or committed.

Images, documents, and audio are built from explicit patterns so each test knows exactly which
facts local processing will measure, and therefore which cross-modal findings are correct.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from audio_builders import pcm_wav, sine_wav
from media_builders import encode, quadrant_image
from PIL import Image

from multimodal_voice_platform.adapters.deterministic import FixtureCatalog
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    ReasoningChunk,
    ReasoningRequest,
    TranscriptionRequest,
    TranscriptSegment,
)
from multimodal_voice_platform.contracts.reasoning import FindingKind
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.crossmodal import (
    CrossModalRecord,
    CrossModalWorkflow,
    ModalitySubmission,
    ReasoningBinding,
    ReasoningKind,
)
from multimodal_voice_platform.speech import (
    SpeechProcessingKind,
    SpeechService,
    SpeechToTextBinding,
)

TEST = EvidenceClass.AUTOMATED_TEST
SESSION = SessionConfig(session_id="sess-xmodal")
CATALOG = FixtureCatalog.load_default()
QUADRANT_PNG = encode(quadrant_image(), "PNG")
"""16 x 16 PNG: top-left red, top-right green, bottom-left blue, bottom-right white."""
TONE_WAV = sine_wav(440.0, 300)
"""300 ms, 16 kHz, 16-bit mono 440 Hz sine tone."""
SILENT_WAV = pcm_wav(b"\x00\x00" * 4_000)
"""250 ms of 16 kHz, 16-bit mono digital silence."""
FIXTURE_TONE_WAV = CATALOG.content("audio-tone")
"""The committed 500 ms 400 Hz square tone, whose fixture-playback transcript is scripted."""
FIXTURE_DOCUMENT = CATALOG.content("document-brief")
"""The committed Markdown fixture containing a deliberate embedded instruction."""
STT_DOUBLE = ProviderDescriptor(
    provider_id="test-double-stt",
    port=ProviderPort.SPEECH_TO_TEXT,
    mode=ExecutionMode.DETERMINISTIC,
)
REASONER_DOUBLE = ProviderDescriptor(
    provider_id="test-double-reasoner",
    port=ProviderPort.REASONING,
    mode=ExecutionMode.DETERMINISTIC,
)


def solid_png(color: tuple[int, int, int], size: tuple[int, int] = (24, 12)) -> bytes:
    """Return a PNG filled with one color."""
    return encode(Image.new("RGB", size, color), "PNG")


def text(value: str) -> ModalitySubmission:
    """Return a text submission."""
    return ModalitySubmission(modality=Modality.TEXT, text=value)


def image(data: bytes = QUADRANT_PNG, name: str = "pattern.png") -> ModalitySubmission:
    """Return a PNG image submission."""
    return ModalitySubmission(
        modality=Modality.IMAGE, media_type="image/png", display_name=name, data=data
    )


def document(body: str | bytes, name: str = "notes.md") -> ModalitySubmission:
    """Return a Markdown document submission."""
    data = body.encode("utf-8") if isinstance(body, str) else body
    return ModalitySubmission(
        modality=Modality.DOCUMENT, media_type="text/markdown", display_name=name, data=data
    )


def audio(
    data: bytes = TONE_WAV, *, transcribe: bool = False, name: str = "clip.wav"
) -> ModalitySubmission:
    """Return a WAV audio submission."""
    return ModalitySubmission(
        modality=Modality.AUDIO,
        media_type="audio/wav",
        display_name=name,
        data=data,
        transcribe=transcribe,
    )


def run(
    submissions: list[ModalitySubmission],
    workflow: CrossModalWorkflow | None = None,
    session: SessionConfig = SESSION,
    **options: Any,
) -> CrossModalRecord:
    """Run the workflow once and return its record."""
    options.setdefault("evidence_class", TEST)
    flow = workflow or CrossModalWorkflow(CATALOG)
    return asyncio.run(flow.run(session, submissions, **options))


def kinds(record: CrossModalRecord) -> list[FindingKind]:
    """Return the kinds of a record's findings, in order."""
    return [finding.kind for finding in record.findings]


def about(record: CrossModalRecord, prop: str) -> list[tuple[FindingKind, str]]:
    """Return (kind, claimed value) for every finding whose claims concern a property."""
    return [
        (finding.kind, claim.value)
        for finding in record.findings
        for claim in finding.claims
        if claim.property == prop
    ]


def spoken(transcript: str) -> SpeechService:
    """Return a speech service whose STT test double 'hears' a fixed transcript."""

    class ScriptedSpeechToText:
        @property
        def descriptor(self) -> ProviderDescriptor:
            return STT_DOUBLE

        async def transcribe(
            self, request: TranscriptionRequest
        ) -> AsyncIterator[TranscriptSegment]:
            end = request.audio.duration_ms or 1
            yield TranscriptSegment(
                provider=STT_DOUBLE, text=transcript, is_final=True, start_ms=0, end_ms=end
            )

    double = ScriptedSpeechToText()
    return SpeechService(
        CATALOG,
        speech_to_text=SpeechToTextBinding(
            lambda _: double, SpeechProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
        ),
    )


class ScriptedReasoner:
    """Reasoning-port test double that streams a fixed script or misbehaves on purpose."""

    def __init__(
        self,
        script: Callable[[ReasoningRequest], AsyncIterator[Any]],
        descriptor: ProviderDescriptor = REASONER_DOUBLE,
    ) -> None:
        self.script = script
        self._descriptor = descriptor
        self.requests: list[ReasoningRequest] = []

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def stream_reason(self, request: ReasoningRequest) -> AsyncIterator[Any]:
        self.requests.append(request)
        return self.script(request)


def scripted_workflow(
    script: Callable[[ReasoningRequest], AsyncIterator[Any]],
    descriptor: ProviderDescriptor = REASONER_DOUBLE,
) -> tuple[CrossModalWorkflow, ScriptedReasoner]:
    """Return a workflow bound to a reasoning test double, and the double."""
    double = ScriptedReasoner(script, descriptor)
    binding = ReasoningBinding(
        factory=lambda: double, processing=ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
    )
    return CrossModalWorkflow(CATALOG, reasoning=binding), double


def chunks(document_text: str, *, final: bool = True) -> Callable[..., AsyncIterator[Any]]:
    """Return a reasoning script that streams one document as a single chunk."""

    async def script(_: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        yield ReasoningChunk(provider=REASONER_DOUBLE, text=document_text, is_final=final)

    return script
