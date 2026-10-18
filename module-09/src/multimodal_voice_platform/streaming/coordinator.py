"""Streaming coordination for real-time voice turns (Story 9.7).

``StreamingVoiceCoordinator`` is the application-core service behind the WebSocket gateway. It runs
the accepted Story 9.6 voice turn stage by stage and yields a typed update each time a stage
produces something observable, while the turn is still running:

1. admission through the shared ``ConversationStore`` (busy, replay, turn, and budget checks);
2. audio validation, processing, and speech-to-text through the Story 9.4 ``SpeechService``;
3. transcript validation and context construction through the shared Story 9.6 helpers;
4. incremental reasoning through an ``IncrementalReplyPort``: each ``ReplyFragment`` is checked
   (attribution, order, bounds, citations) and yielded as soon as the adapter produces it, before
   any later fragment exists; the assembled reply is then validated as a whole;
5. text-to-speech and generated-audio validation through the Story 9.4 ``SpeechService``;
6. the atomic state commit, then exactly one ``TurnFinished`` update with the record.

Nothing is buffered and re-chunked: a fragment update is yielded while the adapter is suspended
between fragments, so a consumer observes it before the reply is complete. The deterministic
adapter is rule-based conversation reasoning, not model inference, and its fragments are whole
reply acts, not model tokens.

Transaction semantics are the Story 9.6 ones. History changes only at the commit, after every
stage succeeded. A turn that fails after fragments were streamed is recorded as rejected or failed
with ``fragments_streamed`` kept, and history is unchanged. If the consumer stops early (the client
disconnects, the turn times out, or the generator is closed or cancelled), the coordinator's
``finally`` blocks close the reasoning stream, which stops the adapter's work, and release the
session's busy mark; nothing is committed and the turn ID stays unused.

Authority (mode, budgets, limits, adapters, evidence class) comes only from application code.
Session IDs are generated here, so a client never chooses or names one.

Story 9.8: a coordinator built with a live reply binding and a server-side credential source opens
opted-in live sessions. Their turns run live speech recognition, live model reasoning whose reply
fragments are released by the provider adapter as the provider streams them (and are still
citation-checked here before they are yielded), and live speech synthesis whose audio is validated
locally. The credential never comes from a client message.
"""

import asyncio
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import SecretStr, ValidationError

from multimodal_voice_platform.adapters.deterministic.errors import UnknownFixtureError
from multimodal_voice_platform.adapters.reasoning.conversation import (
    DeterministicConversationReasoner,
)
from multimodal_voice_platform.contracts.conversation import (
    AssistantReply,
    IncrementalReplyPort,
    ReplyFragment,
)
from multimodal_voice_platform.contracts.errors import ErrorCode, Module9Error, SafeError
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.live import LiveCall, calls_of, live_evidence
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    ReasoningChunk,
    ReasoningRequest,
)
from multimodal_voice_platform.contracts.reasoning import ObservationView
from multimodal_voice_platform.contracts.session import ExecutionMode, SessionConfig
from multimodal_voice_platform.crossmodal.errors import (
    CrossModalConfigurationError,
    ReasoningOutputError,
    ReasoningProviderTimeoutError,
)
from multimodal_voice_platform.crossmodal.records import RESERVED_REASONING_KINDS, ReasoningKind
from multimodal_voice_platform.live.bindings import LiveBinding
from multimodal_voice_platform.live.credentials import live_session, session_credential
from multimodal_voice_platform.speech.errors import SpeechConfigurationError
from multimodal_voice_platform.speech.records import SpeechRecord, SpeechStage, SpeechStatus
from multimodal_voice_platform.streaming.errors import (
    StreamingConfigurationError,
    StreamingInputError,
)
from multimodal_voice_platform.streaming.limits import StreamingLimits
from multimodal_voice_platform.streaming.records import (
    AudioReadyUpdate,
    MilestoneTiming,
    ResponseCompletedUpdate,
    ResponseFragmentUpdate,
    StageTimedUpdate,
    StreamedTurnRecord,
    StreamMilestone,
    TranscriptReadyUpdate,
    TurnAcceptedUpdate,
    TurnFinished,
    TurnUpdate,
)
from multimodal_voice_platform.voice.errors import (
    ReplyRejectedError,
    TranscriptRejectedError,
    UnknownSessionError,
    VoiceConfigurationError,
)
from multimodal_voice_platform.voice.orchestrator import (
    VoiceAssistant,
    VoiceTurnRequest,
    build_turn_context,
    validate_turn_transcript,
)
from multimodal_voice_platform.voice.records import (
    VOICE_EVIDENCE_CLASSES,
    ConversationContext,
    TranscriptView,
    TurnStatus,
    VoiceStage,
    VoiceTiming,
    VoiceTurnRecord,
)
from multimodal_voice_platform.voice.reply import validate_reply
from multimodal_voice_platform.voice.state import ConversationSnapshot, TurnReservation

_REQUIREMENTS: Final = ("SRC-008", "SRC-009", "SRC-010", "SRC-012", "ENG-006", "ENG-007")
_FAILED_CODES: Final = frozenset(
    {ErrorCode.PROVIDER_TIMEOUT, ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.INTERNAL_ERROR}
)
_RETRYABLE_CODES: Final = frozenset({ErrorCode.PROVIDER_TIMEOUT, ErrorCode.PROVIDER_UNAVAILABLE})
_CONFIGURATION_ERRORS: Final = (
    StreamingConfigurationError,
    VoiceConfigurationError,
    SpeechConfigurationError,
    CrossModalConfigurationError,
)
_TRANSCRIPTION_STAGES: Final = {
    SpeechStage.INGESTION: VoiceStage.AUDIO_VALIDATION,
    SpeechStage.AUDIO_PROCESSING: VoiceStage.AUDIO_PROCESSING,
    SpeechStage.SPEECH_TO_TEXT: VoiceStage.SPEECH_TO_TEXT,
}
_SYNTHESIS_STAGES: Final = {
    SpeechStage.INGESTION: VoiceStage.TEXT_TO_SPEECH,
    SpeechStage.TEXT_TO_SPEECH: VoiceStage.TEXT_TO_SPEECH,
    SpeechStage.OUTPUT_VALIDATION: VoiceStage.OUTPUT_AUDIO_VALIDATION,
}
_LIVE_NOTE: Final = (
    "Live mode: fragments are whole reply acts assembled from provider token deltas and released "
    "as the provider streamed them; provider calls are listed without any credential or payload."
)
_NOT_LIVE: Final = (
    "Fragments are whole rule-based reply acts, not model tokens. No speech recognition, speech "
    "synthesis, language model, live provider, network, or credential was used."
)


@dataclass(frozen=True)
class IncrementalReplyBinding:
    """An incremental reply adapter factory and the kind of reasoning its adapter performs.

    Attributes:
        factory: Builds the adapter for one turn.
        processing: What the adapter does. Model inference is reserved and refused.
    """

    factory: Callable[[], IncrementalReplyPort]
    processing: ReasoningKind

    def __post_init__(self) -> None:
        """Reject reasoning kinds a Story 9.7 adapter cannot honestly claim.

        Raises:
            StreamingConfigurationError: If the kind is reserved.
        """
        if self.processing in RESERVED_REASONING_KINDS:
            raise StreamingConfigurationError("model-based reasoning is not available in 9.7")


class _StageFailed(Exception):
    """An embedded Story 9.4 run ended unsuccessfully; carries its safe error."""

    def __init__(self, error: SafeError) -> None:
        super().__init__(error.message)
        self.error = error


@dataclass
class _Run:
    """Mutable progress of one streamed turn, so failures record exactly what completed."""

    started: float
    stage: VoiceStage = VoiceStage.ADMISSION
    stage_started: float = 0.0
    timings: list[VoiceTiming] = field(default_factory=list)
    milestones: list[MilestoneTiming] = field(default_factory=list)
    transcription: SpeechRecord | None = None
    transcript: TranscriptView | None = None
    reply: AssistantReply | None = None
    synthesis: SpeechRecord | None = None
    reached_reasoning: bool = False
    fragments: int = 0
    response_completed: bool = False
    reasoning_ms: float = 0.0
    validation_ms: float = 0.0
    context: ConversationContext | None = None
    kind: ReasoningKind = ReasoningKind.DETERMINISTIC_RULE_INFERENCE
    live: bool = False
    provider: object = None

    def begin(self, stage: VoiceStage) -> None:
        self.stage = stage
        self.stage_started = time.perf_counter()

    def finish(self) -> VoiceTiming:
        timing = VoiceTiming(stage=self.stage, duration_ms=_elapsed(self.stage_started))
        self.timings.append(timing)
        return timing

    def add(self, stage: VoiceStage, duration_ms: float) -> VoiceTiming:
        timing = VoiceTiming(stage=stage, duration_ms=round(max(0.0, duration_ms), 3))
        self.timings.append(timing)
        return timing

    def mark(self, milestone: StreamMilestone) -> float:
        elapsed = _elapsed(self.started)
        self.milestones.append(MilestoneTiming(milestone=milestone, elapsed_ms=elapsed))
        return elapsed

    def absorb(
        self, record: SpeechRecord, stages: dict[SpeechStage, VoiceStage]
    ) -> list[VoiceTiming]:
        """Adopt an embedded speech run's measured stage timings under voice stage names."""
        totals: dict[VoiceStage, float] = {}
        for timing in record.timings:
            stage = stages[timing.stage]
            totals[stage] = totals.get(stage, 0.0) + timing.duration_ms
        added = [self.add(stage, ms) for stage, ms in totals.items()]
        if record.status is not SpeechStatus.SUCCEEDED and record.failed_stage is not None:
            self.stage = stages[record.failed_stage]
        return added


class StreamingVoiceCoordinator:
    """Runs voice turns incrementally over the accepted Story 9.6 assistant and its state."""

    def __init__(
        self,
        voice: VoiceAssistant | None = None,
        *,
        reply: IncrementalReplyBinding | None = None,
        limits: StreamingLimits | None = None,
        budget: ResourceBudget | None = None,
        session_ids: Callable[[], str] | None = None,
        live_reply: LiveBinding[Any] | None = None,
        live_credential: Callable[[], SecretStr] | None = None,
    ) -> None:
        """Create the coordinator.

        Args:
            voice: The voice assistant whose speech service, limits, and conversation store the
                streamed turns use. Defaults to ``VoiceAssistant()`` over the committed fixtures.
            reply: Incremental reply binding. Defaults to the deterministic conversation reasoner,
                which is rule-based reasoning, not model inference.
            limits: Streaming bounds. Defaults to ``StreamingLimits()``.
            budget: Resource budget bound to every session this coordinator opens.
            session_ids: Session ID generator. Defaults to random ``ws-`` identifiers.
            live_reply: Live incremental reply binding (Story 9.8), ``factory(credential)``.
            live_credential: Server-side source of the live key. With ``live_reply``, every
                session this coordinator opens is an opted-in live session. Never a client value.
        """
        self.voice = voice if voice is not None else VoiceAssistant()
        self.limits = limits if limits is not None else StreamingLimits()
        self.budget = budget if budget is not None else ResourceBudget()
        self._reply = reply or IncrementalReplyBinding(
            factory=DeterministicConversationReasoner,
            processing=ReasoningKind.DETERMINISTIC_RULE_INFERENCE,
        )
        self._session_ids = session_ids or _random_session_id
        self._live_reply = live_reply
        self._live_credential = live_credential
        self._active_turns = 0
        self._runs = 0

    @property
    def active_turns(self) -> int:
        """Streamed turns currently running. Zero whenever no turn generator is open."""
        return self._active_turns

    def open_session(self) -> ConversationSnapshot:
        """Open a conversation with a server-generated session ID and application configuration.

        Returns:
            The new conversation's snapshot.

        Raises:
            DuplicateSessionError: If the generated ID is already active.
            ConversationLimitError: If the active-session bound is reached.
        """
        session_id = self._session_ids()
        if self._live_reply is not None and self._live_credential is not None:
            config = live_session(session_id, self._live_credential(), budget=self.budget)
        else:
            config = SessionConfig(session_id=session_id, budget=self.budget)
        return self.voice.start_session(config)

    def close_session(self, session_id: str) -> ConversationSnapshot | None:
        """Close a conversation and release its history, if it is still active.

        Args:
            session_id: The session to close.

        Returns:
            The closed snapshot, or ``None`` if the session had already closed (for example
            because it expired).
        """
        try:
            return self.voice.end_session(session_id)
        except UnknownSessionError:
            return None

    async def stream_fixture_turn(
        self,
        session_id: str,
        turn_id: str,
        fixture_id: str,
        *,
        language: str | None = None,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> AsyncIterator[TurnUpdate]:
        """Stream a turn over a committed audio fixture the server holds.

        Args:
            session_id: An active session.
            turn_id: Turn ID, unique within the session once committed.
            fixture_id: Untrusted audio fixture ID chosen by the client.
            language: Optional language tag.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Yields:
            The turn's updates; a fixture that is not offered yields one rejected ``TurnFinished``.

        Raises:
            StreamingConfigurationError: If the evidence class or reasoning wiring is invalid.
        """
        try:
            request = self._fixture_request(session_id, turn_id, fixture_id, language)
        except (UnknownFixtureError, StreamingInputError, ValidationError):
            self._check_wiring(evidence_class, session_id)
            error = StreamingInputError("the requested fixture is not an offered audio fixture")
            run = _Run(started=time.perf_counter())
            yield TurnFinished(
                turn_id=turn_id,
                record=self._unsuccessful(
                    session_id, turn_id, run, None, error.to_safe_error(), evidence_class
                ),
            )
            return
        async with aclosing(self.stream_turn(request, evidence_class=evidence_class)) as updates:
            async for update in updates:
                yield update

    async def stream_turn(
        self,
        request: VoiceTurnRequest,
        *,
        evidence_class: EvidenceClass = EvidenceClass.DETERMINISTIC_DEMO,
    ) -> AsyncIterator[TurnUpdate]:
        """Run one voice turn, yielding each observable result as soon as it exists.

        Args:
            request: The untrusted spoken turn. Its session must have been opened by application
                code.
            evidence_class: ``deterministic_demo`` for reviewer runs, ``automated_test`` for tests.

        Yields:
            Updates in pipeline order, ending with exactly one ``TurnFinished``.

        Raises:
            StreamingConfigurationError: If the request type, evidence class, or reasoning wiring
                is invalid.
            SpeechConfigurationError: If the speech service cannot honestly produce the evidence
                class.
        """
        if not isinstance(request, VoiceTurnRequest):
            raise StreamingConfigurationError("streamed turns take a VoiceTurnRequest")
        provider, descriptor, kind, live = self._check_wiring(evidence_class, request.session_id)
        voice = self.voice
        turn_id = request.turn_id
        run = _Run(started=time.perf_counter(), kind=kind, live=live, provider=provider)
        reservation: TurnReservation | None = None
        record: StreamedTurnRecord | None = None
        self._active_turns += 1
        try:
            try:
                run.begin(VoiceStage.ADMISSION)
                reservation = voice.store.begin_turn(request.session_id, turn_id)
                config = reservation.config
                run.finish()
                yield TurnAcceptedUpdate(
                    turn_id=turn_id, elapsed_ms=run.mark(StreamMilestone.TURN_ACCEPTED)
                )
                run.stage = VoiceStage.AUDIO_VALIDATION
                transcription = await voice.speech.transcribe_upload(
                    config,
                    media_type=request.media_type,
                    display_name=request.display_name,
                    data=request.data,
                    language=request.language,
                    evidence_class=evidence_class,
                )
                run.transcription = transcription
                for timing in run.absorb(transcription, _TRANSCRIPTION_STAGES):
                    yield _stage(turn_id, timing)
                if transcription.status is not SpeechStatus.SUCCEEDED and transcription.error:
                    raise _StageFailed(transcription.error)
                result, kind = transcription.transcript, transcription.provider_processing
                if result is None or kind is None:
                    raise TranscriptRejectedError("the transcription produced no transcript")
                run.begin(VoiceStage.TRANSCRIPT_VALIDATION)
                text = validate_turn_transcript(config.session_id, result.text, voice.limits)
                run.transcript = TranscriptView(text=text, processing=kind, chars=len(text))
                run.finish()
                yield TranscriptReadyUpdate(
                    turn_id=turn_id,
                    text=text,
                    processing=kind,
                    elapsed_ms=run.mark(StreamMilestone.TRANSCRIPT_READY),
                )
                run.begin(VoiceStage.CONTEXT_CONSTRUCTION)
                reasoning, view, run.context = build_turn_context(
                    voice.store, voice.limits, voice.observation_limits, config, transcription
                )
                run.finish()
                run.stage = VoiceStage.REASONING
                run.reached_reasoning = True
                fragments: list[ReplyFragment] = []
                stream = self._fragments(provider, descriptor, reasoning, config, run)
                async with aclosing(stream) as incoming:
                    async for fragment in incoming:
                        self._check_fragment(fragment, fragments, view, reasoning, run)
                        fragments.append(fragment)
                        run.fragments = len(fragments)
                        if len(fragments) == 1:
                            elapsed = run.mark(StreamMilestone.FIRST_RESPONSE)
                        else:
                            elapsed = _elapsed(run.started)
                        yield ResponseFragmentUpdate(
                            turn_id=turn_id,
                            index=fragment.index,
                            text=fragment.sentence,
                            elapsed_ms=elapsed,
                        )
                        run.stage = VoiceStage.REASONING
                yield _stage(turn_id, run.add(VoiceStage.REASONING, run.reasoning_ms))
                run.begin(VoiceStage.REPLY_VALIDATION)
                run.reply = self._assemble(fragments, view, reasoning)
                run.add(VoiceStage.REPLY_VALIDATION, run.validation_ms + _ms(run.stage_started))
                run.response_completed = True
                yield ResponseCompletedUpdate(
                    turn_id=turn_id,
                    fragment_count=len(fragments),
                    elapsed_ms=run.mark(StreamMilestone.RESPONSE_COMPLETE),
                )
                run.stage = VoiceStage.TEXT_TO_SPEECH
                synthesis = await voice.speech.synthesize_text(
                    config, run.reply.reply, evidence_class=evidence_class
                )
                run.synthesis = synthesis
                for timing in run.absorb(synthesis, _SYNTHESIS_STAGES):
                    yield _stage(turn_id, timing)
                output = synthesis.synthesis
                if synthesis.status is not SpeechStatus.SUCCEEDED or output is None:
                    if synthesis.error is not None:
                        raise _StageFailed(synthesis.error)
                    raise StreamingConfigurationError("synthesis ended without audio or error")
                yield AudioReadyUpdate(
                    turn_id=turn_id,
                    audio_ref=output.audio.audio_ref,
                    media_type=output.audio.media_type,
                    duration_ms=output.audio.duration_ms,
                    audio_sha256=output.audio_sha256,
                    size_bytes=output.audio_size_bytes,
                    elapsed_ms=run.mark(StreamMilestone.AUDIO_READY),
                )
                run.begin(VoiceStage.STATE_COMMIT)
                snapshot = voice.store.commit(reservation, text, run.reply.reply)
                run.finish()
            except _CONFIGURATION_ERRORS:
                raise
            except Module9Error as exc:
                safe = exc.to_safe_error(retryable=exc.code in _RETRYABLE_CODES)
                record = self._unsuccessful(
                    request.session_id, turn_id, run, descriptor, safe, evidence_class
                )
            except _StageFailed as failure:
                record = self._unsuccessful(
                    request.session_id, turn_id, run, descriptor, failure.error, evidence_class
                )
            finally:
                if reservation is not None:
                    voice.store.release(reservation)
            if record is None:
                record = self._committed(
                    request, run, reservation, snapshot, descriptor, evidence_class
                )
            yield TurnFinished(turn_id=turn_id, record=record)
        finally:
            self._active_turns -= 1

    async def _fragments(
        self,
        provider: IncrementalReplyPort,
        descriptor: ProviderDescriptor,
        request: ReasoningRequest,
        config: SessionConfig,
        run: _Run,
    ) -> AsyncIterator[ReplyFragment]:
        """Pull fragments from the adapter one at a time under the request deadline and bounds.

        Only time spent waiting on the adapter counts toward the deadline and the reasoning
        timing; time the consumer spends delivering a fragment does not. Closing this generator
        closes the adapter's stream.
        """
        stream = provider.stream_reply(request)
        deadline = asyncio.get_running_loop().time() + config.budget.request_timeout_s
        final = False
        count = 0
        chars = 0
        try:
            while True:
                pulled = time.perf_counter()
                try:
                    async with asyncio.timeout_at(deadline):
                        chunk = await anext(stream)
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    raise ReasoningProviderTimeoutError(
                        "reasoning provider exceeded the request timeout"
                    ) from exc
                finally:
                    run.reasoning_ms += _ms(pulled)
                if final:
                    raise ReasoningOutputError("reasoning provider streamed after its final chunk")
                if not isinstance(chunk, ReasoningChunk) or chunk.provider != descriptor:
                    raise ReasoningOutputError(
                        "reasoning provider returned a chunk not attributed to it"
                    )
                if chunk.is_final:
                    if chunk.text:
                        raise ReasoningOutputError("a final reply chunk must carry no fragment")
                    final = True
                    continue
                count += 1
                chars += len(chunk.text)
                if count > self.limits.max_reply_fragments:
                    raise ReasoningOutputError("reasoning provider returned too many fragments")
                if chars > self.voice.limits.max_output_chars:
                    raise ReasoningOutputError("reasoning provider exceeded the output size limit")
                try:
                    fragment = ReplyFragment.model_validate_json(chunk.text)
                except ValidationError as exc:
                    raise ReasoningOutputError(
                        "reasoning provider returned output that is not a valid reply fragment"
                    ) from exc
                if fragment.index != count - 1:
                    raise ReasoningOutputError("reasoning provider returned fragments out of order")
                yield fragment
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()
        if not final:
            raise ReasoningOutputError("reasoning provider ended without a final chunk")

    def _check_fragment(
        self,
        fragment: ReplyFragment,
        accepted: list[ReplyFragment],
        view: ObservationView,
        request: ReasoningRequest,
        run: _Run,
    ) -> None:
        """Validate one fragment's citations and the reply length before it is streamed."""
        started = time.perf_counter()
        run.stage = VoiceStage.REPLY_VALIDATION
        try:
            spoken = " ".join([*(f.sentence for f in accepted), fragment.sentence])
            if len(spoken) > self.voice.limits.max_reply_chars:
                raise ReplyRejectedError("the assistant reply exceeds its length limit")
            single = AssistantReply(schema_version=1, reply=fragment.sentence, acts=(fragment.act,))
            validate_reply(single, view, request.history)
        finally:
            run.validation_ms += _ms(started)

    def _assemble(
        self, fragments: list[ReplyFragment], view: ObservationView, request: ReasoningRequest
    ) -> AssistantReply:
        """Assemble the full reply from its fragments and validate it as a whole."""
        if not fragments:
            raise ReasoningOutputError("reasoning provider produced no reply fragments")
        try:
            reply = AssistantReply(
                schema_version=1,
                reply=" ".join(fragment.sentence for fragment in fragments),
                acts=tuple(fragment.act for fragment in fragments),
            )
        except ValidationError as exc:
            raise ReasoningOutputError("the streamed fragments do not form a valid reply") from exc
        if len(reply.reply) > self.voice.limits.max_reply_chars:
            raise ReplyRejectedError("the assistant reply exceeds its length limit")
        return validate_reply(reply, view, request.history)

    def _check_wiring(
        self, evidence_class: EvidenceClass, session_id: str | None = None
    ) -> tuple[IncrementalReplyPort, ProviderDescriptor, ReasoningKind, bool]:
        live_binding = self._live_reply
        config = None
        if live_binding is not None and session_id is not None:
            try:
                config = self.voice.store.session_config(session_id)
            except UnknownSessionError:
                config = None
        if live_binding is not None and config is not None and config.mode is ExecutionMode.LIVE:
            live_binding.check_requested(evidence_class)
            adapter = live_binding.build(session_credential(config))
            kind = (
                ReasoningKind.MODEL_INFERENCE
                if live_binding.real
                else ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
            )
            return adapter, adapter.descriptor, kind, True
        binding = self._reply
        if evidence_class not in VOICE_EVIDENCE_CLASSES:
            raise StreamingConfigurationError("streamed turns produce only deterministic evidence")
        if (
            binding.processing is ReasoningKind.PROVIDER_CONTRACT_TEST_DOUBLE
            and evidence_class is not EvidenceClass.AUTOMATED_TEST
        ):
            raise StreamingConfigurationError(
                "test-double reasoning produces automated_test evidence only"
            )
        provider = binding.factory()
        descriptor = provider.descriptor
        if descriptor.port is not ProviderPort.REASONING or (
            descriptor.mode is not ExecutionMode.DETERMINISTIC
        ):
            raise StreamingConfigurationError("the reply adapter must be deterministic reasoning")
        return provider, descriptor, binding.processing, False

    def _fixture_request(
        self, session_id: str, turn_id: str, fixture_id: str, language: str | None
    ) -> VoiceTurnRequest:
        catalog = self.voice.catalog
        spec = catalog.get(fixture_id)
        if spec.modality is not Modality.AUDIO:
            raise StreamingInputError("voice turns take audio fixtures")
        return VoiceTurnRequest(
            session_id=session_id,
            turn_id=turn_id,
            media_type=spec.media_type,
            display_name=spec.display_name,
            data=catalog.content(fixture_id),
            language=language,
        )

    def _committed(
        self,
        request: VoiceTurnRequest,
        run: _Run,
        reservation: TurnReservation,
        snapshot: ConversationSnapshot,
        descriptor: ProviderDescriptor,
        evidence_class: EvidenceClass,
    ) -> StreamedTurnRecord:
        run.add(VoiceStage.END_TO_END, _ms(run.started))
        record_id = self._next_id()
        first = next(
            m.elapsed_ms for m in run.milestones if m.milestone is StreamMilestone.FIRST_RESPONSE
        )
        summary = (
            f"Streamed voice turn {request.turn_id} committed as exchange {reservation.sequence} "
            f"of session {request.session_id}: transcript ready, then {run.fragments} reply "
            f"fragment(s) by {descriptor.provider_id} yielded while reasoning was still running "
            f"(first after {first:.3f} ms), then the validated reply, validated output audio, and "
            f"an atomic commit. {_LIVE_NOTE if run.live else _NOT_LIVE}"
        )
        turn = VoiceTurnRecord(
            record_id=record_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            status=TurnStatus.COMMITTED,
            committed=True,
            sequence=reservation.sequence,
            transcription=run.transcription,
            transcript=run.transcript,
            context=run.context,
            reasoning_provider=descriptor,
            reasoning_kind=run.kind,
            reply=run.reply,
            synthesis=run.synthesis,
            conversation=snapshot,
            streaming_performed=True,
            timings=tuple(run.timings),
            live_calls=calls_of(run.provider),
            **_flags(run, run.kind),
            evidence=_evidence(record_id, evidence_class, summary, run),
        )
        return self._record(turn, run)

    def _unsuccessful(
        self,
        session_id: str,
        turn_id: str,
        run: _Run,
        descriptor: ProviderDescriptor | None,
        error: SafeError,
        evidence_class: EvidenceClass,
    ) -> StreamedTurnRecord:
        run.add(VoiceStage.END_TO_END, _ms(run.started))
        status = TurnStatus.FAILED if error.code in _FAILED_CODES else TurnStatus.REJECTED
        reached = run.reached_reasoning and descriptor is not None
        try:
            snapshot: ConversationSnapshot | None = self.voice.store.snapshot(session_id)
        except UnknownSessionError:
            snapshot = None
        record_id = self._next_id()
        summary = (
            f"Streamed voice turn {turn_id} {status} safely at the {run.stage} stage with code "
            f"{error.code} after {run.fragments} reply fragment(s) were streamed; conversation "
            f"history unchanged. {_LIVE_NOTE if run.live else _NOT_LIVE}"
        )
        turn = VoiceTurnRecord(
            record_id=record_id,
            session_id=session_id,
            turn_id=turn_id,
            status=status,
            committed=False,
            transcription=run.transcription,
            transcript=run.transcript,
            context=run.context,
            reasoning_provider=descriptor if reached else None,
            reasoning_kind=run.kind if reached else None,
            reply=run.reply,
            synthesis=run.synthesis,
            conversation=snapshot,
            streaming_performed=True,
            timings=tuple(run.timings),
            failed_stage=run.stage,
            error=error,
            live_calls=calls_of(run.provider),
            **_flags(run, run.kind if reached else None),
            evidence=_evidence(record_id, evidence_class, summary, run),
        )
        return self._record(turn, run)

    def _record(self, turn: VoiceTurnRecord, run: _Run) -> StreamedTurnRecord:
        return StreamedTurnRecord(
            turn=turn,
            fragments_streamed=run.fragments,
            response_completed=run.response_completed,
            milestones=tuple(run.milestones),
        )

    def _next_id(self) -> str:
        self._runs += 1
        return f"str-{self._runs:06d}"


def _stage(turn_id: str, timing: VoiceTiming) -> StageTimedUpdate:
    return StageTimedUpdate(turn_id=turn_id, stage=timing.stage, duration_ms=timing.duration_ms)


def _ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000)


def _elapsed(started: float) -> float:
    return round(_ms(started), 3)


def _random_session_id() -> str:
    return f"ws-{secrets.token_hex(8)}"


def _all_calls(run: _Run) -> tuple[LiveCall, ...]:
    embedded = [record for record in (run.transcription, run.synthesis) if record is not None]
    return (*calls_of(run.provider), *(c for record in embedded for c in record.live_calls))


def _flags(run: _Run, kind: ReasoningKind | None) -> dict[str, bool]:
    transcription, synthesis = run.transcription, run.synthesis
    return {
        "speech_recognition_performed": bool(
            transcription is not None and transcription.speech_recognition_performed
        ),
        "speech_synthesis_performed": bool(
            synthesis is not None and synthesis.speech_synthesis_performed
        ),
        "model_inference_performed": kind is ReasoningKind.MODEL_INFERENCE,
        "live_provider_called": any(call.real_endpoint for call in _all_calls(run)),
    }


def _evidence(
    record_id: str, evidence_class: EvidenceClass, summary: str, run: _Run | None = None
) -> EvidenceRecord:
    if run is not None and run.live:
        return live_evidence(
            evidence_id=f"ev-9-8-{record_id}",
            requested=evidence_class,
            calls=_all_calls(run),
            requirement_ids=_REQUIREMENTS,
            summary=summary,
        )
    return EvidenceRecord(
        evidence_id=f"ev-9-7-{record_id}",
        evidence_class=evidence_class,
        story="9.7",
        requirement_ids=_REQUIREMENTS,
        summary=summary[:1000],
        runtime_executed=True,
        live_provider_executed=False,
        execution_mode=ExecutionMode.DETERMINISTIC,
    )
