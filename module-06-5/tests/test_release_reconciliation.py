"""Story 12 Slice 2: mechanical verification of the module-wide release contract."""

import re
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parent
DOCS = MODULE / "docs"
SRC = MODULE / "src" / "harness_engineering"
TESTS = MODULE / "tests"
REQ_IDS = re.compile(r"^(REQ-[A-Z]+-\d{3}|ENG-\d{3}):", re.MULTILINE)


def _requirements() -> list[str]:
    """Approved requirement identifiers exactly as the frozen baseline defines them."""
    text = (DOCS / "REQUIREMENTS.md").read_text(encoding="utf-8")
    ids = REQ_IDS.findall(text)
    assert len(set(ids)) == 69
    return ids


def test_traceability_represents_all_69_approved_requirements() -> None:
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    assert "69 approved requirements" in traceability or "69-approved-requirement" in traceability
    for requirement_id in _requirements():
        assert requirement_id in traceability, f"unclosed: {requirement_id}"


CLI_LABS = ("REQ-LAB-003", "REQ-LAB-004", "REQ-LAB-005", "REQ-LAB-006")
SERVICE_LABS = {"REQ-LAB-001": "run_planning_lab", "REQ-LAB-002": "run_context_lab"}


def _lab_rows(traceability: str) -> dict[str, str]:
    """The six lab evidence rows keyed by requirement id (missing rows fail)."""
    labs_section = traceability.split("### Labs (6 of 6) and deliverables (5 of 5)")[1]
    labs_section = labs_section.split("Deliverable reconciliation:")[0]
    rows = {
        requirement_id: line
        for line in labs_section.splitlines()
        if (match := re.match(r"\| (REQ-LAB-\d{3}) ", line))
        for requirement_id in (match.group(1),)
    }
    for number in range(1, 7):
        assert f"REQ-LAB-{number:03d}" in rows, f"missing lab evidence row {number}"
    return rows


def verify_lab_evidence(traceability: str) -> None:
    """Every cited lab artifact must really exist exactly as documented.

    CLI modules must expose a genuine `main()` / `__main__` surface; service
    functions must be actually defined in accepted implementation source.
    Nothing here requires phantom command strings: a lab may cite a CLI entry,
    a deterministic service function, or the accepted Streamlit demonstration.
    """
    rows = _lab_rows(traceability)
    for row in rows.values():
        cited = re.findall(r"`([^`]+)`", row)
        tests_cited = [item for item in cited if re.fullmatch(r"test_[\w.]+\.py", item)]
        implementation_cited = [
            item for item in cited
            if re.fullmatch(r"[\w.]+\.py", item) and not item.startswith("test_")
        ]
        assert tests_cited, f"no cited test evidence in row: {row}"
        assert implementation_cited, f"no cited implementation in row: {row}"
        for item in cited:
            if (cli := re.fullmatch(r"python -m harness_engineering\.(\w+)", item)):
                lab_module = SRC / f"{cli.group(1)}.py"  # type: ignore[union-attr]
                assert lab_module.is_file(), f"cited CLI module missing: {item}"
                source = lab_module.read_text(encoding="utf-8")
                assert 'if __name__ == "__main__":' in source and "def main" in source, (
                    f"cited CLI surface is not real: {item}"
                )
            elif (service := re.fullmatch(r"run_[a-z_]+\(\)", item)):
                function = service.group(0)[: -2]  # type: ignore[union-attr]
                assert any(
                    f"def {function}" in path.read_text(encoding="utf-8")
                    for path in SRC.glob("*.py")
                ), f"cited service function is not defined anywhere: {item}"
            elif re.fullmatch(r"[\w.]+\.py", item):
                directory = TESTS if item.startswith("test_") else SRC
                assert (directory / item).is_file(), f"cited artifact missing: {item}"
            elif "Streamlit reviewer demonstration" in item:
                continue
            else:
                raise AssertionError(f"unverifiable citation in lab row: {item}")
    for requirement_id, service_function in SERVICE_LABS.items():
        assert service_function in rows[requirement_id], (
            f"{requirement_id} must cite its deterministic service function"
        )
    reviewer_service = (SRC / "reviewer_service.py").read_text(encoding="utf-8")
    for service_function in SERVICE_LABS.values():
        assert service_function in reviewer_service, (
            f"Streamlit reviewer does not demonstrate {service_function}"
        )


def test_six_labs_map_to_real_surfaces() -> None:
    """Six lab rows; CLI-designated labs have real main surfaces; the doc
    distinguishes CLI labs from service/UI-surface labs."""
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    verify_lab_evidence(traceability)
    for requirement_id in CLI_LABS:
        assert "python -m harness_engineering." in _lab_rows(traceability)[requirement_id]
    for requirement_id in SERVICE_LABS:
        line = _lab_rows(traceability)[requirement_id]
        assert "python -m harness_engineering." not in line
        assert "Streamlit reviewer demonstration" in line
    labs_intro = traceability.split("### Labs (6 of 6) and deliverables (5 of 5)")[1]
    labs_intro = labs_intro.split("| Lab (requirement)")[0]
    assert "direct CLI evidence surfaces" in labs_intro
    assert "service functions" in labs_intro
    assert "Streamlit" in labs_intro


def test_fictional_lab_citation_fails_verification() -> None:
    """A fabricated implementation/test path must fail the structural check."""
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    tampered = traceability.replace("`test_planning_engine.py`", "`test_fabricated.py`")
    with pytest.raises(AssertionError, match=r"test_fabricated\.py"):
        verify_lab_evidence(tampered)


def test_missing_lab_row_fails_verification() -> None:
    """Removing a required lab evidence row must fail the structural check."""
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    rows = _lab_rows(traceability)
    row = rows["REQ-LAB-004"]
    with pytest.raises(AssertionError, match=r"missing lab evidence row 4"):
        verify_lab_evidence(traceability.replace(row + "\n", ""))


def test_five_deliverables_reconciled_with_implemented_evidence() -> None:
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    section = traceability.split("### Labs (6 of 6) and deliverables (5 of 5)")[1]
    for deliverable_id in ("REQ-DEL-001", "REQ-DEL-002", "REQ-DEL-003",
                           "REQ-DEL-004", "REQ-DEL-005"):
        assert deliverable_id in section, f"missing deliverable: {deliverable_id}"
    assert "implemented and\nverified evidence" in section


def test_nine_technologies_keep_truthful_roles() -> None:
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    table = traceability.split("### Technologies (9 of 9)")[1]
    table = table.split("### Release non-claims")[0]
    for number, technology in (
        (1, "LangGraph"), (2, "Mem0"), (3, "MCP SDK"), (4, "LangSmith"),
        (5, "Langfuse"), (6, "Guardrails AI"), (7, "Helicone"),
        (8, "OpenAI SDK"), (9, "Anthropic SDK"),
    ):
        assert f"REQ-TECH-{number:03d}" in traceability, f"missing REQ-TECH-{number:03d}"
        row = next(
            (line for line in table.splitlines() if line.startswith(f"| {technology} ")),
            None,
        )
        assert row is not None, f"missing technology row: {technology}"
        assert "critical path" in row or "optional" in row
    assert "non-claim" in table.lower()


def test_traceability_references_accepted_slice_1_integration() -> None:
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    assert "1666e99" in traceability
    assert "story_board.py" in traceability
    assert (DOCS / "STORY_12_SLICE_1.md").is_file()
    assert (MODULE / "src" / "harness_engineering" / "story_board.py").is_file()


def _negated_everywhere(text: str, term: str) -> None:
    """Every occurrence of an assurance term must carry an explicit negation."""
    position = 0
    while (at := text.find(term, position)) != -1:
        context = text[max(0, at - 60):at + len(term) + 60].lower()
        assert any(
            marker in context
            for marker in ("no ", "not ", "without", "never", "none", "adapter")
        ), f"unqualified assurance for {term!r}"
        position = at + 1


def test_release_non_claims_are_preserved_and_not_elevated() -> None:
    """Lower evidence classes stay lower; no release non-claim silently disappears."""
    traceability = (DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
    for non_claim in (
        "No live OpenAI or Anthropic provider verification",
        "No paid inference is required",
        "No hosted LangSmith",
        "no hosted Langfuse verification",
        "No live Helicone",
        "No live Mem0 service requirement",
        "No external production MCP service claim",
        "No genuine production identity/authentication claim",
        "not provider prices; no verified billing exists",
        "not production-latency certification",
        "not OS/container isolation",
        "Deployment evidence does not exist",
    ):
        assert non_claim in traceability, f"missing non-claim: {non_claim}"
    _negated_everywhere(traceability, "live-provider")
    _negated_everywhere(traceability, "deployment evidence")
    _negated_everywhere(traceability, "hosted service")


def test_status_documents_match_acceptance_chronology() -> None:
    for document, required, absent in (
        (
            REPO / "docs" / "PROJECT_STATUS.md",
            ("1666e99", "Story 12 Slice 2", "pending independent review",
             "deployment not started"),
            ("closeout performed, pending independent review",),
        ),
        (
            DOCS / "RELEASE_READINESS.md",
            ("1666e99", "69 of 69", "pending independent review", "non-claim"),
            ("deployment complete", "production-ready now"),
        ),
    ):
        text = document.read_text(encoding="utf-8")
        for phrase in required:
            assert phrase in text, f"{document.name}: missing {phrase!r}"
        for stale in absent:
            assert stale not in text, f"{document.name}: stale {stale!r}"


def test_root_readme_carries_substantive_module_section() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## Module 6.5 - Harness Engineering" in readme
    section = readme.split("## Module 6.5 - Harness Engineering")[1].split("---")[0]
    for entry in ("streamlit run streamlit_app.py", "story board", "LangGraph",
                  "off-switch", "checkpointing", "human-approval", "MCP SDK",
                  "regression", "release reconciliation", "pending independent review",
                  "Deployment verification", "No live OpenAI"):
        assert entry in section, f"README section missing: {entry}"
    roadmap_row = next(
        line for line in readme.splitlines() if line.startswith("| 6.5 |")
    )
    assert "✅ Complete" not in roadmap_row
