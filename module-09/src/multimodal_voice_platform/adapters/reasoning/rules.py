"""Deterministic, rule-based cross-modal reasoning over normalized observations (Story 9.5).

The rules relate observations from different inputs:

1. **Verdicts.** A claim read from one observation (typed text, document text, or a transcript) is
   judged against a fact measured or extracted from a *different* observation (image pixels or
   audio samples): ``corroborated`` when they agree, ``contradicted`` when they do not.
2. **Claim pairs.** Two claims about the same property from different observations are compared:
   a disagreement is always reported as a ``claim_conflict`` and is never resolved arbitrarily; an
   agreement is reported only when nothing measures the property.
3. **Unverified claims.** A claim that no other observation measures is reported as such.
4. **Shared concepts.** Distinctive words shared by statements from two different modalities.

Every finding cites the exact statements and facts it rests on. The rules are a small, fixed
lexicon and fixed tolerances. This is genuine, reproducible inference, but it is not model
inference: it understands nothing outside its vocabulary.
"""

from collections.abc import Sequence
from itertools import combinations
from typing import Final

from multimodal_voice_platform.adapters.reasoning.claims import Claim, content_terms, extract_claims
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.reasoning import (
    MAX_FINDING_FACTS,
    MAX_FINDINGS,
    MAX_SHARED_TERMS,
    Confidence,
    CrossModalFinding,
    FindingKind,
    ObservationView,
    ObservedFact,
    ReasonerOutput,
)

MIN_SHARED_TERMS: Final = 2
COLOR_PRESENCE_SHARE: Final = 0.05
"""Minimum pixel share for a color to count as present in an image."""
STRONG_REGION_SHARE: Final = 0.6
"""Region color share at or above which a region verdict is high confidence."""
DURATION_TOLERANCE_MS: Final = 50.0
DURATION_TOLERANCE_RATIO: Final = 0.10
FREQUENCY_TOLERANCE_RATIO: Final = 0.05
EXCLUSIVE_PROPERTIES: Final = ("image.region.", "image.brightness", "image.orientation")
"""Properties with one true value; ``audio.content`` is also exclusive."""

_Located = tuple[ObservationView, ObservedFact]


def reason(views: Sequence[ObservationView], *, max_findings: int = MAX_FINDINGS) -> ReasonerOutput:
    """Relate observations and return cited findings.

    Args:
        views: Observations in canonical order.
        max_findings: Most findings to return. Later findings are dropped and ``truncated`` set.

    Returns:
        The findings document, in a fixed order: verdicts, claim conflicts, claim agreements,
        unverified claims, shared concepts.
    """
    by_id = {view.observation_id: view for view in views}
    claims = [claim for view in views for claim in extract_claims(view)]
    facts: dict[str, list[_Located]] = {}
    for view in views:
        for fact in view.facts:
            facts.setdefault(fact.property, []).append((view, fact))
    verdicts: list[dict[str, object]] = []
    unverified: list[dict[str, object]] = []
    for claim in claims:
        owner = by_id[claim.observation_id]
        measured = [item for item in facts.get(claim.property, []) if item[0] is not owner]
        if not measured:
            unverified.append(_unverified(claim, by_id, measured_here=claim.property in facts))
            continue
        for view in _owners(measured):
            located = [item for item in measured if item[0] is view]
            verdict = _verdict(claim, view, [fact for _, fact in located], by_id)
            if verdict is not None:
                verdicts.append(verdict)
    conflicts: list[dict[str, object]] = []
    agreements: list[dict[str, object]] = []
    for first, second in combinations(claims, 2):
        if first.observation_id == second.observation_id or first.property != second.property:
            continue
        relation = _compare(first, second)
        if relation is FindingKind.CLAIM_CONFLICT:
            conflicts.append(_pair(relation, first, second, by_id))
        elif relation is FindingKind.CLAIM_AGREEMENT and first.property not in facts:
            agreements.append(_pair(relation, first, second, by_id))
    shared = _shared_concepts(views)
    ordered = [*verdicts, *conflicts, *agreements, *unverified, *shared]
    limit = min(max_findings, MAX_FINDINGS)
    findings = tuple(
        CrossModalFinding(finding_id=f"f-{index:03d}", **fields)
        for index, fields in enumerate(ordered[:limit], start=1)
    )
    return ReasonerOutput(schema_version=1, findings=findings, truncated=len(ordered) > limit)


def _owners(measured: list[_Located]) -> list[ObservationView]:
    owners: list[ObservationView] = []
    for view, _ in measured:
        if view not in owners:
            owners.append(view)
    return owners


def _modalities(
    observation_ids: Sequence[str], by_id: dict[str, ObservationView]
) -> tuple[Modality, ...]:
    return tuple(dict.fromkeys(by_id[oid].modality for oid in observation_ids))


def _claim_ref(claim: Claim) -> dict[str, object]:
    return {
        "observation_id": claim.observation_id,
        "statement_id": claim.statement_id,
        "quote": claim.quote,
        "property": claim.property,
        "value": claim.value,
        "negated": claim.negated,
    }


def _label(observation_id: str, by_id: dict[str, ObservationView]) -> str:
    return f"{observation_id} ({by_id[observation_id].modality})"


def _says(claim: Claim) -> str:
    """Phrase a claim in plain words."""
    prop, value = claim.property, claim.value
    neg = "not " if claim.negated else ""
    if prop.startswith("image.region."):
        return f"the {prop.rsplit('.', 1)[1]} region is {neg}{value}"
    if prop == "image.color":
        return f"the image {'does not contain' if claim.negated else 'contains'} {value}"
    if prop in {"image.brightness", "image.orientation"}:
        return f"the image is {neg}{value}"
    if prop == "audio.content":
        return f"the audio is {neg}{'silent' if value == 'silent' else 'an audible signal'}"
    if prop == "audio.duration_ms":
        return f"the audio lasts about {value} ms"
    return f"the tone is about {value} Hz"


def _fact_text(fact: ObservedFact) -> str:
    share = f" ({round(fact.share * 100)}%)" if fact.share is not None else ""
    return f"{fact.property} = {fact.value}{share}"


def _verdict(
    claim: Claim,
    view: ObservationView,
    located: list[ObservedFact],
    by_id: dict[str, ObservationView],
) -> dict[str, object] | None:
    judged = _judge(claim, located)
    if judged is None:
        return None
    holds, confidence, cited = judged
    kind = FindingKind.CORROBORATED if holds else FindingKind.CONTRADICTED
    ids = (claim.observation_id, view.observation_id)
    measured = "; ".join(_fact_text(fact) for fact in cited)
    effect = "supports" if holds else "contradicts"
    return {
        "kind": kind,
        "observation_ids": ids,
        "modalities": _modalities(ids, by_id),
        "claims": (_claim_ref(claim),),
        "fact_ids": tuple(fact.fact_id for fact in cited),
        "confidence": confidence,
        "explanation": (
            f"{_label(claim.observation_id, by_id)} states that {_says(claim)}; "
            f"{_label(view.observation_id, by_id)} measured {measured}. "
            f"The measurement {effect} the claim."
        )[:600],
    }


def _judge(
    claim: Claim, located: list[ObservedFact]
) -> tuple[bool, Confidence, list[ObservedFact]] | None:
    """Return (claim holds, confidence, cited facts), or ``None`` if the facts cannot judge it."""
    prop = claim.property
    if prop == "image.color":
        present = [
            fact
            for fact in located
            if fact.value == claim.value and (fact.share or 0) >= COLOR_PRESENCE_SHARE
        ]
        cited = present or located[:MAX_FINDING_FACTS]
        return (bool(present) != claim.negated, Confidence.HIGH, cited)
    fact = located[0]
    if prop in {"audio.duration_ms", "audio.tone_hz"}:
        if claim.numeric is None or fact.numeric is None:
            return None
        if prop == "audio.duration_ms":
            tolerance = max(DURATION_TOLERANCE_MS, DURATION_TOLERANCE_RATIO * fact.numeric)
            confidence = Confidence.HIGH
        else:
            tolerance = FREQUENCY_TOLERANCE_RATIO * fact.numeric
            confidence = Confidence.MEDIUM
        return (abs(claim.numeric - fact.numeric) <= tolerance, confidence, [fact])
    matches = fact.value == claim.value
    confidence = Confidence.HIGH
    if prop.startswith("image.region.") and (fact.share or 0) < STRONG_REGION_SHARE:
        confidence = Confidence.MEDIUM
    return (matches != claim.negated, confidence, [fact])


def _exclusive(prop: str) -> bool:
    return prop == "audio.content" or prop.startswith(EXCLUSIVE_PROPERTIES)


def _compare(first: Claim, second: Claim) -> FindingKind | None:
    """Compare two claims about one property. ``None`` means neither agreement nor conflict."""
    if first.numeric is not None and second.numeric is not None:
        larger = max(first.numeric, second.numeric)
        if first.property == "audio.duration_ms":
            tolerance = max(DURATION_TOLERANCE_MS, DURATION_TOLERANCE_RATIO * larger)
        else:
            tolerance = FREQUENCY_TOLERANCE_RATIO * larger
        close = abs(first.numeric - second.numeric) <= tolerance
        return FindingKind.CLAIM_AGREEMENT if close else FindingKind.CLAIM_CONFLICT
    same_value = first.value == second.value
    if same_value:
        if first.negated == second.negated:
            return FindingKind.CLAIM_AGREEMENT
        return FindingKind.CLAIM_CONFLICT
    if _exclusive(first.property) and not first.negated and not second.negated:
        return FindingKind.CLAIM_CONFLICT
    return None


def _pair(
    kind: FindingKind, first: Claim, second: Claim, by_id: dict[str, ObservationView]
) -> dict[str, object]:
    ids = (first.observation_id, second.observation_id)
    if kind is FindingKind.CLAIM_CONFLICT:
        detail = "The claims disagree. No rule resolves the conflict, so it stays unresolved."
        confidence = Confidence.MEDIUM
    else:
        detail = "The claims agree, but nothing supplied measures this property."
        confidence = Confidence.LOW
    return {
        "kind": kind,
        "observation_ids": ids,
        "modalities": _modalities(ids, by_id),
        "claims": (_claim_ref(first), _claim_ref(second)),
        "confidence": confidence,
        "explanation": (
            f"{_label(first.observation_id, by_id)} states that {_says(first)}; "
            f"{_label(second.observation_id, by_id)} states that {_says(second)}. {detail}"
        )[:600],
    }


def _unverified(
    claim: Claim, by_id: dict[str, ObservationView], *, measured_here: bool
) -> dict[str, object]:
    reason_text = (
        "Only the same input measures this property, so it cannot corroborate itself."
        if measured_here
        else "No supplied modality measures this property."
    )
    ids = (claim.observation_id,)
    return {
        "kind": FindingKind.UNVERIFIED_CLAIM,
        "observation_ids": ids,
        "modalities": _modalities(ids, by_id),
        "claims": (_claim_ref(claim),),
        "confidence": Confidence.LOW,
        "explanation": (
            f"{_label(claim.observation_id, by_id)} states that {_says(claim)}. {reason_text}"
        )[:600],
    }


def _shared_concepts(views: Sequence[ObservationView]) -> list[dict[str, object]]:
    by_id = {view.observation_id: view for view in views}
    terms = {view.observation_id: content_terms(view) for view in views}
    findings: list[dict[str, object]] = []
    for first, second in combinations(views, 2):
        if first.modality is second.modality:
            continue
        shared = sorted(terms[first.observation_id] & terms[second.observation_id])
        if len(shared) < MIN_SHARED_TERMS:
            continue
        ids = (first.observation_id, second.observation_id)
        shown = tuple(shared[:MAX_SHARED_TERMS])
        findings.append(
            {
                "kind": FindingKind.SHARED_CONCEPTS,
                "observation_ids": ids,
                "modalities": _modalities(ids, by_id),
                "shared_terms": shown,
                "confidence": Confidence.LOW,
                "explanation": (
                    f"{_label(ids[0], by_id)} and {_label(ids[1], by_id)} share "
                    f"{len(shared)} distinctive words: {', '.join(shown)}. "
                    "This is lexical overlap, not semantic equivalence."
                )[:600],
            }
        )
    return findings
