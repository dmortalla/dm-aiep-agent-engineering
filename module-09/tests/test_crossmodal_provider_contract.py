"""Deterministic cross-modal provider contract regressions; no external requests."""

import json
from copy import deepcopy
from typing import Any

import pytest
from live_builders import FakeOpenAI, run, session
from pydantic import ValidationError
from voice_builders import CATALOG

from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.reasoning import ReasonerOutput
from multimodal_voice_platform.crossmodal.records import CrossModalStatus
from multimodal_voice_platform.crossmodal.service import CrossModalWorkflow, ModalitySubmission
from multimodal_voice_platform.live.errors import LiveConfigurationError
from multimodal_voice_platform.live.prompts import (
    CROSS_MODAL_INSTRUCTIONS,
    CROSS_MODAL_SCHEMA,
    REPLY_FRAGMENTS_SCHEMA,
    UNTRUSTED_NOTICE,
)
from multimodal_voice_platform.understanding.service import UnderstandingService


def _output() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "truncated": False,
        "findings": [
            {
                "finding_id": "f-001",
                "kind": "unverified_claim",
                "observation_ids": ["obs-1"],
                "modalities": ["text"],
                "claims": [
                    {
                        "observation_id": "obs-1",
                        "statement_id": "obs-1-s1",
                        "quote": "The image is red.",
                        "property": "image.color",
                        "value": "red",
                        "negated": False,
                    }
                ],
                "fact_ids": [],
                "shared_terms": [],
                "confidence": "low",
                "explanation": "The supplied claim has no supporting fact.",
            }
        ],
    }


def test_provider_schema_mirrors_all_authoritative_lexical_and_size_constraints() -> None:
    authoritative = ReasonerOutput.model_json_schema()

    def compare(provider: dict[str, Any], application: dict[str, Any]) -> None:
        if "$ref" in application:
            application = authoritative["$defs"][application["$ref"].split("/")[-1]]
        for key in ("pattern", "minLength", "maxLength", "minItems", "maxItems"):
            assert provider.get(key) == application.get(key), (key, application)
        if "properties" in application:
            for name, field in application["properties"].items():
                compare(provider["properties"][name], field)
        if "items" in application:
            compare(provider["items"], application["items"])

    compare(CROSS_MODAL_SCHEMA, authoritative)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observation_id", "obs-0"),
        ("observation_id", "obs-100"),
        ("statement_id", "obs-1-s0"),
        ("statement_id", "obs-1-s1000"),
        ("property", "image.Region"),
        ("property", "text.color"),
        ("property", "image.region.top_left"),
        ("finding_id", "f-1"),
        ("fact_ids", "obs-1-f0"),
        ("shared_terms", "Red"),
    ],
)
def test_invalid_provider_lexical_forms_remain_rejected(field: str, value: str) -> None:
    output = _output()
    finding = output["findings"][0]
    if field == "finding_id":
        finding[field] = value
    elif field in {"fact_ids", "shared_terms"}:
        finding[field] = [value]
    else:
        finding["claims"][0][field] = value
    with pytest.raises(ValidationError):
        ReasonerOutput.model_validate_json(json.dumps(output))


@pytest.mark.parametrize(
    "case",
    [
        "statement_owner",
        "duplicate_observation",
        "outside_claim",
        "outside_fact",
        "corroborated",
        "contradicted",
        "claim_conflict",
        "claim_agreement",
        "unverified_claim",
        "shared_concepts",
        "duplicate_finding",
    ],
)
def test_semantic_invalid_results_remain_fail_closed(case: str) -> None:
    output = _output()
    finding = output["findings"][0]
    if case == "statement_owner":
        finding["claims"][0]["statement_id"] = "obs-2-s1"
    elif case == "duplicate_observation":
        finding["observation_ids"] *= 2
    elif case == "outside_claim":
        finding["observation_ids"] = ["obs-2"]
    elif case == "outside_fact":
        finding.update(
            kind="corroborated", observation_ids=["obs-1", "obs-2"], fact_ids=["obs-3-f1"]
        )
    elif case == "duplicate_finding":
        output["findings"].append(deepcopy(finding))
    elif case == "unverified_claim":
        finding["claims"] = []
    else:
        finding["kind"] = case
    with pytest.raises(ValidationError):
        ReasonerOutput.model_validate_json(json.dumps(output))


@pytest.mark.parametrize(
    "requested", [EvidenceClass.AUTOMATED_TEST, EvidenceClass.LIVE_INTEGRATION]
)
def test_nonempty_fake_provider_result_parses_without_becoming_live(
    requested: EvidenceClass,
) -> None:
    fake = FakeOpenAI()
    fake.reasoning_deltas = [json.dumps(_output())]
    bindings = fake.bindings()
    workflow = CrossModalWorkflow(
        CATALOG, live_reasoning=bindings.cross_modal,
        understanding=UnderstandingService(CATALOG, live_vision=bindings.vision),
    )
    submissions = [
        ModalitySubmission(modality=Modality.TEXT, text="The image is red."),
        ModalitySubmission(modality=Modality.DOCUMENT, media_type="text/markdown",
                           display_name="brief.md", data=CATALOG.content("document-brief")),
    ]
    if requested is EvidenceClass.LIVE_INTEGRATION:
        with pytest.raises(LiveConfigurationError):
            run(workflow.run(session(), submissions, evidence_class=requested))
        assert fake.requests == []
        return
    record = run(workflow.run(session(), submissions, evidence_class=requested))
    assert record.status is CrossModalStatus.SUCCEEDED
    assert record.evidence.evidence_class is EvidenceClass.AUTOMATED_TEST
    assert not record.evidence.live_provider_executed
    assert len(record.findings) == 1


def test_instructions_preserve_semantic_rules_and_untrusted_boundary() -> None:
    for requirement in (
        "Never invent supplied observation, statement, or fact identifiers",
        "A claim's statement belongs to its observation",
        "Every claim and fact cited by a finding belongs to one of that "
        "finding's cited observations",
        "Observation IDs within a finding are unique",
        "fact IDs within a finding are unique",
        "finding IDs within the result are unique",
        "exact sequence f-001, f-002, etc.",
        "corroborated / contradicted: exactly one claim, at least one fact, no "
        "shared terms, at least two observations",
        "claim_conflict / claim_agreement: exactly two claims from distinct "
        "observations, exactly two observations, no facts or shared terms",
        "unverified_claim: exactly one claim, exactly one observation, no facts or shared terms",
        "shared_concepts: no claims or facts, at least two shared terms, exactly two observations",
        "every shared term must occur literally as a whole word, case-insensitively, "
        "in the statement",
        "text of each cited observation; if fewer than two such terms exist, "
        "omit shared_concepts",
        UNTRUSTED_NOTICE,
    ):
        assert requirement in CROSS_MODAL_INSTRUCTIONS
    assert "nothingis" not in CROSS_MODAL_INSTRUCTIONS


def test_conversation_statement_schema_is_still_unconstrained() -> None:
    properties = REPLY_FRAGMENTS_SCHEMA["properties"]["fragments"]["items"]["properties"]
    assert properties["statement_id"] == {"type": "string"}
