"""Operations library and offline checker contracts for Story 10.10."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from module10_ai.operations import (
    CHECKLIST_GATE_ITEMS,
    CHECKLIST_NOTE,
    ROLLBACK_AUTHORITY,
    ROLLBACK_NOTE,
    EvidenceError,
    checklist_report,
    cost_report,
    incident_report,
    load_evidence,
    rollback_plan_report,
    slo_report,
)

SCRIPT = str(Path(__file__).parents[1] / "scripts" / "operations_check.py")
IMAGE = "m10acrttvvwx.azurecr.io/module10-ai@sha256:" + "a" * 64
REVISION = "m10-api-ttvvwx--0000001"
NOW = "2026-11-22T00:00:00+00:00"


def write(directory: Path, payload: object, name: str = "evidence.json") -> str:
    """Write one exact evidence artifact and return its path string."""
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def checklist_payload(**overrides: object) -> dict:
    """Build one schema-exact readiness checklist matching accepted reality."""
    items = [{"name": name, "status": "passed"} for name in CHECKLIST_GATE_ITEMS]
    items += [{"name": name, "status": "open"} for name in
              ("tested_source_provenance", "rollback_execution",
               "live_slo_attainment")]
    payload = {"schema_version": 1, "classification":
               "MODULE 10 OPERATIONAL READINESS / OFFLINE DETERMINISTIC",
               "generated_at": NOW, "items": items}
    payload.update(overrides)
    return payload


def rollback_payload(**overrides: object) -> dict:
    """Build one schema-exact data-only rollback plan."""
    payload = {"schema_version": 1,
               "classification": "MODULE 10 ROLLBACK PLAN / DATA ONLY",
               "target_revision": REVISION, "target_image": IMAGE,
               "trigger": "operational_regression",
               "post_rollback_checks": ["liveness", "readiness",
                                        "deterministic_inference",
                                        "azure_monitor_receipt",
                                        "revision_traffic"],
               "execution_authority": ROLLBACK_AUTHORITY,
               "deployment_authorized": False,
               "provenance_precondition": "unresolved", "prepared_at": NOW}
    payload.update(overrides)
    return payload


def incident_payload(scenario: str, observations: dict) -> dict:
    """Build one schema-exact incident diagnostic evidence document."""
    return {"schema_version": 1,
            "classification":
            "MODULE 10 INCIDENT DIAGNOSTIC / OFFLINE DETERMINISTIC",
            "observed_at": NOW, "scenario": scenario,
            "observations": observations}


def test_checklist_accepts_consistent_readiness(tmp_path: Path) -> None:
    """The accepted point-in-time state yields ready with open items carried."""
    report = checklist_report(checklist_payload())
    assert report["status"] == "ready"
    assert len(report["gates_passed"]) == 8
    assert report["open_items"] == ["tested_source_provenance",
                                    "rollback_execution",
                                    "live_slo_attainment"]
    assert report["authority_note"] == CHECKLIST_NOTE
    assert "error" not in report


def test_checklist_failed_gate_not_ready(tmp_path: Path) -> None:
    """An honestly failed gate yields not_ready, never a masked pass."""
    items = checklist_payload()["items"]
    for item in items:
        if item["name"] == "azure_monitor_receipt":
            item["status"] = "failed"
    report = checklist_report(checklist_payload(items=items))
    assert report["status"] == "not_ready"
    assert report["gates_not_passed"] == ["azure_monitor_receipt"]


def test_checklist_rejects_unsupported_open_claim() -> None:
    """Claiming provenance or rollback execution complete is contradictory."""
    items = checklist_payload()["items"]
    for item in items:
        if item["name"] == "tested_source_provenance":
            item["status"] = "passed"
    report = checklist_report(checklist_payload(items=items))
    assert report["status"] == "contradictory"
    assert "tested_source_provenance" in report["error"]


@pytest.mark.parametrize("mutation", [
    {"classification": "UNREVIEWED REGISTER"},
    {"schema_version": 2},
])
def test_checklist_rejects_incompatible_identity(mutation: dict) -> None:
    """Classification or schema-version drift is incompatible."""
    report = checklist_report(checklist_payload(**mutation))
    assert report["status"] == "incompatible"


def test_checklist_rejects_missing_item_and_unknown_field(tmp_path: Path) -> None:
    """A missing required item is incomplete; an unknown field is malformed."""
    payload = checklist_payload()
    payload["items"] = payload["items"][:-1]
    assert checklist_report(payload)["status"] == "incomplete"
    payload = checklist_payload()
    payload["operator_note"] = "unexpected"
    assert checklist_report(payload)["status"] == "malformed"


def test_checklist_rejects_malformed_timestamp() -> None:
    """A naive or non-ISO timestamp is malformed."""
    report = checklist_report(checklist_payload(generated_at="2026-11-22T00:00:00"))
    assert report["status"] == "malformed"


@pytest.mark.parametrize("scenario,observations,summary_key", [
    ("health-flap", {"readiness_outcomes": ["success", "failure"],
                     "window_minutes": 10}, "readiness_failures"),
    ("queue-saturation", {"queue_rejected": 5, "window_minutes": 15},
     "queue_rejected"),
    ("inference-deadline", {"inference_timeouts": 2, "window_minutes": 15},
     "inference_timeouts"),
    ("telemetry-gap", {"monitor_receipt_rows": 0}, "monitor_receipt_rows"),
    ("revision-drift", {"expected_revision": REVISION,
                        "observed_revision": "m10-api-ttvvwx--0000002"},
     "expected_revision"),
])
def test_incident_classifies_accepted_scenarios(
        scenario: str, observations: dict, summary_key: str) -> None:
    """Accepted scenarios classify with fixed read-only guidance."""
    report = incident_report(incident_payload(scenario, observations))
    assert report["status"] == "classified"
    assert report["scenario"] == scenario
    assert summary_key in report["summary"]
    assert report["boundary_note"].startswith("Diagnostics are read-only")


def test_incident_rejects_unsupported_scenario() -> None:
    """An unknown scenario is unsupported, never invented into a class."""
    report = incident_report(incident_payload("data-exfiltration", {}))
    assert report["status"] == "unsupported"


def test_incident_rejects_contradictory_observations() -> None:
    """Wrong observation fields fail closed per scenario."""
    report = incident_report(incident_payload("health-flap",
                                              {"queue_rejected": 3}))
    assert report["status"] == "malformed"
    report = incident_report(incident_payload(
        "revision-drift", {"expected_revision": "../escape",
                           "observed_revision": REVISION}))
    assert report["status"] == "malformed"


def test_rollback_plan_validates_data_only_contract() -> None:
    """A conforming plan validates with the explicit authority boundary."""
    report = rollback_plan_report(rollback_payload())
    assert report["status"] == "validated"
    assert report["deployment_authorized"] is False
    assert report["authority_note"] == ROLLBACK_NOTE
    assert report["provenance_precondition"] == "unresolved"


def test_rollback_plan_never_carries_authority() -> None:
    """A plan claiming deployment authority is incompatible."""
    report = rollback_plan_report(rollback_payload(deployment_authorized=True))
    assert report["status"] == "incompatible"
    assert "authority" in report["error"]


def test_rollback_plan_rejects_unknown_trigger_and_check_drift() -> None:
    """Promotion-contract vocabulary drift fails closed."""
    report = rollback_plan_report(rollback_payload(trigger="operator-mood"))
    assert report["status"] == "malformed"
    report = rollback_plan_report(rollback_payload(
        post_rollback_checks=["liveness"]))
    assert report["status"] == "incomplete"


def test_rollback_plan_rejects_resolved_provenance_claim() -> None:
    """A plan cannot claim the unresolved provenance precondition resolved."""
    report = rollback_plan_report(
        rollback_payload(provenance_precondition="resolved"))
    assert report["status"] == "contradictory"


def test_rollback_plan_rejects_wrong_authority_string() -> None:
    """Execution authority must equal the accepted promotion contract value."""
    report = rollback_plan_report(
        rollback_payload(execution_authority="agent discretion"))
    assert report["status"] == "incompatible"


def slo_payload(entries: list[dict]) -> dict:
    """Build one schema-exact SLO register."""
    return {"schema_version": 1,
            "classification": "MODULE 10 SLO REGISTER / EVIDENCE-GROUNDED",
            "objectives": entries}


def test_slo_register_accepts_label_discipline() -> None:
    """Measured requires a value and source; proposed carries no value."""
    entries = [{"name": "readiness_availability", "label": "measured",
                "objective": "readiness succeeds during accepted exercises",
                "measurement_source": "local-telemetry", "measurement": 1.0},
               {"name": "inference_latency", "label": "proposed",
                "objective": "sub-second cooperative deadline budget",
                "measurement_source": "local-telemetry"}]
    report = slo_report(slo_payload(entries))
    assert report["status"] == "consistent"
    assert report["objectives"][1].get("measurement") is None


def test_slo_measured_without_measurement_is_contradictory() -> None:
    """A measured claim without a measurement value cannot pass."""
    entries = [{"name": "liveness", "label": "measured",
                "objective": "liveness holds",
                "measurement_source": "verifier-gates"}]
    report = slo_report(slo_payload(entries))
    assert report["status"] == "contradictory"


def test_slo_measured_with_no_source_is_contradictory() -> None:
    """A measured claim against source 'none' is unsupported."""
    entries = [{"name": "liveness", "label": "measured",
                "objective": "liveness holds", "measurement_source": "none",
                "measurement": 1}]
    assert slo_report(slo_payload(entries))["status"] == "contradictory"


def test_slo_proposed_with_measurement_is_contradictory() -> None:
    """Proposed/illustrative objectives must not fabricate measurements."""
    entries = [{"name": "monitor_receipt_presence", "label": "illustrative",
                "objective": "receipt appears within the ingestion window",
                "measurement_source": "azure-monitor-receipt",
                "measurement": 1}]
    assert slo_report(slo_payload(entries))["status"] == "contradictory"


def test_cost_register_separates_verified_from_assumption() -> None:
    """Verified entries need observed configuration; assumptions need judgment."""
    entries = [{"item": "container-app", "kind": "verified",
                "basis": "observed-configuration"},
               {"item": "teardown", "kind": "assumption",
                "basis": "operator-judgment"}]
    report = cost_report({"schema_version": 1, "classification":
                          "MODULE 10 COST REGISTER / CONFIGURATION-BOUNDED",
                          "entries": entries,
                          "budget_threshold": "bounded-by-human-review"})
    assert report["status"] == "consistent"
    assert report["budget_threshold"] == "bounded-by-human-review"
    assert "dollar" in report["amount_note"]


def test_cost_register_rejects_mismatched_basis() -> None:
    """A verified claim resting on judgment is contradictory."""
    entries = [{"item": "registry", "kind": "verified",
                "basis": "operator-judgment"}]
    report = cost_report({"schema_version": 1, "classification":
                          "MODULE 10 COST REGISTER / CONFIGURATION-BOUNDED",
                          "entries": entries})
    assert report["status"] == "contradictory"


def test_cost_register_rejects_monetary_claim() -> None:
    """Dollar amounts are not an accepted field; the entry fails closed."""
    entries = [{"item": "registry", "kind": "verified",
                "basis": "observed-configuration", "amount_usd": 12}]
    report = cost_report({"schema_version": 1, "classification":
                          "MODULE 10 COST REGISTER / CONFIGURATION-BOUNDED",
                          "entries": entries})
    assert report["status"] == "malformed"
    assert "amount_usd" not in json.dumps(report)


def test_reports_are_deterministic() -> None:
    """Identical inputs produce byte-identical reports; no clock is read."""
    first = json.dumps(checklist_report(checklist_payload()), sort_keys=True)
    second = json.dumps(checklist_report(checklist_payload()), sort_keys=True)
    assert first == second
    plan = json.dumps(rollback_plan_report(rollback_payload()), sort_keys=True)
    assert plan == json.dumps(rollback_plan_report(rollback_payload()),
                              sort_keys=True)


def test_load_evidence_rejects_missing_and_oversize(tmp_path: Path) -> None:
    """The bounded reader fails closed with fixed messages only."""
    with pytest.raises(ValueError):
        load_evidence(str(tmp_path / "absent.json"))
    big = tmp_path / "big.json"
    big.write_text("x" * 40000, encoding="utf-8")
    with pytest.raises(ValueError):
        load_evidence(str(big))
    with pytest.raises(ValueError):
        load_evidence("bad\x00path")


@pytest.mark.parametrize("command,payload,status", [
    ("checklist", checklist_payload(), "ready"),
    ("rollback-plan", rollback_payload(), "validated"),
])
def test_cli_success_and_failure_paths(tmp_path: Path, command: str,
                                       payload: dict, status: str) -> None:
    """The real CLI exits 0 on accepted evidence and 1 on rejection."""
    good = write(tmp_path, payload, "good.json")
    done = subprocess.run([sys.executable, SCRIPT, command,
                           "--evidence", good],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
    assert json.loads(done.stdout)["status"] == status
    bad = write(tmp_path, {"schema_version": 1}, "bad.json")
    done = subprocess.run([sys.executable, SCRIPT, command,
                           "--evidence", bad],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1
    report = json.loads(done.stdout)
    assert report["status"] in ("incomplete", "malformed", "incompatible")
    done = subprocess.run([sys.executable, SCRIPT, command, "--evidence",
                           str(tmp_path / "absent.json")],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1
    assert json.loads(done.stdout)["status"] == "missing"


def test_checklist_rejects_open_item_not_reading_open() -> None:
    """A carried-open item claiming anything but open fails closed."""
    for victim in ("tested_source_provenance", "rollback_execution",
                   "live_slo_attainment"):
        items = checklist_payload()["items"]
        for item in items:
            if item["name"] == victim:
                item["status"] = "failed"
        report = checklist_report(checklist_payload(items=items))
        assert report["status"] == "contradictory"
        assert victim in report["error"]


def test_load_evidence_rejects_deeply_nested_json(tmp_path: Path) -> None:
    """Deeply nested JSON fails closed with a fixed message, never a fault."""
    path = tmp_path / "deep.json"
    path.write_text("[" * 16000 + "]" * 16000, encoding="utf-8")
    with pytest.raises(EvidenceError) as caught:
        load_evidence(str(path))
    assert caught.value.status == "malformed"
    assert "too deeply" in str(caught.value)


def test_cli_deeply_nested_json_fails_closed(tmp_path: Path) -> None:
    """The CLI reports malformed evidence as JSON, never as an unhandled fault."""
    path = tmp_path / "deep.json"
    path.write_text("[" * 16000 + "]" * 16000, encoding="utf-8")
    done = subprocess.run([sys.executable, SCRIPT, "checklist", "--evidence",
                           str(path)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 1
    assert done.stderr == ""
    report = json.loads(done.stdout)
    assert report["status"] == "malformed"


def test_cli_malformed_evidence_is_not_reported_as_missing(tmp_path: Path) -> None:
    """Malformed and oversized evidence carry their own status token."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    done = subprocess.run([sys.executable, SCRIPT, "checklist", "--evidence",
                           str(broken)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 1
    assert json.loads(done.stdout)["status"] == "malformed"
    oversize = tmp_path / "big.json"
    oversize.write_text("x" * 40000, encoding="utf-8")
    done = subprocess.run([sys.executable, SCRIPT, "checklist", "--evidence",
                           str(oversize)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 1
    assert json.loads(done.stdout)["status"] == "malformed"
