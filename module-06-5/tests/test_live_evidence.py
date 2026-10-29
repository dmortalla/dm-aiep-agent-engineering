"""Story 13: accepted live-provider evidence is recorded, classified and bounded correctly.

The raw artifact stays external. These tests prove the repository-owned record is
exact, immutable-by-hash, free of response content and credentials, shown
truthfully by the reviewer UI, and that runtime code cannot promote itself to
``live_provider``. No network, credentials or provider call is used.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness_engineering.domain import EvidenceClass
from harness_engineering.live_readiness import (
    ACCEPTED_LIVE_EXERCISES,
    REPOSITORY_EVIDENCE,
    REVIEW_DISPOSITION,
    AcceptedLiveExercise,
    ReadinessStatus,
    live_provider_ready,
    provider_readiness,
)
from harness_engineering.providers import FakeProvider, ProviderRuntime

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parent
SRC = MODULE / "src" / "harness_engineering"
APP = MODULE / "streamlit_app.py"
HASH = "389287FC65C9F51F84850E2D2929C50EC21FDEC4B70BC902FD0CE65100D7FCF4"
ARTIFACT = "module-06-5-third-live-evidence-20261027-002708.json"
BASELINE = "e1e5e1ac5f931f95a146c85baaace40cc3357230"
BY_PROVIDER = {e.provider: e for e in ACCEPTED_LIVE_EXERCISES}


def test_accepted_exercises_match_the_reviewed_artifact_facts() -> None:
    assert set(BY_PROVIDER) == {"openai", "anthropic"} and len(ACCEPTED_LIVE_EXERCISES) == 2
    openai, anthropic = BY_PROVIDER["openai"], BY_PROVIDER["anthropic"]
    assert (openai.model, openai.input_tokens, openai.output_tokens,
            openai.returned_text_bytes, openai.live_exposure_usd) == (
        "gpt-6-luna", 20, 39, 27, Decimal("0.0000215"))
    assert (anthropic.model, anthropic.input_tokens, anthropic.output_tokens,
            anthropic.returned_text_bytes, anthropic.live_exposure_usd) == (
        "claude-haiku-5-5", 35, 27, 86, Decimal("0.0000170"))
    assert (anthropic.cache_creation_input_tokens, anthropic.cache_read_input_tokens) == (0, 0)
    for record in ACCEPTED_LIVE_EXERCISES:
        assert record.status == "success" and (record.attempts, record.retries) == (1, 0)
        assert record.artifact_sha256 == HASH and record.artifact_name == ARTIFACT
        assert record.baseline_commit == BASELINE
        assert record.review_disposition == REVIEW_DISPOSITION
        assert record.max_cost_usd == Decimal("0.001")
        assert record.live_exposure_usd < record.max_cost_usd
        assert record.output_tokens <= 256 and record.returned_text_bytes <= 4096


def test_record_pins_hash_and_cannot_hold_content_or_credentials() -> None:
    fields = set(AcceptedLiveExercise.model_fields)
    assert fields == {
        "provider", "model", "run_reference", "baseline_commit", "artifact_name",
        "artifact_sha256", "review_disposition", "status", "attempts", "retries",
        "input_tokens", "output_tokens", "returned_text_bytes",
        "cache_creation_input_tokens", "cache_read_input_tokens", "live_exposure_usd",
        "max_cost_usd",
    }
    assert not {"text", "content", "response", "api_key", "credential", "reasoning"} & fields
    good = BY_PROVIDER["openai"].model_dump()
    with pytest.raises(ValidationError):
        AcceptedLiveExercise(**good, response_text="leaked")
    for patch in ({"artifact_sha256": HASH.lower()}, {"artifact_sha256": HASH[:-1]},
                  {"baseline_commit": "e1e5e1a"}, {"attempts": 2}, {"retries": 1},
                  {"status": "failed"}, {"review_disposition": "ACCEPTED"},
                  {"live_exposure_usd": Decimal("0.002")}, {"live_exposure_usd": Decimal("0")},
                  {"output_tokens": 257}, {"returned_text_bytes": 4097}, {"provider": "other"}):
        with pytest.raises(ValidationError):
            AcceptedLiveExercise(**(good | patch))


def test_accepted_evidence_is_classified_live_provider_with_review_provenance() -> None:
    live = [r for r in REPOSITORY_EVIDENCE if r.evidence is EvidenceClass.LIVE_PROVIDER]
    assert {r.subject for r in live} == {"openai", "anthropic"}
    for record in live:
        assert HASH in record.basis and ARTIFACT in record.basis
        assert record.independent_review == REVIEW_DISPOSITION
        assert record.authorization_reference.startswith("module-06-5-third-live-20261027")
    assert live_provider_ready(REPOSITORY_EVIDENCE, "openai")
    assert live_provider_ready(REPOSITORY_EVIDENCE, "anthropic")


def test_readiness_shows_accepted_evidence_without_implying_more() -> None:
    items = {i.capability: i for i in provider_readiness()}
    for label in ("Live OpenAI evidence", "Live Anthropic evidence"):
        assert items[label].status is ReadinessStatus.ACCEPTED
        assert "Not an SLA or billing validation" in items[label].summary
    assert items["Deployment verification"].status is ReadinessStatus.PENDING
    assert items["Provider-level production readiness"].status is ReadinessStatus.NOT_CLAIMED
    assert items["BYOK live mode in this deployment"].status is ReadinessStatus.AVAILABLE
    assert items["Deterministic no-key mode"].status is ReadinessStatus.VERIFIED
    assert items["Provider adapter readiness"].status is ReadinessStatus.VERIFIED
    text = " ".join(i.summary for i in items.values())
    assert "not_executed" not in text and "Not yet authorized" not in text


def test_runtime_cannot_self_promote_to_live_provider() -> None:
    assert ProviderRuntime(provider=FakeProvider()).evidence_class is EvidenceClass.DETERMINISTIC
    from tests.live_seam import live_runtime

    for vendor in ("openai", "anthropic"):
        assert live_runtime(vendor).evidence_class is EvidenceClass.ADAPTER
    # Runtime and live-path code never consults the repository evidence record.
    for module in ("providers.py", "vendor_providers.py", "live_authorization.py",
                   "live_credentials.py", "config.py", "usage.py"):
        source = (SRC / module).read_text(encoding="utf-8-sig")
        assert "live_readiness" not in source and "ACCEPTED_LIVE_EXERCISES" not in source
        assert "EvidenceClass.LIVE_PROVIDER" not in source


def test_external_artifact_stays_external_and_documents_pin_it() -> None:
    assert not list(REPO.rglob(ARTIFACT)) and not (REPO / "EVIDENCE").exists()
    story = " ".join(
        (MODULE / "docs" / "STORY_13.md").read_text(encoding="utf-8-sig").split()
    )
    for required in (HASH, ARTIFACT, BASELINE, REVIEW_DISPOSITION, "First attempt: failed",
                     "Second attempt: failed", "Third attempt: succeeded",
                     "Story 13's live-evidence gate is satisfied", "0.0000215", "0.0000170",
                     "closeout is not complete", "no maintained live-validation tool"):
        assert required in story, f"STORY_13 missing: {required}"
    for document in ("RELEASE_READINESS.md", "TRACEABILITY.md"):
        assert HASH in (MODULE / "docs" / document).read_text(encoding="utf-8-sig")


def test_documents_keep_deployment_not_verified_and_module_incomplete() -> None:
    readiness = (MODULE / "docs" / "RELEASE_READINESS.md").read_text(encoding="utf-8-sig")
    traceability = (MODULE / "docs" / "TRACEABILITY.md").read_text(encoding="utf-8-sig")
    assert "`deployment`: none." in readiness
    assert "Deployment evidence does not exist" in traceability
    assert "Final live deployment verification" in readiness
    assert "deployment complete" not in readiness
    readme = (REPO / "README.md").read_text(encoding="utf-8-sig")
    roadmap = next(line for line in readme.splitlines() if line.startswith("| 6.5 |"))
    assert "✅ Complete" not in roadmap


SECRET_LIKE = (
    r"sk-[A-Za-z0-9_-]{16,}", r"sk-ant-[A-Za-z0-9_-]{8,}", r"Bearer\s+[A-Za-z0-9._-]{16,}",
    r"AKIA[0-9A-Z]{16}", r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9._-]{12,}['\"]",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)


def test_reconciliation_files_contain_no_secret_like_material() -> None:
    files = [SRC / "live_readiness.py", APP, MODULE / "docs" / "STORY_13.md",
             MODULE / "docs" / "RELEASE_READINESS.md", MODULE / "docs" / "TRACEABILITY.md",
             MODULE / "docs" / "IMPLEMENTATION_PLAN.md", REPO / "README.md",
             REPO / "docs" / "PROJECT_STATUS.md", Path(__file__)]
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        for pattern in SECRET_LIKE:
            hit = re.search(pattern, text)
            if path == Path(__file__) and hit and "SECRET_LIKE" in text[max(0, hit.start() - 80):]:
                continue  # This file's own pattern definitions.
            assert hit is None, f"secret-like material in {path.name}: {pattern}"
    # The only long hex string allowed is the pinned artifact hash and git commits.
    for path in files[:-1]:
        for token in re.findall(r"\b[0-9A-Fa-f]{64}\b", path.read_text(encoding="utf-8-sig")):
            assert token == HASH, f"unexpected 64-hex value in {path.name}"


def test_reviewer_ui_reports_accepted_live_evidence_and_pending_deployment() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    text = "\n".join(item.value for item in at.markdown)
    caption = "\n".join(item.value for item in at.caption)
    assert "`accepted`" in text and "`not_executed`" not in text
    assert "Live OpenAI evidence" in text and "Live Anthropic evidence" in text
    assert "gpt-6-luna" in text and "claude-haiku-5-5" in text
    deployment = next(line for line in text.splitlines() if line.startswith("**Deployment"))
    assert "`pending`" in deployment
    production = next(line for line in text.splitlines()
                      if line.startswith("**Provider-level production"))
    assert "`not_claimed`" in production
    assert "not yet verified" in caption and "not yet authorized" not in text + caption
    assert not at.text_input and not at.text_area and not at.number_input


def test_caption_follows_the_records_and_never_asserts_evidence_independently() -> None:
    from harness_engineering.live_readiness import live_evidence_caption

    non_live = tuple(
        r for r in REPOSITORY_EVIDENCE if r.evidence is not EvidenceClass.LIVE_PROVIDER
    )
    only_openai = non_live + tuple(
        r for r in REPOSITORY_EVIDENCE
        if r.evidence is EvidenceClass.LIVE_PROVIDER and r.subject == "openai"
    )
    assert "openai and anthropic" in live_evidence_caption()
    assert "recorded for openai:" in live_evidence_caption(only_openai)
    assert "anthropic" not in live_evidence_caption(only_openai)
    absent = live_evidence_caption(non_live)
    assert "No accepted live-provider evidence is recorded" in absent
    assert "recorded for" not in absent and "independently reviewed" not in absent
    assert live_evidence_caption(()) == absent


def test_ui_without_accepted_records_claims_no_live_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove the accepted records through the module seam: rows and caption both revert."""
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    import harness_engineering.live_readiness as readiness

    non_live = tuple(
        r for r in REPOSITORY_EVIDENCE if r.evidence is not EvidenceClass.LIVE_PROVIDER
    )
    monkeypatch.setattr(readiness, "REPOSITORY_EVIDENCE", non_live)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    text = "\n".join(item.value for item in at.markdown)
    caption = "\n".join(item.value for item in at.caption)
    assert "`not_executed`" in text and "`accepted`" not in text
    assert "No accepted live-provider evidence is recorded" in caption
    for claim in ("recorded for", "independently reviewed", "gpt-6-luna", "claude-haiku-5-5"):
        assert claim not in caption + text, f"UI claims live evidence without records: {claim}"
    assert "`pending`" in text and "`not_claimed`" in text  # deployment and readiness unchanged


def test_traceability_states_both_the_evidence_and_the_unclaimed_readiness() -> None:
    text = " ".join(
        (MODULE / "docs" / "TRACEABILITY.md").read_text(encoding="utf-8-sig").split()
    )
    assert "accepted, bounded live-provider evidence exists for the reviewed run" in text
    assert "production-readiness claim is still not made" in text
    assert "No longer true" not in text


@pytest.mark.parametrize("serving_live", [False, True])
def test_public_byok_availability_is_separate_from_server_configuration(serving_live: bool) -> None:
    from harness_engineering.config import default_config
    from tests.live_seam import live_config

    config = live_config("openai") if serving_live else default_config()
    items = {item.capability: item for item in provider_readiness(config=config)}
    byok = items["BYOK live mode in this deployment"]
    server = items["Server credential path"]
    assert byok.status is ReadinessStatus.AVAILABLE and byok.evidence is None
    assert server.status is ReadinessStatus.DISABLED and server.evidence is None
    assert "Live mode in this deployment" not in items
    assert "temporary user-supplied" in byok.summary
    assert "connectivity only, never application authority" in byok.summary
    assert "Intentionally disabled for public deployment" in server.summary
    assert "not required for BYOK" in server.summary
    assert items["Deployment verification"].status is ReadinessStatus.PENDING
    assert items["Provider-level production readiness"].status is ReadinessStatus.NOT_CLAIMED
    assert items["Secure live seam (credential-free)"].evidence is EvidenceClass.MOCKED


def test_server_flag_alone_does_not_establish_configuration_or_evidence() -> None:
    items = {item.capability: item for item in provider_readiness(server_path_enabled=True)}
    assert items["Server credential path"].status is ReadinessStatus.NOT_CONFIGURED
    assert items["BYOK live mode in this deployment"].status is ReadinessStatus.AVAILABLE
    assert items["Deployment verification"].status is ReadinessStatus.PENDING
    assert items["Provider-level production readiness"].status is ReadinessStatus.NOT_CLAIMED


def test_byok_availability_is_derived_from_the_credential_source_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import harness_engineering.live_readiness as readiness
    from harness_engineering.live_credentials import (
        EnvironmentCredentialSource,
        SecretStoreCredentialSource,
    )

    present = {i.capability: i for i in provider_readiness()}
    available = present["BYOK live mode in this deployment"]
    assert available.status is ReadinessStatus.AVAILABLE
    for phrase in ("explicit per-session opt-in", "temporary user-supplied credential",
                   "bounded call", "connectivity only, never application authority"):
        assert phrase in available.summary, phrase
    monkeypatch.setattr(
        readiness, "CREDENTIAL_SOURCE_TYPES",
        (EnvironmentCredentialSource, SecretStoreCredentialSource),
    )
    absent = {i.capability: i for i in provider_readiness()}
    unavailable = absent["BYOK live mode in this deployment"]
    assert unavailable.status is ReadinessStatus.NOT_CONFIGURED
    # The summary comes from the same branch as the status: no stale positive wording.
    assert unavailable.summary.startswith("Not supported:")
    assert "no BYOK credential source" in unavailable.summary
    assert "Available" not in unavailable.summary
    for implied in ("available", "enabled", "ready", "configured", "usable", "opt-in"):
        assert implied not in unavailable.summary.lower(), implied
    assert unavailable.summary != available.summary
    assert absent["Server credential path"].status is ReadinessStatus.DISABLED  # Independent.
    assert "Live mode in this deployment" not in absent