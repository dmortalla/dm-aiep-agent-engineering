"""Structured cross-modal reasoning input and output contracts (Story 9.5, ADR-009-003/006/007).

``ReasoningPort`` streams text. Cross-modal reasoning exchanges structured data over it: each
``ReasoningPart`` carries one canonical ``ObservationView`` JSON document, and a reasoning adapter
streams back one ``ReasonerOutput`` JSON document. Both directions are untrusted data.

These models define shapes and invariants only. Whether a finding's citations actually exist in a
given context is checked by the application core (``crossmodal.findings``), never assumed.
"""

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from multimodal_voice_platform.contracts.modality import (
    UNTRUSTED_LEVELS,
    Identifier,
    InputSource,
    Modality,
    TrustLevel,
)

MAX_FACTS_PER_OBSERVATION: Final = 32
MAX_STATEMENTS_PER_OBSERVATION: Final = 48
MAX_STATEMENT_CHARS: Final = 1_000
MAX_FINDINGS: Final = 64
MAX_QUOTE_CHARS: Final = 300
MAX_FINDING_OBSERVATIONS: Final = 4
MAX_FINDING_FACTS: Final = 8
MAX_SHARED_TERMS: Final = 12

ObservationId = Annotated[str, StringConstraints(pattern=r"^obs-[1-9][0-9]?$")]
StatementId = Annotated[str, StringConstraints(pattern=r"^obs-[1-9][0-9]?-s[1-9][0-9]{0,2}$")]
FactId = Annotated[str, StringConstraints(pattern=r"^obs-[1-9][0-9]?-f[1-9][0-9]{0,2}$")]
FindingId = Annotated[str, StringConstraints(pattern=r"^f-[0-9]{3}$")]
PropertyName = Annotated[
    str,
    StringConstraints(pattern=r"^(image|audio|document)\.[a-z_]+(\.[a-z-]+)?$", max_length=64),
]
ShortValue = Annotated[str, StringConstraints(min_length=1, max_length=120)]
SharedTerm = Annotated[str, StringConstraints(pattern=r"^[a-z]{3,40}$")]


class FactOrigin(StrEnum):
    """Where a fact or statement came from. Kept distinct so reviewers can weigh it honestly."""

    USER_PROVIDED = "user_provided"
    LOCAL_MEASUREMENT = "local_measurement"
    LOCAL_EXTRACTION = "local_extraction"
    FIXTURE_PLAYBACK = "fixture_playback"
    PROVIDER_CONTRACT_TEST_DOUBLE = "provider_contract_test_double"
    MODEL_INFERENCE = "model_inference"


FACT_ORIGINS: Final = frozenset({FactOrigin.LOCAL_MEASUREMENT, FactOrigin.LOCAL_EXTRACTION})
"""Facts are measured or extracted locally from the input. Never claimed by a user or a model."""

STATEMENT_ORIGINS: Final = {
    Modality.TEXT: frozenset({FactOrigin.USER_PROVIDED}),
    Modality.IMAGE: frozenset(),
    Modality.DOCUMENT: frozenset({FactOrigin.LOCAL_EXTRACTION}),
    Modality.AUDIO: frozenset(
        {FactOrigin.FIXTURE_PLAYBACK, FactOrigin.PROVIDER_CONTRACT_TEST_DOUBLE}
    ),
}
"""Statement origins each modality can produce in Story 9.5. Model inference is not one of them."""


class ObservedFact(BaseModel):
    """One locally measured or extracted fact about an input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: FactId
    property: PropertyName
    value: ShortValue
    numeric: float | None = Field(default=None, allow_inf_nan=False)
    share: float | None = Field(default=None, ge=0, le=1)
    origin: FactOrigin

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        """Keep facts to local measurement and extraction.

        Returns:
            The validated fact.

        Raises:
            ValueError: If the fact claims any other origin.
        """
        if self.origin not in FACT_ORIGINS:
            raise ValueError("facts are local measurements or extractions only")
        return self


class Statement(BaseModel):
    """One bounded piece of text taken from an input. Untrusted data, never instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_id: StatementId
    text: str = Field(min_length=1, max_length=MAX_STATEMENT_CHARS)
    origin: FactOrigin


class ObservationView(BaseModel):
    """The reasoning-visible normalized observation of one processed input.

    It carries derived facts and bounded statements only, never raw binary content.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: ObservationId
    modality: Modality
    input_id: Identifier
    source: InputSource
    trust: TrustLevel
    facts: tuple[ObservedFact, ...] = Field(default=(), max_length=MAX_FACTS_PER_OBSERVATION)
    statements: tuple[Statement, ...] = Field(
        default=(), max_length=MAX_STATEMENTS_PER_OBSERVATION
    )
    truncated: bool = False

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        """Bind identifiers, trust, and origins to the observation and its modality.

        Returns:
            The validated view.

        Raises:
            ValueError: If identifiers do not belong to the observation or repeat, trust is not
                the untrusted level for the modality, origins do not fit the modality, or the
                view is empty.
        """
        prefix = f"{self.observation_id}-"
        ids = [fact.fact_id for fact in self.facts] + [s.statement_id for s in self.statements]
        if any(not item.startswith(prefix) for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("fact and statement IDs must be unique and belong to the observation")
        expected_trust = (
            TrustLevel.UNTRUSTED_EXTERNAL
            if self.modality is Modality.TEXT
            else TrustLevel.UNTRUSTED_MODEL_OUTPUT
        )
        if self.trust not in UNTRUSTED_LEVELS or self.trust is not expected_trust:
            raise ValueError(f"{self.modality} observations must be classified {expected_trust}")
        if self.modality is Modality.TEXT and self.facts:
            raise ValueError("text observations carry statements only")
        allowed = STATEMENT_ORIGINS[self.modality]
        if any(statement.origin not in allowed for statement in self.statements):
            raise ValueError(f"statement origin is not valid for {self.modality} observations")
        if not ids:
            raise ValueError("an observation carries at least one fact or statement")
        return self


class FindingKind(StrEnum):
    """Kinds of cross-observation relationship a reasoning adapter may report."""

    CORROBORATED = "corroborated"
    CONTRADICTED = "contradicted"
    CLAIM_CONFLICT = "claim_conflict"
    CLAIM_AGREEMENT = "claim_agreement"
    UNVERIFIED_CLAIM = "unverified_claim"
    SHARED_CONCEPTS = "shared_concepts"


VERDICT_KINDS: Final = frozenset({FindingKind.CORROBORATED, FindingKind.CONTRADICTED})
"""A claim judged against a measurement taken from a different observation."""

CLAIM_PAIR_KINDS: Final = frozenset({FindingKind.CLAIM_CONFLICT, FindingKind.CLAIM_AGREEMENT})
"""Two claims from different observations compared with each other."""


class Confidence(StrEnum):
    """How strongly the cited evidence supports a finding."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClaimRef(BaseModel):
    """A claim read from a statement, with the exact quote it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: ObservationId
    statement_id: StatementId
    quote: str = Field(min_length=1, max_length=MAX_QUOTE_CHARS)
    property: PropertyName
    value: ShortValue
    negated: bool = False

    @model_validator(mode="after")
    def validate_owner(self) -> Self:
        """Require the statement to belong to the cited observation.

        Returns:
            The validated claim reference.

        Raises:
            ValueError: If the statement ID belongs to another observation.
        """
        if not self.statement_id.startswith(f"{self.observation_id}-"):
            raise ValueError("claim statement must belong to the cited observation")
        return self


class CrossModalFinding(BaseModel):
    """One relationship between observations, citing the statements and facts behind it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: FindingId
    kind: FindingKind
    observation_ids: tuple[ObservationId, ...] = Field(
        min_length=1, max_length=MAX_FINDING_OBSERVATIONS
    )
    modalities: tuple[Modality, ...] = Field(min_length=1, max_length=MAX_FINDING_OBSERVATIONS)
    claims: tuple[ClaimRef, ...] = Field(default=(), max_length=2)
    fact_ids: tuple[FactId, ...] = Field(default=(), max_length=MAX_FINDING_FACTS)
    shared_terms: tuple[SharedTerm, ...] = Field(default=(), max_length=MAX_SHARED_TERMS)
    confidence: Confidence
    explanation: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        """Require the citations each kind of finding needs.

        Returns:
            The validated finding.

        Raises:
            ValueError: If identifiers repeat, citations fall outside the cited observations, or
                the claims, facts, and terms do not fit the kind.
        """
        observations = set(self.observation_ids)
        if len(observations) != len(self.observation_ids):
            raise ValueError("observation IDs must be unique")
        if len(set(self.fact_ids)) != len(self.fact_ids):
            raise ValueError("fact IDs must be unique")
        if any(claim.observation_id not in observations for claim in self.claims):
            raise ValueError("claims must come from the cited observations")
        if any(fact.rsplit("-", 1)[0] not in observations for fact in self.fact_ids):
            raise ValueError("facts must come from the cited observations")
        claims, facts, terms = len(self.claims), len(self.fact_ids), len(self.shared_terms)
        kind = self.kind
        if kind in VERDICT_KINDS:
            valid = claims == 1 and facts >= 1 and not terms and len(observations) >= 2
        elif kind in CLAIM_PAIR_KINDS:
            valid = claims == 2 and not facts and not terms and len(observations) == 2
            valid = valid and self.claims[0].observation_id != self.claims[1].observation_id
        elif kind is FindingKind.UNVERIFIED_CLAIM:
            valid = claims == 1 and not facts and not terms and len(observations) == 1
        else:
            valid = not claims and not facts and terms >= 2 and len(observations) == 2
        if not valid:
            raise ValueError(f"{kind} findings do not carry the citations they require")
        return self


class ReasonerOutput(BaseModel):
    """The structured document a reasoning adapter streams back. Untrusted model output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    findings: tuple[CrossModalFinding, ...] = Field(default=(), max_length=MAX_FINDINGS)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        """Require unique finding IDs.

        Returns:
            The validated output.

        Raises:
            ValueError: If a finding ID repeats.
        """
        ids = [finding.finding_id for finding in self.findings]
        if len(set(ids)) != len(ids):
            raise ValueError("finding IDs must be unique")
        return self
