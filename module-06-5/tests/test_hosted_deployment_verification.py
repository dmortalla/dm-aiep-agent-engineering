"""Hosted deployment verification: recorded, classified as deployment, and claim-bounded.

The public Streamlit deployment was rebuilt from the accepted main release, installed
openai 2.54.0, anthropic 1.13.0 and mcp 2.3.0 from ``uv.lock``, started, and completed one
bounded explicit BYOK OpenAI call through the governed path. That is deployment-verification
evidence. It is adapter-class for the call, never ``live_provider`` evidence, makes no
Anthropic hosted claim, and makes no provider-level production-readiness, SLA, billing or
scale claim. No network, credential or provider call is used here.
"""

import json
import re
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

import harness_engineering.live_readiness as readiness
from harness_engineering.domain import EvidenceClass
from harness_engineering.live_readiness import (
    HOSTED_DEPLOYMENT_VERIFICATIONS,
    REPOSITORY_EVIDENCE,
    HostedByokCall,
    HostedDeploymentVerification,
    ReadinessStatus,
    deployment_caption,
    live_provider_ready,
    provider_readiness,
)

MODULE = Path(__file__).resolve().parents[1]
APP = MODULE / "streamlit_app.py"
HOSTED = HOSTED_DEPLOYMENT_VERIFICATIONS[0]


def rows(**kwargs: object) -> dict[str, readiness.ReadinessItem]:
    return {item.capability: item for item in provider_readiness(**kwargs)}  # type: ignore[arg-type]


def locked_versions() -> dict[str, str]:
    lock = tomllib.loads((MODULE / "uv.lock").read_text(encoding="utf-8"))
    return {package["name"]: package["version"] for package in lock["package"]}


def test_recorded_hosted_versions_match_the_locked_versions() -> None:
    locked = locked_versions()
    assert HOSTED.openai_version == locked["openai"]
    assert HOSTED.anthropic_version == locked["anthropic"]
    assert HOSTED.mcp_version == locked["mcp"]
    # Streamlit is host-supplied, so it is deliberately not asserted against the lock.


def test_provenance_digests_are_pinned_and_documented() -> None:
    assert HOSTED.deployment_log_sha256 == (
        "2AA36C78E94D4D4338A8F42513C96C56F91C20DDCDBC518FA61151BC7837499B")
    assert HOSTED.byok_screenshot_sha256 == (
        "5D80C5E6AA8D5C832CE9904EC4F91E93FF9CE547F2B31FAB0C82E8466063094B")
    for name in ("RELEASE_READINESS.md", "TRACEABILITY.md"):
        text = (MODULE / "docs" / name).read_text(encoding="utf-8-sig")
        assert HOSTED.deployment_log_sha256 in text and HOSTED.byok_screenshot_sha256 in text
    payload = HOSTED.model_dump(mode="json")
    for patch in ({"deployment_log_sha256": "abc"}, {"byok_screenshot_sha256": "g" * 64},
                  {"deployment_log_sha256": "a" * 64}):
        with pytest.raises(ValidationError):
            HostedDeploymentVerification(**(payload | patch))


def test_module_documents_agree_with_the_hosted_record() -> None:
    for name in ("RELEASE_READINESS.md", "TRACEABILITY.md", "STORY_13.md"):
        text = " ".join((MODULE / "docs" / name).read_text(encoding="utf-8-sig").split())
        for fact in ("2.54.0", "1.13.0", "2.3.0", "gpt-6-luna", "0.0000256"):
            assert fact in text, f"{name}: {fact}"
        assert "Anthropic" in text and "not exercised" in text, name
    for name in ("RELEASE_READINESS.md", "TRACEABILITY.md"):
        text = (MODULE / "docs" / name).read_text(encoding="utf-8-sig")
        assert "`deployment`: none." not in text
        assert "Deployment evidence does not exist" not in text


STALE_DEPLOYMENT_STATUS = re.compile(
    r"deployment(?: verification| evidence)?\b[^.;]{0,40}?"
    r"\b(?:remains?|stays?|is|are|was not|has not|have not)\s+(?:still\s+|yet\s+)?"
    r"(?:not\s+(?:yet\s+)?(?:verified|exist|occurred)|`?pending`?|unverified|none)",
    re.IGNORECASE,
)
HISTORICAL_MARKERS = (
    "checkpoint", "at this stage", "at that time", "earlier", "superseded", "before the",
    "previously", "then", "historical", "formerly", "was not yet", "at the time",
)


def sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [part for part in re.split(r"(?<=[.;])\s+(?=[A-Z`*(])", flat) if part]


def test_no_document_states_deployment_is_still_unverified_as_current_status() -> None:
    """Pending/unverified deployment wording must be explicitly historical or about root docs."""
    offenders = []
    for name in ("STORY_13.md", "RELEASE_READINESS.md", "TRACEABILITY.md"):
        text = (MODULE / "docs" / name).read_text(encoding="utf-8-sig")
        for sentence in sentences(text):
            if not STALE_DEPLOYMENT_STATUS.search(sentence):
                continue
            window = sentence.lower()
            if any(marker in window for marker in HISTORICAL_MARKERS):
                continue
            offenders.append(f"{name}: {sentence[:160]}")
    assert offenders == []


def test_the_stale_status_detector_flags_unqualified_and_allows_historical_wording() -> None:
    assert STALE_DEPLOYMENT_STATUS.search("Deployment remains not verified and it is open.")
    assert STALE_DEPLOYMENT_STATUS.search("deployment verification stays `pending`.")
    assert STALE_DEPLOYMENT_STATUS.search("Deployment is not verified.")
    historical = ("At this checkpoint, deployment was not yet verified; "
                  "deployment verification was `pending` (superseded).")
    assert any(m in historical.lower() for m in HISTORICAL_MARKERS)
    assert sentences("A first. Second one; Third.") == ["A first.", "Second one;", "Third."]


def test_deployment_verification_is_verified_and_classified_as_deployment() -> None:
    row = rows()["Deployment verification"]
    assert row.status is ReadinessStatus.VERIFIED and row.evidence is EvidenceClass.DEPLOYMENT
    for phrase in ("rebuilt from the accepted main release", "openai 2.54.0",
                   "anthropic 1.13.0", "mcp 2.3.0", "Streamlit supplied by the host", "started",
                   "one bounded explicit BYOK openai call", "gpt-6-luna", "21/47 tokens",
                   "$0.0000256"):
        assert phrase in row.summary, phrase


def test_the_recorded_facts_match_the_hosted_observation() -> None:
    assert (HOSTED.branch, HOSTED.entrypoint, HOSTED.dependency_install) == (
        "main", "module-06-5/streamlit_app.py", "uv-sync of module-06-5/uv.lock")
    assert (HOSTED.openai_version, HOSTED.anthropic_version, HOSTED.mcp_version) == (
        "2.54.0", "1.13.0", "2.3.0")
    assert HOSTED.streamlit_version_host_supplied == "1.66.1" and HOSTED.startup_succeeded
    call = HOSTED.byok_call
    assert (call.provider, call.model, call.status, call.credential_path) == (
        "openai", "gpt-6-luna", "succeeded", "byok")
    assert (call.attempts, call.retries, call.input_tokens, call.output_tokens) == (1, 0, 21, 47)
    assert call.live_exposure_usd == Decimal("0.0000256")
    assert HOSTED.server_credential_path_used is False


def test_the_hosted_call_stays_adapter_class_and_is_never_live_provider_evidence() -> None:
    assert HOSTED.byok_call.evidence_class == "adapter"
    live = [r for r in REPOSITORY_EVIDENCE if r.evidence is EvidenceClass.LIVE_PROVIDER]
    assert {r.subject for r in live} == {"openai", "anthropic"} and len(live) == 2
    for record in live:  # Still exactly the independently accepted third-run records.
        assert "module-06-5-third-live-evidence-20261027-002708.json" in record.basis
    assert not any("hosted" in r.basis.lower() for r in REPOSITORY_EVIDENCE)
    # Deployment records cannot create or alter live-provider readiness.
    assert live_provider_ready(REPOSITORY_EVIDENCE, "openai")
    non_live = tuple(
        r for r in REPOSITORY_EVIDENCE if r.evidence is not EvidenceClass.LIVE_PROVIDER
    )
    assert not live_provider_ready(non_live, "openai") and not live_provider_ready(
        non_live, "anthropic")
    without_live = rows(records=non_live)
    assert without_live["Live OpenAI evidence"].status is ReadinessStatus.NOT_EXECUTED
    assert without_live["Deployment verification"].status is ReadinessStatus.VERIFIED


def test_other_claim_boundaries_are_unchanged() -> None:
    items = rows()
    assert items["Provider-level production readiness"].status is ReadinessStatus.NOT_CLAIMED
    assert items["Provider-level production readiness"].evidence is EvidenceClass.LIVE_PROVIDER
    for label in ("Live OpenAI evidence", "Live Anthropic evidence"):
        assert items[label].status is ReadinessStatus.ACCEPTED
        assert items[label].evidence is EvidenceClass.LIVE_PROVIDER
    assert items["Deterministic no-key mode"].evidence is EvidenceClass.DETERMINISTIC
    assert items["Provider adapter readiness"].evidence is EvidenceClass.ADAPTER
    assert items["Secure live seam (credential-free)"].evidence is EvidenceClass.MOCKED
    assert items["BYOK live mode in this deployment"].status is ReadinessStatus.AVAILABLE
    assert items["Server credential path"].status is ReadinessStatus.DISABLED
    summary = items["Deployment verification"].summary.lower()
    assert "no sla, billing, scale or production-readiness claim" in summary
    assert "not live-provider evidence" in summary


def test_anthropic_is_not_claimed_on_the_hosted_app() -> None:
    assert HOSTED.anthropic_exercised_on_hosted_app is False
    summary = rows()["Deployment verification"].summary
    assert "Anthropic not exercised on the hosted app" in summary
    assert "anthropic" not in HostedByokCall.model_fields["provider"].annotation.__args__
    payload = HOSTED.model_dump(mode="json")
    with pytest.raises(ValidationError):
        HostedDeploymentVerification(**(payload | {"anthropic_exercised_on_hosted_app": True}))
    with pytest.raises(ValidationError):
        HostedDeploymentVerification(
            **(payload | {"byok_call": payload["byok_call"] | {"provider": "anthropic",
                                                                "model": "claude-haiku-5-5"}}))


@pytest.mark.parametrize("patch", [
    {"evidence_class": "live_provider"}, {"credential_path": "server"}, {"status": "failed"},
    {"retries": 1}, {"attempts": 2}, {"output_tokens": 257}, {"live_exposure_usd": "0.002"},
    {"live_exposure_usd": "0"}, {"api_key": "x"}, {"response_text": "leak"},
])
def test_the_hosted_call_record_rejects_promotion_overreach_and_content(
    patch: dict[str, object],
) -> None:
    call = HOSTED.byok_call.model_dump(mode="json")
    with pytest.raises(ValidationError):
        HostedByokCall(**(call | patch))


@pytest.mark.parametrize("patch", [
    {"startup_succeeded": False}, {"server_credential_path_used": True},
    {"branch": "dev"}, {"entrypoint": "other/app.py"}, {"openai_version": "latest"},
    {"source": "self-reported"}, {"credentials": "x"}, {"response_text": "leak"},
])
def test_the_deployment_record_rejects_unverified_or_overreaching_values(
    patch: dict[str, object],
) -> None:
    payload = HOSTED.model_dump(mode="json")
    with pytest.raises(ValidationError):
        HostedDeploymentVerification(**(payload | patch))


def test_without_a_hosted_record_the_deployment_row_reverts_to_pending() -> None:
    row = rows(deployments=())["Deployment verification"]
    assert row.status is ReadinessStatus.PENDING and row.evidence is EvidenceClass.DEPLOYMENT
    assert "Not verified" in row.summary and "hosted app" not in row.summary
    assert "not yet verified" in deployment_caption(())
    assert "hosted deployment was verified" in deployment_caption()


def test_the_record_holds_no_key_or_response_content() -> None:
    dumped = json.dumps(HOSTED.model_dump(mode="json")).lower()
    for forbidden in ("api_key", "sk-", "bearer", "secret", "response_text", "password"):
        assert forbidden not in dumped
    assert set(HostedByokCall.model_fields).isdisjoint({"text", "content", "key", "credential"})


def test_runtime_and_live_path_code_never_consult_the_deployment_record() -> None:
    root = MODULE / "src" / "harness_engineering"
    for module in ("providers.py", "vendor_providers.py", "live_session.py",
                   "live_authorization.py", "live_credentials.py", "config.py"):
        source = (root / module).read_text(encoding="utf-8-sig")
        assert "HOSTED_DEPLOYMENT_VERIFICATIONS" not in source
        assert "live_readiness" not in source


def test_streamlit_renders_the_same_application_owned_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    text = "\n".join(item.value for item in at.markdown)
    caption = "\n".join(item.value for item in at.caption)
    expected = rows()["Deployment verification"]
    assert f"**Deployment verification** · `verified` · deployment  \n{expected.summary}" in text
    assert deployment_caption() in caption
    assert "`pending`" not in text and "not yet verified" not in caption
    # Same seam, record removed: the page follows the record back to pending.
    monkeypatch.setattr(readiness, "HOSTED_DEPLOYMENT_VERIFICATIONS", ())
    at = AppTest.from_file(APP, default_timeout=30).run()
    text = "\n".join(item.value for item in at.markdown)
    caption = "\n".join(item.value for item in at.caption)
    assert "**Deployment verification** · `pending` · deployment" in text
    assert deployment_caption(()) in caption and "hosted deployment was verified" not in caption
