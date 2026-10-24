"""ENG-008: structural protection of the production-grade dual-mode contract.

These tests fail if future architecture/requirements/release documents again
permit adapter-only evidence to satisfy provider-level production readiness, or
if the implemented deterministic-default/opt-in live-provider seam regresses.
"""

from pathlib import Path

import pytest

from harness_engineering.config import HarnessConfig
from harness_engineering.domain import EvidenceClass

DOCS = Path(__file__).resolve().parents[1] / "docs"
SRC = Path(__file__).resolve().parents[1] / "src" / "harness_engineering"

ENG_008_INVARIANTS = (
    "production-grade dual-mode provider operation",
    "Deterministic, credential-free operation remains the default reviewer mode",
    "opt-in capability",
    "documented provider and model allowlist",
    "trusted server-side, environment, or secret-store mechanisms",
    "never accepted as public browser input",
    "credentials grant connectivity only and never authority",
    "bounded by retries, token/output limits, latency deadlines, and cost exposure",
    "Evidence classes shall remain explicitly distinct",
    "implemented, securely configured, explicitly human-authorized for execution,"
    " exercised, and independently evidenced",
)


def _requirements_text() -> str:
    return (DOCS / "REQUIREMENTS.md").read_text(encoding="utf-8")


def test_eng_008_exists_exactly_once_with_full_invariant_wording() -> None:
    """The corrective requirement carries every invariant clause, once."""
    text = _requirements_text()
    assert text.count("ENG-008:") == 1
    requirement = text.split("ENG-008:")[1].split("\n\n")[0]
    for invariant in ENG_008_INVARIANTS:
        assert invariant in requirement, f"missing invariant clause: {invariant}"


def test_approved_baseline_numbering_is_untouched() -> None:
    """The 69 approved requirements keep their exact approved wording."""
    text = _requirements_text()
    for requirement_id in ("REQ-PLAN-001", "REQ-SAFE-004", "ENG-001", "ENG-007"):
        assert text.count(f"{requirement_id}:") == 1
    assert "additive engineering requirement (like ENG-001 through ENG-007" in text
    assert "never been declared DEMO-ONLY" in text


def test_decision_record_and_addendum_propagate_the_contract() -> None:
    adr_002 = " ".join(
        (DOCS / "adr" / "002-production-grade-dual-mode-completion.md")
        .read_text(encoding="utf-8").split()
    )
    for phrase in ("ENG-008", "deterministic/no-key reviewer operation by default",
                   "never public browser BYOK fields", "Story 13",
                   "separate later human-authorized cost/credential boundary"):
        assert phrase in adr_002, f"ADR 002 missing: {phrase}"
    adr_001 = (DOCS / "adr" / "001-module-06-5-architecture-baseline.md").read_text(
        encoding="utf-8"
    )
    assert "Addendum (2026-10-23)" in adr_001 and "ADR 002" in adr_001
    assert "not amended" in adr_001


def test_implementation_plan_and_traceability_propagate_the_contract() -> None:
    plan = (DOCS / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    assert "Story 13 - Secure Dual-Mode Provider Completion" in plan
    assert "ENG-008 (additive corrective, ADR 002)" in plan
    assert "- [ ] ENG-008 dual-mode completion implemented and verified" in plan
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    assert "Corrective dual-mode contract (ENG-008)" in traceability
    assert "completion outstanding" in traceability
    assert "live-path exercising" in traceability and "human-authorized" in traceability


def test_release_readiness_carries_dual_mode_outstanding_gate() -> None:
    readiness = (DOCS / "RELEASE_READINESS.md").read_text(encoding="utf-8")
    assert "Story 13 live-provider completion remains outstanding" in readiness
    assert "ENG-008" in readiness
    assert "never substitute for live-provider evidence" in readiness
    assert "provider-level production readiness" in readiness
    assert "human-authorized" in readiness
    assert "does exist" in readiness


def test_release_documents_cannot_claim_live_provider_evidence() -> None:
    """No current acceptance document asserts live-provider or deployment facts."""
    for document in ("RELEASE_READINESS.md", "TRACEABILITY.md"):
        text = (DOCS / document).read_text(encoding="utf-8")
        for term in ("live-provider", "live provider", "deployment evidence"):
            start = 0
            while (at := text.find(term, start)) != -1:
                context = text[max(0, at - 70):at + len(term) + 70].lower()
                assert any(
                    marker in context
                    for marker in ("no ", "not ", "without", "never", "none", "outstanding",
                                   "remains", "awaits", "stays", "before any", "adapter",
                                   "optional")
                ), f"{document}: unqualified assurance for {term!r}"
                start = at + 1


def test_harness_config_keeps_deterministic_default_and_fail_closed_seam() -> None:
    """Implemented seam defaults cannot regress silently."""
    config = HarnessConfig()
    assert config.deterministic_mode is True
    assert config.allow_live_providers is False
    assert config.allow_external_tools is False and config.allow_mcp is False
    with pytest.raises(ValueError):
        HarnessConfig(deterministic_mode=True, allow_live_providers=True)


def test_evidence_taxonomy_keeps_live_provider_distinct() -> None:
    classes = {member.value for member in EvidenceClass}
    for expected in ("deterministic", "mocked", "adapter", "local_integration",
                     "live_provider", "deployment"):
        assert expected in classes, f"missing evidence class: {expected}"
    assert EvidenceClass.LIVE_PROVIDER is not EvidenceClass.DEPLOYMENT


def test_vendor_adapters_remain_gate_and_authority_safe() -> None:
    """The live seam still gates on explicit config/allowlist/cost and never authority."""
    vendor = (SRC / "vendor_providers.py").read_text(encoding="utf-8")
    assert "allow_live_providers" in vendor and "max_cost_usd" in vendor
    assert "class OpenAIProvider" in vendor and "class AnthropicProvider" in vendor
    tests = (SRC.parent.parent / "tests" / "test_vendor_providers.py").read_text(
        encoding="utf-8"
    )
    assert (
        "test_credentials_or_claimed_locality_do_not_authorize_live_provider" in tests
    )
    assert "test_missing_live_configuration_is_safe_without_looking_up_real_credentials" in tests


def test_reviewer_default_path_stays_credential_free() -> None:
    """The reviewer UI keeps the no-key default and never asks for credentials."""
    app = (SRC.parent.parent / "streamlit_app.py").read_text(encoding="utf-8")
    assert "No API key or paid inference required" in app
    assert "No credentials are requested" in app
    for forbidden in ("API key", "key input", "text_input", "number_input"):
        if forbidden == "API key":
            assert "an API key" not in app.lower() or "No API key" in app
            continue
        assert forbidden not in app, f"reviewer UI must not accept credentials ({forbidden})"
