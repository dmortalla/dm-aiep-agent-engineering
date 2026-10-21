"""Story 11 Slice 1: REQ-EVAL-002/003, REQ-DEL-005 regression harness evidence.

Runs accepted services against the retained golden set with a denied network.
Deterministic and local-integration evidence only; no live or paid execution.
"""

import json
import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from harness_engineering.domain import EvidenceClass
from harness_engineering.errors import ContractValidationError
from harness_engineering.evaluation import CaseStatus, MismatchKind, RegressionReport, observation
from harness_engineering.evaluation_lab import main, render_text, run_regression
from harness_engineering.evaluation_probes import HOSTILE_TEXT, REGISTRY, Probe

FAST = ("planning.dependency-priority-order", "lifecycle.retry-backoff")
SECRET = "SENTINEL-PROBE-EXCEPTION-DO-NOT-REPORT"


LOOPBACK = frozenset({"127.0.0.1", "::1"})


def deny_network(patch: pytest.MonkeyPatch) -> list[int]:
    """Count and deny every non-loopback connection.

    Loopback stays available because Windows asyncio builds its in-process
    self-pipe with a loopback socketpair (used by the local MCP SDK transport).
    """
    attempts = [0]
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guard(original: Callable[..., object]) -> Callable[..., object]:
        def connect(self: socket.socket, address: object, *args: object) -> object:
            host = address[0] if isinstance(address, tuple) and address else None
            if host in LOOPBACK:
                return original(self, address, *args)
            attempts[0] += 1
            raise OSError("Offline evaluation network attempt")

        return connect

    patch.setattr(socket.socket, "connect", guard(original_connect))
    patch.setattr(socket.socket, "connect_ex", guard(original_connect_ex))
    return attempts


def test_network_guard_denies_and_counts_external_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = deny_network(monkeypatch)
    with socket.socket() as sock, pytest.raises(OSError, match="Offline"):
        sock.connect(("192.0.2.1", 443))
    assert attempts == [1]


@pytest.fixture(scope="module")
def full_run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[RegressionReport, int]]:
    with pytest.MonkeyPatch.context() as patch:
        attempts = deny_network(patch)
        report = run_regression(tmp_path_factory.mktemp("evaluation") / "run")
        yield report, attempts[0]


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    return deny_network(monkeypatch)


def golden_copy(tmp_path: Path) -> dict:
    from importlib import resources

    text = resources.files("harness_engineering").joinpath(
        "evaluation_golden_set.json").read_text(encoding="utf-8")
    return json.loads(text)


def write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / f"golden-{uuid4().hex}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_full_regression_passes_every_golden_case(full_run) -> None:
    report, network_attempts = full_run
    assert report.succeeded
    assert (report.passed, report.regressed, report.errors) == (len(REGISTRY), 0, 0)
    assert tuple(case.case_id for case in report.cases) == tuple(REGISTRY)
    assert all(case.status is CaseStatus.PASSED for case in report.cases)
    assert report.evidence == (EvidenceClass.DETERMINISTIC, EvidenceClass.LOCAL_INTEGRATION)
    assert report.golden_source == "packaged"
    assert network_attempts == 0


def test_full_regression_measures_workflow_latency_against_frozen_slo(full_run) -> None:
    latency = full_run[0].workflow_latency
    assert latency.sample_count == 20
    assert latency.sufficient_samples
    assert latency.slo_p95_seconds == 5.0
    assert latency.cohort.evidence is EvidenceClass.DETERMINISTIC
    assert latency.slo_met is (latency.p95_seconds <= 5.0)


def test_report_is_machine_readable_and_revalidates(full_run) -> None:
    report = full_run[0]
    assert RegressionReport.model_validate_json(report.model_dump_json()) == report


def test_report_and_text_never_echo_hostile_fixture_or_paths(full_run, tmp_path: Path) -> None:
    report = full_run[0]
    for rendered in (report.model_dump_json(), render_text(report)):
        assert HOSTILE_TEXT not in rendered
        assert "SENTINEL-EVAL" not in rendered
        assert "Traceback" not in rendered
        assert str(tmp_path.parent) not in rendered


def test_text_contains_reviewer_guidance(full_run) -> None:
    text = render_text(full_run[0])
    for label in ("Demonstrates:", "Run:", "Action:", "Expect:", "Proves:", "Evidence:",
                  "Limitations:", "Verdict:"):
        assert label in text
    assert "-> PASS" in text


def test_edited_golden_expectation_is_detected_as_regression(tmp_path: Path) -> None:
    document = golden_copy(tmp_path)
    case = next(c for c in document["cases"] if c["case_id"] == "lifecycle.retry-backoff")
    case["expected"]["values"]["total_attempts"] = 4
    report = run_regression(tmp_path / "run", golden_path=write(tmp_path, document),
                            case_ids=FAST, latency_samples=1)
    assert not report.succeeded
    assert report.golden_source == "reviewer_file"
    regressed = next(c for c in report.cases if c.case_id == "lifecycle.retry-backoff")
    assert regressed.status is CaseStatus.REGRESSED
    assert [(m.field, m.kind, m.expected, m.observed) for m in regressed.mismatches] == [
        ("total_attempts", MismatchKind.CHANGED, 4, 5)
    ]
    assert report.cases[0].status is CaseStatus.PASSED


def test_behavior_drift_in_accepted_service_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = REGISTRY["planning.dependency-priority-order"]
    monkeypatch.setitem(REGISTRY, original.case_id, Probe(
        original.case_id, original.area, original.requirements, original.purpose,
        original.evidence,
        lambda _: observation(initial_ready=("metadata", "research"),
                              after_research_ready=("analyze", "metadata"),
                              execution_order=("research", "analyze", "draft", "review",
                                               "metadata")),
    ))
    report = run_regression(tmp_path / "run", case_ids=FAST[:1], latency_samples=1)
    (case,) = report.cases
    assert case.status is CaseStatus.REGRESSED
    assert case.mismatches[0].field == "initial_ready"


def test_probe_failure_is_reported_as_error_without_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = REGISTRY["planning.dependency-priority-order"]

    def failing(_: Path) -> object:
        raise ContractValidationError(SECRET)

    monkeypatch.setitem(REGISTRY, original.case_id, Probe(
        original.case_id, original.area, original.requirements, original.purpose,
        original.evidence, failing))
    report = run_regression(tmp_path / "run", case_ids=FAST, latency_samples=1)
    assert not report.succeeded
    assert report.cases[0].status is CaseStatus.ERROR
    assert report.cases[0].error_type == "ContractValidationError"
    assert report.cases[1].status is CaseStatus.PASSED  # Case isolation.
    assert SECRET not in report.model_dump_json()
    assert SECRET not in render_text(report)


def test_programming_defect_in_probe_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = REGISTRY["planning.dependency-priority-order"]

    def broken(_: Path) -> object:
        raise TypeError("probe defect")

    monkeypatch.setitem(REGISTRY, original.case_id, Probe(
        original.case_id, original.area, original.requirements, original.purpose,
        original.evidence, broken))
    with pytest.raises(TypeError, match="probe defect"):
        run_regression(tmp_path / "run", case_ids=FAST[:1], latency_samples=1)


@pytest.mark.parametrize("mutate", [
    lambda d: d["cases"].pop(),
    lambda d: d["cases"].append({"case_id": "unknown.case", "expected": {"values": {}}}),
    lambda d: d["cases"][0].update(evidence=["deployment"]),
])
def test_golden_cannot_add_remove_or_promote_cases(tmp_path: Path, mutate) -> None:
    document = golden_copy(tmp_path)
    mutate(document)
    with pytest.raises(ContractValidationError):
        run_regression(tmp_path / "run", golden_path=write(tmp_path, document),
                       case_ids=FAST, latency_samples=1)
    assert not (tmp_path / "run").exists()  # Rejected before any execution.


@pytest.mark.parametrize("case_ids", [(), ("unknown.case",), (FAST[0], FAST[0]),
                                      ("a.b",) * 33])
def test_case_selection_is_bounded_and_trusted(tmp_path: Path, case_ids: tuple) -> None:
    with pytest.raises(ContractValidationError):
        run_regression(tmp_path / "run", case_ids=case_ids, latency_samples=1)


@pytest.mark.parametrize("samples", [0, 21, True, 2.0, -1])
def test_latency_samples_are_bounded(tmp_path: Path, samples: object) -> None:
    with pytest.raises(ContractValidationError):
        run_regression(tmp_path / "run", case_ids=FAST, latency_samples=samples)  # type: ignore[arg-type]


def test_small_latency_cohort_never_claims_slo(tmp_path: Path) -> None:
    report = run_regression(tmp_path / "run", case_ids=FAST, latency_samples=1)
    assert report.succeeded
    assert report.evidence == (EvidenceClass.DETERMINISTIC,)
    assert report.workflow_latency.sample_count == 1
    assert report.workflow_latency.slo_met is None
    assert "not assessed" in render_text(report)


def test_existing_directory_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    with pytest.raises(FileExistsError):
        run_regression(tmp_path / "run", case_ids=FAST, latency_samples=1)


def test_cli_exit_codes_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--case", FAST[0], "--case", FAST[1], "--latency-samples", "1"]
    assert main(["--directory", str(tmp_path / "ok"), "--format", "json", *args]) == 0
    parsed = RegressionReport.model_validate_json(capsys.readouterr().out)
    assert parsed.succeeded

    document = golden_copy(tmp_path)
    document["cases"][0]["expected"]["values"]["initial_ready"] = ["metadata"]
    golden = write(tmp_path, document)
    assert main(["--directory", str(tmp_path / "drift"), "--golden", str(golden), *args]) == 1
    assert "[REGRESSED] planning.dependency-priority-order" in capsys.readouterr().out

    document["cases"][0]["evidence"] = ["live_provider"]
    forged = write(tmp_path, document)
    assert main(["--directory", str(tmp_path / "forged"), "--golden", str(forged), *args]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "evaluation_failed: ContractValidationError"

    assert main(["--directory", str(tmp_path / "ok"), *args]) == 2
    assert "new --directory" in capsys.readouterr().err


@pytest.mark.parametrize("depth", [17, 1200, 10000])
def test_cli_rejects_nesting_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], depth: int,
) -> None:
    import harness_engineering.evaluation_lab as lab

    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append("execution")
        pytest.fail("Malformed input reached evaluation execution")

    monkeypatch.setattr(lab, "_run_case", forbidden)
    monkeypatch.setattr(lab, "run_provider_workflow", forbidden)
    path = tmp_path / "deep.json"
    path.write_text("[" * depth + "0" + "]" * depth, encoding="utf-8")
    output = tmp_path / "must-not-exist"
    with pytest.raises(ContractValidationError):
        run_regression(output, golden_path=path)
    assert main(["--golden", str(path), "--directory", str(output)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "evaluation_failed: ContractValidationError"
    assert "Traceback" not in captured.err
    assert "RecursionError" not in captured.err
    assert calls == []
    assert not output.exists()
