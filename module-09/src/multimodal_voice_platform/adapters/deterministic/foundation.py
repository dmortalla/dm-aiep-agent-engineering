"""No-key deterministic execution of committed fixtures through the provider ports (ENG-001).

``DeterministicFoundation`` stages a committed fixture as a validated ``ModalityInput``, runs it
through the matching deterministic adapter, and returns a typed, evidence-classified record that a
later reviewer-facing layer can display. It is a single-fixture harness. Modality routing,
cross-modal reasoning, and voice orchestration belong to later stories.
"""

from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.deterministic.errors import (
    DeterministicInputError,
    FixtureBudgetError,
    FixtureIntegrityError,
)
from multimodal_voice_platform.adapters.deterministic.fixtures import (
    FixtureCatalog,
    FixtureSpec,
    Sha256Hex,
)
from multimodal_voice_platform.adapters.deterministic.providers import (
    DeterministicDocumentProvider,
    DeterministicSpeechToTextProvider,
    DeterministicVisionProvider,
)
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import (
    Identifier,
    InputSource,
    Modality,
    ModalityInput,
)
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
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig

DETERMINISTIC_EVIDENCE_CLASSES: Final = frozenset(
    {EvidenceClass.AUTOMATED_TEST, EvidenceClass.DETERMINISTIC_DEMO}
)
"""The only evidence classes deterministic execution may produce."""

_PORT_FOR_MODALITY: Final = {
    Modality.IMAGE: ProviderPort.VISION,
    Modality.DOCUMENT: ProviderPort.DOCUMENT_UNDERSTANDING,
    Modality.AUDIO: ProviderPort.SPEECH_TO_TEXT,
}


class DeterministicRunRecord(BaseModel):
    """Typed, reviewer-displayable record of one deterministic fixture run.

    Records which fixture ran, its modality, the validated input, which deterministic adapter
    executed (``None`` for text, which no provider port processes), the typed output, and the
    evidence class. ``live_provider_called`` is always ``False``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: Identifier
    fixture_sha256: Sha256Hex
    modality: Modality
    input: ModalityInput
    provider: ProviderDescriptor | None
    vision: VisionResult | None = None
    document: DocumentResult | None = None
    transcript: tuple[TranscriptSegment, ...] = ()
    live_provider_called: Literal[False] = False
    evidence: EvidenceRecord

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        """Keep the record internally consistent and its evidence honest.

        Returns:
            The validated record.

        Raises:
            ValueError: If the provider, outputs, or evidence contradict the modality or claim
                anything other than deterministic, non-live execution.
        """
        if self.input.modality is not self.modality:
            raise ValueError("record modality must match its input")
        expected_port = _PORT_FOR_MODALITY.get(self.modality)
        actual_port = self.provider.port if self.provider else None
        if actual_port is not expected_port:
            raise ValueError(f"{self.modality} records require the {expected_port} port")
        if self.provider is not None and self.provider.mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("deterministic records require a deterministic provider")
        outputs = {
            Modality.IMAGE: self.vision is not None,
            Modality.DOCUMENT: self.document is not None,
            Modality.AUDIO: bool(self.transcript),
        }
        if any(present != (modality is self.modality) for modality, present in outputs.items()):
            raise ValueError(f"{self.modality} record carries the wrong outputs")
        results = [*self.transcript, *(r for r in (self.vision, self.document) if r is not None)]
        if any(result.provider != self.provider for result in results):
            raise ValueError("every output must be attributed to the record's provider")
        if self.evidence.evidence_class not in DETERMINISTIC_EVIDENCE_CLASSES:
            raise ValueError("deterministic records allow only deterministic evidence classes")
        if self.evidence.execution_mode is not ExecutionMode.DETERMINISTIC:
            raise ValueError("deterministic records require deterministic execution mode")
        if self.evidence.live_provider_executed:
            raise ValueError("deterministic records never execute a live provider")
        return self


class DeterministicFoundation:
    """Stages and runs committed fixtures through deterministic adapters. Needs no key."""

    def __init__(
        self,
        catalog: FixtureCatalog | None = None,
        store: SessionContentStore | None = None,
    ) -> None:
        """Create the foundation.

        Args:
            catalog: Verified fixture catalog. Defaults to the packaged committed fixtures.
            store: Session content store. Defaults to a new empty store.

        Raises:
            FixtureIntegrityError: If the default catalog fails verification.
        """
        self.catalog = catalog if catalog is not None else FixtureCatalog.load_default()
        self.store = store if store is not None else SessionContentStore()
        self.vision = DeterministicVisionProvider(self.catalog, self.store)
        self.document = DeterministicDocumentProvider(self.catalog, self.store)
        self.speech_to_text = DeterministicSpeechToTextProvider(self.catalog, self.store)

    def stage(self, session: SessionConfig, fixture_id: str) -> ModalityInput:
        """Validate a committed fixture against the session and normalize it into an input.

        Text is carried inline. Binary content is placed in the session content store and carried
        by opaque reference.

        Args:
            session: Application-owned session configuration. Must be deterministic.
            fixture_id: Fixture ID from the catalog.

        Returns:
            The validated, untrusted ``ModalityInput``.

        Raises:
            DeterministicInputError: If the session is not deterministic or the input fails
                contract validation.
            UnknownFixtureError: If the fixture ID is not in the catalog.
            FixtureBudgetError: If the fixture exceeds the session budget.
            FixtureIntegrityError: If a text fixture is not valid UTF-8.
        """
        if session.mode is not ExecutionMode.DETERMINISTIC:
            raise DeterministicInputError("deterministic fixtures require a deterministic session")
        spec = self.catalog.get(fixture_id)
        _enforce_budget(spec, session.budget)
        content = self.catalog.content(fixture_id)
        input_id = f"{spec.fixture_id}-input"
        fields: dict[str, object] = {}
        if spec.modality is Modality.TEXT:
            try:
                fields["text"] = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise FixtureIntegrityError("text fixture is not valid UTF-8") from exc
        else:
            fields["content_ref"] = self.store.put(session.session_id, input_id, content)
        try:
            return ModalityInput(
                input_id=input_id,
                session_id=session.session_id,
                modality=spec.modality,
                media_type=spec.media_type,
                source=InputSource.DETERMINISTIC_FIXTURE,
                size_bytes=spec.size_bytes,
                display_name=spec.display_name,
                duration_ms=spec.duration_ms,
                page_count=spec.page_count,
                **fields,
            )
        except ValidationError as exc:
            raise DeterministicInputError("fixture failed modality input validation") from exc

    async def run(
        self,
        session: SessionConfig,
        fixture_id: str,
        *,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> DeterministicRunRecord:
        """Stage one fixture and run it through its deterministic adapter.

        Args:
            session: Application-owned session configuration. Must be deterministic.
            fixture_id: Fixture ID from the catalog.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            The typed, evidence-classified run record.

        Raises:
            DeterministicInputError: If the evidence class is not deterministic, or staging or
                playback rejects the input.
        """
        if evidence_class not in DETERMINISTIC_EVIDENCE_CLASSES:
            raise DeterministicInputError("deterministic runs produce only deterministic evidence")
        item = self.stage(session, fixture_id)
        spec = self.catalog.get(fixture_id)
        provider: ProviderDescriptor | None = None
        outputs: dict[str, object] = {}
        if item.modality is Modality.IMAGE:
            provider = self.vision.descriptor
            outputs["vision"] = await self.vision.analyze(VisionRequest(image=item))
        elif item.modality is Modality.DOCUMENT:
            provider = self.document.descriptor
            outputs["document"] = await self.document.understand(DocumentRequest(document=item))
        elif item.modality is Modality.AUDIO:
            provider = self.speech_to_text.descriptor
            request = TranscriptionRequest(audio=item)
            outputs["transcript"] = tuple(
                [segment async for segment in self.speech_to_text.transcribe(request)]
            )
        executor = provider.provider_id if provider else "text passthrough (no provider port)"
        evidence = EvidenceRecord(
            evidence_id=f"ev-9-2-{spec.fixture_id}",
            evidence_class=evidence_class,
            story="9.2",
            requirement_ids=("ENG-001",),
            summary=(
                f"Deterministic fixture playback of {spec.fixture_id} ({spec.modality}) by "
                f"{executor}. No model, live provider, network, or credential was used."
            ),
            runtime_executed=True,
            live_provider_executed=False,
            execution_mode=ExecutionMode.DETERMINISTIC,
        )
        return DeterministicRunRecord(
            fixture_id=spec.fixture_id,
            fixture_sha256=spec.sha256,
            modality=spec.modality,
            input=item,
            provider=provider,
            evidence=evidence,
            **outputs,
        )

    def release(self, session_id: str) -> int:
        """Delete all staged content for a session.

        Args:
            session_id: Session to release.

        Returns:
            How many content references were deleted.
        """
        return self.store.release(session_id)


def _enforce_budget(spec: FixtureSpec, budget: ResourceBudget) -> None:
    limits = {
        Modality.IMAGE: budget.max_image_bytes,
        Modality.AUDIO: budget.max_audio_bytes,
        Modality.DOCUMENT: budget.max_document_bytes,
    }
    limit = limits.get(spec.modality)
    if limit is not None and spec.size_bytes > limit:
        raise FixtureBudgetError(f"{spec.modality} fixture exceeds the session byte budget")
    if spec.duration_ms is not None and spec.duration_ms > budget.max_audio_duration_ms:
        raise FixtureBudgetError("audio fixture exceeds the session duration budget")
    if spec.page_count is not None and spec.page_count > budget.max_document_pages:
        raise FixtureBudgetError("document fixture exceeds the session page budget")
