"""Story 11 Slice 1: REQ-EVAL-001 inline invariants and golden-set contracts.

Deterministic local evidence only; no provider, credential or network use.
"""

import dataclasses
import hashlib
import json
from importlib import resources
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness_engineering.domain import EvidenceClass
from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.evaluation import (
    MAX_GOLDEN_BYTES,
    CaseResult,
    CaseStatus,
    EvaluationArea,
    InlineInvariantMonitor,
    Invariant,
    InvariantViolationError,
    Mismatch,
    MismatchKind,
    compare,
    load_golden_set,
    observation,
)
from harness_engineering.evaluation_probes import REGISTRY, workflow_plan
from harness_engineering.lifecycle_controls import WorkflowPolicy
from harness_engineering.orchestration import (
    BoundarySnapshot,
    LifecycleInput,
    LifecyclePhase,
    LifecycleRuntime,
    StepResult,
    StopReason,
    TransientStepError,
)

SENTINEL = "SENTINEL-GOLDEN-CONTENT-DO-NOT-ECHO"


def ok(*_: object) -> StepResult:
    return StepResult(text="ok")


def flaky(failures: int):
    remaining = {"collect": failures}

    def step(task, _):
        if remaining.get(task.task_id, 0):
            remaining[task.task_id] -= 1
            raise TransientStepError("fixture")
        return StepResult(text="ok")

    return step


def recorded(runtime: LifecycleRuntime) -> tuple[BoundarySnapshot, ...]:
    snapshots: list[BoundarySnapshot] = []
    runtime.run_observed(LifecycleInput(), observer=snapshots.append)
    return tuple(snapshots)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- REQ-EVAL-001 inline invariant monitor ------------------------------------------


@pytest.mark.parametrize("step,boundaries,phase", [
    (ok, 3, LifecyclePhase.COMPLETED),
    (flaky(2), 5, LifecyclePhase.COMPLETED),
])
def test_monitor_accepts_real_lifecycle_runs(step, boundaries: int, phase) -> None:
    runtime = LifecycleRuntime(workflow_plan(), step, wait=lambda _: None)
    monitor = InlineInvariantMonitor(runtime.bounds())
    state = runtime.run_observed(LifecycleInput(), observer=monitor)
    assert state.phase is phase
    assert monitor.boundaries_checked == boundaries


def test_monitor_aborts_run_on_schedule_order_violation() -> None:
    calls: list[str] = []

    def step(task, _):
        calls.append(task.task_id)
        return StepResult(text="ok")

    runtime = LifecycleRuntime(workflow_plan(), step)
    wrong = dataclasses.replace(runtime.bounds(), task_ids=("report", "collect", "audit"))
    with pytest.raises(InvariantViolationError) as caught:
        runtime.run_observed(LifecycleInput(), observer=InlineInvariantMonitor(wrong))
    assert str(caught.value) == Invariant.SCHEDULE_ORDER.value
    assert calls == ["audit"]  # Fail closed: no further step after the violation.


def test_monitor_detects_attempt_bound_violation() -> None:
    runtime = LifecycleRuntime(workflow_plan(), flaky(2), wait=lambda _: None)
    tight = dataclasses.replace(runtime.bounds(), max_attempts_per_action=1)
    with pytest.raises(InvariantViolationError, match="retry bound"):
        runtime.run_observed(LifecycleInput(), observer=InlineInvariantMonitor(tight))


def test_monitor_detects_attempt_after_exhausted_deadline() -> None:
    clock = Clock()

    def slow(*_: object) -> StepResult:
        clock.now += 4.0
        return StepResult(text="ok")

    runtime = LifecycleRuntime(workflow_plan(), slow, clock=clock)
    tighter = dataclasses.replace(runtime.bounds(), deadline_seconds=3.0)
    with pytest.raises(InvariantViolationError, match="deadline"):
        runtime.run_observed(LifecycleInput(), observer=InlineInvariantMonitor(tighter))


def test_monitor_accepts_accepted_deadline_stop() -> None:
    clock = Clock()

    def slow(*_: object) -> StepResult:
        clock.now += 4.0
        return StepResult(text="ok")

    runtime = LifecycleRuntime(workflow_plan(), slow, clock=clock,
                               workflow_policy=WorkflowPolicy(deadline_seconds=5.0))
    monitor = InlineInvariantMonitor(runtime.bounds())
    state = runtime.run_observed(LifecycleInput(), observer=monitor)
    assert state.stop_reason is StopReason.DEADLINE_EXHAUSTED
    assert monitor.boundaries_checked == 3


def test_monitor_rejects_boundary_after_terminal_phase() -> None:
    runtime: LifecycleRuntime | None = None

    def cancel(*_: object) -> StepResult:
        assert runtime is not None
        runtime.cancel()
        return StepResult(text="ok")

    runtime = LifecycleRuntime(workflow_plan(), cancel)
    snapshots = recorded(runtime)
    assert snapshots[-1].lifecycle.phase is LifecyclePhase.SAFE_STOP
    monitor = InlineInvariantMonitor(runtime.bounds())
    for snapshot in snapshots:
        monitor(snapshot)
    with pytest.raises(InvariantViolationError, match="terminal"):
        monitor(snapshots[-1])


def test_monitor_rejects_regressing_progress() -> None:
    runtime = LifecycleRuntime(workflow_plan(), ok)
    first, second, _ = recorded(runtime)
    monitor = InlineInvariantMonitor(runtime.bounds())
    monitor(second)
    with pytest.raises(InvariantViolationError, match="never regress"):
        monitor(first)


def test_monitor_rejects_inconsistent_attempt_accounting() -> None:
    runtime = LifecycleRuntime(workflow_plan(), ok)
    first = recorded(runtime)[0]
    forged = BoundarySnapshot(first.lifecycle, (2,), first.elapsed_seconds)
    with pytest.raises(InvariantViolationError, match="sum to total"):
        InlineInvariantMonitor(runtime.bounds())(forged)


def test_monitor_bounds_boundary_count() -> None:
    runtime = LifecycleRuntime(workflow_plan(), ok)
    first = recorded(runtime)[0]
    monitor = InlineInvariantMonitor(dataclasses.replace(
        runtime.bounds(), task_ids=("audit",), max_attempts_per_action=1,
    ))
    monitor(first)
    monitor(first)
    with pytest.raises(InvariantViolationError, match="boundary count"):
        monitor(first)


@pytest.mark.parametrize("bounds", [None, object(), {"task_ids": ()}])
def test_monitor_requires_trusted_bounds(bounds: object) -> None:
    with pytest.raises(ContractValidationError):
        InlineInvariantMonitor(bounds)  # type: ignore[arg-type]


def test_monitor_rejects_forged_snapshot_type() -> None:
    monitor = InlineInvariantMonitor(LifecycleRuntime(workflow_plan(), ok).bounds())
    with pytest.raises(InvariantViolationError):
        monitor({"lifecycle": "completed"})  # type: ignore[arg-type]


def test_invariant_violation_is_harness_error_without_data() -> None:
    assert issubclass(InvariantViolationError, HarnessError)
    assert all(SENTINEL not in item.value for item in Invariant)


# --- REQ-EVAL-002 golden-set contract ----------------------------------------------


def packaged() -> dict:
    resource = resources.files("harness_engineering").joinpath("evaluation_golden_set.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def write(tmp_path: Path, document: object, name: str = "golden.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_packaged_golden_set_covers_trusted_registry_exactly() -> None:
    loaded = load_golden_set()
    assert loaded.source == "packaged"
    assert {case.case_id for case in loaded.golden.cases} == set(REGISTRY)
    raw = resources.files("harness_engineering").joinpath(
        "evaluation_golden_set.json").read_bytes()
    assert loaded.sha256 == hashlib.sha256(raw).hexdigest()


def test_registry_covers_every_architecture_area() -> None:
    assert {probe.area for probe in REGISTRY.values()} == set(EvaluationArea)
    assert all(set(p.evidence) <= {EvidenceClass.DETERMINISTIC,
                                   EvidenceClass.LOCAL_INTEGRATION}
               for p in REGISTRY.values())


def test_reviewer_golden_file_round_trips(tmp_path: Path) -> None:
    loaded = load_golden_set(write(tmp_path, packaged()))
    assert loaded.source == "reviewer_file"
    assert loaded.golden == load_golden_set().golden


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version=2),
    lambda d: d.update(evidence="live_provider"),
    lambda d: d["cases"][0].update(evidence=["live_provider"]),
    lambda d: d["cases"][0].update(area="cost"),
    lambda d: d["cases"][0].update(probe="os.system"),
    lambda d: d["cases"].append(d["cases"][0]),
    lambda d: d["cases"][0].update(case_id="../escape"),
    lambda d: d["cases"][0]["expected"]["values"].update(x=1.5),
    lambda d: d["cases"][0]["expected"]["values"].update(x={"nested": SENTINEL}),
    lambda d: d["cases"][0]["expected"]["values"].update(x=SENTINEL * 20),
    lambda d: d["cases"][0]["expected"]["values"].update(x=list(range(33))),
    lambda d: d["cases"][0]["expected"]["values"].update(BadName=1),
    lambda d: d.update(cases=[]),
])
def test_invalid_golden_documents_fail_closed_without_echo(tmp_path: Path, mutate) -> None:
    document = packaged()
    mutate(document)
    with pytest.raises(ContractValidationError) as caught:
        load_golden_set(write(tmp_path, document))
    assert SENTINEL not in str(caught.value)
    assert SENTINEL not in repr(caught.value)


@pytest.mark.parametrize("raw", [
    b"{not json",
    b"\xff\xfe\x00",
    b'{"schema_version": 1, "schema_version": 1, "name": "x", "cases": []}',
    b"[]",
])
def test_malformed_golden_bytes_fail_closed(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "golden.json"
    path.write_bytes(raw)
    with pytest.raises(ContractValidationError):
        load_golden_set(path)


def test_oversized_and_missing_golden_files_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (MAX_GOLDEN_BYTES + 1))
    with pytest.raises(ContractValidationError, match="exceeds"):
        load_golden_set(path)
    with pytest.raises(ContractValidationError, match="could not be read"):
        load_golden_set(tmp_path / "missing.json")


# --- REQ-EVAL-003 exact comparison -------------------------------------------------


def test_compare_is_exact_typed_and_ordered() -> None:
    expected = observation(flag=True, order=("a", "b"), count=1, gone="x", same=None)
    observed = observation(flag=1, order=("b", "a"), count=1, extra=False, same=None)
    assert compare(expected, observed) == (
        Mismatch(field="extra", kind=MismatchKind.UNEXPECTED, observed=False),
        Mismatch(field="flag", kind=MismatchKind.CHANGED, expected=True, observed=1),
        Mismatch(field="gone", kind=MismatchKind.MISSING, expected="x"),
        Mismatch(field="order", kind=MismatchKind.CHANGED, expected=("a", "b"),
                 observed=("b", "a")),
    )
    assert compare(expected, expected) == ()


@pytest.mark.parametrize("value", [1.5, {"a": 1}, object(), tuple(range(33)), "x" * 257])
def test_probe_observations_are_bounded_json_facts(value: object) -> None:
    with pytest.raises(ContractValidationError):
        observation(field=value)


def result(**changes: object) -> dict:
    base = dict(case_id="lifecycle.retry-backoff", area=EvaluationArea.LIFECYCLE,
                requirements=("REQ-EXEC-001",), purpose="p",
                evidence=(EvidenceClass.DETERMINISTIC,), status=CaseStatus.PASSED,
                mismatches=(), error_type=None, duration_seconds=0.0)
    base.update(changes)
    return base


@pytest.mark.parametrize("changes", [
    {"evidence": (EvidenceClass.LIVE_PROVIDER,)},
    {"evidence": (EvidenceClass.DEPLOYMENT,)},
    {"evidence": (EvidenceClass.MOCKED,)},
    {"status": CaseStatus.ERROR},
    {"error_type": "ValueError"},
    {"status": CaseStatus.REGRESSED},
    {"mismatches": (Mismatch(field="x", kind=MismatchKind.MISSING),)},
    {"error_type": "x: secret"},
])
def test_case_results_cannot_promote_evidence_or_hide_failure(changes: dict) -> None:
    CaseResult(**result())
    with pytest.raises(ValidationError):
        CaseResult(**result(**changes))


@pytest.mark.parametrize("depth", [17, 1200, 10000])
def test_loader_rejects_excessive_nesting(tmp_path: Path, depth: int) -> None:
    path = tmp_path / "deep.json"
    path.write_text("[" * depth + "0" + "]" * depth, encoding="utf-8")
    with pytest.raises(ContractValidationError) as caught:
        load_golden_set(path)
    assert "RecursionError" not in str(caught.value)


@pytest.mark.parametrize("depth", [16, 17, 1200])
def test_parsed_normalization_depth_boundary(depth: int) -> None:
    from harness_engineering.evaluation import MAX_VALUE_DEPTH, _freeze

    value: object = 0
    for _ in range(depth):
        value = [value]
    if depth <= MAX_VALUE_DEPTH:
        frozen = _freeze(value)
        for _ in range(depth):
            assert isinstance(frozen, tuple)
            frozen = frozen[0]
        assert frozen == 0
    else:
        with pytest.raises(ContractValidationError, match="nesting safety bound"):
            _freeze(value)
        with pytest.raises(ContractValidationError):
            observation(deep=value)


def test_loader_translates_decoder_recursion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def exhausted(*args: object, **kwargs: object) -> object:
        raise RecursionError("private decoder detail")

    path = tmp_path / "input.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(json, "loads", exhausted)
    with pytest.raises(ContractValidationError) as caught:
        load_golden_set(path)
    assert isinstance(caught.value.__cause__, RecursionError)
    assert str(caught.value) == "Golden set does not satisfy the contract."


def test_normalization_translates_recursion(monkeypatch: pytest.MonkeyPatch) -> None:
    import harness_engineering.evaluation as evaluation

    def exhausted(value: object) -> object:
        raise RecursionError("private normalization detail")

    monkeypatch.setattr(evaluation, "_freeze_bounded", exhausted)
    with pytest.raises(ContractValidationError) as caught:
        observation(value=[1])
    assert isinstance(caught.value.__cause__, RecursionError)
