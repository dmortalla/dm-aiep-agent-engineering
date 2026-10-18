"""Provider-neutral live-execution contracts and the live evidence ladder (Story 9.8).

Every live provider adapter, whatever its vendor, reports each provider call as a ``LiveCall``:
which capability it served, the configured model identifier it used, whether it reached the real
provider endpoint or a contract test double, its outcome, latency, a provider request identifier
when one is safe to keep, and bounded usage quantities. No credential, prompt, payload, or provider
response body is ever part of a ``LiveCall``.

The evidence ladder is application-owned and enforced here:

- a run in which any call reached the real provider endpoint is ``live_integration`` evidence;
- a run whose live adapter talked only to a contract test double (a mocked transport) is
  ``automated_test`` evidence with live execution mode, and can never be ``live_integration``;
- a live-mode run that was rejected before any provider call executed only deterministic local
  processing, so it is ``deterministic_demo`` (reviewer runs) or ``automated_test`` (tests) evidence
  with deterministic execution mode.

Every live-mode record is Story 9.8 evidence.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.evidence import EvidenceClass, EvidenceRecord
from multimodal_voice_platform.contracts.modality import Identifier
from multimodal_voice_platform.contracts.session import ExecutionMode

LIVE_STORY: Final = "9.8"
MAX_LIVE_CALLS: Final = 8
"""Most provider calls one record may report."""
MAX_USAGE_QUANTITY: Final = 10_000_000

ModelId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:-]{0,79}$")]
"""A provider model identifier from application configuration, such as ``gpt-5.4-mini``."""
RequestId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
"""A provider request or response correlation identifier. Never a secret."""

LIVE_REQUESTABLE_CLASSES: Final = frozenset(
    {EvidenceClass.LIVE_INTEGRATION, EvidenceClass.AUTOMATED_TEST}
)
"""What application code may request for a live-mode run: real provider or contract double."""


class LiveCapability(StrEnum):
    """Which provider capability a live call served."""

    VISION = "vision"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    REASONING = "reasoning"


class ProviderUsage(BaseModel):
    """Bounded, provider-neutral usage quantities reported by the provider. No cost estimate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = Field(default=None, ge=0, le=MAX_USAGE_QUANTITY)
    output_tokens: int | None = Field(default=None, ge=0, le=MAX_USAGE_QUANTITY)
    reasoning_tokens: int | None = Field(default=None, ge=0, le=MAX_USAGE_QUANTITY)
    total_tokens: int | None = Field(default=None, ge=0, le=MAX_USAGE_QUANTITY)
    audio_seconds: float | None = Field(default=None, ge=0, le=86_400, allow_inf_nan=False)
    input_characters: int | None = Field(default=None, ge=0, le=MAX_USAGE_QUANTITY)


class LiveCall(BaseModel):
    """Non-secret evidence of one provider call made by a live adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_family: Identifier
    capability: LiveCapability
    model: ModelId
    real_endpoint: bool
    streamed: bool = False
    outcome: Literal["succeeded", "failed", "cancelled"]
    failure: ErrorCode | None = None
    request_id: RequestId | None = None
    usage: ProviderUsage | None = None
    latency_ms: float = Field(ge=0, le=3_600_000, allow_inf_nan=False)
    first_output_ms: float | None = Field(default=None, ge=0, le=3_600_000, allow_inf_nan=False)
    output_events: int = Field(default=0, ge=0, le=100_000)


class ReportsLiveCalls(Protocol):
    """A live adapter: whether it talks to the real endpoint, and the calls it made."""

    @property
    def real_endpoint(self) -> bool:
        """Whether the adapter's transport is the real provider endpoint."""
        ...

    @property
    def live_calls(self) -> tuple[LiveCall, ...]:
        """The calls this adapter instance made, in order."""
        ...


def calls_of(provider: object) -> tuple[LiveCall, ...]:
    """Return the live calls an adapter reports, or nothing for a deterministic adapter.

    Args:
        provider: Any adapter instance.

    Returns:
        Its ``live_calls``, validated as ``LiveCall`` instances, or an empty tuple.
    """
    calls = getattr(provider, "live_calls", ())
    return tuple(call for call in calls if isinstance(call, LiveCall))


def live_evidence(
    *,
    evidence_id: str,
    requested: EvidenceClass,
    calls: Iterable[LiveCall],
    requirement_ids: tuple[str, ...],
    summary: str,
) -> EvidenceRecord:
    """Classify a live-mode run by what actually executed.

    Args:
        evidence_id: Identifier for the evidence record.
        requested: ``live_integration`` (real adapters) or ``automated_test`` (contract doubles).
        calls: Every provider call made in the run, including embedded runs.
        requirement_ids: Requirements the run bears on.
        summary: Human-readable summary. Never contains credentials or payloads.

    Returns:
        The evidence record.

    Raises:
        ValueError: If the requested class is not a live-requestable class.
    """
    if requested not in LIVE_REQUESTABLE_CLASSES:
        raise ValueError("live-mode runs request live_integration or automated_test evidence")
    made = tuple(calls)
    real = any(call.real_endpoint for call in made)
    if real:
        evidence_class, mode = EvidenceClass.LIVE_INTEGRATION, ExecutionMode.LIVE
    elif made:
        evidence_class, mode = EvidenceClass.AUTOMATED_TEST, ExecutionMode.LIVE
    elif requested is EvidenceClass.LIVE_INTEGRATION:
        evidence_class, mode = EvidenceClass.DETERMINISTIC_DEMO, ExecutionMode.DETERMINISTIC
    else:
        evidence_class, mode = EvidenceClass.AUTOMATED_TEST, ExecutionMode.DETERMINISTIC
    return EvidenceRecord(
        evidence_id=evidence_id,
        evidence_class=evidence_class,
        story=LIVE_STORY,
        requirement_ids=requirement_ids,
        summary=summary[:1000],
        runtime_executed=True,
        live_provider_executed=real,
        execution_mode=mode,
    )


def check_live_evidence(evidence: EvidenceRecord, calls: Iterable[LiveCall]) -> None:
    """Validate a live-mode record's evidence against the calls it reports.

    Args:
        evidence: The record's evidence.
        calls: Every provider call the record and its embedded records report.

    Raises:
        ValueError: If the evidence claims more, or less, than the calls show.
    """
    made = tuple(calls)
    real = any(call.real_endpoint for call in made)
    if evidence.story != LIVE_STORY:
        raise ValueError("live-mode records are Story 9.8 evidence")
    if real:
        if evidence.evidence_class is not EvidenceClass.LIVE_INTEGRATION:
            raise ValueError("a run that reached the real provider is live_integration evidence")
    elif made:
        if (
            evidence.evidence_class is not EvidenceClass.AUTOMATED_TEST
            or evidence.execution_mode is not ExecutionMode.LIVE
        ):
            raise ValueError("contract-double live runs are automated_test evidence in live mode")
    elif evidence.evidence_class not in {
        EvidenceClass.AUTOMATED_TEST,
        EvidenceClass.DETERMINISTIC_DEMO,
    } or (evidence.execution_mode is not ExecutionMode.DETERMINISTIC):
        raise ValueError("a live-mode run with no provider call ran deterministic processing only")


def real_call_made(calls: Iterable[LiveCall]) -> bool:
    """Whether any call reached the real provider endpoint.

    Args:
        calls: Provider calls.

    Returns:
        ``True`` if at least one call was made to the real endpoint.
    """
    return any(call.real_endpoint for call in calls)
