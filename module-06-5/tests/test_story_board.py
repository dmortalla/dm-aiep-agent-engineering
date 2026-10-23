"""Story 12 Slice 1 composed story board integration evidence tests."""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness_engineering.story_board import (
    _CHECK_IDS,
    _NONCLAIMS,
    StoryBoardEvidence,
    StoryBoardFailure,
    main,
    story_board,
)


def test_story_board_closes_all_composed_segments(tmp_path: Path) -> None:
    """One fresh directory run produces the complete measured evidence set."""
    evidence = story_board(tmp_path / "run")
    assert isinstance(evidence, StoryBoardEvidence)
    assert evidence.sdk_version == "2.3.0"
    assert evidence.classification == ("deterministic_fixture", "local_integration")
    assert tuple(item.check for item in evidence.checks) == _CHECK_IDS
    assert all(item.observed for item in evidence.checks)
    assert evidence.facts.provider_attempts == 3
    assert evidence.facts.provider_samples == 3
    assert evidence.facts.tool_invocations == 2
    assert evidence.facts.authorization_decisions == 4
    assert evidence.facts.slo_samples_sufficient is False
    assert evidence.facts.compression_reduced is True
    assert evidence.facts.short_term_routes == 1
    assert evidence.facts.long_term_routes == 1
    assert evidence.facts.mcp_protocol_calls == 1
    assert evidence.facts.mcp_denied_calls == 2
    assert evidence.facts.mcp_sessions == 1
    assert evidence.facts.anomaly_signals == 5
    assert evidence.facts.approval_histories == 2
    assert evidence.facts.approval_consumed_exactly_once is True
    assert evidence.facts.effect_invocations == 1
    assert evidence.facts.effect_replays == 0
    assert evidence.facts.context_estimated_tokens > 0
    assert evidence.nonclaims == _NONCLAIMS
    assert str(evidence.identity.workflow_id).endswith("-0000-000000a65001")
    assert "HumanIdentity" not in evidence.model_dump_json()


def test_story_board_is_reproducible_across_fresh_directories(tmp_path: Path) -> None:
    """Two independent runs measure identical facts with no carried state."""
    first = story_board(tmp_path / "first")
    second = story_board(tmp_path / "second")
    assert first.model_dump(exclude={"identity"}) == second.model_dump(exclude={"identity"})
    assert first.identity == second.identity
    for directory in ("first", "second"):
        names = {item.name for item in (tmp_path / directory).iterdir()}
        assert names == {"cost.sqlite", "approval", "approval-redline", "recovery"}


def test_story_board_rejects_reused_directory(tmp_path: Path) -> None:
    """The artifact boundary requires a fresh directory for every run."""
    run_directory = tmp_path / "run"
    story_board(run_directory)
    with pytest.raises(FileExistsError):
        story_board(run_directory)


def test_story_board_evidence_fails_closed_on_tampering(tmp_path: Path) -> None:
    """Missing measurements or altered nonclaims can never produce valid evidence."""
    evidence = story_board(tmp_path / "run")
    truncated = evidence.model_dump() | {"checks": evidence.checks[:-1]}
    with pytest.raises(ValidationError):
        StoryBoardEvidence.model_validate(truncated)
    with pytest.raises(ValidationError):
        StoryBoardEvidence.model_validate(
            evidence.model_dump() | {"nonclaims": _NONCLAIMS[:-1]}
        )


def test_cli_reports_sanitized_failures_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed run prints one sanitized JSON line and exits nonzero."""
    monkeypatch.setattr(sys, "argv", ["story_board", "--directory", str(tmp_path / "x")])
    monkeypatch.setattr(
        sys.modules["harness_engineering.story_board"],
        "story_board",
        lambda _directory: (_ for _ in ()).throw(StoryBoardFailure("expected abort")),
    )
    with pytest.raises(SystemExit) as exit_status:
        main()
    assert exit_status.value.code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"failure": "expected abort", "cause": "None"}
