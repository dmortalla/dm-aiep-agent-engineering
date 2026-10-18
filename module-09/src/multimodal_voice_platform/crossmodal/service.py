"""Cross-modal reasoning workflow (Story 9.5).

``CrossModalWorkflow`` is the application-facing entry point for Story 9.5. One run:

1. validates the request (input count, per-modality count, at least two distinct modalities,
   aggregate size, duplicate content, provider-call budget, deterministic mode);
2. routes each input to its accepted processing path: text validation, the Story 9.3
   ``UnderstandingService`` for images and documents, or the Story 9.4 ``SpeechService`` for audio
   (analysis, or transcription when requested);
3. normalizes every successful result into a ``ModalityObservation`` in canonical order, so the
   result does not depend on submission order;
4. builds one bounded ``CrossModalContext`` and a ``ReasoningRequest`` with a fixed task;
5. runs the bound ``ReasoningPort`` adapter under the request timeout with bounded output;
6. validates every finding's citations against the context and derives the conclusion;
7. returns a ``CrossModalRecord`` for every outcome.

The default reasoning adapter is ``DeterministicCrossModalReasoner``: rule-based inference that is
not model inference. Inputs that fail processing are recorded and excluded; the run continues as
``partial`` if at least two modalities remain. Intentional failures (``Module9Error``) become safe
rejected or failed records; configuration defects and any other exception propagate.

Each processing call stages content in its own store and releases it before returning (SEC-022).
Authority (mode, budgets, limits, adapters) comes only from application code and the
application-owned ``SessionConfig``; content and reasoning output never change it.
"""

import asyncio
import hashlib
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from multimodal_voice_platform.adapters.deterministic.fixtures import FixtureCatalog
from multimodal_voice_platform.adapters.reasoning.rule_reasoner import (
    DeterministicCrossModalReasoner,
)
from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error, SafeError
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.limits import MAX_TEXT_CHARS
from multimodal_voice_platform.contracts.live import (
    LiveCall,
    calls_of,
    live_evidence,
    real_call_made,
)
from multimodal_voice_platform.contracts.modality import Modality, ModalityInput
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    ReasoningChunk,
    ReasoningPort,
    ReasoningRequest,
)
from multimodal_voice_platform.contracts.reasoning import CrossModalFinding
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.crossmodal.context import (
    ContextStats,
    build_context,
    reasoning_request,
)
from multimodal_voice_platform.crossmodal.errors import (
    CrossModalConfigurationError,
    CrossModalInputError,
    CrossModalLimitError,
    InsufficientModalitiesError,
    LiveReasoningUnavailableError,
    ReasoningOutputError,
    ReasoningProviderTimeoutError,
)
from multimodal_voice_platform.crossmodal.findings import (
    CrossModalConclusion,
    conclude,
    parse_reasoner_output,
    validate_findings,
)
from multimodal_voice_platform.crossmodal.limits import CrossModalLimits
from multimodal_voice_platform.crossmodal.observations import (
    ModalityObservation,
    observe_speech,
    observe_text,
    observe_understanding,
)
from multimodal_voice_platform.crossmodal.records import (
    CROSS_MODAL_EVIDENCE_CLASSES,
    RESERVED_REASONING_KINDS,
    CrossModalRecord,
    CrossModalStage,
    CrossModalStatus,
    CrossModalTiming,
    ModalityOutcome,
    OutcomeStatus,
    ReasoningKind,
)
from multimodal_voice_platform.ingestion.errors import IngestionError
from multimodal_voice_platform.live.bindings import LiveBinding
from multimodal_voice_platform.live.credentials import session_credential
from multimodal_voice_platform.speech.errors import SpeechConfigurationError
from multimodal_voice_platform.speech.records import SpeechRecord, SpeechStatus
from multimodal_voice_platform.speech.service import SpeechService
from multimodal_voice_platform.speech.text_input import stage_text_input
from multimodal_voice_platform.understanding.records import (
    UnderstandingRecord,
    UnderstandingStatus,
)
from multimodal_voice_platform.understanding.service import (
    UnderstandingConfigurationError,
    UnderstandingService,
)

_REQUIREMENTS: Final = ("SRC-005", "SRC-015", "ENG-006")
_MODALITY_ORDER: Final = {modality: index for index, modality in enumerate(Modality)}
_FAILED_CODES: Final = frozenset(
    {ErrorCode.PROVIDER_TIMEOUT, ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.INTERNAL_ERROR}
)
_RETRYABLE_CODES: Final = frozenset({ErrorCode.PROVIDER_TIMEOUT, ErrorCode.PROVIDER_UNAVAILABLE})
_CONFIGURATION_ERRORS: Final = (
    CrossModalConfigurationError,
    SpeechConfigurationError,
    UnderstandingConfigurationError,
)
_KIND_NOTES: Final = {
    ReasoningKind.DETERMINISTIC_RULE_INFERENCE: (
        "Rule-based deterministic reasoning over a closed vocabulary; not model inference."
    ),
    ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE: (
        "The reasoning provider was a contract test double; no reasoning model ran."
    ),
}
_NO_LIVE: Final = "No language or multimodal model, live provider, network, or credential was used."
_LIVE_KIND_NOTES: Final = {
    ReasoningKind.MODEL_INFERENCE: (
        "Live model reasoning; every cited statement and fact was checked by the application."
    ),
}
_OUTCOME_STATUS: Final = {
    UnderstandingStatus.SUCCEEDED: OutcomeStatus.PROCESSED,
    UnderstandingStatus.REJECTED: OutcomeStatus.REJECTED,
    UnderstandingStatus.FAILED: OutcomeStatus.FAILED,
    SpeechStatus.SUCCEEDED: OutcomeStatus.PROCESSED,
    SpeechStatus.REJECTED: OutcomeStatus.REJECTED,
    SpeechStatus.FAILED: OutcomeStatus.FAILED,
}


class ModalitySubmission(BaseModel):
    """One untrusted input supplied to the workflow.

    Text is supplied inline. Image, document, and audio content is supplied as bytes with a
    declared media type and display name, both verified downstream. ``data`` is excluded from
    serialization and repr so raw content is never echoed or retained in records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    modality: Modality
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT_CHARS)
    media_type: str | None = Field(default=None, min_length=1, max_length=100)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    data: bytes | None = Field(default=None, min_length=1, exclude=True, repr=False)
    transcribe: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        """Require exactly the fields the modality uses.

        Returns:
            The validated submission.

        Raises:
            ValueError: If text input carries binary fields, binary input lacks bytes, media type,
                or display name or carries text, or a non-audio input asks for transcription.
        """
        binary = (self.media_type, self.display_name, self.data)
        if self.modality is Modality.TEXT:
            if self.text is None or any(value is not None for value in binary):
                raise ValueError("text submissions carry inline text only")
        elif self.text is not None or any(value is None for value in binary):
            raise ValueError(f"{self.modality} submissions carry bytes, media type, and name")
        if self.transcribe and self.modality is not Modality.AUDIO:
            raise ValueError("only audio submissions can be transcribed")
        return self

    @property
    def size_bytes(self) -> int:
        """Size of the supplied content in bytes (UTF-8 for text)."""
        return len(self.data) if self.data is not None else len((self.text or "").encode("utf-8"))

    @property
    def digest(self) -> str:
        """SHA-256 of the supplied content, used to reject duplicate inputs."""
        content = self.data if self.data is not None else (self.text or "").encode("utf-8")
        return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ReasoningBinding:
    """A reasoning adapter factory and the kind of reasoning its adapter performs.

    Attributes:
        factory: Builds the adapter for one run.
        processing: What the adapter does. Model inference is reserved and refused.
    """

    factory: Callable[[], ReasoningPort]
    processing: ReasoningKind

    def __post_init__(self) -> None:
        """Reject reasoning kinds a Story 9.5 adapter cannot honestly claim.

        Raises:
            CrossModalConfigurationError: If the kind is reserved.
        """
        if self.processing in RESERVED_REASONING_KINDS:
            raise CrossModalConfigurationError("model-based reasoning is not available in 9.5")


@dataclass
class _Processed:
    """Result of routing one submission to its processing path."""

    position: int
    modality: Modality
    status: OutcomeStatus
    item: ModalityInput | None = None
    text_ms: float = 0.0
    understanding: UnderstandingRecord | None = None
    speech: SpeechRecord | None = None
    error: SafeError | None = None


@dataclass
class _Run:
    """Mutable progress of one run, so failures record exactly what completed."""

    stage: CrossModalStage = CrossModalStage.VALIDATION
    started: float = 0.0
    timings: list[CrossModalTiming] = field(default_factory=list)
    outcomes: list[ModalityOutcome] = field(default_factory=list)
    observations: list[ModalityObservation] = field(default_factory=list)
    context: ContextStats | None = None

    def begin(self, stage: CrossModalStage) -> None:
        self.stage = stage
        self.started = time.perf_counter()

    def finish(self) -> None:
        self.timings.append(CrossModalTiming(stage=self.stage, duration_ms=_elapsed(self.started)))


class CrossModalWorkflow:
    """Relates text, image, document, and audio inputs in one bounded reasoning run."""

    def __init__(
        self,
        catalog: FixtureCatalog | None = None,
        *,
        limits: CrossModalLimits | None = None,
        reasoning: ReasoningBinding | None = None,
        understanding: UnderstandingService | None = None,
        speech: SpeechService | None = None,
        live_reasoning: LiveBinding[Any] | None = None,
    ) -> None:
        """Create the workflow.

        Args:
            catalog: Verified fixture catalog shared with the default processing services.
                Defaults to the packaged committed fixtures.
            limits: Workflow bounds. Defaults to ``CrossModalLimits()``.
            reasoning: Reasoning binding. Defaults to the deterministic rule-based reasoner.
            understanding: Image and document service. Defaults to the Story 9.3 service.
            speech: Audio service. Defaults to the Story 9.4 service (fixture-playback STT).
            live_reasoning: Live reasoning binding (Story 9.8), ``factory(credential)``. Without
                it, live sessions are refused. Live runs also need live-capable understanding and
                speech services for the modalities they process.

        Raises:
            FixtureIntegrityError: If the default catalog fails verification.
        """
        self.catalog = catalog if catalog is not None else FixtureCatalog.load_default()
        self.limits = limits if limits is not None else CrossModalLimits()
        self.understanding = understanding or UnderstandingService(self.catalog)
        self.speech = speech or SpeechService(self.catalog)
        max_findings = self.limits.max_findings
        self._reasoning = reasoning or ReasoningBinding(
            factory=lambda: DeterministicCrossModalReasoner(max_findings=max_findings),
            processing=ReasoningKind.DETERMINISTIC_RULE_INFERENCE,
        )
        self._live_reasoning = live_reasoning
        self._runs = 0

    async def run(
        self,
        session: SessionConfig,
        submissions: Sequence[ModalitySubmission],
        *,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> CrossModalRecord:
        """Process the submissions and reason across them.

        Args:
            session: Application-owned session configuration.
            submissions: Untrusted inputs from at least two distinct modalities.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Returns:
            A succeeded, partial, rejected, or failed record.

        Raises:
            CrossModalConfigurationError: If the evidence class or reasoning wiring is invalid.
        """
        live_binding = self._live_reasoning if session.mode is ExecutionMode.LIVE else None
        if live_binding is not None:
            live_binding.check_requested(evidence_class)
            provider = live_binding.build(session_credential(session))
            kind = (
                ReasoningKind.MODEL_INFERENCE
                if live_binding.real
                else ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
            )
        else:
            binding = self._reasoning
            self._check_evidence_class(evidence_class, binding.processing)
            provider = binding.factory()
            kind = binding.processing
        live = live_binding is not None
        descriptor = provider.descriptor
        expected_mode = ExecutionMode.LIVE if live else ExecutionMode.DETERMINISTIC
        if descriptor.port is not ProviderPort.REASONING or descriptor.mode is not expected_mode:
            raise CrossModalConfigurationError(f"the reasoning adapter must be {expected_mode}")
        run = _Run()
        started = time.perf_counter()
        try:
            run.begin(CrossModalStage.VALIDATION)
            if session.mode is not ExecutionMode.DETERMINISTIC and not live:
                raise LiveReasoningUnavailableError(
                    "live reasoning providers are not available; use deterministic mode"
                )
            items = self._validate(session, submissions)
            run.finish()
            run.begin(CrossModalStage.MODALITY_PROCESSING)
            processed = [
                await self._process(session, position, item, evidence_class)
                for position, item in enumerate(items)
            ]
            self._observe(run, processed)
            if len({obs.view.modality for obs in run.observations}) < 2:
                raise InsufficientModalitiesError(
                    "fewer than two modalities were processed successfully"
                )
            run.finish()
            run.begin(CrossModalStage.CONTEXT_CONSTRUCTION)
            context = build_context([obs.view for obs in run.observations], self.limits)
            request = reasoning_request(context, session)
            run.context = context.stats
            run.finish()
            run.begin(CrossModalStage.REASONING)
            text = await collect_reasoning_output(
                provider, request, descriptor, session.budget.request_timeout_s, self.limits
            )
            run.finish()
            run.begin(CrossModalStage.OUTPUT_VALIDATION)
            output = parse_reasoner_output(text, self.limits)
            findings = validate_findings(output, context)
            conclusion = conclude(findings, truncated=output.truncated)
            run.finish()
        except _CONFIGURATION_ERRORS:
            raise
        except Module9Error as exc:
            run.timings.append(
                CrossModalTiming(stage=CrossModalStage.END_TO_END, duration_ms=_elapsed(started))
            )
            return self._unsuccessful(
                session, run, exc, evidence_class, live, calls_of(provider)
            )
        run.timings.append(
            CrossModalTiming(stage=CrossModalStage.END_TO_END, duration_ms=_elapsed(started))
        )
        return self._succeeded(
            session,
            run,
            descriptor,
            kind,
            findings,
            conclusion,
            evidence_class,
            live,
            calls_of(provider),
        )

    @staticmethod
    def _check_evidence_class(evidence_class: EvidenceClass, kind: ReasoningKind) -> None:
        if evidence_class not in CROSS_MODAL_EVIDENCE_CLASSES:
            raise CrossModalConfigurationError(
                "cross-modal runs produce only deterministic evidence"
            )
        if (
            kind is ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
            and evidence_class is not EvidenceClass.AUTOMATED_TEST
        ):
            raise CrossModalConfigurationError(
                "test-double reasoning produces automated_test evidence only"
            )

    def _validate(
        self, session: SessionConfig, submissions: Sequence[ModalitySubmission]
    ) -> tuple[ModalitySubmission, ...]:
        if isinstance(submissions, str | bytes) or not isinstance(submissions, Sequence):
            raise CrossModalInputError("submissions must be a sequence of modality submissions")
        if any(not isinstance(item, ModalitySubmission) for item in submissions):
            raise CrossModalInputError("every submission must be a modality submission")
        limits = self.limits
        if len(submissions) > limits.max_items:
            raise CrossModalLimitError(f"at most {limits.max_items} inputs are allowed per run")
        counts = Counter(item.modality for item in submissions)
        if counts and max(counts.values()) > limits.max_items_per_modality:
            raise CrossModalLimitError(
                f"at most {limits.max_items_per_modality} inputs of one modality are allowed"
            )
        if len(counts) < 2:
            raise InsufficientModalitiesError("at least two distinct modalities are required")
        if sum(item.size_bytes for item in submissions) > limits.max_aggregate_bytes:
            raise CrossModalLimitError("the inputs exceed the aggregate size limit")
        digests = [item.digest for item in submissions]
        if len(set(digests)) != len(digests):
            raise CrossModalInputError("the same content was supplied more than once")
        calls = sum(1 for item in submissions if item.modality is not Modality.TEXT) + 1
        if calls > session.budget.max_provider_calls_per_session:
            raise CrossModalLimitError("the run would exceed the session provider-call budget")
        return tuple(submissions)

    async def _process(
        self,
        session: SessionConfig,
        position: int,
        item: ModalitySubmission,
        evidence_class: EvidenceClass,
    ) -> _Processed:
        modality = item.modality
        if modality is Modality.TEXT:
            started = time.perf_counter()
            try:
                staged = stage_text_input(session.session_id, item.text or "")
            except IngestionError as exc:
                return _Processed(
                    position, modality, OutcomeStatus.REJECTED, error=exc.to_safe_error()
                )
            return _Processed(
                position,
                modality,
                OutcomeStatus.PROCESSED,
                item=staged,
                text_ms=_elapsed(started),
            )
        upload = {
            "media_type": item.media_type or "",
            "display_name": item.display_name or "",
            "data": item.data or b"",
            "evidence_class": evidence_class,
        }
        if modality is Modality.AUDIO:
            if item.transcribe:
                speech = await self.speech.transcribe_upload(session, **upload)
            else:
                speech = await self.speech.analyze_audio_upload(session, **upload)
            return _Processed(
                position,
                modality,
                _OUTCOME_STATUS[speech.status],
                item=speech.input,
                speech=speech,
                error=speech.error,
            )
        record = await self.understanding.understand_upload(session, modality=modality, **upload)
        return _Processed(
            position,
            modality,
            _OUTCOME_STATUS[record.status],
            item=record.input,
            understanding=record,
            error=record.error,
        )

    def _observe(self, run: _Run, processed: list[_Processed]) -> None:
        """Assign canonical observation IDs and normalize every processed input."""
        usable = sorted(
            (
                (entry, entry.item)
                for entry in processed
                if entry.status is OutcomeStatus.PROCESSED and entry.item is not None
            ),
            key=lambda pair: (
                _MODALITY_ORDER[pair[0].modality],
                pair[1].input_id,
                pair[0].position,
            ),
        )
        assigned: dict[int, str] = {}
        limits = self.limits
        for number, (entry, item) in enumerate(usable, start=1):
            oid = f"obs-{number}"
            assigned[entry.position] = oid
            if entry.understanding is not None:
                observation = observe_understanding(oid, entry.understanding, limits)
            elif entry.speech is not None:
                observation = observe_speech(oid, entry.speech, limits)
            else:
                observation = observe_text(oid, item, limits, entry.text_ms)
            run.observations.append(observation)
        for entry in processed:
            run.outcomes.append(
                ModalityOutcome(
                    position=entry.position,
                    modality=entry.modality,
                    status=entry.status,
                    observation_id=assigned.get(entry.position),
                    text_input=entry.item if entry.modality is Modality.TEXT else None,
                    understanding=entry.understanding,
                    speech=entry.speech,
                    error=entry.error,
                )
            )

    def _succeeded(
        self,
        session: SessionConfig,
        run: _Run,
        descriptor: ProviderDescriptor,
        kind: ReasoningKind,
        findings: tuple[CrossModalFinding, ...],
        conclusion: CrossModalConclusion,
        evidence_class: EvidenceClass,
        live: bool = False,
        calls: tuple[LiveCall, ...] = (),
    ) -> CrossModalRecord:
        partial = any(o.status is not OutcomeStatus.PROCESSED for o in run.outcomes)
        status = CrossModalStatus.PARTIAL if partial else CrossModalStatus.SUCCEEDED
        record_id = self._next_id()
        present = {obs.view.modality for obs in run.observations}
        modalities = ", ".join(m.value for m in Modality if m in present)
        context = run.context
        summary = (
            f"Cross-modal workflow over {modalities} ({len(run.observations)} observations"
            f"{', partial' if partial else ''}): local modality processing, a bounded context of "
            f"{context.context_chars if context else 0} characters, and {descriptor.provider_id} "
            f"({kind}) produced {len(findings)} cited findings, {conclusion.cross_modal_findings} "
            f"relating two or more modalities; conclusion {conclusion.consistency}. "
            f"{_LIVE_KIND_NOTES.get(kind) or _KIND_NOTES[kind]} "
            f"{_mode_note(live, _all_calls(run, calls))}"
        )
        return CrossModalRecord(
            record_id=record_id,
            session_id=session.session_id,
            status=status,
            outcomes=tuple(run.outcomes),
            observations=tuple(run.observations),
            context=context,
            reasoning_provider=descriptor,
            reasoning_kind=kind,
            findings=findings,
            conclusion=conclusion,
            timings=tuple(run.timings),
            model_inference_performed=kind is ReasoningKind.MODEL_INFERENCE,
            live_provider_called=real_call_made(_all_calls(run, calls)),
            live_calls=calls,
            evidence=_evidence(record_id, evidence_class, summary, live, _all_calls(run, calls)),
        )

    def _unsuccessful(
        self,
        session: SessionConfig,
        run: _Run,
        error: Module9Error,
        evidence_class: EvidenceClass,
        live: bool = False,
        calls: tuple[LiveCall, ...] = (),
    ) -> CrossModalRecord:
        failed = error.code in _FAILED_CODES
        status = CrossModalStatus.FAILED if failed else CrossModalStatus.REJECTED
        safe = error.to_safe_error(retryable=error.code in _RETRYABLE_CODES)
        record_id = self._next_id()
        return CrossModalRecord(
            record_id=record_id,
            session_id=session.session_id,
            status=status,
            outcomes=tuple(run.outcomes),
            observations=tuple(run.observations),
            context=run.context,
            timings=tuple(run.timings),
            failed_stage=run.stage,
            error=safe,
            live_provider_called=real_call_made(_all_calls(run, calls)),
            live_calls=calls,
            evidence=_evidence(
                record_id,
                evidence_class,
                f"Cross-modal workflow {status} safely at the {run.stage} stage with code "
                f"{safe.code}. {_mode_note(live, _all_calls(run, calls))}",
                live,
                _all_calls(run, calls),
            ),
        )

    def _next_id(self) -> str:
        self._runs += 1
        return f"xmr-{self._runs:06d}"


async def collect_reasoning_output(
    provider: ReasoningPort,
    request: ReasoningRequest,
    descriptor: ProviderDescriptor,
    timeout_s: float,
    limits: CrossModalLimits,
) -> str:
    """Collect a reasoning provider's chunk stream under the timeout and output bounds.

    Shared by the cross-modal workflow (Story 9.5) and the voice assistant (Story 9.6), so every
    reasoning call is bounded and attributed the same way.

    Args:
        provider: The bound reasoning adapter.
        request: The validated reasoning request.
        descriptor: The adapter's descriptor; every chunk must carry it.
        timeout_s: Request timeout from the application-owned session budget.
        limits: Output chunk and character bounds.

    Returns:
        The concatenated chunk text, which is still untrusted and unparsed.

    Raises:
        ReasoningOutputError: If a chunk is misattributed, streams after the final chunk, or the
            output exceeds its bounds or never ends with a final chunk.
        ReasoningProviderTimeoutError: If the provider exceeds the request timeout.
    """
    stream = provider.stream_reason(request)
    pieces: list[str] = []
    total = 0
    final = False
    try:
        async with asyncio.timeout(timeout_s):
            async for chunk in stream:
                if final:
                    raise ReasoningOutputError("reasoning provider streamed after its final chunk")
                if not isinstance(chunk, ReasoningChunk) or chunk.provider != descriptor:
                    raise ReasoningOutputError(
                        "reasoning provider returned a chunk not attributed to it"
                    )
                if len(pieces) >= limits.max_output_chunks:
                    raise ReasoningOutputError("reasoning provider returned too many chunks")
                total += len(chunk.text)
                if total > limits.max_output_chars:
                    raise ReasoningOutputError("reasoning provider exceeded the output size limit")
                pieces.append(chunk.text)
                final = chunk.is_final
    except TimeoutError as exc:
        raise ReasoningProviderTimeoutError(
            "reasoning provider exceeded the request timeout"
        ) from exc
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()
    if not final:
        raise ReasoningOutputError("reasoning provider ended without a final chunk")
    return "".join(pieces)


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _all_calls(run: _Run, calls: tuple[LiveCall, ...]) -> tuple[LiveCall, ...]:
    embedded = [
        call
        for outcome in run.outcomes
        for record in (outcome.understanding, outcome.speech)
        if record is not None
        for call in record.live_calls
    ]
    return (*calls, *embedded)


def _mode_note(live: bool, calls: tuple[LiveCall, ...]) -> str:
    if not live:
        return _NO_LIVE
    real = sum(call.real_endpoint for call in calls)
    if real:
        return f"Live mode: {real} call(s) to the real provider endpoint; no credential recorded."
    if calls:
        return "Live mode over provider contract test doubles; no real provider was called."
    return "Live mode, but no provider call was made; only local processing ran."


def _evidence(
    record_id: str,
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
            requirement_ids=_REQUIREMENTS,
            summary=summary,
        )
    return EvidenceRecord(
        evidence_id=f"ev-9-5-{record_id}",
        evidence_class=evidence_class,
        story="9.5",
        requirement_ids=_REQUIREMENTS,
        summary=summary[:1000],
        runtime_executed=True,
        live_provider_executed=False,
        execution_mode=ExecutionMode.DETERMINISTIC,
    )

