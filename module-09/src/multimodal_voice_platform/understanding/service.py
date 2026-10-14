"""Image and document understanding service (Story 9.3).

``UnderstandingService`` is the application-facing entry point for Story 9.3. It validates and
stages untrusted bytes, runs them through the local vision or document adapter, and returns an
``UnderstandingRecord`` for every outcome. Intentional failures (``Module9Error``) become safe,
reviewer-visible rejected or failed records; anything else is a defect and propagates.

Content is staged in a store that lives only for one call and is released before the call
returns, so uploaded bytes are never retained after processing (SEC-022). Authority (mode, budget,
limits) comes only from the application-owned ``SessionConfig``; content never changes it.
"""

import time
from typing import Final

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.deterministic.fixtures import FixtureCatalog
from multimodal_voice_platform.adapters.local.errors import ProcessingTimeoutError
from multimodal_voice_platform.adapters.local.limits import LocalProcessingLimits
from multimodal_voice_platform.adapters.local.providers import (
    LocalDocumentProvider,
    LocalVisionProvider,
)
from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.limits import LatencyStage
from multimodal_voice_platform.contracts.modality import InputSource, Modality
from multimodal_voice_platform.contracts.providers import DocumentRequest, VisionRequest
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.ingestion.staging import stage_content
from multimodal_voice_platform.understanding.records import (
    LOCAL_EVIDENCE_CLASSES,
    LOCAL_PROCESSING,
    PATH_FOR_MODALITY,
    StageTiming,
    UnderstandingRecord,
    UnderstandingStatus,
)

_REQUIREMENTS: Final = {
    Modality.IMAGE: ("SRC-002", "ENG-006"),
    Modality.DOCUMENT: ("SRC-004", "ENG-006"),
}
_NO_MODEL: Final = "No model inference, live provider, network, or credential was used."


class UnderstandingConfigurationError(Module9Error):
    """Raised when application code requests an evidence class local processing cannot produce."""


class LiveUnderstandingUnavailableError(Module9Error):
    """Raised when a live session requests understanding. Live adapters are Story 9.8."""

    code = ErrorCode.LIVE_MODE_NOT_AUTHORIZED


class UnderstandingService:
    """Validates, processes, and records image and document understanding. Needs no key."""

    def __init__(self, catalog: FixtureCatalog | None = None) -> None:
        """Create the service.

        Args:
            catalog: Verified fixture catalog used by ``understand_fixture``. Defaults to the
                packaged committed fixtures.

        Raises:
            FixtureIntegrityError: If the default catalog fails verification.
        """
        self.catalog = catalog if catalog is not None else FixtureCatalog.load_default()
        self._runs = 0

    async def understand_upload(
        self,
        session: SessionConfig,
        *,
        modality: Modality,
        media_type: str,
        display_name: str,
        data: bytes,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> UnderstandingRecord:
        """Validate and process one untrusted upload.

        Args:
            session: Application-owned session configuration.
            modality: Modality the upload is submitted as (image or document).
            media_type: Declared media type. Verified against the content.
            display_name: Untrusted file name.
            data: Untrusted content bytes.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            A succeeded, rejected, or failed record.

        Raises:
            UnderstandingConfigurationError: If the evidence class is not a local class.
        """
        return await self._run(
            session,
            modality=modality,
            media_type=media_type,
            display_name=display_name,
            data=data,
            source=InputSource.USER_UPLOAD,
            evidence_class=evidence_class,
        )

    async def understand_fixture(
        self,
        session: SessionConfig,
        fixture_id: str,
        *,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> UnderstandingRecord:
        """Process a committed fixture's bytes through the genuine local path.

        Unlike Story 9.2 fixture playback, nothing scripted is replayed: the fixture bytes are
        decoded and analyzed exactly as an upload would be.

        Args:
            session: Application-owned session configuration.
            fixture_id: Fixture ID from the committed catalog.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            A succeeded, rejected, or failed record.

        Raises:
            UnderstandingConfigurationError: If the evidence class is not a local class.
            UnknownFixtureError: If the fixture ID is not in the catalog. Fixture IDs come from
                application code, so an unknown ID is a defect rather than untrusted input.
        """
        spec = self.catalog.get(fixture_id)
        return await self._run(
            session,
            modality=spec.modality,
            media_type=spec.media_type,
            display_name=spec.display_name,
            data=self.catalog.content(fixture_id),
            source=InputSource.DETERMINISTIC_FIXTURE,
            evidence_class=evidence_class,
        )

    @staticmethod
    def _check_evidence_class(evidence_class: EvidenceClass) -> None:
        if evidence_class not in LOCAL_EVIDENCE_CLASSES:
            raise UnderstandingConfigurationError(
                "local understanding produces only deterministic evidence"
            )

    async def _run(
        self,
        session: SessionConfig,
        *,
        modality: Modality,
        media_type: str,
        display_name: str,
        data: bytes,
        source: InputSource,
        evidence_class: EvidenceClass,
    ) -> UnderstandingRecord:
        self._check_evidence_class(evidence_class)
        timings: list[StageTiming] = []
        store = SessionContentStore()
        try:
            if session.mode is not ExecutionMode.DETERMINISTIC:
                raise LiveUnderstandingUnavailableError(
                    "live understanding providers are not available; use deterministic mode"
                )
            started = time.perf_counter()
            item = stage_content(
                store,
                session_id=session.session_id,
                budget=session.budget,
                modality=modality,
                media_type=media_type,
                display_name=display_name,
                data=data,
                source=source,
            )
            timings.append(_timing(LatencyStage.INGESTION, started))
            limits = LocalProcessingLimits.from_budget(session.budget)
            started = time.perf_counter()
            if modality is Modality.IMAGE:
                vision = await LocalVisionProvider(store, limits).inspect(VisionRequest(image=item))
                outputs: dict[str, object] = {
                    "vision": vision.result,
                    "image_analysis": vision.analysis,
                }
                provider = vision.result.provider
                stage = LatencyStage.VISION
            else:
                document = await LocalDocumentProvider(store, limits).inspect(
                    DocumentRequest(document=item)
                )
                outputs = {"document": document.result, "document_analysis": document.analysis}
                provider = document.result.provider
                stage = LatencyStage.DOCUMENT_UNDERSTANDING
            timings.append(_timing(stage, started))
        except Module9Error as exc:
            return self._unsuccessful(session, modality, exc, timings, evidence_class)
        finally:
            store.release(session.session_id)
        path = PATH_FOR_MODALITY[modality][0]
        record_id = self._next_id()
        return UnderstandingRecord(
            record_id=record_id,
            session_id=session.session_id,
            status=UnderstandingStatus.SUCCEEDED,
            modality=modality,
            input=item,
            path=path,
            provider=provider,
            processing=LOCAL_PROCESSING,
            timings=tuple(timings),
            evidence=_evidence(
                record_id,
                modality,
                evidence_class,
                f"Local {path} of {modality} input {item.input_id} ({item.media_type}) by "
                f"{provider.provider_id}: extraction and structural analysis only. {_NO_MODEL}",
            ),
            **outputs,
        )

    def _unsuccessful(
        self,
        session: SessionConfig,
        modality: Modality,
        error: Module9Error,
        timings: list[StageTiming],
        evidence_class: EvidenceClass,
    ) -> UnderstandingRecord:
        timed_out = isinstance(error, ProcessingTimeoutError)
        status = UnderstandingStatus.FAILED if timed_out else UnderstandingStatus.REJECTED
        record_id = self._next_id()
        safe = error.to_safe_error(retryable=timed_out)
        return UnderstandingRecord(
            record_id=record_id,
            session_id=session.session_id,
            status=status,
            modality=modality,
            timings=tuple(timings),
            error=safe,
            evidence=_evidence(
                record_id,
                modality,
                evidence_class,
                f"{modality} input {status} safely with code {safe.code}. {_NO_MODEL}",
            ),
        )

    def _next_id(self) -> str:
        self._runs += 1
        return f"und-{self._runs:06d}"


def _timing(stage: LatencyStage, started: float) -> StageTiming:
    return StageTiming(stage=stage, duration_ms=round((time.perf_counter() - started) * 1000, 3))


def _evidence(
    record_id: str, modality: Modality, evidence_class: EvidenceClass, summary: str
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"ev-9-3-{record_id}",
        evidence_class=evidence_class,
        story="9.3",
        requirement_ids=_REQUIREMENTS.get(modality, ("ENG-006",)),
        summary=summary,
        runtime_executed=True,
        live_provider_executed=False,
        execution_mode=ExecutionMode.DETERMINISTIC,
    )
