"""Revision 6 behavioral contract; synthetic gates never certify their own pytest."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from reliability_safety_observability.domain import EvidenceClass
from reliability_safety_observability.evidence_records import EvidenceError, EvidenceStore
from reliability_safety_observability.release_readiness import (
    GateExecutor,
    ReadinessValidationError,
    ReadinessVerifier,
    jcs_bytes,
    record_projection,
    tagged_integer,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence(tmp_path):
    """Produce genuine evidence in an isolated runtime store."""
    store = EvidenceStore(tmp_path / "records")
    verifier = ReadinessVerifier(ROOT, store)
    binding = verifier.binding()
    evaluation = store.record_evaluation(
        candidate=binding.candidate_id, contract=binding.contract_sha256
    )
    lab = store.record_lab(candidate=binding.candidate_id, contract=binding.contract_sha256)
    return store, verifier, binding, evaluation, lab


def test_01_producer_projection_jcs_and_integer_contract(evidence):
    store, verifier, binding, evaluation, _ = evidence
    record = verifier.record_projection(evaluation)
    verifier.verify_projection(record)
    # RFC 8785 section 3.2.3 member ordering, using a fixed independent expectation.
    vector = {"€": "euro", "\r": "control", "😀": "emoji", "דּ": "hebrew", "1": "one"}
    expected = '{"\\r":"control","1":"one","€":"euro","😀":"emoji","דּ":"hebrew"}'.encode()
    assert jcs_bytes(vector) == expected
    assert jcs_bytes({"b": [True, None], "a": {"é": "x"}}) == (
        '{"a":{"é":"x"},"b":[true,null]}'.encode()
    )
    for version in (1, 2**53 - 1, 2**53, 2**53 + 7, 2**100):
        reference = store.record_evaluation(
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            target_version=version,
        )
        assert verifier.record_projection(reference).projection["versions"]["target_version"] == {
            "$integer": str(version)
        }
    for value in (True, 1.0, "1", Decimal(1), Fraction(1), {"$integer": "01"}):
        with pytest.raises(ReadinessValidationError):
            tagged_integer(value)
        with pytest.raises(EvidenceError):
            store.record_evaluation(
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                target_version=value,
            )
    for value in ("01", "+1", "\u0661", "1e0", " 1", {"$integer": "1"}):
        with pytest.raises(EvidenceError):
            store.record_evaluation(
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                target_version=value,
            )
    for forged in (
        replace(record, run_reference="0" * 64),
        replace(record, canonical_bytes=b"forged"),
        replace(record, projection_sha256="0" * 64),
    ):
        with pytest.raises(EvidenceError):
            verifier.verify_projection(forged)


def test_02_store_integrity_and_read_only_load(evidence, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor

    store, _, binding, reference, _ = evidence
    path = store.root / (reference + ".json")
    before = path.read_bytes()
    store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="evaluation_engine",
    )
    assert path.read_bytes() == before
    outside = store.root.parent / "outside-record.json"
    outside.write_bytes(before)
    redirected = store.root / ("f" * 64 + ".json")
    try:
        redirected.symlink_to(outside)
    except OSError as error:
        assert getattr(error, "winerror", None) == 1314
        print("DESTINATION_SYMLINK_UNAVAILABLE: Windows privilege 1314")
    else:
        try:
            with pytest.raises(EvidenceError):
                store.load(
                    "f" * 64,
                    candidate=binding.candidate_id,
                    contract=binding.contract_sha256,
                    producer="evaluation_engine",
                )
            assert outside.read_bytes() == before
        finally:
            redirected.unlink()
    # Two bounded processes share the real runtime store, including its origin
    # key. Publication may refuse contention, but cannot silently overwrite.
    import subprocess
    import sys

    child = (
        "import sys; from pathlib import Path; "
        "from reliability_safety_observability.evidence_records import EvidenceStore; "
        "s=EvidenceStore(Path(sys.argv[1])); "
        "print(s.record_evaluation(candidate=sys.argv[2],contract=sys.argv[3],"
        "target_version=int(sys.argv[4])))"
    )
    for versions in ((10, 10), (11, 12)):
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(store.root),
                    binding.candidate_id,
                    binding.contract_sha256,
                    str(version),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for version in versions
        ]
        successes = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=60)
                if process.returncode == 0:
                    child_reference = stdout.decode().strip()
                    store.load(
                        child_reference,
                        candidate=binding.candidate_id,
                        contract=binding.contract_sha256,
                        producer="evaluation_engine",
                    )
                    successes.append(child_reference)
                else:
                    assert b"publication busy" in stderr
            assert successes
            if versions[0] == versions[1]:
                assert len(set(successes)) == 1
            else:
                assert len(set(successes)) == len(successes)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    # Re-executing the accepted deterministic producer is idempotent.
    def produce(version=1):
        return store.record_evaluation(
            candidate=binding.candidate_id, contract=binding.contract_sha256, target_version=version
        )

    assert produce() == reference
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: produce(), range(2))) == [reference, reference]
    with ThreadPoolExecutor(max_workers=2) as pool:
        distinct = list(pool.map(produce, (2, 3)))
    assert len(set(distinct)) == 2 and reference not in distinct
    assert not list(store.root.glob("*.pending"))
    import os

    if os.name == "nt":
        target = store.root.parent / "junction-target"
        target.mkdir()
        junction = store.root.parent / "junction"
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            check=False,
        )
        assert created.returncode == 0, "Windows junction fixture could not be created"
        try:
            with pytest.raises(EvidenceError, match="Unsafe"):
                EvidenceStore(junction / "escape")
            assert not (target / "escape").exists()
        finally:
            junction.rmdir()

    original_link = os.link
    observed_publications = []

    def observe_link(source, destination):
        assert not destination.exists()
        assert json.loads(source.read_bytes())["envelope"]["producer"] == "evaluation_engine"
        original_link(source, destination)
        assert destination.read_bytes() == source.read_bytes()
        observed_publications.append(destination)

    with monkeypatch.context() as context:
        context.setattr(os, "link", observe_link)
        produce(20)
    assert len(observed_publications) == 1
    inventory = set(store.root.glob("*.json"))

    def failed_link(source, destination):
        raise OSError("controlled publication failure")

    with monkeypatch.context() as context:
        context.setattr(os, "link", failed_link)
        with pytest.raises(OSError, match="controlled publication failure"):
            produce(21)
    assert set(store.root.glob("*.json")) == inventory
    assert not list(store.root.glob("*.pending"))
    assert not (store.root / "publication.lock").exists()
    # Every envelope mutation invalidates the existing authenticated reference.
    for field, changed in (
        ("schema", 99),
        ("producer", "live_vendor"),
        ("candidate", "other"),
        ("contract", "other"),
        ("payload", {"class": "live_model"}),
    ):
        document = json.loads(before)
        document["envelope"][field] = changed
        path.write_text(json.dumps(document))
        with pytest.raises(EvidenceError):
            store.load(
                reference,
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                producer="evaluation_engine",
            )
        path.write_bytes(before)
    store.capacity = len(list(store.root.glob("*.json")))
    with pytest.raises(EvidenceError, match="capacity"):
        produce(4)
    # Occupied corrupt content cannot be overwritten by a producer rerun.
    path.write_bytes(b"corrupt")
    with pytest.raises(EvidenceError, match="collision"):
        produce()
    assert path.read_bytes() == b"corrupt"
    path.write_bytes(before)
    for invalid in ("../origin.key", "missing", "0" * 64):
        with pytest.raises(EvidenceError):
            store.load(
                invalid,
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                producer="evaluation_engine",
            )
    path.write_bytes(before[:20])  # Adversarial corruption in disposable runtime storage.
    with pytest.raises(EvidenceError):
        store.load(
            reference,
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            producer="evaluation_engine",
        )


def test_03_three_lab_support(evidence):
    store, verifier, binding, evaluation, lab = evidence
    links = verifier.reconcile_labs(evaluation, lab)
    assert set(links) == {"evaluation", "failure_recovery", "observability"}
    assert links["observability"]["status"] == "open"
    with pytest.raises(EvidenceError):
        verifier.reconcile_labs(lab, evaluation)
    workflow = store.record_workflow(
        candidate=binding.candidate_id, contract=binding.contract_sha256
    )
    observed = verifier.observability(workflow)
    linked = verifier.reconcile_labs(evaluation, lab, workflow=workflow)
    assert linked["observability"]["reference"] == workflow
    assert linked["observability"]["status"] == "verified_local_execution"
    assert observed["source_identity"]["workflow_id"]
    assert observed["semantics"]["authorization"] == "allow"
    assert observed["class"] == "deterministic_fixture"
    with pytest.raises(EvidenceError):
        verifier.observability(evaluation)
    acceptance = verifier.artifacts(evaluation, lab, workflow=workflow)["integrated_acceptance"]
    assert acceptance["observability"]["reference"] == workflow
    rows = {
        row["requirement"]: row
        for row in verifier.reconcile_traceability(evaluation, workflow=workflow)
    }
    for identifier in ("REQ-OBS-001", "REQ-OBS-002", "REQ-OBS-003"):
        assert rows[identifier]["status"] == "verified"
        assert rows[identifier]["evidence_reference"] == workflow
    assert rows["REQ-OBS-005"]["status"] == "open"
    assert rows["REQ-OBS-004"]["status"] == "open"
    assert rows["REQ-OBS-004"]["remaining_gaps"]
    complete_sources = {
        row["requirement"]: row
        for row in verifier.reconcile_traceability(evaluation, workflow=workflow, lab=lab)
    }
    assert complete_sources["REQ-OBS-005"]["status"] == "open"
    assert complete_sources["REQ-OBS-005"]["evidence_reference"] == lab
    lab_row = complete_sources["REQ-LAB-003"]
    assert lab_row["status"] == "verified"
    assert lab_row["evidence_references"] == [lab]
    assert lab_row["historical_qualifications"]
    assert len(lab_row["observed_lab_scenarios"]) == 20
    assert [r["kind"] for r in complete_sources["REQ-REL-001"]["observed_lab_scenarios"]] == [
        "s01",
        "s05",
    ]
    assert lab in complete_sources["REQ-REL-001"]["evidence_references"]
    from copy import deepcopy

    from reliability_safety_observability.evidence_records import _RECORDING_AUTHORITY

    source_lab = store.load(
        lab,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="failure_lab",
    )["payload"]
    _assert_lab_classification_consistency(evidence, workflow, source_lab)
    bad = deepcopy(source_lab)
    bad["summary"]["passed_count"] -= 1
    inconsistent = store._publish(
        "failure_lab",
        binding.candidate_id,
        binding.contract_sha256,
        bad,
        _authority=_RECORDING_AUTHORITY,
    )
    with pytest.raises(EvidenceError, match="contradicts"):
        verifier.reconcile_traceability(evaluation, lab=inconsistent)
    negative = deepcopy(bad)
    negative["summary"]["failed_count"] = 1
    negative["results"][0]["passed"] = False
    rejected = store._publish(
        "failure_lab",
        binding.candidate_id,
        binding.contract_sha256,
        negative,
        _authority=_RECORDING_AUTHORITY,
    )
    negative_rows = {
        r["requirement"]: r for r in verifier.reconcile_traceability(evaluation, lab=rejected)
    }
    assert negative_rows["REQ-LAB-003"]["status"] == "rejected"
    assert negative_rows["REQ-LAB-003"]["remaining_gaps"]
    assert negative_rows["REQ-REL-001"]["status"] == "open"
    verifier.verify_traceability_claim(evaluation, lab_row, workflow=workflow, lab=lab)
    with pytest.raises(EvidenceError):
        verifier.verify_traceability_claim(evaluation, lab_row)
    for identifier in ("REQ-LAB-001", "REQ-DEL-001"):
        assert complete_sources[identifier]["status"] == "open"
        assert complete_sources[identifier]["evidence_reference"] == workflow


def _assert_lab_classification_consistency(evidence, workflow, source_lab):
    """Refuse authenticated class-count contradictions without publishing claims."""
    from copy import deepcopy

    from reliability_safety_observability.evidence_records import _RECORDING_AUTHORITY

    store, verifier, binding, evaluation, lab = evidence
    counts = {
        "simulated_failure": 13,
        "mocked_provider_contract": 6,
        "deterministic_fixture": 1,
    }
    assert source_lab["summary"]["evidence_counts"] == counts
    assert {
        r["requirement"]: r
        for r in verifier.reconcile_traceability(evaluation, workflow=workflow, lab=lab)
    }["REQ-LAB-003"]["status"] == "verified"

    def publish(payload):
        return store._publish(
            "failure_lab",
            binding.candidate_id,
            binding.contract_sha256,
            payload,
            _authority=_RECORDING_AUTHORITY,
        )

    # Keep sums at twenty where possible to prove that arithmetic totals alone
    # do not establish agreement with the actual scenario classifications.
    attacks = [
        {"live_vendor": 20},
        {"live_model": 20},
        {"simulated_failure": 14, "mocked_provider_contract": 6},
        {**counts, "unexpected_class": 0},
        {**counts, "live_vendor": 0},
        {"simulated_failure": 12, "mocked_provider_contract": 7, "deterministic_fixture": 1},
        None,
        [13, 6, 1],
    ]
    for malformed in (True, False, "13", 13.0, None, -1, 21, [], {}):
        attacks.append({**counts, "simulated_failure": malformed})
    for changed_counts in attacks:
        payload = deepcopy(source_lab)
        payload["summary"]["evidence_counts"] = changed_counts
        reference = publish(payload)
        result = None
        with pytest.raises(EvidenceError, match="classification"):
            result = verifier.reconcile_traceability(evaluation, workflow=workflow, lab=reference)
        # Neither REQ-LAB-003 nor any other requirement can escape as VERIFIED.
        assert result is None
        with pytest.raises(EvidenceError, match="classification"):
            verifier.artifacts(evaluation, reference, workflow=workflow)
    # A supported label added with a positive count is also contradictory when
    # no individual observation has that class. Legitimate zero entries remain
    # accepted exactly as permitted by LabSummary's established schema.
    homogeneous = deepcopy(source_lab)
    for result in homogeneous["results"]:
        result["evidence_class"] = "simulated_failure"
    for zero_counts in (
        {"simulated_failure": 20},
        {"simulated_failure": 20, "mocked_provider_contract": 0, "deterministic_fixture": 0},
    ):
        homogeneous["summary"]["evidence_counts"] = zero_counts
        reference = publish(homogeneous)
        row = next(
            r
            for r in verifier.reconcile_traceability(evaluation, lab=reference)
            if r["requirement"] == "REQ-LAB-003"
        )
        assert row["status"] == "verified"
    homogeneous["summary"]["evidence_counts"] = {
        "simulated_failure": 19,
        "deterministic_fixture": 1,
    }
    with pytest.raises(EvidenceError, match="classification"):
        verifier.reconcile_traceability(evaluation, lab=publish(homogeneous))
    invalid_observation = deepcopy(source_lab)
    invalid_observation["results"][0]["evidence_class"] = "live_vendor"
    with pytest.raises(EvidenceError, match="classification"):
        verifier.reconcile_traceability(evaluation, lab=publish(invalid_observation))
    # Invalid signed fixture records never poison the independently valid input.
    assert (
        next(
            r
            for r in verifier.reconcile_traceability(evaluation, lab=lab)
            if r["requirement"] == "REQ-LAB-003"
        )["status"]
        == "verified"
    )


def test_04_engine_baseline_provenance(evidence):
    from streamlit.testing.v1 import AppTest

    store, _, binding, reference, _ = evidence
    source = store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="evaluation_engine",
    )
    assert source["payload"]["baseline_digest"] and source["payload"]["rows"]
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
    app.button(key="run_workflow").click().run()
    assert not app.exception
    assert any("workflow_id" in row.value and "trace_id" in row.value for row in app.json)
    assert any("deterministic_fixture" in row.value for row in app.json)
    assert "deterministic_demo_complete" not in repr(app.json)
    with pytest.raises(EvidenceError):
        record_projection(binding, "invented", {"verdict": "pass"})


def test_05_genuine_failure_summary(evidence):
    from streamlit.testing.v1 import AppTest

    _, verifier, _, evaluation, lab = evidence
    failure = verifier.artifacts(evaluation, lab)["failure_path"]
    summary = failure["source"]["summary"]
    assert summary["scenario_count"] == summary["passed_count"] + summary["failed_count"]
    assert failure["reference"] == lab
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
    app.button(key="run_benchmark").click().run()
    assert not app.exception
    assert any(
        "report_digest" in row.value
        and "regression" in row.value
        and "deterministic_fixture" in row.value
        for row in app.json
    )


def test_06_dependency_runtime_support(evidence):
    import streamlit

    store, verifier, binding, evaluation, lab = evidence
    dependency = verifier.artifacts(evaluation, lab)["dependency"]
    assert dependency["streamlit_pin_matches"]
    assert dependency["registry_sources_verified"]
    assert not dependency["prohibited_present"]
    assert streamlit.__version__ == "1.66.1"
    reference = store.record_accepted_tests(
        candidate=binding.candidate_id, contract=binding.contract_sha256
    )
    recorded = store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="accepted_test_execution",
    )
    assert recorded["payload"]["exit_code"] == 0
    assert len(recorded["payload"]["reports"]) >= 17
    bundled = verifier.artifacts(evaluation, lab, accepted_tests=reference)
    assert bundled["dependency"]["accepted_test_reference"] == reference
    assert bundled["dependency"]["accepted_test_reports"]
    assert all(
        report["outcome"] == "passed" for report in bundled["dependency"]["accepted_test_reports"]
    )
    bound_rows = {r["requirement"]: r for r in bundled["traceability"]["rows"]}
    assert "Scoped passing test observations" in bound_rows["REQ-COST-003"]["reason"]
    assert bound_rows["REQ-COST-003"]["observed_test_references"]
    assert bound_rows["REQ-COST-003"]["status"] == "open"
    tools = bundled["integrated_acceptance"]["tool_evidence"]
    assert {item["tool"] for item in tools} == {"Langfuse", "LangSmith", "Helicone", "Guardrails"}
    assert all(item["status"] == "qualified" and item["reference"] == reference for item in tools)
    assert all(item["class"] not in {"live_vendor", "live_model"} for item in tools)
    integrated = bundled["integrated_acceptance"]
    security = bundled["adversarial_security"]
    execution = recorded["payload"]
    evaluation_payload = store.load(
        evaluation,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="evaluation_engine",
    )["payload"]
    lab_payload = store.load(
        lab,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="failure_lab",
    )["payload"]
    expected_classes = {}
    for payload in (evaluation_payload, lab_payload, execution):
        label = payload["class"]
        expected_classes[label] = expected_classes.get(label, 0) + 1
    assert integrated["evidence_class_tally"] == expected_classes
    assert integrated["accepted_test_reports"] == execution["reports"]
    assert integrated["accepted_test_order"] == [item["node_id"] for item in execution["reports"]]
    assert integrated["accepted_test_timing"] == {
        key: execution[key] for key in ("started_at_utc", "finished_at_utc", "duration_ns")
    }
    from datetime import datetime

    started = datetime.fromisoformat(execution["started_at_utc"])
    finished = datetime.fromisoformat(execution["finished_at_utc"])
    assert started.tzinfo is not None
    assert finished.tzinfo is not None
    assert finished >= started
    assert isinstance(execution["duration_ns"], int)
    assert execution["duration_ns"] > 0
    assert security["evidence_class"] == evaluation_payload["class"]
    assert security["accepted_test_reference"] == reference
    assert security["accepted_test_evidence_class"] == execution["class"]
    expected_security_reports = [
        item
        for item in execution["reports"]
        if item["node_id"].startswith(
            (
                "tests/test_reliability.py::test_safety_",
                "tests/test_guardrails_integration.py::",
            )
        )
    ]
    assert security["test_reports"] == expected_security_reports
    assert security["test_references"] == [
        item["node_id"]
        for item in expected_security_reports
        if item["phase"] == "call" and item["outcome"] == "passed"
    ]
    assert security["test_status"] == "qualified"
    reconciled = {
        row["requirement"]: row
        for row in verifier.reconcile_traceability(evaluation, accepted_tests=reference)
    }
    for requirement in ("REQ-SEC-010", "REQ-ISO-001", "REQ-ISO-002"):
        assert reconciled[requirement]["status"] == "verified"
        assert reconciled[requirement]["evidence_reference"] == reference
        assert reconciled[requirement]["observed_test_references"]
        assert set(reconciled[requirement]["observed_test_references"]) <= set(
            reconciled[requirement]["test_references"]
        )
        assert reference in reconciled[requirement]["evidence_references"]


def test_07_integrated_acceptance_binding(evidence):
    _, verifier, binding, evaluation, lab = evidence
    result = verifier.artifacts(evaluation, lab)["integrated_acceptance"]
    assert result["candidate"] == binding.candidate_id
    assert result["contract"] == binding.contract_sha256
    assert result["status"] == "open"
    assert result["accepted_test_reference"] is None
    assert result["accepted_test_reports"] == []
    assert result["accepted_test_order"] == []
    assert result["accepted_test_timing"] is None
    security = verifier.artifacts(evaluation, lab)["adversarial_security"]
    assert security["accepted_test_reference"] is None
    assert security["accepted_test_evidence_class"] is None
    assert security["test_references"] == []
    assert security["test_reports"] == []
    assert security["test_status"] == "open"
    failure = verifier.artifacts(evaluation, lab)["failure_path"]["source"]
    assert len(failure["results"]) == failure["summary"]["scenario_count"]
    assert (
        result["lab_reconciliation"]["failure_recovery"]["summary_digest"]
        == (failure["summary"]["digest"])
    )


def test_08_actual_security_outcomes(evidence):
    _, verifier, binding, evaluation, lab = evidence
    checks = verifier.artifacts(evaluation, lab)["adversarial_security"]["checks"]
    assert any(row["classification"] == "authorization_denied" for row in checks)
    assert any(row["classification"] == "safety_denied" for row in checks)
    # Direct, non-recursive producer-authority assertions: unauthorized
    # publication, unsupported producer identities and contradictory
    # captured-result classes fail closed at the authenticated seam.
    from reliability_safety_observability import evidence_records as records

    authority = records._RECORDING_AUTHORITY
    for producer, payload, expected in (
        ("evaluation_engine", {"class": "live_vendor"}, "not producer-compatible"),
        ("failure_lab", {"class": "live_vendor"}, "not producer-compatible"),
        ("accepted_test_execution", {"class": "live_model"}, "not producer-compatible"),
        # Unsupported identities are refused by the capability gate itself:
        # the producer whitelist and the internal-authority requirement share
        # one fail-closed boundary.
        ("live_vendor", {"class": "deterministic_fixture"}, "capability"),
        ("live_model", {"class": "simulated_failure"}, "capability"),
    ):
        with pytest.raises(EvidenceError, match=expected):
            evidence[0]._publish(
                producer,
                binding.candidate_id,
                binding.contract_sha256,
                payload,
                _authority=authority,
            )
    for attacker in (object(), "authority", None):
        with pytest.raises(EvidenceError, match="capability"):
            evidence[0]._publish(
                "evaluation_engine",
                binding.candidate_id,
                binding.contract_sha256,
                {"class": "deterministic_fixture"},
                _authority=attacker,
            )
    genuine = next(
        row
        for row in verifier.reconcile_traceability(evaluation)
        if row["requirement"] == "REQ-EVD-001"
    )
    verifier.verify_traceability_claim(evaluation, genuine)
    for forged in (
        {**genuine, "adrs": ["ADR-007-010"]},
        {**genuine, "story": "9"},
        {**genuine, "tests": ["19"]},
        {**genuine, "evidence_reference": lab},
    ):
        with pytest.raises(EvidenceError):
            verifier.verify_traceability_claim(evaluation, forged)
    with pytest.raises(EvidenceError):
        verifier.policy_outcomes(lab)
    with pytest.raises(EvidenceError):
        verifier.artifacts(evaluation, lab, accepted_tests=evaluation)
    with pytest.raises(EvidenceError):
        verifier.artifacts(evaluation, lab, accepted_tests=lab)
    with pytest.raises(EvidenceError):
        verifier.artifacts(lab, evaluation)
    # Untrusted claims are rejected as inputs; they never define authority.
    attacks = (
        lambda: verifier.record_projection({"producer": "evaluation_engine", "run": "forged"}),
        lambda: verifier.artifacts({"status": "verified"}, lab),
        lambda: verifier.reconcile_traceability(
            {
                "requirement": "REQ-INVENTED-001",
                "adr": "ADR-007-999",
                "story": "99",
                "test": "21",
                "evidence": evaluation,
            }
        ),
        lambda: verifier.reconcile_labs(evaluation, {"lab": "invented", "status": "passed"}),
        lambda: verifier.policy_outcomes({"budget": "within_budget"}),
        lambda: GateExecutor(verifier).verify(
            {"commands": ["invented"], "output_digest": "0" * 64}
        ),
        lambda: verifier.record_projection("0" * 64),
    )
    for attack in attacks:
        with pytest.raises(EvidenceError):
            attack()
    original = verifier.record_projection(evaluation)
    for copied in (
        replace(original, binding=replace(original.binding, candidate_id="0" * 64)),
        replace(original, binding=replace(original.binding, contract_sha256="0" * 64)),
    ):
        with pytest.raises(EvidenceError):
            verifier.verify_projection(copied)


def test_09_authoritative_traceability(evidence):
    _, verifier, _, evaluation, _ = evidence
    rows = verifier.reconcile_traceability(evaluation)
    import re

    required = set(
        re.findall(r"^REQ-[A-Z]+-[0-9]{3}", (ROOT / "docs/REQUIREMENTS.md").read_text(), re.M)
    )
    assert {row["requirement"] for row in rows} == required
    automated = next(row for row in rows if row["requirement"] == "REQ-EVAL-001")
    assert automated["status"] == "verified" and automated["evidence_reference"] == evaluation
    replay = [row for row in verifier.policy_outcomes(evaluation) if row["replayed"]]
    assert replay and all(row["effects"] == 1 for row in replay)
    assert all(row["source_line"] > 0 for row in rows)
    _assert_complete_reconciliation(rows, required)
    expected_concepts = {
        "REQ-EVD-001": [1, 7, 8, 10],
        "REQ-EVD-002": [1, 14],
        "REQ-EVD-003": [1, 17],
        "REQ-EVD-004": [1, 7, 17],
        "REQ-EVD-005": [11, 12, 20],
        "REQ-EVD-006": [17, 18],
        "REQ-EVD-007": [1, 13, 17, 18],
    }
    for row in rows:
        if row["requirement"] in expected_concepts:
            assert row["conceptual_tests"] == expected_concepts[row["requirement"]]
        if row["status"] == "open" and row["evidence_references"]:
            assert row["evidence_gap_kind"] == "partial_current_support"
    assert all(row["status"] != "qualified_historical" for row in rows)
    print(
        "TRACEABILITY_COUNTS",
        {
            status: sum(row["status"] == status for row in rows)
            for status in ("verified", "open", "qualified_historical", "rejected")
        },
    )
    assert {f"REQ-EVD-{number:03}" for number in range(1, 8)} <= {
        row["requirement"] for row in rows
    }


def _assert_complete_reconciliation(rows, required):
    """Compare the output against the frozen row shape, not a second generator."""
    assert [r["requirement_id"] for r in rows] == sorted(required)
    assert len(rows) == len(required) == 96
    for row in rows:
        assert row["status"] in {"open", "qualified_historical", "verified", "rejected"}
        for field in (
            "adr_ids",
            "story_ids",
            "implementation_references",
            "test_references",
            "evidence_references",
        ):
            assert isinstance(row[field], list)
            assert row[field] == sorted(set(row[field]))
        assert row["requirement"] == row["requirement_id"]
        assert row["adrs"] == row["adr_ids"]
        assert row["implementing_stories"] == row["story_ids"]
        assert {d["reference"] for d in row["evidence_details"]} == set(row["evidence_references"])
        assert all(
            d["candidate"] == row["candidate"] and d["contract"] == row["contract"]
            for d in row["evidence_details"]
        )
        if row["status"] == "verified":
            assert row["implementation_references"] and row["evidence_references"]
            assert row["remaining_gaps"] == [] and row["required_proof"] == ""
            assert row["evidence_gap_kind"] == "none"
        else:
            assert row["remaining_gaps"]
        assert row["implementation_scope"]


def test_10_actual_budget_outcomes(evidence):
    _, verifier, _, evaluation, _ = evidence
    outcomes = verifier.policy_outcomes(evaluation)
    assert any(row["budget"] == "budget_exhausted" for row in outcomes)
    assert any(row["budget"] == "within_budget" for row in outcomes)
    with pytest.raises(EvidenceError):
        verifier.policy_outcomes("invented")


def test_11_classification_anti_promotion(evidence, monkeypatch):
    store, _, binding, reference, _ = evidence
    for producer in ("evaluation_engine", "live_vendor", "live_model", "gate_executor"):
        with pytest.raises(EvidenceError, match=r"capability|producer-compatible"):
            store._publish(
                producer,
                binding.candidate_id,
                binding.contract_sha256,
                {"class": "live_vendor", "status": "passed"},
            )
    assert {item.value for item in EvidenceClass} == {
        "deterministic_fixture",
        "simulated_failure",
        "mocked_provider_contract",
        "live_vendor",
        "live_model",
    }
    for producer in ("live_vendor", "live_model"):
        with pytest.raises(EvidenceError):
            store.load(
                reference,
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                producer=producer,
            )

    _assert_contradictory_authenticated_payloads_rejected(evidence, monkeypatch)


def _assert_contradictory_authenticated_payloads_rejected(evidence, monkeypatch):
    """Reject sealed contradictions at publication and artifact reload."""
    from copy import deepcopy

    from reliability_safety_observability import evidence_records as records

    store, verifier, binding, evaluation, lab = evidence
    reference = store.record_accepted_tests(
        candidate=binding.candidate_id, contract=binding.contract_sha256
    )
    genuine = store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="accepted_test_execution",
    )["payload"]
    lab_payload = store.load(
        lab,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="failure_lab",
    )["payload"]
    attacks = []
    for producer, payload, field, value in (
        ("failure_lab", lab_payload, "class", "live_vendor"),
        ("failure_lab", lab_payload, "class", None),
        ("accepted_test_execution", genuine, "class", "live_model"),
        ("accepted_test_execution", genuine, "class", None),
        ("accepted_test_execution", genuine, "selection", []),
        ("accepted_test_execution", genuine, "sources", {}),
        ("accepted_test_execution", genuine, "started_at_utc", "invalid"),
        ("accepted_test_execution", genuine, "finished_at_utc", genuine["started_at_utc"]),
        ("accepted_test_execution", genuine, "duration_ns", -1),
        ("accepted_test_execution", genuine, "duration_ns", 180_000_000_000),
        ("accepted_test_execution", genuine, "reports", []),
        ("accepted_test_execution", genuine, "exit_code", 1),
    ):
        changed = deepcopy(payload)
        changed[field] = value
        attacks.append((producer, changed))
    changed = deepcopy(genuine)
    first = next(iter(changed["sources"]))
    changed["sources"][first]["digest"] = "0" * 64
    attacks.append(("accepted_test_execution", changed))
    changed = deepcopy(genuine)
    changed["sources"][first]["assertion_lines"] = []
    attacks.append(("accepted_test_execution", changed))
    for node, outcome in (
        ("tests/unrelated.py::test_x", "passed"),
        ("tests/test_reliability.py::test_safety_invented", "passed"),
        ("tests/test_reliability.py::test_safety_provider_failure_never_recovers", "invented"),
        ("tests/test_reliability.py::test_safety_provider_failure_never_recovers", "failed"),
    ):
        changed = deepcopy(genuine)
        changed["reports"] = [{"node_id": node, "phase": "call", "outcome": outcome}]
        attacks.append(("accepted_test_execution", changed))
    changed = deepcopy(genuine)
    changed.update(
        selection=[],
        sources={},
        reports=[
            {
                "node_id": "tests/test_reliability.py::test_safety_provider_failure_never_recovers",
                "phase": "call",
                "outcome": "passed",
            }
        ],
        started_at_utc="invalid",
        finished_at_utc="invalid",
        duration_ns=-1,
    )
    attacks.append(("accepted_test_execution", changed))
    for producer, payload in attacks:
        with pytest.raises(EvidenceError):
            store._publish(
                producer,
                binding.candidate_id,
                binding.contract_sha256,
                payload,
                _authority=records._RECORDING_AUTHORITY,
            )
        # Mint an authenticated legacy contradiction using a test-only seam.
        # Restore the real validator before exercising the public reload path.
        with monkeypatch.context() as context:
            context.setattr(records, "_validate_evidence_payload", lambda *_: None)
            forged = store._publish(
                producer,
                binding.candidate_id,
                binding.contract_sha256,
                payload,
                _authority=records._RECORDING_AUTHORITY,
            )
        with pytest.raises(EvidenceError):
            if producer == "failure_lab":
                verifier.artifacts(evaluation, forged)
            else:
                verifier.artifacts(evaluation, lab, accepted_tests=forged)
    artifacts = verifier.artifacts(evaluation, lab, accepted_tests=reference)
    assert artifacts["adversarial_security"]["test_status"] == "qualified"
    assert artifacts["adversarial_security"]["accepted_test_evidence_class"] == (
        "deterministic_fixture"
    )


def test_12_record_minimization(evidence, monkeypatch):
    store, verifier, binding, evaluation, lab = evidence
    canary = "controlled-secret-canary-sk-test-DO-NOT-PERSIST"
    for producer in (store.record_evaluation, store.record_workflow, store.record_lab):
        with pytest.raises(EvidenceError) as refused:
            producer(candidate=canary, contract=binding.contract_sha256)
        assert canary not in str(refused.value)
    inventory = {path.name: path.read_bytes() for path in store.root.glob("*.json")}
    # These are deliberately unsupported inputs, not redaction-success claims.
    for name in ("dataset_id", "credential", "provider_telemetry", "usage", "cost", "timing"):
        with pytest.raises(TypeError) as caught:
            store.record_evaluation(
                candidate=binding.candidate_id, contract=binding.contract_sha256, **{name: canary}
            )
        assert canary not in str(caught.value)
    with pytest.raises(EvidenceError) as caught:
        store.record_evaluation(
            candidate=binding.candidate_id, contract=binding.contract_sha256, target_version=canary
        )
    assert canary not in str(caught.value)
    assert inventory == {path.name: path.read_bytes() for path in store.root.glob("*.json")}
    outputs = repr(verifier.artifacts(evaluation, lab))
    raw = (store.root / (evaluation + ".json")).read_text()
    assert "module7::canary::" not in outputs + raw
    assert '"content"' not in raw
    assert canary not in outputs + raw
    # Use the accepted file-loader fixture seam without changing its digest pin
    # or promoting synthetic source content into accepted producer authority.
    import json

    from reliability_safety_observability import evaluation_dataset as dataset_module

    source = Path(dataset_module.__file__).parent / "evaluation_data/module7-benchmark-v1.json"
    pristine = json.loads(source.read_bytes())

    class SourceFixture:
        def __init__(self, content):
            self.content = content

        def files(self, package):
            return self

        def __truediv__(self, name):
            return self

        def read_bytes(self):
            return self.content

    for field in ("dataset_id", "provider_telemetry", "usage", "cost", "timing", "credential"):
        altered = {**pristine, field: canary}
        with monkeypatch.context() as context:
            context.setattr(
                dataset_module, "resources", SourceFixture(json.dumps(altered).encode())
            )
            with pytest.raises(dataset_module.ContractValidationError) as rejection:
                store.record_evaluation(
                    candidate=binding.candidate_id, contract=binding.contract_sha256
                )
            assert canary not in str(rejection.value)
        assert inventory == {path.name: path.read_bytes() for path in store.root.glob("*.json")}


def _integrated_network_guard(monkeypatch, on_ipc=None):
    """Install one shared guard with a thread-local internal IPC exception."""
    from contextlib import contextmanager

    @contextmanager
    def guarded():
        import inspect
        import socket
        import threading

        native_connect, native_pair = socket.socket.connect, socket.socketpair
        ipc = threading.local()

        def forbidden(*args, **kwargs):
            raise AssertionError("Unauthorized network activation")

        def connect(self_socket, address, *args, **kwargs):
            if not (
                getattr(ipc, "allowed", False)
                and type(address) is tuple
                and address
                and address[0] == "127.0.0.1"
            ):
                forbidden()
            return native_connect(self_socket, address, *args, **kwargs)

        def socketpair(*args, **kwargs):
            caller = inspect.currentframe().f_back
            if not (
                caller.f_code.co_name == "_make_self_pipe"
                and caller.f_globals.get("__name__")
                in {
                    "asyncio.proactor_events",
                    "asyncio.selector_events",
                }
            ):
                raise AssertionError("Unauthorized socketpair activation")
            ipc.allowed = True
            try:
                if on_ipc is not None:
                    on_ipc()
                return native_pair(*args, **kwargs)
            finally:
                ipc.allowed = False

        with monkeypatch.context() as context:
            context.setattr(socket.socket, "connect", connect)
            context.setattr(socket, "getaddrinfo", forbidden)
            context.setattr(socket, "socketpair", socketpair)
            yield

    return guarded()


def _assert_ipc_exception_is_thread_scoped(monkeypatch):
    """Force a concurrent denial inside the actual asyncio IPC window."""
    import asyncio
    import socket
    import threading

    entered, attempted = threading.Event(), threading.Event()
    outcomes = []

    def attacker():
        if not entered.wait(5):
            outcomes.append("window_not_entered")
            return
        try:
            with socket.socket() as probe:
                probe.connect(("127.0.0.1", 9))
        except AssertionError:
            outcomes.append("denied")
        except OSError:
            outcomes.append("guard_bypassed")
        else:
            outcomes.append("guard_bypassed")
        finally:
            attempted.set()

    def inside_ipc():
        entered.set()
        assert attempted.wait(5), "concurrent attempt did not complete inside IPC"

    with _integrated_network_guard(monkeypatch, inside_ipc):
        worker = threading.Thread(target=attacker, name="story10-concurrent-denial")
        worker.start()
        try:
            loop = asyncio.new_event_loop()
            loop.close()
        finally:
            entered.set()
            worker.join(timeout=5)
        assert not worker.is_alive()
        assert outcomes == ["denied"]
        with socket.socket() as probe, pytest.raises(AssertionError, match="Unauthorized network"):
            probe.connect(("127.0.0.1", 9))
        with pytest.raises(AssertionError, match="Unauthorized socketpair"):
            socket.socketpair()
        with pytest.raises(AssertionError, match="Unauthorized network"):
            socket.getaddrinfo("fixture.invalid", 443)


def test_13_integrated_zero_network(tmp_path, monkeypatch):
    """Guard every integrated producer and deterministically reject IPC piggybacking."""
    _assert_ipc_exception_is_thread_scoped(monkeypatch)
    with _integrated_network_guard(monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "controlled-secret-canary")
        store = EvidenceStore(tmp_path / "records")
        verifier = ReadinessVerifier(ROOT, store)
        binding = verifier.binding()
        evaluation = store.record_evaluation(
            candidate=binding.candidate_id, contract=binding.contract_sha256
        )
        lab = store.record_lab(candidate=binding.candidate_id, contract=binding.contract_sha256)
        verifier.verify_projection(verifier.record_projection(evaluation))
        artifacts = verifier.artifacts(evaluation, lab)
        assert len(artifacts) == 8
        assert artifacts["integrated_acceptance"]["evaluation"] == evaluation
        assert artifacts["failure_path"]["reference"] == lab


def test_14_claim_audit_requires_evidence(evidence, monkeypatch):
    store, verifier, binding, evaluation, lab = evidence
    audit = verifier.artifacts(evaluation, lab)["claim_audit"]
    assert audit["status"] == "open" and audit["source_digests"]
    assert "streamlit_app.py" in audit["source_digests"]
    assert audit["occurrences"]
    assert all(row["status"] == "open" for row in audit["occurrences"])
    assert audit["qualifications"]["windows_destination_symlink"] == "platform_unverified"
    assert (
        audit["qualifications"]["arbitrary_accepted_provider_payload_redaction"]
        == "not_established"
    )
    # Verify the authorized status correction without invoking a provider.
    import tempfile
    from types import SimpleNamespace

    monkeypatch.setattr(tempfile, "tempdir", str(store.root.parent))
    from streamlit.testing.v1 import AppTest, app_test

    monkeypatch.setattr(app_test, "TMP_DIR", SimpleNamespace(name=str(store.root.parent)))

    from reliability_safety_observability.config import RuntimeSettings
    from reliability_safety_observability.console_presenter import ConsoleBoundary

    monkeypatch.syspath_prepend(str(ROOT))
    import streamlit_app

    calls = []
    console = ConsoleBoundary(
        RuntimeSettings(
            mode="live", live_integrations_enabled=True, provider_api_key="controlled-fixture"
        ),
        live_config_resolver=lambda _: ("https://fixture.invalid", 5),
    )

    def mock_verifier(grant):
        calls.append(grant.provider)
        return {"outcome": "confirmed", "evidence_class": "mocked_provider_contract"}

    monkeypatch.setattr(streamlit_app, "boundary", lambda: console)
    monkeypatch.setattr(streamlit_app, "run_live_verifier", mock_verifier)
    rendered = AppTest.from_string(
        "import streamlit_app\nstreamlit_app.main()", default_timeout=30
    ).run(timeout=30)
    assert not rendered.exception and not calls
    assert any("No provider verifier has been run" in item.value for item in rendered.info)
    rendered.checkbox(key="live_confirmation").check().run()
    rendered.button(key="run_live_verifier").click().run()
    assert not rendered.exception and calls == ["Langfuse"]
    assert rendered.session_state["live_result"]["outcome"] == "confirmed"
    assert any("confirmed" in item.value for item in rendered.json)
    assert any("confirmed result" in item.value for item in rendered.info)
    assert not any("No provider verifier has been run" in item.value for item in rendered.info)
    rendered.run(timeout=30)
    assert calls == ["Langfuse"]
    assert any("confirmed result" in item.value for item in rendered.info)
    reference = store.record_candidate_audit(
        candidate=binding.candidate_id, contract=binding.contract_sha256
    )
    findings = store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="candidate_audit",
    )["payload"]["findings"]
    assert len(findings) == 33
    assert sum(row["disposition"] == "QUALIFIED" for row in findings) == 33
    final = findings[-1]
    assert final["finding_id"] == "S10-AUDIT-33" and final["disposition"] == "QUALIFIED"
    assert "C13" in final["assessment"] and "authorized" in final["assessment"]
    review = next(
        row
        for row in final["inspected_sources"]
        if row["path"] == "docs/STORY-10-SEMANTIC-CLAIM-REVIEW.md"
    )
    from reliability_safety_observability.evidence_records import digest

    assert review["digest"] == digest((ROOT / review["path"]).read_bytes())
    bundled = verifier.artifacts(evaluation, lab, audit=reference)
    assert bundled["claim_audit"]["audit_reference"] == reference
    assert bundled["claim_audit"]["authenticated_findings"] == findings
    assert bundled["integrated_acceptance"]["audit_reference"] == reference
    with pytest.raises(EvidenceError):
        verifier.artifacts(evaluation, lab, audit=evaluation)
    with pytest.raises(EvidenceError):
        verifier.artifacts(evaluation, lab, accepted_tests=reference)


def test_15_live_lanes_remain_open(evidence):
    _, verifier, _, evaluation, lab = evidence
    lanes = verifier.artifacts(evaluation, lab)["live_claim_ledger"]["lanes"]
    assert {row["provider"] for row in lanes} == {"Langfuse", "LangSmith", "Helicone"}
    assert all(row["status"] == "open" and row["live_evidence"] is None for row in lanes)


def test_16_eight_derived_artifacts(evidence):
    _, verifier, binding, evaluation, lab = evidence
    artifacts = verifier.artifacts(evaluation, lab)
    assert len(artifacts) == 8
    assert all(row["candidate"] == binding.candidate_id for row in artifacts.values())


def test_17_synthetic_gate_failure_and_rerun(evidence, monkeypatch, capsys):
    import subprocess

    _, verifier, _, _, _ = evidence
    executor = GateExecutor(verifier)

    original_run = subprocess.run
    calls = []
    fail_once = [True]

    def failed(command, **kwargs):
        if command[0] == "git":
            return original_run(command, **kwargs)
        calls.append(tuple(command))
        code = 1 if fail_once.pop() else 0
        return subprocess.CompletedProcess(
            command, code, b"controlled-subprocess-secret-canary", b""
        )

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(EvidenceError):
        executor.execute()
    assert executor._failed_gate == 0 and executor._history
    failure_reference = executor._history[0]
    failure = verifier.store.load_failure(failure_reference)
    assert failure["payload"]["entries"][-1]["exit_code"] == 1
    executor = GateExecutor(verifier)
    assert executor._failed_gate == 0 and executor._history == [failure_reference]
    assert "streamlit_app.py" in executor._commands()[2]
    # A controlled process seam tests the mechanism; it never certifies pytest.
    fail_once[:] = [False] * 4
    reference = executor.execute()
    executor.verify(reference)
    _, _, _, evaluation, lab = evidence
    _assert_gate_reconciliation(verifier, evaluation, lab, reference)
    assert "controlled-subprocess-secret-canary" not in capsys.readouterr().out
    restarted = GateExecutor(verifier)
    assert restarted._failed_gate is None and restarted._history == []
    history_path = verifier.store.root / (failure_reference + ".json")
    authentic_history = history_path.read_bytes()
    try:
        history_path.write_bytes(b"corrupted history")
        with pytest.raises(EvidenceError, match="history"):
            GateExecutor(verifier)
    finally:
        history_path.write_bytes(authentic_history)
    assert calls == [executor._commands()[0], executor._commands()[0], *executor._commands()]
    current = verifier.binding()
    for kind in ("launch", "timeout"):
        isolated_store = EvidenceStore(verifier.store.root / kind)
        isolated = ReadinessVerifier(ROOT, isolated_store)

        def exceptional(command, captured_kind=kind, **kwargs):
            if command[0] == "git":
                return original_run(command, **kwargs)
            if captured_kind == "timeout":
                raise subprocess.TimeoutExpired(command, 1200)
            raise OSError("controlled launch failure")

        with monkeypatch.context() as context:
            context.setattr(subprocess, "run", exceptional)
            with pytest.raises(EvidenceError):
                GateExecutor(isolated).execute()
            recovered = GateExecutor(isolated)
            assert recovered._failed_gate == 0
            attempt = isolated_store.load_failure(recovered._history[-1])
            assert attempt["payload"]["entries"][-1]["failure_kind"] == (
                "subprocess_timeout" if kind == "timeout" else "subprocess_launch_failed"
            )
    for changed in (
        replace(current, candidate_id="0" * 64),
        replace(current, contract_sha256="0" * 64),
    ):
        with monkeypatch.context() as context:
            context.setattr(verifier, "binding", lambda changed=changed: changed)
            with pytest.raises(EvidenceError):
                executor.verify(reference)

    # A verifier already constructed before the new failure must reload history.
    fail_once[:] = [True, False]
    with pytest.raises(EvidenceError, match="immutable failure reference"):
        GateExecutor(verifier).execute()
    for checking in (executor, GateExecutor(verifier)):
        with pytest.raises(EvidenceError, match="superseded"):
            checking.verify(reference)
    with pytest.raises(EvidenceError, match="superseded"):
        verifier.reconcile_traceability(evaluation, gate=reference)
    fail_once[:] = [False] * 4
    replacement = GateExecutor(verifier).execute()
    GateExecutor(verifier).verify(replacement)
    _, _, _, evaluation, lab = evidence
    quality = verifier.artifacts(evaluation, lab, replacement)["quality_gate"]
    assert quality["reference"] == replacement
    assert [entry["gate"] for entry in quality["execution"]["entries"]] == [1, 0, 1, 2]
    with pytest.raises(EvidenceError, match="superseded"):
        executor.verify(reference)
    _assert_candidate_isolated_recovery(verifier, monkeypatch, fail_once)


def _assert_gate_reconciliation(verifier, evaluation, lab, reference):
    """Bind the same authenticated gate through generation and claim verification."""
    without = {r["requirement"]: r for r in verifier.reconcile_traceability(evaluation)}
    rows = verifier.reconcile_traceability(evaluation, lab=lab, gate=reference)
    keyed = {r["requirement"]: r for r in rows}
    for identifier in ("REQ-QG-001", "REQ-DOD-007", "REQ-EVD-006"):
        assert without[identifier]["status"] == "open"
        assert "supplied" in without[identifier]["reason"]
        row = keyed[identifier]
        assert row["status"] == "verified" and row["evidence_reference"] == reference
        assert reference in row["evidence_references"]
        verifier.verify_traceability_claim(evaluation, row, lab=lab, gate=reference)
        with pytest.raises(EvidenceError):
            verifier.verify_traceability_claim(evaluation, row, lab=lab)
        for field, value in (
            ("status", "qualified"),
            ("implementation_references", []),
            ("test_references", ["invented"]),
            ("evidence_references", [evaluation]),
        ):
            with pytest.raises(EvidenceError):
                verifier.verify_traceability_claim(
                    evaluation, {**row, field: value}, lab=lab, gate=reference
                )
    assert keyed["REQ-QG-003"]["status"] == "open"
    assert reference in keyed["REQ-QG-003"]["evidence_references"]
    assert "retry history" in keyed["REQ-QG-003"]["reason"]
    bundle = verifier.artifacts(evaluation, lab, reference)
    assert bundle["traceability"]["rows"] == rows
    with pytest.raises(EvidenceError):
        verifier.reconcile_traceability(evaluation, gate=evaluation)
    with pytest.raises(EvidenceError):
        verifier.reconcile_traceability(evaluation, gate="0" * 64)


def _assert_candidate_isolated_recovery(verifier, monkeypatch, fail_once):
    """Reuse the synthetic process seam to exercise interleaved candidate histories."""
    from reliability_safety_observability.evidence_records import _RECORDING_AUTHORITY

    first = verifier.binding()
    other = replace(first, candidate_id="b" * 64)
    store = EvidenceStore(verifier.store.root / "candidate-isolation")
    separate = ReadinessVerifier(ROOT, store)
    current = first
    monkeypatch.setattr(separate, "binding", lambda: current)

    fail_once[:] = [True, False]
    with pytest.raises(EvidenceError, match="immutable failure"):
        GateExecutor(separate).execute()
    first_failure = GateExecutor(separate)._history[0]
    first_path = store.root / (first_failure + ".json")
    original = first_path.read_bytes()

    current = other
    unrelated = GateExecutor(separate)
    assert unrelated._history == [] and unrelated._failed_gate is None
    fail_once[:] = [False] * 3
    other_success = unrelated.execute()
    unrelated.verify(other_success)
    try:
        first_path.write_bytes(b"tampered historical record")
        with pytest.raises(EvidenceError, match="history"):
            unrelated.verify(other_success)
    finally:
        first_path.write_bytes(original)

    current = first
    retry = GateExecutor(separate)
    assert retry._history == [first_failure] and retry._failed_gate == 1
    with pytest.raises(EvidenceError, match="cannot be verified") as rejected:
        retry.verify(other_success)
    assert "candidate or contract mismatch" in str(rejected.value.__cause__)
    fail_once[:] = [False] * 4
    first_success = retry.execute()
    retry.verify(first_success)
    assert first_path.read_bytes() == original

    fail_once[:] = [True]
    with pytest.raises(EvidenceError, match="immutable failure"):
        retry.execute()
    unresolved = GateExecutor(separate)._history[0]
    with pytest.raises(EvidenceError, match="superseded"):
        retry.verify(first_success)
    current = other
    unrelated.verify(other_success)
    payload = store.load(
        other_success,
        candidate=other.candidate_id,
        contract=other.contract_sha256,
        producer="gate_executor",
    )["payload"]
    payload["resolved_failures"] = [unresolved]
    payload["entries"][-1]["ended_ns"] = (
        store.load_failure(unresolved)["payload"]["entries"][-1]["ended_ns"] + 1
    )
    store._publish(
        "gate_executor",
        other.candidate_id,
        other.contract_sha256,
        payload,
        _authority=_RECORDING_AUTHORITY,
    )
    with pytest.raises(EvidenceError, match="own candidate history"):
        unrelated.verify(other_success)


def test_18_gate_wrong_producer_rejected(evidence, monkeypatch):
    import os
    import subprocess

    _, verifier, _, evaluation, _ = evidence
    with pytest.raises(EvidenceError):
        GateExecutor(verifier).verify(evaluation)

    hostile = (
        "MODULE7_LANGFUSE_LIVE_VERIFICATION",
        "MODULE7_LANGSMITH_LIVE_VERIFICATION",
        "MODULE7_HELICONE_LIVE_VERIFICATION",
        "MODULE7_EXECUTION_MODE",
        "OPENAI_API_KEY",
        "LANGCHAIN_TRACING_V2",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
    )
    for name in hostile:
        monkeypatch.setenv(name, "1")
    original_run = subprocess.run
    pytest_seen = []

    def observed(command, **kwargs):
        if command[0] == "git":
            return original_run(command, **kwargs)
        environment = kwargs["env"]
        assert not set(hostile).intersection(environment)
        assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert Path(environment["TEMP"]).is_relative_to(verifier.store.root)
        if command[2] == "pytest":
            assert command[3:] == ("-m", "not live_vendor")
            assert all(os.environ[name] == "1" for name in hostile)
            collection = original_run(
                (
                    *command,
                    "--collect-only",
                    "-q",
                    "tests/test_langfuse_live.py",
                    "tests/test_langsmith_live.py",
                    "tests/test_helicone_contract.py",
                ),
                **kwargs,
            )
            assert collection.returncode == 0
            assert b"3 deselected" in collection.stdout
            pytest_seen.append(True)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", observed)
    GateExecutor(verifier).execute()
    assert pytest_seen == [True]


def test_19_story9_session_ownership():
    from reliability_safety_observability.console_presenter import ConsoleBoundary

    anchor = object()
    boundary = ConsoleBoundary(session_anchor=anchor)
    assert boundary.owned_by(anchor)
    assert not boundary.owned_by(object())
    assert boundary.issue_live_confirmation("Langfuse") is None


def test_20_aggregation_missing_evidence_rejected(evidence):
    _, verifier, _, evaluation, lab = evidence
    acceptance = verifier.artifacts(evaluation, lab)["integrated_acceptance"]
    assert acceptance["status"] == "open"
    assert acceptance["reliability_risk"]["status"] == "unresolved_intermittent"
    assert acceptance["qualified_historical"] == "656 passed, 3 skipped, 1 failed"
    with pytest.raises(EvidenceError):
        verifier.artifacts(evaluation, "0" * 64)
