"""Validate untrusted reasoning output against its context, and derive the conclusion.

Reasoning output is ``untrusted_model_output`` whichever adapter produced it. Before anything is
recorded, every finding's citations are checked against the context it claims to rest on: cited
observations, statements, and facts must exist; every quote must appear in its statement; verdict
facts must measure the claimed property in a different observation; shared terms must occur in both
observations. A single bad citation rejects the whole output.

The conclusion is computed here from validated findings, never accepted from the provider.
"""

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.reasoning import (
    MAX_FINDINGS,
    VERDICT_KINDS,
    CrossModalFinding,
    FindingKind,
    ReasonerOutput,
)
from multimodal_voice_platform.crossmodal.context import CrossModalContext
from multimodal_voice_platform.crossmodal.errors import ReasoningOutputError
from multimodal_voice_platform.crossmodal.limits import CrossModalLimits

_NOT_MODEL: Final = "Rule-based deterministic reasoning, not model inference."


class Consistency(StrEnum):
    """Overall assessment of how the supplied modalities relate."""

    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    MIXED = "mixed"
    UNVERIFIED = "unverified"


class CrossModalConclusion(BaseModel):
    """Counts and an overall assessment derived from validated findings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    consistency: Consistency
    corroborated: int = Field(ge=0)
    contradicted: int = Field(ge=0)
    claim_conflicts: int = Field(ge=0)
    claim_agreements: int = Field(ge=0)
    unverified_claims: int = Field(ge=0)
    shared_concepts: int = Field(ge=0)
    cross_modal_findings: int = Field(ge=0)
    modalities_relied_on: tuple[Modality, ...] = ()
    findings_truncated: bool = False
    statement: str = Field(min_length=1, max_length=1000)


def parse_reasoner_output(text: str, limits: CrossModalLimits) -> ReasonerOutput:
    """Parse the provider's streamed document into the typed output contract.

    Args:
        text: The concatenated chunk text.
        limits: Workflow bounds.

    Returns:
        The typed output.

    Raises:
        ReasoningOutputError: If the text is not a valid findings document or has too many
            findings. The provider's payload is never echoed.
    """
    try:
        output = ReasonerOutput.model_validate_json(text)
    except ValidationError as exc:
        raise ReasoningOutputError(
            "reasoning provider returned output that is not a valid findings document"
        ) from exc
    if len(output.findings) > min(limits.max_findings, MAX_FINDINGS):
        raise ReasoningOutputError("reasoning provider returned too many findings")
    return output


def validate_findings(
    output: ReasonerOutput, context: CrossModalContext
) -> tuple[CrossModalFinding, ...]:
    """Check every finding's citations against the context.

    Args:
        output: Typed provider output.
        context: The context the reasoning ran over.

    Returns:
        The findings, unchanged, once every citation is verified.

    Raises:
        ReasoningOutputError: If any citation is missing, misattributed, or inconsistent.
    """
    for finding in output.findings:
        _check(finding, context)
    return output.findings


def _fail(message: str) -> ReasoningOutputError:
    return ReasoningOutputError(f"reasoning output failed provenance checks: {message}")


def _check(finding: CrossModalFinding, context: CrossModalContext) -> None:
    views = [context.view(oid) for oid in finding.observation_ids]
    if any(view is None for view in views):
        raise _fail("a finding cites an unknown observation")
    expected = tuple(dict.fromkeys(view.modality for view in views if view is not None))
    if finding.modalities != expected:
        raise _fail("a finding misstates the modalities of its observations")
    for claim in finding.claims:
        statement = context.statement(claim.statement_id)
        if statement is None:
            raise _fail("a claim cites an unknown statement")
        if claim.quote.casefold() not in statement.text.casefold():
            raise _fail("a claim quote does not appear in its statement")
    for fact_id in finding.fact_ids:
        fact = context.fact(fact_id)
        if fact is None:
            raise _fail("a finding cites an unknown fact")
        if finding.kind in VERDICT_KINDS:
            claim = finding.claims[0]
            if fact.property != claim.property:
                raise _fail("a verdict cites a fact about a different property")
            if fact_id.rsplit("-", 1)[0] == claim.observation_id:
                raise _fail("a claim cannot be verified by its own observation")
    if finding.kind is FindingKind.SHARED_CONCEPTS:
        for view in views:
            text = " ".join(s.text for s in view.statements) if view else ""
            if any(not re.search(rf"\b{t}\b", text, re.IGNORECASE) for t in finding.shared_terms):
                raise _fail("a shared term does not occur in both observations")
    if finding.kind in {FindingKind.CLAIM_CONFLICT, FindingKind.CLAIM_AGREEMENT}:
        first, second = finding.claims
        if first.property != second.property:
            raise _fail("compared claims concern different properties")


def conclude(
    findings: Sequence[CrossModalFinding], *, truncated: bool = False
) -> CrossModalConclusion:
    """Derive counts and an overall assessment from validated findings.

    Args:
        findings: Validated findings.
        truncated: Whether the provider reported dropping findings.

    Returns:
        The conclusion. ``consistent`` means at least one claim was corroborated and none was
        contradicted or in conflict; ``inconsistent`` means contradictions or conflicts with no
        corroboration; ``mixed`` means both; ``unverified`` means no claim was judged either way.
    """
    counts = {kind: sum(1 for f in findings if f.kind is kind) for kind in FindingKind}
    negative = counts[FindingKind.CONTRADICTED] + counts[FindingKind.CLAIM_CONFLICT]
    positive = counts[FindingKind.CORROBORATED]
    if positive and negative:
        consistency = Consistency.MIXED
    elif negative:
        consistency = Consistency.INCONSISTENT
    elif positive:
        consistency = Consistency.CONSISTENT
    else:
        consistency = Consistency.UNVERIFIED
    cross = [f for f in findings if len(set(f.modalities)) >= 2]
    relied = tuple(m for m in Modality if any(m in f.modalities for f in cross))
    statement = (
        f"{consistency.value.capitalize()}: {positive} claim(s) corroborated and "
        f"{counts[FindingKind.CONTRADICTED]} contradicted by measurements from another modality; "
        f"{counts[FindingKind.CLAIM_CONFLICT]} unresolved claim conflict(s); "
        f"{counts[FindingKind.UNVERIFIED_CLAIM]} unverified claim(s); "
        f"{len(cross)} finding(s) relate two or more modalities. {_NOT_MODEL}"
    )
    return CrossModalConclusion(
        consistency=consistency,
        corroborated=positive,
        contradicted=counts[FindingKind.CONTRADICTED],
        claim_conflicts=counts[FindingKind.CLAIM_CONFLICT],
        claim_agreements=counts[FindingKind.CLAIM_AGREEMENT],
        unverified_claims=counts[FindingKind.UNVERIFIED_CLAIM],
        shared_concepts=counts[FindingKind.SHARED_CONCEPTS],
        cross_modal_findings=len(cross),
        modalities_relied_on=relied,
        findings_truncated=truncated,
        statement=statement,
    )
