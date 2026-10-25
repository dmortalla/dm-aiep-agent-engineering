"""Story 13: truthful dual-mode readiness derived from classified evidence records.

Readiness is computed from application-owned evidence records, never from the
presence of credentials, adapter construction, or in-process test success.
Only an independently evidenced, human-authorized ``live_provider`` record can
mark live-provider readiness; deterministic, mocked, and adapter evidence never
can. No such record exists in this repository, so live readiness is reported as
not executed and not authorized.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.config import HarnessConfig, default_config
from harness_engineering.domain import EvidenceClass


class ReadinessStatus(StrEnum):
    """Finite reviewer-facing readiness outcomes."""

    VERIFIED = "verified"
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    NOT_EXECUTED = "not_executed"
    NOT_CLAIMED = "not_claimed"


class EvidenceRecord(BaseModel):
    """One classified, application-owned evidence fact.

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


# Accepted repository evidence. Deliberately contains no live-provider record.
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
    summary: Annotated[str, Field(max_length=240)]


def provider_readiness(
    records: tuple[EvidenceRecord, ...] = REPOSITORY_EVIDENCE,
    config: HarnessConfig | None = None,
) -> tuple[ReadinessItem, ...]:
    """Derive truthful dual-mode readiness for presentation.

    Args:
        records: Classified evidence; defaults to accepted repository evidence.
        config: Serving configuration; defaults to the deterministic reviewer
            configuration. Credentials are never consulted.

    Returns:
        Readiness items for deterministic, adapter, mocked live-seam, live
        configuration, per-provider live evidence, and provider-level readiness.
    """
    serving = default_config() if config is None else config
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
            summary="Requires trusted server-side configuration and explicit human "
                    "authorization; never enabled from the browser.",
        ),
    ]
    for provider, label in (("openai", "OpenAI"), ("anthropic", "Anthropic")):
        ready = live_provider_ready(records, provider)
        items.append(ReadinessItem(
            capability=f"Live {label} evidence", evidence=EvidenceClass.LIVE_PROVIDER,
            status=ReadinessStatus.VERIFIED if ready else ReadinessStatus.NOT_EXECUTED,
            summary="Independently evidenced authorized live exercise." if ready
            else "Not yet authorized or executed; adapter evidence does not count.",
        ))
    items.append(ReadinessItem(
        capability="Provider-level production readiness", evidence=EvidenceClass.LIVE_PROVIDER,
        status=ReadinessStatus.VERIFIED
        if all(live_provider_ready(records, p) for p in ("openai", "anthropic"))
        else ReadinessStatus.NOT_CLAIMED,
        summary="Claimed only after authorized live exercises are independently evidenced.",
    ))
    return tuple(items)
