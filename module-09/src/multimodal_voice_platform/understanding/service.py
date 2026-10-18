"""Image and document understanding service (Story 9.3).

``UnderstandingService`` is the application-facing entry point for Story 9.3. It validates and
stages untrusted bytes, runs them through the local vision or document adapter, and returns an
``UnderstandingRecord`` for every outcome. Intentional failures (``Module9Error``) become safe,
reviewer-visible rejected or failed records; anything else is a defect and propagates.

Content is staged in a store that lives only for one call and is released before the call
returns, so uploaded bytes are never retained after processing (SEC-022).

Story 9.8: a service built with a live vision binding also accepts opted-in live sessions. Images
are still validated and analyzed locally first; the live model's interpretation is then added
beside the local measurements, never instead of them. Documents keep local extraction.

Authority (mode, budget, limits) comes only from the application-owned ``SessionConfig``; content
never changes it.
"""

import time
from typing import Any, Final

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
from multimodal_voice_platform.contracts.live import (
    LiveCall,
    calls_of,
    live_evidence,
    real_call_made,
)
from multimodal_voice_platform.contracts.modality import InputSource, Modality
from multimodal_voice_platform.contracts.providers import (
    DocumentRequest,
    VisionRequest,
    VisionResult,
)
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.ingestion.staging import stage_content
from multimodal_voice_platform.live.bindings import LiveBinding
from multimodal_voice_platform.live.credentials import session_credential
from multimodal_voice_platform.live.errors import LiveProviderError, ProviderOutputError
from multimodal_voice_platform.live.prompts import VISION_QUESTION
from multimodal_voice_platform.understanding.records import (
    LOCAL_EVIDENCE_CLASSES,
    LOCAL_PROCESSING,
    PATH_FOR_MODALITY,
    ProcessingKind,
    StageTiming,
    UnderstandingRecord,
    UnderstandingStatus,
)

_REQUIREMENTS: Final = {
    Modality.IMAGE: ("SRC-002", "ENG-006"),
    Modality.DOCUMENT: ("SRC-004", "ENG-006"),
}
_NO_MODEL: Final = "No model inference, live provider, network, or credential was used."
_FAILED_CODES: Final = frozenset(
    {ErrorCode.PROVIDER_TIMEOUT, ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.INTERNAL_ERROR}
)


class UnderstandingConfigurationError(Module9Error):
    """Raised when application code requests an evidence class local processing cannot produce."""


class LiveUnderstandingUnavailableError(Module9Error):
    """Raised when a live session requests understanding from a service with no live adapter."""

    code = ErrorCode.LIVE_MODE_NOT_AUTHORIZED


class UnderstandingService:
    """Validates, processes, and records image and document understanding. Needs no key."""

    def __init__(
        self,
        catalog: FixtureCatalog | None = None,
        *,
        live_vision: LiveBinding[Any] | None = None,
    ) -> None:
        """Create the service.

        Args:
            catalog: Verified fixture catalog used by ``understand_fixture``. Defaults to the
                packaged committed fixtures.
            live_vision: Live vision binding (Story 9.8), ``factory(credential, store)``. Without
                it, live sessions are refused. Documents always use local extraction.

        Raises:
            FixtureIntegrityError: If the default catalog fails verification.
        """
        self.catalog = catalog if catalog is not None else FixtureCatalog.load_default()
        self._live_vision = live_vision
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

    def _check_evidence_class(self, evidence_class: EvidenceClass, live: bool = False) -> None:
        if live and self._live_vision is not None:
            self._live_vision.check_requested(evidence_class)
            return
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
        live = session.mode is ExecutionMode.LIVE and self._live_vision is not None
        self._check_evidence_class(evidence_class, live)
        timings: list[StageTiming] = []
        store = SessionContentStore()
        model_provider = None
        if live and modality is Modality.IMAGE and self._live_vision is not None:
            model_provider = self._live_vision.build(session_credential(session), store)
        try:
            if session.mode is not ExecutionMode.DETERMINISTIC and not live:
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
                if model_provider is not None:
                    request = VisionRequest(image=item, question=VISION_QUESTION)
                    model_vision = await model_provider.analyze(request)
                    if (
                        not isinstance(model_vision, VisionResult)
                        or model_vision.provider != model_provider.descriptor
                    ):
                        raise ProviderOutputError("the live vision result is not attributed")
                    outputs["model_vision"] = model_vision
                    outputs["model_provider"] = model_provider.descriptor
            else:
                document = await LocalDocumentProvider(store, limits).inspect(
                    DocumentRequest(document=item)
                )
                outputs = {"document": document.result, "document_analysis": document.analysis}
                provider = document.result.provider
                stage = LatencyStage.DOCUMENT_UNDERSTANDING
            timings.append(_timing(stage, started))
        except Module9Error as exc:
            return self._unsuccessful(
                session, modality, exc, timings, evidence_class, live, calls_of(model_provider)
            )
        finally:
            store.release(session.session_id)
        path = PATH_FOR_MODALITY[modality][0]
        record_id = self._next_id()
        calls = calls_of(model_provider)
        processing = LOCAL_PROCESSING
        summary = (
            f"Local {path} of {modality} input {item.input_id} ({item.media_type}) by "
            f"{provider.provider_id}: extraction and structural analysis only."
        )
        if model_provider is not None:
            kind = (
                ProcessingKind.MODEL_INFERENCE
                if model_provider.real_endpoint
                else ProcessingKind.PROVIDER_CONTRACT_TEST_DOUBLE
            )
            processing = (*LOCAL_PROCESSING, kind)
            summary += (
                f" Model interpretation by {model_provider.descriptor.provider_id} ({kind}), kept "
                "separate from the local measurements and untrusted."
            )
        return UnderstandingRecord(
            record_id=record_id,
            session_id=session.session_id,
            status=UnderstandingStatus.SUCCEEDED,
            modality=modality,
            input=item,
            path=path,
            provider=provider,
            processing=processing,
            model_inference_performed=ProcessingKind.MODEL_INFERENCE in processing,
            live_provider_called=real_call_made(calls),
            live_calls=calls,
            timings=tuple(timings),
            evidence=_evidence(
                record_id,
                modality,
                evidence_class,
                f"{summary} {_mode_note(live, calls)}",
                live,
                calls,
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
        live: bool = False,
        calls: tuple[LiveCall, ...] = (),
    ) -> UnderstandingRecord:
        timed_out = isinstance(error, ProcessingTimeoutError) or (
            isinstance(error, LiveProviderError) and error.code in _FAILED_CODES
        )
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
            live_provider_called=real_call_made(calls),
            live_calls=calls,
            evidence=_evidence(
                record_id,
                modality,
                evidence_class,
                f"{modality} input {status} safely with code {safe.code}. "
                f"{_mode_note(live, calls)}",
                live,
                calls,
            ),
        )

    def _next_id(self) -> str:
        self._runs += 1
        return f"und-{self._runs:06d}"


def _timing(stage: LatencyStage, started: float) -> StageTiming:
    return StageTiming(stage=stage, duration_ms=round((time.perf_counter() - started) * 1000, 3))


def _mode_note(live: bool, calls: tuple[LiveCall, ...]) -> str:
    if not live:
        return _NO_MODEL
    real = sum(call.real_endpoint for call in calls)
    if real:
        return f"Live mode: {real} call(s) to the real provider endpoint; no credential recorded."
    if calls:
        return "Live mode over a provider contract test double; no real provider was called."
    return "Live mode, but no provider call was made; only local processing ran."


def _evidence(
    record_id: str,
    modality: Modality,
    evidence_class: EvidenceClass,
    summary: str,
    live: bool = False,
    calls: tuple[LiveCall, ...] = (),
) -> EvidenceRecord:
    if live:
        return live_evidence(
            evidence_id=f"ev-9-8-{record_id}",
            requested=evidence_class,
            calls=calls,
            requirement_ids=_REQUIREMENTS.get(modality, ("ENG-006",)),
            summary=summary,
        )
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
