"""Story 9.5 workflow tests: modality combinations, dependence on each modality, conflicts,
partial failure, reproducibility, provenance, and reviewer-visible records."""

from crossmodal_builders import (
    FIXTURE_DOCUMENT,
    FIXTURE_TONE_WAV,
    SESSION,
    SILENT_WAV,
    TONE_WAV,
    about,
    audio,
    document,
    image,
    kinds,
    run,
    solid_png,
    spoken,
    text,
)

from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.modality import Modality, TrustLevel
from multimodal_voice_platform.contracts.providers import ProviderPort
from multimodal_voice_platform.contracts.reasoning import FactOrigin, FindingKind
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.crossmodal import (
    REASONING_TASK,
    Consistency,
    CrossModalStage,
    CrossModalStatus,
    CrossModalWorkflow,
    ObservationPath,
    OutcomeStatus,
    ReasoningKind,
)

C, X = FindingKind.CORROBORATED, FindingKind.CONTRADICTED
REGION = "image.region.top-left"


def test_text_and_image_claims_are_judged_against_measured_pixels() -> None:
    record = run(
        [
            text("The top-left quadrant of the image is red, but the bottom-right is black."),
            image(),
        ]
    )
    assert record.status is CrossModalStatus.SUCCEEDED
    assert about(record, REGION) == [(C, "red")]
    assert about(record, "image.region.bottom-right") == [(X, "black")]
    first = record.findings[0]
    assert first.modalities == (Modality.TEXT, Modality.IMAGE)
    fact_owner = {f.fact_id: o.view.modality for o in record.observations for f in o.view.facts}
    assert all(fact_owner[fid] is Modality.IMAGE for fid in first.fact_ids)
    assert record.conclusion is not None
    assert record.conclusion.consistency is Consistency.MIXED
    assert record.conclusion.modalities_relied_on == (Modality.TEXT, Modality.IMAGE)


def test_whole_image_color_brightness_and_orientation_claims() -> None:
    record = run(
        [
            text("The picture is dark and blue. The image is landscape, not square."),
            image(solid_png((10, 20, 120))),
        ]
    )
    assert about(record, "image.color") == [(C, "blue")]
    assert about(record, "image.brightness") == [(C, "dark")]
    assert sorted(about(record, "image.orientation")) == [(C, "landscape"), (C, "square")]
    negated = [c for f in record.findings for c in f.claims if c.value == "square"]
    assert negated and negated[0].negated is True


def test_text_and_audio_claims_are_judged_against_measured_samples() -> None:
    record = run([text("The recording is a tone lasting 300 ms at about 440 Hz."), audio()])
    assert about(record, "audio.content") == [(C, "signal")]
    assert about(record, "audio.duration_ms") == [(C, "300")]
    assert about(record, "audio.tone_hz") == [(C, "440")]
    silent = run([text("The recording is silent and lasts 2 seconds."), audio()])
    assert about(silent, "audio.content") == [(X, "silent")]
    assert about(silent, "audio.duration_ms") == [(X, "2000")]
    assert silent.conclusion is not None
    assert silent.conclusion.consistency is Consistency.INCONSISTENT


def test_document_statements_are_judged_against_an_image() -> None:
    spec = "# Expected pattern\n\nThe top-left quadrant is red. The top-right quadrant is blue.\n"
    record = run([document(spec), image()])
    assert about(record, REGION) == [(C, "red")]
    assert about(record, "image.region.top-right") == [(X, "blue")]
    claim = record.findings[0].claims[0]
    statement = next(
        s for obs in record.observations for s in obs.view.statements
        if s.statement_id == claim.statement_id
    )
    assert statement.origin is FactOrigin.LOCAL_EXTRACTION
    assert claim.quote.casefold() in statement.text.casefold()


def test_text_and_document_share_concepts_and_compare_claims() -> None:
    record = run(
        [
            text("Calibration report: the recording is silent. Calibration passed review."),
            document("# Calibration\n\nCalibration report notes: the recording is a tone."),
        ]
    )
    assert FindingKind.CLAIM_CONFLICT in kinds(record)
    shared = [f for f in record.findings if f.kind is FindingKind.SHARED_CONCEPTS]
    assert shared and {"calibration", "report"} <= set(shared[0].shared_terms)


def test_spoken_description_is_judged_against_an_image() -> None:
    workflow = CrossModalWorkflow(speech=spoken("The top left corner of the image is green."))
    record = run([audio(transcribe=True), image()], workflow)
    assert record.status is CrossModalStatus.SUCCEEDED
    assert about(record, REGION) == [(X, "green")]
    audio_obs = next(o for o in record.observations if o.view.modality is Modality.AUDIO)
    assert audio_obs.provenance.processing_path is ObservationPath.LOCAL_AUDIO_TRANSCRIPTION
    assert {s.origin for s in audio_obs.view.statements} == {
        FactOrigin.PROVIDER_CONTRACT_TEST_DOUBLE
    }


def test_fixture_transcript_is_labeled_playback_and_cannot_corroborate_its_own_audio() -> None:
    record = run([text("The clip is silent."), audio(FIXTURE_TONE_WAV, transcribe=True)])
    audio_obs = next(o for o in record.observations if o.view.modality is Modality.AUDIO)
    assert {s.origin for s in audio_obs.view.statements} == {FactOrigin.FIXTURE_PLAYBACK}
    assert about(record, "audio.content") == [
        (X, "silent"),
        (FindingKind.CLAIM_CONFLICT, "silent"),
        (FindingKind.CLAIM_CONFLICT, "signal"),
        (FindingKind.UNVERIFIED_CLAIM, "signal"),
    ]
    self_claims = [f for f in record.findings if f.kind is FindingKind.UNVERIFIED_CLAIM]
    assert all("same input" in f.explanation for f in self_claims)


def test_removing_the_image_removes_the_corroboration() -> None:
    claim = "The top-left quadrant of the image is red."
    full = run([text(claim), image(), audio()])
    assert about(full, REGION) == [(C, "red")]
    without_image = run([text(claim), audio()])
    assert without_image.status is CrossModalStatus.SUCCEEDED
    assert about(without_image, REGION) == [(FindingKind.UNVERIFIED_CLAIM, "red")]
    assert C not in kinds(without_image)


def test_removing_the_text_removes_the_inference() -> None:
    full = run([text("The top-left quadrant of the image is red."), image(), audio()])
    assert about(full, REGION)
    without_text = run([image(), audio()])
    assert without_text.status is CrossModalStatus.SUCCEEDED
    assert about(without_text, REGION) == []
    assert without_text.findings == ()
    assert without_text.conclusion is not None
    assert without_text.conclusion.consistency is Consistency.UNVERIFIED


def test_changing_the_measured_modality_changes_the_verdict() -> None:
    claim = text("The recording is silent.")
    assert about(run([claim, audio(SILENT_WAV)]), "audio.content") == [(C, "silent")]
    assert about(run([claim, audio(TONE_WAV)]), "audio.content") == [(X, "silent")]


def test_conflicting_claims_stay_unresolved_without_a_measurement() -> None:
    record = run(
        [
            text("The top-left quadrant of the image is blue."),
            document("# Spec\n\nThe top-left quadrant is red."),
        ]
    )
    assert kinds(record) == [
        FindingKind.CLAIM_CONFLICT,
        FindingKind.UNVERIFIED_CLAIM,
        FindingKind.UNVERIFIED_CLAIM,
    ]
    assert "unresolved" in record.findings[0].explanation
    assert record.conclusion is not None
    assert record.conclusion.consistency is Consistency.INCONSISTENT
    assert record.conclusion.corroborated == 0


def test_a_measurement_judges_each_conflicting_claim_but_keeps_the_conflict() -> None:
    record = run(
        [
            text("The top-left quadrant of the image is blue."),
            image(),
            document("# Spec\n\nThe top-left quadrant is red."),
        ]
    )
    assert sorted(about(record, REGION)) == sorted(
        [
            (X, "blue"),
            (C, "red"),
            (FindingKind.CLAIM_CONFLICT, "blue"),
            (FindingKind.CLAIM_CONFLICT, "red"),
        ]
    )
    assert record.conclusion is not None
    assert record.conclusion.consistency is Consistency.MIXED


def test_agreeing_unmeasured_claims_are_reported_as_unverified_agreement() -> None:
    record = run([text("The recording lasts 2 seconds."), document("# Log\n\nThe clip lasts 2 s.")])
    assert FindingKind.CLAIM_AGREEMENT in kinds(record)
    assert record.conclusion is not None
    assert record.conclusion.consistency is Consistency.UNVERIFIED


def test_four_modalities_in_one_run_produce_one_typed_result() -> None:
    record = run(
        [
            document(FIXTURE_DOCUMENT, "brief.md"),
            audio(FIXTURE_TONE_WAV, transcribe=True),
            image(),
            text("The top-left quadrant of the image is red and the tone is 400 Hz."),
        ]
    )
    assert record.status is CrossModalStatus.SUCCEEDED
    views = [obs.view for obs in record.observations]
    assert [v.observation_id for v in views] == ["obs-1", "obs-2", "obs-3", "obs-4"]
    assert [v.modality for v in views] == [
        Modality.TEXT,
        Modality.IMAGE,
        Modality.AUDIO,
        Modality.DOCUMENT,
    ]
    assert [v.trust for v in views] == [TrustLevel.UNTRUSTED_EXTERNAL] + [
        TrustLevel.UNTRUSTED_MODEL_OUTPUT
    ] * 3
    assert about(record, "audio.tone_hz")[0] == (C, "400")
    assert [t.stage for t in record.timings] == list(CrossModalStage)
    assert record.context is not None and record.context.modality_count == 4
    assert record.reasoning_kind is ReasoningKind.DETERMINISTIC_RULE_INFERENCE
    assert record.reasoning_provider is not None
    assert record.reasoning_provider.port is ProviderPort.REASONING
    assert record.reasoning_provider.mode is ExecutionMode.DETERMINISTIC
    paths = [obs.provenance.processing_path for obs in record.observations]
    assert paths == [
        ObservationPath.TEXT_PASSTHROUGH,
        ObservationPath.LOCAL_IMAGE_ANALYSIS,
        ObservationPath.LOCAL_AUDIO_TRANSCRIPTION,
        ObservationPath.LOCAL_DOCUMENT_EXTRACTION,
    ]
    assert all(o.provenance.source_record_id for o in record.observations[1:])


def test_results_are_reproducible_and_independent_of_submission_order() -> None:
    items = [
        text("The top-left quadrant of the image is red. The recording is silent."),
        image(),
        audio(),
        document("# Notes\n\nThe recording is a tone and the image is square."),
    ]
    first = run(items)
    second = run(list(reversed(items)))
    keep = {"findings", "conclusion", "context"}
    assert first.model_dump(include=keep) == second.model_dump(include=keep)
    assert [o.view for o in first.observations] == [o.view for o in second.observations]
    stable = {"processing_ms", "source_record_id"}
    assert [o.provenance.model_dump(exclude=stable) for o in first.observations] == [
        o.provenance.model_dump(exclude=stable) for o in second.observations
    ]
    assert [o.position for o in second.outcomes] == [0, 1, 2, 3]
    assert second.outcomes[0].modality is Modality.DOCUMENT


def test_every_finding_cites_existing_statements_and_facts() -> None:
    record = run(
        [
            text("The top-left quadrant of the image is red. The recording is silent."),
            image(),
            audio(),
        ]
    )
    statements = {s.statement_id: s for o in record.observations for s in o.view.statements}
    facts = {f.fact_id: f for o in record.observations for f in o.view.facts}
    assert record.findings
    for finding in record.findings:
        for claim in finding.claims:
            assert claim.quote.casefold() in statements[claim.statement_id].text.casefold()
        for fact_id in finding.fact_ids:
            assert facts[fact_id].property == finding.claims[0].property
            assert facts[fact_id].origin is FactOrigin.LOCAL_MEASUREMENT


def test_a_failed_modality_is_recorded_and_the_rest_still_reason() -> None:
    record = run(
        [
            text("The top-left quadrant of the image is red."),
            image(),
            document(b"\x89PNG\r\n\x1a\nnot markdown", "broken.md"),
        ]
    )
    assert record.status is CrossModalStatus.PARTIAL
    broken = record.outcomes[2]
    assert broken.status is OutcomeStatus.REJECTED and broken.observation_id is None
    assert broken.error is not None and broken.understanding is not None
    assert about(record, REGION) == [(C, "red")]
    assert "partial" in record.evidence.summary


def test_too_few_surviving_modalities_rejects_the_run() -> None:
    record = run([text("The image is red."), image(b"\x89PNG\r\n\x1a\ntruncated")])
    assert record.status is CrossModalStatus.REJECTED
    assert record.failed_stage is CrossModalStage.MODALITY_PROCESSING
    assert record.error is not None and record.error.code == "unsupported_modality"
    assert [o.status for o in record.outcomes] == [OutcomeStatus.PROCESSED, OutcomeStatus.REJECTED]
    assert record.findings == () and record.conclusion is None


def test_record_serializes_for_reviewers_without_raw_bytes() -> None:
    record = run([text("The top-left quadrant of the image is red."), image(), audio()])
    payload = record.model_dump_json()
    assert REASONING_TASK not in payload
    assert "IHDR" not in payload and "RIFF" not in payload
    assert '"reasoning_kind":"deterministic_rule_inference"' in payload
    assert '"model_inference_performed":false' in payload
    assert record.evidence.evidence_class is EvidenceClass.AUTOMATED_TEST
    assert record.session_id == SESSION.session_id
