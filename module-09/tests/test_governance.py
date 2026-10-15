"""Deterministic governance checks: traceability, ADRs, stories, evidence, isolation, encoding."""

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import LatencyStage
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.providers import ProviderPort
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.contracts.streaming import StreamEventType

MODULE_ROOT = Path(__file__).resolve().parents[1]
DOCS = MODULE_ROOT / "docs"
SKIPPED_DIRS = {".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}
TEXT_SUFFIXES = {".md", ".py", ".toml", ".json", ".txt", ".lock", ".yaml", ".yml"}
ALLOWED_THIRD_PARTY = {"pydantic", "pytest", "multimodal_voice_platform"}
RESTRICTED_THIRD_PARTY = {
    "PIL": {"adapters/local/image_analysis.py"},
    "pypdf": {"adapters/local/document_parsing.py"},
}
"""Story 9.3 decoders, each allowed in exactly one source module (and in tests)."""
FORBIDDEN_MODULES = {"subprocess", "pty", "os.system"}
FORBIDDEN_CALLS = {"eval", "exec", "system", "popen", "spawn"}


@pytest.fixture(scope="module")
def governance() -> dict[str, Any]:
    return json.loads((DOCS / "governance" / "module-09-governance.json").read_text("utf-8"))


def _doc(name: str) -> str:
    return (DOCS / name).read_text("utf-8")


def _owned_files(suffixes: set[str]) -> list[Path]:
    return [
        path
        for path in MODULE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and not SKIPPED_DIRS.intersection(path.relative_to(MODULE_ROOT).parts)
    ]


def test_all_17_source_groups_are_traced(governance: dict[str, Any]) -> None:
    source = [req for req in governance["requirements"] if req["kind"] == "source"]
    assert {req["group"] for req in source} == set(range(1, 18))
    assert governance["source_group_count"] == 17
    assert [req["id"] for req in source] == [f"SRC-{n:03d}" for n in range(1, 19)]
    deliverables = {req["title"] for req in source if req["group"] == 17}
    assert deliverables == {
        "Deliverable: voice-enabled AI assistant",
        "Deliverable: multimodal AI platform",
    }


def test_every_requirement_is_documented_and_mapped_to_real_stories(
    governance: dict[str, Any],
) -> None:
    story_ids = {story["id"] for story in governance["stories"]}
    requirements_doc = _doc("REQUIREMENTS.md")
    traceability_doc = _doc("TRACEABILITY.md")
    for req in governance["requirements"]:
        assert req["id"] in requirements_doc, req["id"]
        assert req["id"] in traceability_doc, req["id"]
        assert req["stories"], req["id"]
        assert set(req["stories"]) <= story_ids, req["id"]
    referenced = {story for req in governance["requirements"] for story in req["stories"]}
    assert referenced == story_ids


def test_nine_adrs_exist_and_match_governance(governance: dict[str, Any]) -> None:
    adrs = governance["adrs"]
    assert [adr["id"] for adr in adrs] == [f"ADR-009-{n:03d}" for n in range(1, 10)]
    for adr in adrs:
        text = (DOCS / adr["file"]).read_text("utf-8")
        heading = text.splitlines()[0]
        assert heading.startswith(f"# {adr['id']}: "), adr["id"]
        assert heading.removeprefix(f"# {adr['id']}: ").lower() == adr["title"].lower()
        assert "## Status\n\nAccepted" in text, adr["id"]
    assert len(list((DOCS / "adr").glob("ADR-009-*.md"))) == 9


def test_ten_stories_are_represented(governance: dict[str, Any]) -> None:
    stories = governance["stories"]
    assert [story["id"] for story in stories] == [f"9.{n}" for n in range(1, 11)]
    stories_doc = _doc("STORIES.md")
    for story in stories:
        assert f"| {story['id']} | {story['title']} |" in stories_doc, story["id"]


def test_story_9_1_claims_design_evidence_only(governance: dict[str, Any]) -> None:
    assert governance["story_9_1_evidence_class"] == EvidenceClass.DESIGN_DOCUMENTATION
    statuses = {story["id"]: story["status"] for story in governance["stories"]}
    assert statuses["9.1"] == "complete-design-only"
    for name in ("../README.md", "PROJECT_STATUS.md", "EVIDENCE_POLICY.md"):
        assert "design" in _doc(name).lower()


def test_story_9_2_claims_only_the_deterministic_foundation(governance: dict[str, Any]) -> None:
    assert governance["story_9_2_evidence_class"] == EvidenceClass.AUTOMATED_TEST
    assert governance["implemented_capabilities"][0] == "deterministic_multimodal_foundation"
    statuses = {req["id"]: req["status"] for req in governance["requirements"]}
    assert statuses["ENG-001"] == "partially-implemented"
    stories = {story["id"]: story["status"] for story in governance["stories"]}
    assert stories["9.2"] == "complete-deterministic-foundation"
    foundation_doc = _doc("DETERMINISTIC_FOUNDATION.md")
    assert "no inference" in foundation_doc.lower()
    for name in ("../README.md", "PROJECT_STATUS.md", "EVIDENCE_POLICY.md"):
        assert "no inference" in " ".join(_doc(name).lower().split()), name


def test_story_9_3_claims_only_local_understanding(governance: dict[str, Any]) -> None:
    assert governance["story_9_3_evidence_class"] == EvidenceClass.AUTOMATED_TEST
    assert governance["implemented_capabilities"][:2] == [
        "deterministic_multimodal_foundation",
        "local_document_vision_understanding",
    ]
    statuses = {req["id"]: req["status"] for req in governance["requirements"]}
    for rid in ("SRC-002", "SRC-004", "ENG-006"):
        assert statuses[rid] == "partially-implemented", rid
    stories = {story["id"]: story["status"] for story in governance["stories"]}
    assert stories["9.3"] == "complete-local-understanding"
    understanding_doc = " ".join(_doc("UNDERSTANDING.md").lower().split())
    assert "no model inference" in understanding_doc
    assert "not semantic" in understanding_doc
    for name in ("../README.md", "PROJECT_STATUS.md", "EVIDENCE_POLICY.md", "TRACEABILITY.md"):
        assert "no model inference" in " ".join(_doc(name).lower().split()), name


def test_story_9_4_claims_only_the_audio_speech_pipeline(governance: dict[str, Any]) -> None:
    assert governance["story_9_4_evidence_class"] == EvidenceClass.AUTOMATED_TEST
    assert governance["implemented_capabilities"][:3] == [
        "deterministic_multimodal_foundation",
        "local_document_vision_understanding",
        "local_audio_speech_pipeline",
    ]
    statuses = {req["id"]: req["status"] for req in governance["requirements"]}
    for rid in ("SRC-003", "SRC-006", "SRC-007", "ENG-006"):
        assert statuses[rid] == "partially-implemented", rid
    stories = {story["id"]: story["status"] for story in governance["stories"]}
    assert stories["9.4"] == "complete-audio-speech-pipeline"
    audio_doc = " ".join(_doc("AUDIO_SPEECH.md").lower().split())
    for phrase in ("not speech recognition", "not speech synthesis", "fixture playback"):
        assert phrase in audio_doc, phrase
    for name in ("../README.md", "PROJECT_STATUS.md", "EVIDENCE_POLICY.md", "TRACEABILITY.md"):
        text = " ".join(_doc(name).lower().split())
        assert "not speech recognition" in text and "not speech synthesis" in text, name


def test_story_9_5_claims_only_deterministic_cross_modal_reasoning(
    governance: dict[str, Any],
) -> None:
    assert governance["story_9_5_evidence_class"] == EvidenceClass.AUTOMATED_TEST
    assert governance["implemented_capabilities"][:4] == [
        "deterministic_multimodal_foundation",
        "local_document_vision_understanding",
        "local_audio_speech_pipeline",
        "deterministic_cross_modal_reasoning_workflow",
    ]
    statuses = {req["id"]: req["status"] for req in governance["requirements"]}
    for rid in ("SRC-005", "SRC-015", "ENG-006"):
        assert statuses[rid] == "partially-implemented", rid
    stories = {story["id"]: story["status"] for story in governance["stories"]}
    assert stories["9.5"] == "complete-cross-modal-reasoning"
    cross_doc = " ".join(_doc("CROSS_MODAL.md").lower().split())
    phrases = ("not model inference", "rule-based", "closed vocabulary", "partially implemented")
    for phrase in phrases:
        assert phrase in cross_doc, phrase
    for name in ("../README.md", "PROJECT_STATUS.md", "EVIDENCE_POLICY.md", "TRACEABILITY.md"):
        text = " ".join(_doc(name).lower().split())
        assert "not model inference" in text, name


def test_story_9_6_claims_only_deterministic_voice_orchestration(
    governance: dict[str, Any],
) -> None:
    assert governance["story_9_6_evidence_class"] == EvidenceClass.AUTOMATED_TEST
    assert governance["implemented_capabilities"] == [
        "deterministic_multimodal_foundation",
        "local_document_vision_understanding",
        "local_audio_speech_pipeline",
        "deterministic_cross_modal_reasoning_workflow",
        "deterministic_voice_assistant_orchestration",
    ]
    statuses = {req["id"]: req["status"] for req in governance["requirements"]}
    partial = {
        "ENG-001",
        "SRC-002",
        "SRC-003",
        "SRC-004",
        "SRC-005",
        "SRC-006",
        "SRC-007",
        "SRC-008",
        "SRC-009",
        "SRC-013",
        "SRC-014",
        "SRC-015",
        "SRC-017",
        "ENG-006",
        "ENG-007",
    }
    assert {rid for rid, status in statuses.items() if status != "designed"} == partial
    assert {statuses[rid] for rid in partial} == {"partially-implemented"}
    for later in ("SRC-010", "SRC-011", "SRC-012", "SRC-016", "ENG-003", "ENG-005"):
        assert statuses[later] == "designed", later
    stories = {story["id"]: story["status"] for story in governance["stories"]}
    assert stories.pop("9.1") == "complete-design-only"
    assert stories.pop("9.2") == "complete-deterministic-foundation"
    assert stories.pop("9.3") == "complete-local-understanding"
    assert stories.pop("9.4") == "complete-audio-speech-pipeline"
    assert stories.pop("9.5") == "complete-cross-modal-reasoning"
    assert stories.pop("9.6") == "complete-voice-assistant-orchestration"
    assert set(stories.values()) == {"not-started"}
    voice_doc = " ".join(_doc("VOICE_ASSISTANT.md").lower().split())
    for phrase in (
        "not speech recognition",
        "not model inference",
        "not speech synthesis",
        "not streaming",
        "partially implemented",
    ):
        assert phrase in voice_doc, phrase
    for name in ("../README.md", "PROJECT_STATUS.md", "EVIDENCE_POLICY.md", "TRACEABILITY.md"):
        text = " ".join(_doc(name).lower().split())
        assert "voice-assistant" in text or "voice assistant" in text, name
        assert "nothing is streamed" in text or "nothing streamed" in text, name


def test_evidence_classes_are_distinct_and_match_contract(governance: dict[str, Any]) -> None:
    classes = {item["id"]: item for item in governance["evidence_classes"]}
    assert set(classes) == {member.value for member in EvidenceClass}
    assert classes["design_documentation"]["runtime_executed"] is False
    live = [name for name, item in classes.items() if item["live_provider_executed"]]
    assert live == ["live_integration"]
    for name in classes:
        assert f"`{name}`" in _doc("EVIDENCE_POLICY.md"), name


def test_vocabularies_match_contracts(governance: dict[str, Any]) -> None:
    assert governance["stream_events"] == [member.value for member in StreamEventType]
    assert governance["latency_stages"] == [member.value for member in LatencyStage]
    assert governance["modalities"] == [member.value for member in Modality]
    assert governance["provider_ports"] == [member.value for member in ProviderPort]
    assert governance["execution_modes"] == [member.value for member in ExecutionMode]


def test_security_invariants_are_documented(governance: dict[str, Any]) -> None:
    invariants = governance["security_invariants"]
    assert [item["id"] for item in invariants] == [f"SEC-{n:03d}" for n in range(1, 27)]
    threat_model = _doc("SECURITY_THREAT_MODEL.md")
    for item in invariants:
        assert f"| {item['id']} | {item['title']} |" in threat_model, item["id"]
        assert item["control"] and item["stories"], item["id"]


def test_definition_of_done_matches_governance(governance: dict[str, Any]) -> None:
    checklist = re.findall(r"^- \[ \] (.+)$", _doc("DEFINITION_OF_DONE.md"), re.MULTILINE)
    assert checklist == governance["definition_of_done"]
    assert len(checklist) == 25


def test_module_imports_only_stdlib_pydantic_pytest_itself_and_scoped_decoders() -> None:
    allowed = set(sys.stdlib_module_names) | ALLOWED_THIRD_PARTY
    package = MODULE_ROOT / "src" / "multimodal_voice_platform"
    test_helpers = {path.stem for path in (MODULE_ROOT / "tests").glob("*.py")}
    for path in _owned_files({".py"}):
        in_tests = path.is_relative_to(MODULE_ROOT / "tests")
        owner = path.relative_to(package).as_posix() if path.is_relative_to(package) else None
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root in RESTRICTED_THIRD_PARTY:
                    assert in_tests or owner in RESTRICTED_THIRD_PARTY[root], f"{path}: {name}"
                    continue
                assert root in allowed or (in_tests and root in test_helpers), f"{path}: {name}"


def test_source_has_no_command_execution_path() -> None:
    for path in (MODULE_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                module = getattr(node, "module", None) or ""
                names = {module, *(alias.name for alias in node.names)}
                assert not names & FORBIDDEN_MODULES, path
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                assert name not in FORBIDDEN_CALLS, f"{path}: {name}"


def test_owned_text_files_are_utf8_without_bom() -> None:
    files = _owned_files(TEXT_SUFFIXES)
    assert files
    for path in files:
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), path
        raw.decode("utf-8")
