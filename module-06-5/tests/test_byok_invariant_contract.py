"""Program invariant: deterministic/no-key reviewer mode AND secure explicit opt-in BYOK/live mode.

Every production-grade TAIE module that supports provider-backed AI must provide
deterministic/no-key reviewer operation AND secure explicit opt-in BYOK/live operation.
Server-side credentials may supplement BYOK but may not replace it.

These checks make removal of the BYOK path, or reintroduction of a server-side-only
rule in an authoritative current-state surface, fail acceptance. Historical records
(`STORY_12_SLICE_3.md`) and `STORY_13.md` (which quotes the superseded wording to
explain it) are deliberately excluded from the obsolete-wording scan.
"""

import re
from pathlib import Path
from typing import get_args

import pytest

from harness_engineering.config import CredentialSourceKind, LiveProviderPolicy
from harness_engineering.live_credentials import (
    CREDENTIAL_SOURCE_TYPES,
    EnvironmentCredentialSource,
    TransientCredentialSource,
)

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parent
INVARIANT = (
    "Every production-grade TAIE module that supports provider-backed AI must provide "
    "deterministic/no-key reviewer operation AND secure explicit opt-in BYOK/live operation. "
    "Server-side credentials may supplement BYOK but may not replace it."
)
OBSOLETE_PHRASES = (
    "never accepted as public browser input", "never browser input",
    "never public browser input", "never public browser byok", "never as public browser input",
    "cannot be enabled or supplied from this page", "no byok control", "server-side only",
    "server-side-only",
)
CURRENT_SURFACES = (
    MODULE / "docs" / "REQUIREMENTS.md", MODULE / "docs" / "TRACEABILITY.md",
    MODULE / "docs" / "IMPLEMENTATION_PLAN.md", MODULE / "docs" / "RELEASE_READINESS.md",
    MODULE / "docs" / "adr" / "002-production-grade-dual-mode-completion.md",
    MODULE / "streamlit_app.py", REPO / "README.md", REPO / "docs" / "PROJECT_STATUS.md",
    *sorted((MODULE / "src" / "harness_engineering").glob("*.py")),
)


def normalized(path: Path) -> str:
    """Return the file text with whitespace collapsed, for phrase checks across wraps."""
    return " ".join(path.read_text(encoding="utf-8-sig").split())


def invariant_violations(text: str) -> list[str]:
    """Return why a current-state document contradicts the program invariant."""
    lowered = text.lower()
    return [f"obsolete wording: {phrase}" for phrase in OBSOLETE_PHRASES if phrase in lowered]


def test_the_program_invariant_is_encoded_in_every_governance_surface() -> None:
    for path in (REPO / "docs" / "ENGINEERING_SOP.md", REPO / "AGENTS.md", REPO / "CLAUDE.md"):
        assert INVARIANT in normalized(path), f"{path.name} lacks the program invariant"


def test_eng_008_and_adr_002_require_byok_and_forbid_server_side_only() -> None:
    requirement = normalized(MODULE / "docs" / "REQUIREMENTS.md")
    eng_008 = requirement.split("ENG-008:")[1].split("## Freeze rule")[0]
    for clause in ("explicit opt-in capability", "temporary user-supplied (BYOK) credential",
                   "never persisted, logged, or exposed",
                   "may supplement but shall not replace the BYOK path",
                   "credentials grant connectivity only and never authority",
                   "documented provider and model allowlist"):
        assert clause in eng_008, f"ENG-008 lacks: {clause}"
    adr = normalized(MODULE / "docs" / "adr" / "002-production-grade-dual-mode-completion.md")
    assert "session-scoped, never-persisted BYOK key" in adr
    assert "may supplement but never replace BYOK" in adr


def test_no_current_surface_states_a_server_side_only_credential_rule() -> None:
    for path in CURRENT_SURFACES:
        found = invariant_violations(path.read_text(encoding="utf-8-sig"))
        assert not found, f"{path.name}: {found}"
    story = normalized(MODULE / "docs" / "STORY_13.md")
    assert "were errors against this requirement and are superseded" in story


def test_the_checker_itself_rejects_server_side_only_and_missing_byok_wording() -> None:
    assert invariant_violations("Credentials are never browser input.")
    assert invariant_violations("Live mode is a server-side only capability.")
    assert invariant_violations("Keys arrive via secret store and never accepted as public "
                                "browser input.")
    assert invariant_violations("An approved credential source: BYOK or server-side.") == []
    assert INVARIANT not in "Server-side credentials replace BYOK."


def test_the_byok_credential_path_is_a_first_class_supported_kind() -> None:
    assert "byok" in get_args(CredentialSourceKind)
    assert {"environment", "secret_store"} <= set(get_args(CredentialSourceKind))
    kinds = {source.kind for source in CREDENTIAL_SOURCE_TYPES}
    assert kinds == {"environment", "secret_store", "byok"}
    assert TransientCredentialSource in CREDENTIAL_SOURCE_TYPES
    assert EnvironmentCredentialSource in CREDENTIAL_SOURCE_TYPES  # Supplements, not replaces.
    policy = LiveProviderPolicy(
        allowed_providers=("openai",), allowed_models={"openai": ("gpt-6-luna",)},
        credential_source="byok",
    )
    assert policy.credential_source == "byok"


def test_the_ui_provides_deterministic_default_and_explicit_opt_in_byok() -> None:
    app = (MODULE / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'DETERMINISTIC_MODE = "Deterministic (default, no key)"' in app
    assert "LIVE_MODE = " in app and "explicit opt-in" in app
    assert app.index("if live_mode:") < app.index('type="password"')
    assert "clear_on_submit=True" in app and "run_live_check(" in app
    assert re.search(r"BYOK credential for this session", app)
    assert "never grant application authority" in app.replace("\n", " ")


def test_removing_the_byok_ui_path_would_fail_this_contract() -> None:
    app = (MODULE / "streamlit_app.py").read_text(encoding="utf-8")
    stripped = app.replace('type="password"', 'type="default"')
    with pytest.raises(AssertionError):
        assert stripped.count("st.text_input(") == 1 and 'type="password"' in stripped
