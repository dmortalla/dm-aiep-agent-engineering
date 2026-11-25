"""Reviewer adapter and high-value native UI contracts."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from module10_ai import InferenceRequest, InferenceResult, InferenceService
from module10_ai.execution import JobTimeout, QueueUnavailable
from module10_ai.reviewer import (
    ACCEPTANCE_CHECKS,
    ACCEPTANCE_TEARDOWN,
    cloud_evidence_report,
    exercise,
)

CHECKS = {name: "passed" for name in ACCEPTANCE_CHECKS}
LIMITS = ["point-in-time acceptance; no SLA or load-test claim",
          "no live AI provider; queue/cache remain process-local",
          "operator must separately establish tested-artifact provenance",
          "C-026/C-027 final acceptance deferred"]
IMAGE = "m10acrtestqa.azurecr.io/module10-ai@sha256:" + "a" * 64
REVISION = "m10-api-testqa--0000001"


def write_evidence(directory: Path, payload: object, name: str = "acceptance.json") -> str:
    """Write one exact evidence artifact file and return its path string."""
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def accepted_payload() -> dict:
    """Build one schema-exact acceptance artifact matching the verifier contract."""
    return {"schema_version": 1,
            "classification": "AZURE CLOUD / DETERMINISTIC INFERENCE",
            "verified_at": datetime.now(UTC).isoformat(), "deployment_authorized": False,
            "region": "southcentralus", "image": IMAGE, "revision": REVISION,
            "checks": dict(CHECKS), "replicas": {"minimum": 0, "maximum": 2},
            "limits": list(LIMITS), "teardown": ACCEPTANCE_TEARDOWN}


def test_real_exercise() -> None:
    """Real queue/cache/runtime emit correlated evidence and cleanly stop."""
    report = asyncio.run(exercise("Beta alpha beta gamma"))
    cold, warm = report["runs"]
    assert cold["result"] == warm["result"]
    assert cold["result"]["word_count"] == 4
    assert cold["result"]["evidence"] == "deterministic"
    assert cold["cache"]["misses"] == 1
    assert warm["cache"]["hits"] == 1
    assert cold["admission"] == "queued"
    assert warm["outcome"] == "succeeded"
    assert report["readiness_during_exercise"] is True
    assert report["accepting_after_cleanup"] is False
    assert report["queue_after_cleanup"]["running"] == 0
    assert report["queue_after_cleanup"]["pending_slots"] == 0
    assert report["metrics"]["telemetry_failures"] == 0
    events = report["events"]
    assert len(events) == 7
    assert len({event["correlation_id"] for event in events}) == 1
    assert "Beta" not in json.dumps(events)


@pytest.mark.parametrize("text,limit", [("", 3), ("   ", 3), ("x" * 4097, 3),
                                       ("valid", 11), ("valid", True)],
                         ids=["empty", "blank", "oversize", "limit", "boolean"])
def test_invalid_input(text: str, limit: int) -> None:
    """Accepted validation rejects malformed input without running jobs."""
    report = asyncio.run(exercise(text, limit))
    assert "error" in report
    assert report["queue_after_cleanup"]["submitted"] == 0
    assert not report["accepting_after_cleanup"]


def test_upper_bound() -> None:
    """The inclusive domain ceiling remains usable."""
    assert "error" not in asyncio.run(exercise("x" * 4096, 10))


class BrokenService(InferenceService):
    """Trusted failure injection with sensitive diagnostics."""

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Fail at the application boundary."""
        raise RuntimeError("SECRET_SENTINEL C:/private/internal.py")


def test_failure_minimized() -> None:
    """Unexpected defects produce safe feedback and accepted telemetry categories."""
    report = asyncio.run(exercise("hello", service=BrokenService()))
    assert report["error"] == "The local application could not complete this exercise."
    assert "SECRET_SENTINEL" not in json.dumps(report)
    assert "internal.py" not in json.dumps(report)
    assert any(e["event"] == "application.failure" for e in report["events"])
    assert report["queue_after_cleanup"]["running"] == 0


@pytest.mark.parametrize("failure,message", [
    (JobTimeout("private"), "The bounded exercise timed out. Try again."),
    (QueueUnavailable("private"), "Local execution capacity is unavailable. Try again."),
    (TimeoutError("private"), "The local application could not complete this exercise."),
])
def test_safe_expected_errors(failure: Exception, message: str,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    """Expected capacity/deadline errors are safe; unrelated timeouts remain defects."""
    async def fail(self: InferenceService, request: InferenceRequest) -> InferenceResult:
        raise failure

    monkeypatch.setattr(InferenceService, "infer", fail)
    report = asyncio.run(exercise("hello"))
    assert report["error"] == message
    assert "private" not in json.dumps(report)
    assert not report["accepting_after_cleanup"]


def test_ui_workflow() -> None:
    """UI imports, submits, renders real evidence, reruns and rejects blank input.

    The AppTest bound is 60 seconds: this test is the accepted baseline case
    that timed out at its previous 15-second bound in three separate full-suite
    runs across three sessions (Step 410.1-era record, Step 414 and Step 419.1
    §K.1), while isolated runs complete in about one second — a load-sensitivity
    of the bound on this machine's Windows venv, not an application defect. The
    exercise's own cooperative deadline is 12 seconds, so 60 still bounds a
    genuine hang at five times that budget while tolerating suite-contention
    scheduling spikes.
    """
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).parents[1] / "ui/app.py"),
                            default_timeout=60).run()
    assert not app.exception
    assert len(app.tabs) == 3
    app.button[0].click().run()
    assert not app.exception
    assert app.success
    assert app.metric[0].value == "4"
    first = app.session_state.report
    app.run()
    assert app.session_state.report == first
    assert not app.exception
    assert any("not connected" in item.value for item in app.warning)
    assert any("not deployed" in item.value for item in app.warning)
    app.text_area[0].set_value("   ")
    app.button[0].click().run()
    assert app.error
    assert not app.exception


def test_cloud_evidence_accepts_sanitized_artifact(tmp_path: Path) -> None:
    """A schema-exact verifier artifact is accepted with minimized fields only."""
    report = cloud_evidence_report(write_evidence(tmp_path, accepted_payload()))
    assert report["status"] == "verified"
    assert report["deployment_authorized"] is False
    assert report["stale"] is False
    assert report["region"] == "southcentralus"
    assert report["image"] == IMAGE
    assert report["revision"] == REVISION
    assert report["checks"] == list(ACCEPTANCE_CHECKS)
    assert report["replicas"] == {"minimum": 0, "maximum": 2}
    assert report["limits"] == LIMITS
    assert report["teardown"] == ACCEPTANCE_TEARDOWN
    assert "error" not in report


def test_cloud_evidence_missing_file(tmp_path: Path) -> None:
    """A path without an artifact reports missing evidence, never acceptance."""
    report = cloud_evidence_report(str(tmp_path / "absent.json"))
    assert report["status"] == "missing"
    assert "error" in report


@pytest.mark.parametrize("path", ["", "   ", "x" * 1001, "bad\x00path"])
def test_cloud_evidence_invalid_path(path: str) -> None:
    """Blank, oversized or control-character paths are rejected as missing."""
    report = cloud_evidence_report(path)
    assert report["status"] == "missing"


def test_cloud_evidence_rejects_malformed(tmp_path: Path) -> None:
    """Content that is not a valid JSON object fails closed as malformed."""
    path = tmp_path / "malformed.json"
    path.write_text("{not json", encoding="utf-8")
    report = cloud_evidence_report(str(path))
    assert report["status"] == "malformed"


def test_cloud_evidence_rejects_incomplete(tmp_path: Path) -> None:
    """A missing required field is reported as incomplete, not accepted."""
    payload = accepted_payload()
    del payload["revision"]
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "incomplete"


def test_cloud_evidence_rejects_failed_gate(tmp_path: Path) -> None:
    """A non-passed verifier gate blocks acceptance and names only gate vocabulary."""
    payload = accepted_payload()
    payload["checks"] = dict(CHECKS, azure_monitor_receipt="missing")
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "failed"
    assert "azure_monitor_receipt" in report["error"]


def test_cloud_evidence_rejects_authority_claim(tmp_path: Path) -> None:
    """An artifact claiming deployment authority is incompatible and rejected."""
    payload = accepted_payload()
    payload["deployment_authorized"] = True
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "incompatible"
    assert "authority" in report["error"]


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("classification", "UNREVIEWED CLOUD"), ("region", "westeurope"),
])
def test_cloud_evidence_rejects_wrong_identity(field: str, value: object,
                                               tmp_path: Path) -> None:
    """Schema/classification/region mismatches are incompatible or malformed."""
    payload = accepted_payload()
    payload[field] = value
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] in ("incompatible", "malformed")


def test_cloud_evidence_rejects_oversized_file(tmp_path: Path) -> None:
    """Files beyond the accepted evidence bound are rejected without parsing."""
    path = tmp_path / "oversize.json"
    path.write_text(json.dumps(accepted_payload()) + " " * 40000, encoding="utf-8")
    report = cloud_evidence_report(str(path))
    assert report["status"] == "malformed"


def test_cloud_evidence_rejects_oversized_field(tmp_path: Path) -> None:
    """Oversized or excessive limitation entries fail the bounds check."""
    payload = accepted_payload()
    payload["limits"] = ["x" * 300]
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "malformed"


def test_cloud_evidence_rejects_unexpected_field(tmp_path: Path) -> None:
    """Fields outside the allowlisted schema reject the whole artifact."""
    payload = accepted_payload()
    payload["principal_id"] = "SECRET_SENTINEL-principal"
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "malformed"
    assert "SECRET_SENTINEL" not in json.dumps(report)


def test_cloud_evidence_stale_flag(tmp_path: Path) -> None:
    """Acceptance older than the staleness bound still displays but flags stale."""
    payload = accepted_payload()
    payload["verified_at"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "verified"
    assert report["stale"] is True


def test_cloud_evidence_rejects_future_timestamp(tmp_path: Path) -> None:
    """A future acceptance timestamp is malformed, never accepted."""
    payload = accepted_payload()
    payload["verified_at"] = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "malformed"


def test_cloud_evidence_never_reflects_content(tmp_path: Path) -> None:
    """Accepted artifacts expose only allowlisted fields; sentinels never surface."""
    payload = accepted_payload()
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert "SECRET_SENTINEL" not in json.dumps(report)
    assert set(report) <= {"status", "evidence", "deployment_authorized", "verified_at",
                           "stale", "region", "image", "revision", "checks", "replicas",
                           "limits", "teardown", "error"}


def test_ui_hosted_mode_disables_server_path_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hosted mode must not read arbitrary server paths supplied through the browser."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("MODULE10_HOSTED", "1")
    app = AppTest.from_file(str(Path(__file__).parents[1] / "ui/app.py"),
                            default_timeout=30).run()
    assert not app.exception
    assert len(app.button) == 1  # Only the deterministic exercise form remains.
    assert len(app.text_input) == 0
    assert any("unavailable in the hosted" in item.value for item in app.info)
    app.button[0].click().run()
    assert not app.exception
    assert app.success


def test_ui_local_mode_keeps_evidence_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local mode preserves the accepted operator-supplied evidence workflow."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("MODULE10_HOSTED", raising=False)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "ui/app.py"),
                            default_timeout=30).run()
    assert not app.exception
    assert len(app.button) == 2 and len(app.text_input) == 1


def test_ui_cloud_evidence_workflow(tmp_path: Path) -> None:
    """The console accepts a valid artifact, then rejects malformed replacement."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).parents[1] / "ui/app.py"),
                            default_timeout=30).run()
    assert not app.exception
    assert len(app.button) == 2
    app.button[1].click().run()
    assert not app.exception
    artifact = write_evidence(tmp_path, accepted_payload())
    app.text_input[0].set_value(artifact)
    app.button[1].click().run()
    assert not app.exception
    assert app.success
    assert any("deployment_authorized=false" in item.value for item in app.caption)
    (tmp_path / "acceptance.json").write_text("{broken", encoding="utf-8")
    app.button[1].click().run()
    assert app.error
    assert not app.exception

def test_cloud_evidence_rejects_deeply_nested_json(tmp_path: Path) -> None:
    """Deeply nested JSON fails closed instead of raising out of the boundary."""
    path = tmp_path / "deep.json"
    path.write_text("[" * 16000 + "]" * 16000, encoding="utf-8")
    report = cloud_evidence_report(str(path))
    assert report["status"] == "malformed"
    assert "error" in report


def test_cloud_evidence_normalizes_timestamp(tmp_path: Path) -> None:
    """The displayed instant is canonical, never the raw artifact timestamp bytes."""
    payload = accepted_payload()
    payload["verified_at"] = "20200101T000000+0000"
    report = cloud_evidence_report(write_evidence(tmp_path, payload))
    assert report["status"] == "verified"
    assert report["verified_at"] == "2020-01-01T00:00:00+00:00"

