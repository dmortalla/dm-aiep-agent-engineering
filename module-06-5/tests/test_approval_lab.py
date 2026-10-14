"""Integrated local evidence assertions over real approval, recovery and graph services."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from harness_engineering.approval_lab import (
    INPUT,
    SCENARIOS,
    ApprovalLabEvidence,
    ScenarioEvidence,
    _Fixture,
    run_approval_lab,
    run_scenario,
)
from harness_engineering.approval_persistence import ApprovalEventKind
from harness_engineering.approvals import ApprovalTrigger, HumanDecisionKind
from harness_engineering.errors import HarnessError


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_integrated_matrix(tmp_path: Path, scenario: str) -> None:
    evidence = run_scenario(tmp_path / scenario, scenario)
    assert evidence.original_collected
    assert evidence.compiled_graph and evidence.framework_checkpointer_absent
    assert evidence.graph_execute_nodes >= 1
    assert evidence.executed == (
        ("prepare", "protected") if evidence.expected == "execute" else ("prepare",)
    )
    if evidence.suspended:
        assert evidence.before.status is ApprovalEventKind.PENDING
        assert evidence.before.completed == ("prepare",)
        assert evidence.before.pending == ("protected",)
        assert evidence.before.audit_sequences == (1,)
        assert evidence.before.threshold == 0.8
        if evidence.expected == "execute":
            assert evidence.resume == "completed"
            assert evidence.execution_statuses == (ApprovalEventKind.CONSUMED,)
            assert evidence.after.pending == ()
            assert evidence.after.completed == ("prepare", "protected")
            assert evidence.after.audit_sequences == (1, 2, 3)
            assert evidence.after.audit_statuses == (
                ApprovalEventKind.PENDING,
                ApprovalEventKind.OVERRIDDEN
                if scenario == "override"
                else ApprovalEventKind.APPROVED,
                ApprovalEventKind.CONSUMED,
            )
            assert evidence.after.elapsed_milliseconds >= 31_000
        else:
            assert evidence.rejection_type
            assert evidence.execution_statuses == ()
            assert evidence.resume in ("rejected", "interrupted")
        if scenario.startswith("deny"):
            assert evidence.after.status is ApprovalEventKind.DENIED
            assert evidence.after.audit_sequences == (1, 2)
        if scenario in ("crash", "competing", "consumed"):
            assert evidence.after.status is ApprovalEventKind.CONSUMED
            assert evidence.after.pending == ("protected",)
    else:
        assert scenario == "confidence_equal"
        assert evidence.authorization == "not_required"


def test_threshold_and_separate_override_evidence(tmp_path: Path) -> None:
    low = run_scenario(tmp_path / "low", "approve")
    assert low.before.confidence < 0.8
    assert low.before.reasons == (ApprovalTrigger.LOW_CONFIDENCE,)
    expected = {
        "confidence_high": ApprovalTrigger.CONSEQUENTIAL,
        "privileged": ApprovalTrigger.PRIVILEGED_SCOPE,
        "risk": ApprovalTrigger.CONFIGURED_RISK,
        "escalation": ApprovalTrigger.ESCALATION,
    }
    for scenario, trigger in expected.items():
        result = run_scenario(tmp_path / scenario, scenario)
        assert result.before.confidence > 0.8
        assert result.before.reasons == (trigger,)
    override = run_scenario(tmp_path / "override", "override")
    assert override.after.decision_kind is HumanDecisionKind.OVERRIDE
    assert override.after.override_reason == "Accept ordinary low confidence"
    assert override.after.decision_evidence == "Independent local review"


def test_report_is_bounded_inert_and_immutable(tmp_path: Path) -> None:
    report = run_approval_lab(tmp_path / "all")
    assert len(report.scenarios) == len(SCENARIOS)
    assert report.classification == ("deterministic_fixture", "local_integration")
    raw = json.loads(report.model_dump_json())
    assert ApprovalLabEvidence.model_validate_json(report.model_dump_json()) == report

    def inspect(value: object) -> None:
        assert not callable(value)
        if isinstance(value, dict):
            assert not {
                "approvers",
                "override_approvers",
                "actor",
                "callback",
                "permission",
                "route",
                "principal_id",
                "_permit",
            }.intersection(value)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        else:
            assert value is None or type(value) in (str, int, float, bool)

    inspect(raw)
    with pytest.raises(ValidationError):
        report.scenarios[0].scenario = "forged"
    with pytest.raises(ValidationError):
        ApprovalLabEvidence.model_validate(
            {**report.model_dump(), "scenarios": report.scenarios + report.scenarios}
        )
    with pytest.raises(ValidationError):
        ScenarioEvidence.model_validate({**report.scenarios[0].model_dump(), "actor": "reviewer"})


def test_actual_framework_command_is_inert_input(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, "approve", 100)
    fixture.build().start(INPUT)
    fixture.decide(HumanDecisionKind.APPROVE, fixture.humans[0])
    with pytest.raises(HarnessError):
        fixture.build().resume(Command(resume={"approved": True}), actor=fixture.humans[0])
    assert fixture.calls == ["prepare"]
    assert fixture.inspect().status is ApprovalEventKind.APPROVED


def test_two_real_concurrent_resumes_cannot_execute_twice(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, "approve", 101)
    fixture.build().start(INPUT)
    fixture.decide(HumanDecisionKind.APPROVE, fixture.humans[0])
    contenders = (fixture.build(), fixture.build())
    barrier = Barrier(2)

    def resume(index: int) -> bool:
        barrier.wait(timeout=10)
        try:
            contenders[index].resume(INPUT, actor=fixture.humans[0])
        except HarnessError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(resume, (0, 1)))
    assert sum(outcomes) <= 1
    assert fixture.calls.count("protected") <= 1
    assert fixture.inspect().audit_sequences in ((1, 2), (1, 2, 3))
    with pytest.raises(HarnessError):
        fixture.build().resume(INPUT, actor=fixture.humans[0])
    assert fixture.calls.count("protected") <= 1


def test_fresh_directory_and_unknown_scenario_do_not_overwrite(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        run_approval_lab(tmp_path)
    with pytest.raises(ValueError):
        run_scenario(tmp_path / "unused", "unknown")
    assert not (tmp_path / "unused").exists()


def test_unexpected_programming_error_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: _Fixture) -> object:
        raise RuntimeError("unexpected defect")

    monkeypatch.setattr(_Fixture, "build", broken)
    with pytest.raises(RuntimeError, match="unexpected defect"):
        run_scenario(tmp_path / "broken", "approve")
