"""Reviewer adapter and high-value native UI contracts."""

import asyncio
import json
from pathlib import Path

import pytest

from module10_ai import InferenceRequest, InferenceResult, InferenceService
from module10_ai.execution import JobTimeout, QueueUnavailable
from module10_ai.reviewer import exercise


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
    """UI imports, submits, renders real evidence, reruns and rejects blank input."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).parents[1] / "ui/app.py"),
                           default_timeout=15).run()
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
