"""Story 13: truthful dual-mode readiness derived from classified evidence records.

Readiness is computed from repository-owned evidence records, never from the
presence of credentials, adapter construction, or in-process test success.
Only an independently reviewed, human-authorized ``live_provider`` record can
mark live-provider evidence; deterministic, mocked, and adapter evidence never
can. The runtime never imports or consults this module: it reports at most
``adapter`` for itself, and promotion to ``live_provider`` happens only here,
as a recorded outcome of independent review of an external, hash-pinned artifact.
Live-provider evidence is not deployment validation, an SLA, billing accuracy,
or universal provider validation.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.config import HarnessConfig, default_config
from harness_engineering.domain import EvidenceClass


class ReadinessStatus(StrEnum):
    """Finite reviewer-facing readiness outcomes."""

    VERIFIED = "verified"
    ACCEPTED = "accepted"
    CONFIGURED = "configured"
    PENDING = "pending"
    NOT_CONFIGURED = "not_configured"
    NOT_EXECUTED = "not_executed"
    NOT_CLAIMED = "not_claimed"


class EvidenceRecord(BaseModel):
    """One classified, repository-owned evidence fact.

    Attributes:
        evidence: Evidence class; the taxonomy is unchanged by Story 13.
        subject: Provider or capability the record concerns.
        basis: Verifiable basis (test module, commit, or durable record).
        authorization_reference: Required for, and only for, live-provider
            records: the separate human live-execution authorization.
        independent_review: Required for live-provider records: the independent
            evidence review that accepted the exercise.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence: EvidenceClass
    subject: Literal["fake", "openai", "anthropic"]
    basis: Annotated[str, Field(min_length=1, max_length=256)]
    authorization_reference: Annotated[str, Field(min_length=8, max_length=256)] | None = None
    independent_review: Annotated[str, Field(min_length=8, max_length=256)] | None = None

    @model_validator(mode="after")
    def validate_live_provenance(self) -> Self:
        """Bind live-provider class to human authorization and independent review.

        Returns:
            The validated record.

        Raises:
            ValueError: If a live-provider record lacks provenance, or a lower
                class claims live provenance it cannot have.
        """
        live = self.evidence is EvidenceClass.LIVE_PROVIDER
        provenance = (self.authorization_reference, self.independent_review)
        if live and None in provenance:
            raise ValueError("live-provider evidence requires authorization and review")
        if live and self.subject == "fake":
            raise ValueError("the deterministic fake cannot produce live-provider evidence")
        if not live and provenance != (None, None):
            raise ValueError("only live-provider evidence carries live provenance")
        return self


REVIEW_DISPOSITION = "ACCEPTED — LIVE_PROVIDER EVIDENCE VERIFIED"


class AcceptedLiveExercise(BaseModel):
    """Sanitized structural and accounting facts of one independently accepted live run.

    The raw artifact stays external and immutable; this record pins it by SHA256
    and baseline commit. It deliberately has no field for response text, reasoning
    content, credentials, or raw provider errors, so none can be stored here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: Literal["openai", "anthropic"]
    model: Annotated[str, Field(min_length=1, max_length=128)]
    run_reference: Annotated[str, Field(min_length=8, max_length=128)]
    baseline_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    artifact_name: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{8,200}\.json$")]
    artifact_sha256: Annotated[str, Field(pattern=r"^[0-9A-F]{64}$")]
    review_disposition: Literal["ACCEPTED — LIVE_PROVIDER EVIDENCE VERIFIED"]
    status: Literal["success"]
    attempts: Annotated[int, Field(ge=1, le=1)]
    retries: Annotated[int, Field(ge=0, le=0)]
    input_tokens: Annotated[int, Field(ge=0, le=512)]
    output_tokens: Annotated[int, Field(ge=0, le=256)]
    returned_text_bytes: Annotated[int, Field(ge=1, le=4096)]
    cache_creation_input_tokens: Annotated[int, Field(ge=0, le=0)] | None = None
    cache_read_input_tokens: Annotated[int, Field(ge=0, le=0)] | None = None
    live_exposure_usd: Decimal
    max_cost_usd: Decimal

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """Require recorded exposure to be positive and within the approved cap.

        Returns:
            The validated record.

        Raises:
            ValueError: If exposure is non-positive or exceeds the recorded cap.
        """
        if not Decimal(0) < self.live_exposure_usd <= self.max_cost_usd:
            raise ValueError("live exposure must be positive and within the approved cap")
        return self

    def as_evidence_record(self) -> EvidenceRecord:
        """Return the classified evidence record this accepted exercise establishes.

        Returns:
            A ``live_provider`` record whose provenance is the human authorization
            run reference and the independent review disposition.
        """
        return EvidenceRecord(
            evidence=EvidenceClass.LIVE_PROVIDER,
            subject=self.provider,
            basis=f"external artifact {self.artifact_name} sha256 {self.artifact_sha256}",
            authorization_reference=f"{self.run_reference}-{self.provider}",
            independent_review=self.review_disposition,
        )


_THIRD_RUN = {
    "run_reference": "module-06-5-third-live-20261027-002708",
    "baseline_commit": "e1e5e1ac5f931f95a146c85baaace40cc3357230",
    "artifact_name": "module-06-5-third-live-evidence-20261027-002708.json",
    "artifact_sha256": "389287FC65C9F51F84850E2D2929C50EC21FDEC4B70BC902FD0CE65100D7FCF4",
    "review_disposition": REVIEW_DISPOSITION,
    "status": "success",
    "attempts": 1,
    "retries": 0,
    "max_cost_usd": Decimal("0.001"),
}

# Bounds of the accepted run: max_context_tokens=512, max_output_tokens=256,
# max_output_bytes=4096, max_cost_usd=0.001 per provider, one attempt, zero
# retries, action timeout 20 s. Two earlier attempts failed and are recorded in
# docs/STORY_13.md; they are not evidence of success.
ACCEPTED_LIVE_EXERCISES: tuple[AcceptedLiveExercise, ...] = (
    AcceptedLiveExercise(
        provider="openai", model="gpt-6-luna", input_tokens=20, output_tokens=39,
        returned_text_bytes=27, live_exposure_usd=Decimal("0.0000215"), **_THIRD_RUN,
    ),
    AcceptedLiveExercise(
        provider="anthropic", model="claude-haiku-5-5", input_tokens=35, output_tokens=27,
        returned_text_bytes=86, cache_creation_input_tokens=0, cache_read_input_tokens=0,
        live_exposure_usd=Decimal("0.0000170"), **_THIRD_RUN,
    ),
)

# Accepted repository evidence, by class.
REPOSITORY_EVIDENCE: tuple[EvidenceRecord, ...] = (
    EvidenceRecord(evidence=EvidenceClass.DETERMINISTIC, subject="fake",
                   basis="tests/test_providers.py; reviewer labs; no credentials"),
    EvidenceRecord(evidence=EvidenceClass.ADAPTER, subject="openai",
                   basis="tests/test_vendor_providers.py: genuine SDK over MockTransport"),
    EvidenceRecord(evidence=EvidenceClass.ADAPTER, subject="anthropic",
                   basis="tests/test_vendor_providers.py: genuine SDK over MockTransport"),
    EvidenceRecord(evidence=EvidenceClass.MOCKED, subject="openai",
                   basis="tests/test_story13_dual_mode.py: live seam, patched SDK resource"),
    EvidenceRecord(evidence=EvidenceClass.MOCKED, subject="anthropic",
                   basis="tests/test_story13_dual_mode.py: live seam, patched SDK resource"),
    *(exercise.as_evidence_record() for exercise in ACCEPTED_LIVE_EXERCISES),
)


def live_provider_ready(records: tuple[EvidenceRecord, ...], provider: str) -> bool:
    """Return whether a provider has independently evidenced live execution.

    Args:
        records: Classified evidence records.
        provider: Catalogued provider name.

    Returns:
        True only for a validated live-provider record for that provider.
        Deterministic, mocked, adapter, local-integration, and deployment
        records never satisfy live-provider readiness.
    """
    return any(
        type(record) is EvidenceRecord
        and record.evidence is EvidenceClass.LIVE_PROVIDER
        and record.subject == provider
        for record in records
    )


class ReadinessItem(BaseModel):
    """One inert reviewer-facing readiness line."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    capability: Annotated[str, Field(max_length=80)]
    evidence: EvidenceClass | None
    status: ReadinessStatus
    summary: Annotated[str, Field(max_length=360)]


def _accepted_summary(provider: str) -> str:
    """Summarize the accepted exercise for a provider from its sanitized record."""
    exercise = next(e for e in ACCEPTED_LIVE_EXERCISES if e.provider == provider)
    return (
        f"Independently accepted bounded exercise: {exercise.model}, one attempt, no retry, "
        f"{exercise.input_tokens}/{exercise.output_tokens} tokens, "
        f"{exercise.returned_text_bytes}-byte reply, exposure ${exercise.live_exposure_usd:f} "
        f"(artifact sha256 {exercise.artifact_sha256[:12]}…). Not an SLA or billing validation."
    )


def live_evidence_caption(records: tuple[EvidenceRecord, ...] | None = None) -> str:
    """Return the reviewer caption about live-provider evidence, from records only.

    The text asserts live-provider evidence only for providers that have a validated
    live-provider record; with none it states that none is recorded. It never
    asserts anything independently of the evidence records.

    Args:
        records: Classified evidence; defaults to the repository records, read at
            call time.

    Returns:
        A fixed-template caption naming only providers with recorded evidence.
    """
    chosen = REPOSITORY_EVIDENCE if records is None else records
    ready = [p for p in ("openai", "anthropic") if live_provider_ready(chosen, p)]
    if not ready:
        return (
            "Evidence classes stay separate. No accepted live-provider evidence is recorded; "
            "deterministic, mocked and adapter evidence never count as live-provider evidence."
        )
    return (
        "Evidence classes stay separate; deterministic, mocked and adapter evidence never "
        f"count as live-provider evidence. Live-provider evidence is recorded for "
        f"{' and '.join(ready)}: one bounded, human-authorized exercise each (one attempt, no "
        "retries, fixed token, byte, time and cost caps), from an independently reviewed "
        "external artifact; it was not run by this page and is not deployment validation."
    )


def provider_readiness(
    records: tuple[EvidenceRecord, ...] | None = None,
    config: HarnessConfig | None = None,
) -> tuple[ReadinessItem, ...]:
    """Derive truthful dual-mode readiness for presentation.

    Args:
        records: Classified evidence; defaults to the repository evidence, read at
            call time so presentation always follows the authoritative records.
        config: Serving configuration; defaults to the deterministic reviewer
            configuration. Credentials are never consulted.

    Returns:
        Readiness items for deterministic, adapter, mocked live-seam, live
        configuration, per-provider live evidence, deployment, and provider-level
        production readiness.
    """
    serving = default_config() if config is None else config
    records = REPOSITORY_EVIDENCE if records is None else records
    classes = {record.evidence for record in records if type(record) is EvidenceRecord}

    def verified(evidence: EvidenceClass) -> ReadinessStatus:
        return ReadinessStatus.VERIFIED if evidence in classes else ReadinessStatus.NOT_EXECUTED

    items = [
        ReadinessItem(
            capability="Deterministic no-key mode", evidence=EvidenceClass.DETERMINISTIC,
            status=verified(EvidenceClass.DETERMINISTIC),
            summary="Default reviewer mode; fixed local fake provider, no credentials or cost.",
        ),
        ReadinessItem(
            capability="Provider adapter readiness", evidence=EvidenceClass.ADAPTER,
            status=verified(EvidenceClass.ADAPTER),
            summary="Genuine OpenAI and Anthropic SDK adapters over in-memory HTTP only.",
        ),
        ReadinessItem(
            capability="Secure live seam (credential-free)", evidence=EvidenceClass.MOCKED,
            status=verified(EvidenceClass.MOCKED),
            summary="Allowlists, trusted credentials, authorization and bounds verified "
                    "offline with patched SDK resources; not a live call.",
        ),
        ReadinessItem(
            # A configuration fact, not evidence of any class.
            capability="Live mode in this deployment", evidence=None,
            status=ReadinessStatus.CONFIGURED if serving.live is not None
            else ReadinessStatus.NOT_CONFIGURED,
            summary="This reviewer never runs live providers; live mode requires trusted "
                    "server-side configuration and explicit human authorization, never "
                    "browser input.",
        ),
    ]
    for provider, label in (("openai", "OpenAI"), ("anthropic", "Anthropic")):
        ready = live_provider_ready(records, provider)
        items.append(ReadinessItem(
            capability=f"Live {label} evidence", evidence=EvidenceClass.LIVE_PROVIDER,
            status=ReadinessStatus.ACCEPTED if ready else ReadinessStatus.NOT_EXECUTED,
            summary=_accepted_summary(provider) if ready
            else "Not yet authorized or executed; adapter evidence does not count.",
        ))
    items.append(ReadinessItem(
        capability="Deployment verification", evidence=EvidenceClass.DEPLOYMENT,
        status=ReadinessStatus.PENDING,
        summary="Not verified: live-provider evidence does not validate the hosted deployment.",
    ))
    items.append(ReadinessItem(
        capability="Provider-level production readiness", evidence=EvidenceClass.LIVE_PROVIDER,
        status=ReadinessStatus.NOT_CLAIMED,
        summary="Not claimed: bounded live evidence is not universal provider validation, an "
                "SLA, billing accuracy beyond the run, deployment, or scale readiness.",
    ))
    return tuple(items)
