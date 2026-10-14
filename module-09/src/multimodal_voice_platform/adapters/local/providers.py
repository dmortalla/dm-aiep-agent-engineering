"""Local processing adapters for the vision and document understanding ports (Story 9.3).

Unlike the Story 9.2 fixture-playback adapters, these adapters process whatever validated content
they receive: images are decoded and analyzed pixel by pixel, and documents are parsed and their
text extracted. They run in-process with no network and no credentials, so their execution mode is
``deterministic``. They run no model: their output is local extraction and structural analysis,
never semantic model inference. Every result is ``untrusted_model_output`` (ADR-009-007).

CPU-bound decoding runs in a worker thread bounded by the request timeout. A timed-out worker
cannot be forcibly stopped in-process; byte, pixel, and page limits bound how long it can run.
"""

import asyncio
from collections.abc import Callable
from typing import Final

from pydantic import BaseModel, ConfigDict

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.local.document_parsing import (
    DocumentAnalysis,
    parse_document,
)
from multimodal_voice_platform.adapters.local.errors import (
    LocalProcessingError,
    ProcessingTimeoutError,
)
from multimodal_voice_platform.adapters.local.image_analysis import ImageAnalysis, analyze_image
from multimodal_voice_platform.adapters.local.limits import LocalProcessingLimits
from multimodal_voice_platform.contracts.modality import ModalityInput
from multimodal_voice_platform.contracts.providers import (
    DocumentRequest,
    DocumentResult,
    ProviderDescriptor,
    ProviderPort,
    VisionRequest,
    VisionResult,
)
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.ingestion.media import verify_media_content

LOCAL_VISION_ID: Final = "local-image-analysis"
LOCAL_DOCUMENT_ID: Final = "local-document-extraction"
NO_MODEL_NOTE: Final = "Local pixel statistics only. No vision model interpreted the image content."


class LocalVisionOutput(BaseModel):
    """Port result plus the full structured pixel analysis behind it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: VisionResult
    analysis: ImageAnalysis


class LocalDocumentOutput(BaseModel):
    """Port result plus the full structural analysis behind it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: DocumentResult
    analysis: DocumentAnalysis


class _LocalAdapter:
    """Shared content resolution and bounded execution for the local adapters."""

    def __init__(
        self,
        store: SessionContentStore,
        limits: LocalProcessingLimits,
        provider_id: str,
        port: ProviderPort,
    ) -> None:
        self._store = store
        self._limits = limits
        self._descriptor = ProviderDescriptor(
            provider_id=provider_id, port=port, mode=ExecutionMode.DETERMINISTIC
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter: its ID, port, and in-process deterministic execution mode."""
        return self._descriptor

    def _content(self, item: ModalityInput) -> bytes:
        if item.content_ref is None:
            raise LocalProcessingError("binary input requires a content reference")
        data = self._store.read(item.session_id, item.content_ref)
        if len(data) != item.size_bytes:
            raise LocalProcessingError("stored content does not match the input size")
        verify_media_content(item.modality, item.media_type, data)
        return data

    async def _bounded[T](self, work: Callable[[], T]) -> T:
        try:
            return await asyncio.wait_for(asyncio.to_thread(work), timeout=self._limits.timeout_s)
        except TimeoutError as exc:
            raise ProcessingTimeoutError("local processing exceeded the request timeout") from exc


class LocalVisionProvider(_LocalAdapter):
    """``VisionPort`` adapter that decodes images and computes local pixel statistics."""

    def __init__(self, store: SessionContentStore, limits: LocalProcessingLimits) -> None:
        """Create the adapter.

        Args:
            store: Session content store holding staged image bytes.
            limits: Processing limits from application configuration.
        """
        super().__init__(store, limits, LOCAL_VISION_ID, ProviderPort.VISION)

    async def analyze(self, request: VisionRequest) -> VisionResult:
        """Analyze an image and describe its visual properties.

        Args:
            request: Validated vision request.

        Returns:
            Description and observations derived from pixel statistics.

        Raises:
            ContentNotFoundError: If the content reference is unknown or released.
            IngestionError: If the stored bytes do not match the declared media type.
            LocalProcessingError: If the image is malformed, too large, or times out.
        """
        return (await self.inspect(request)).result

    async def inspect(self, request: VisionRequest) -> LocalVisionOutput:
        """Analyze an image and return both the port result and the full analysis.

        Args:
            request: Validated vision request.

        Returns:
            The port result and the structured pixel analysis.

        Raises:
            ContentNotFoundError: If the content reference is unknown or released.
            IngestionError: If the stored bytes do not match the declared media type.
            LocalProcessingError: If the image is malformed, too large, or times out.
        """
        item = request.image
        data = self._content(item)
        analysis = await self._bounded(lambda: analyze_image(data, item.media_type, self._limits))
        return LocalVisionOutput(
            result=VisionResult(
                provider=self.descriptor,
                description=describe_image(analysis),
                observations=_observations(analysis, asked=request.question is not None),
            ),
            analysis=analysis,
        )


class LocalDocumentProvider(_LocalAdapter):
    """``DocumentUnderstandingPort`` adapter that extracts text and structure locally."""

    def __init__(self, store: SessionContentStore, limits: LocalProcessingLimits) -> None:
        """Create the adapter.

        Args:
            store: Session content store holding staged document bytes.
            limits: Processing limits from application configuration.
        """
        super().__init__(store, limits, LOCAL_DOCUMENT_ID, ProviderPort.DOCUMENT_UNDERSTANDING)

    async def understand(self, request: DocumentRequest) -> DocumentResult:
        """Extract a document's title and sections.

        Args:
            request: Validated document request.

        Returns:
            Extracted title and sections.

        Raises:
            ContentNotFoundError: If the content reference is unknown or released.
            IngestionError: If the stored bytes do not match the declared media type.
            LocalProcessingError: If the document is malformed, unsupported, empty, too large,
                or times out.
        """
        return (await self.inspect(request)).result

    async def inspect(self, request: DocumentRequest) -> LocalDocumentOutput:
        """Extract a document and return both the port result and the structural analysis.

        Args:
            request: Validated document request.

        Returns:
            The port result and the structural analysis.

        Raises:
            ContentNotFoundError: If the content reference is unknown or released.
            IngestionError: If the stored bytes do not match the declared media type.
            LocalProcessingError: If the document is malformed, unsupported, empty, too large,
                or times out.
        """
        item = request.document
        data = self._content(item)
        parsed = await self._bounded(lambda: parse_document(data, item.media_type, self._limits))
        return LocalDocumentOutput(
            result=DocumentResult(
                provider=self.descriptor, title=parsed.title, sections=parsed.sections
            ),
            analysis=parsed.analysis,
        )


def describe_image(analysis: ImageAnalysis) -> str:
    """Write a one-paragraph description of an image from its pixel analysis.

    Args:
        analysis: Structured pixel analysis.

    Returns:
        A factual description of dimensions, tone, and dominant colors.
    """
    colors = ", ".join(f"{c.color} {round(c.share * 100)}%" for c in analysis.dominant_colors)
    return (
        f"{analysis.width} x {analysis.height} pixel {analysis.decoder_format} image "
        f"({analysis.orientation}), {analysis.brightness} with {analysis.contrast}. "
        f"Dominant colors: {colors}."
    )


def _observations(analysis: ImageAnalysis, *, asked: bool) -> tuple[str, ...]:
    lines = [
        f"{region.region.capitalize()} region is mostly {region.color} "
        f"({round(region.share * 100)}%)."
        for region in analysis.regions
    ]
    lines.append(f"Detail: {analysis.detail} (edge density {analysis.edge_density}).")
    lines.append(f"Color: {analysis.colorfulness_label} (colorfulness {analysis.colorfulness}).")
    if analysis.has_alpha:
        lines.append(
            f"Has transparency ({round(analysis.transparent_share * 100)}% of analyzed pixels "
            "mostly transparent); analyzed over a white background."
        )
    if analysis.frame_count > 1:
        lines.append(f"Animated with {analysis.frame_count} frames; only the first was analyzed.")
    if asked:
        lines.append("A question was supplied, but local pixel analysis does not answer questions.")
    lines.append(NO_MODEL_NOTE)
    return tuple(lines)
