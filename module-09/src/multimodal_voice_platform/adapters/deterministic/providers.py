"""Deterministic fixture-playback adapters for the vision, document, and speech-to-text ports.

These adapters perform no inference. Each one resolves the request's content reference, confirms
by exact SHA-256 digest that the content is a committed fixture, and replays that fixture's
scripted output from the manifest. Content that is not a committed fixture is rejected. They make
no network calls and need no credentials. Every result carries a ``deterministic`` descriptor and
is classified ``untrusted_model_output`` like any provider result (ADR-009-007).
"""

from collections.abc import AsyncIterator
from typing import Final

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.deterministic.errors import DeterministicInputError
from multimodal_voice_platform.adapters.deterministic.fixtures import FixtureCatalog, FixtureSpec
from multimodal_voice_platform.contracts.modality import ModalityInput
from multimodal_voice_platform.contracts.providers import (
    DocumentRequest,
    DocumentResult,
    ProviderDescriptor,
    ProviderPort,
    TranscriptionRequest,
    TranscriptSegment,
    VisionRequest,
    VisionResult,
)
from multimodal_voice_platform.contracts.session import ExecutionMode

DETERMINISTIC_VISION_ID: Final = "deterministic-fixture-vision"
DETERMINISTIC_DOCUMENT_ID: Final = "deterministic-fixture-document"
DETERMINISTIC_STT_ID: Final = "deterministic-fixture-stt"


class _FixturePlayback:
    """Shared fixture resolution for the deterministic adapters."""

    def __init__(
        self,
        catalog: FixtureCatalog,
        store: SessionContentStore,
        provider_id: str,
        port: ProviderPort,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._descriptor = ProviderDescriptor(
            provider_id=provider_id, port=port, mode=ExecutionMode.DETERMINISTIC
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter: its ID, port, and deterministic execution mode."""
        return self._descriptor

    def _resolve(self, item: ModalityInput) -> FixtureSpec:
        if item.content_ref is None:
            raise DeterministicInputError("binary input requires a content reference")
        content = self._store.read(item.session_id, item.content_ref)
        spec = self._catalog.match(item.modality, content)
        if spec.media_type != item.media_type or spec.size_bytes != item.size_bytes:
            raise DeterministicInputError("input metadata does not match the deterministic fixture")
        return spec


class DeterministicVisionProvider(_FixturePlayback):
    """``VisionPort`` adapter that replays scripted annotations for committed image fixtures."""

    def __init__(self, catalog: FixtureCatalog, store: SessionContentStore) -> None:
        """Create the adapter.

        Args:
            catalog: Verified fixture catalog.
            store: Session content store that holds staged fixture bytes.
        """
        super().__init__(catalog, store, DETERMINISTIC_VISION_ID, ProviderPort.VISION)

    async def analyze(self, request: VisionRequest) -> VisionResult:
        """Replay the scripted annotation for a committed image fixture.

        Args:
            request: Validated vision request. ``question`` does not change the scripted output.

        Returns:
            The scripted image annotation, attributed to this deterministic adapter.

        Raises:
            ContentNotFoundError: If the content reference is unknown or released.
            DeterministicInputError: If the content is not a committed image fixture.
        """
        spec = self._resolve(request.image)
        script = spec.vision
        if script is None:
            raise DeterministicInputError("fixture has no scripted vision output")
        return VisionResult(
            provider=self.descriptor,
            description=script.description,
            observations=script.observations,
        )


class DeterministicDocumentProvider(_FixturePlayback):
    """``DocumentUnderstandingPort`` adapter that replays scripted structure for documents."""

    def __init__(self, catalog: FixtureCatalog, store: SessionContentStore) -> None:
        """Create the adapter.

        Args:
            catalog: Verified fixture catalog.
            store: Session content store that holds staged fixture bytes.
        """
        super().__init__(
            catalog, store, DETERMINISTIC_DOCUMENT_ID, ProviderPort.DOCUMENT_UNDERSTANDING
        )

    async def understand(self, request: DocumentRequest) -> DocumentResult:
        """Replay the scripted structure for a committed document fixture.

        Args:
            request: Validated document request.

        Returns:
            The scripted document structure, attributed to this deterministic adapter.

        Raises:
            ContentNotFoundError: If the content reference is unknown or released.
            DeterministicInputError: If the content is not a committed document fixture.
        """
        spec = self._resolve(request.document)
        script = spec.document
        if script is None:
            raise DeterministicInputError("fixture has no scripted document output")
        return DocumentResult(
            provider=self.descriptor, title=script.title, sections=script.sections
        )


class DeterministicSpeechToTextProvider(_FixturePlayback):
    """``SpeechToTextPort`` adapter that replays scripted transcripts for audio fixtures."""

    def __init__(self, catalog: FixtureCatalog, store: SessionContentStore) -> None:
        """Create the adapter.

        Args:
            catalog: Verified fixture catalog.
            store: Session content store that holds staged fixture bytes.
        """
        super().__init__(catalog, store, DETERMINISTIC_STT_ID, ProviderPort.SPEECH_TO_TEXT)

    async def transcribe(self, request: TranscriptionRequest) -> AsyncIterator[TranscriptSegment]:
        """Replay the scripted partial and final segments for a committed audio fixture.

        The fixture is resolved before the first segment is yielded, so invalid input fails before
        any output is produced.

        Args:
            request: Validated transcription request. ``language`` does not change the script.

        Yields:
            Scripted segments in order, ending with exactly one final segment.

        Raises:
            ContentNotFoundError: If the content reference is unknown or released.
            DeterministicInputError: If the content is not a committed audio fixture.
        """
        spec = self._resolve(request.audio)
        script = spec.transcript
        if script is None:
            raise DeterministicInputError("fixture has no scripted transcript")
        for segment in script.segments:
            yield TranscriptSegment(
                provider=self.descriptor,
                text=segment.text,
                is_final=segment.is_final,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
            )
