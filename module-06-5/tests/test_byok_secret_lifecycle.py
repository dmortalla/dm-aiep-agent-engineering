"""BYOK secret lifecycle: prove what the application guarantees, and disclose what it cannot.

Application-controlled: no durable persistence, no disk write, no logging, no evidence or
telemetry persistence, no prompt inclusion, no credential echo, no application authority.
Framework-managed: Streamlit may keep the typed widget value in server memory until its
rerun/session lifecycle clears it. This module therefore deliberately does NOT claim that
the key is erased from server memory or absent from every session-state structure, and
it records the framework retention so a stronger claim is not reintroduced.
"""

import copy
import logging
import socket
import tempfile
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest

from harness_engineering.live_credentials import TransientCredentialSource
from harness_engineering.live_readiness import REPOSITORY_EVIDENCE, provider_readiness
from harness_engineering.live_session import SERVER_PATH_ENABLE_VARIABLE, LiveSession
from harness_engineering.providers import ProviderRuntime
from harness_engineering.vendor_providers import OpenAIProvider
from tests.live_seam import authorization, live_config
from tests.test_live_response_compat import openai_body
from tests.test_story13_dual_mode import patch_sdk

KEY = "dummy-byok-session-key-0001"
MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parent
APP = MODULE / "streamlit_app.py"
APP_OWNED_KEYS = ("demo_results", "live_session", "live_view", "demo_choice", "provider_mode",
                  "live_provider", "live_model", "live_prompt", "live_path")
TEXT_KINDS = ("markdown", "code", "caption", "warning", "error", "info", "success", "exception",
              "metric", "text", "title", "header", "subheader", "json")


@pytest.fixture(autouse=True)
def sealed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", SERVER_PATH_ENABLE_VARIABLE):
        monkeypatch.delenv(name, raising=False)
    original = socket.socket.connect

    def guard(self: socket.socket, address: object, *args: object) -> object:
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
            return original(self, address, *args)  # Windows asyncio self-pipe only.
        raise OSError("external network denied")

    monkeypatch.setattr(socket.socket, "connect", guard)
    yield


def locate(obj: object, path: str = "root", seen: set[int] | None = None,
           depth: int = 0) -> list[str]:
    """Return bounded paths at which ``KEY`` occurs inside nested containers/objects."""
    seen = set() if seen is None else seen
    if id(obj) in seen or depth > 8:
        return []
    seen.add(id(obj))
    found: list[str] = []
    if isinstance(obj, str):
        return [path] if KEY in obj else []
    if isinstance(obj, dict):
        for name, value in list(obj.items()):
            label = f"{path}[{str(name)[:40]!r}]"
            if isinstance(name, str) and KEY in name:
                found.append(label + "<key>")
            found += locate(value, label, seen, depth + 1)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for index, value in enumerate(list(obj)):
            found += locate(value, f"{path}[{index}]", seen, depth + 1)
    elif hasattr(obj, "model_dump_json"):
        if KEY in obj.model_dump_json():
            found.append(f"{path}.<model>")
    elif not isinstance(obj, type):
        names = list(getattr(obj, "__dict__", {})) + [
            slot for cls in type(obj).__mro__ for slot in getattr(cls, "__slots__", ())
        ]
        for name in names:
            if hasattr(obj, name):
                found += locate(getattr(obj, name), f"{path}.{name}", seen, depth + 1)
    return found


def submit_flow(at: Any) -> Any:
    at.selectbox(key="provider_mode").select("Live provider (explicit opt-in)").run()
    at.text_input[0].input(KEY)
    at.checkbox[0].check()
    next(b for b in at.button if b.label == "Run one bounded live call").click().run()
    return at


def app_test() -> Any:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=30).run()


def test_no_application_owned_session_entry_holds_a_copy_of_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    at = submit_flow(app_test())
    assert not at.exception and "live_view" in at.session_state
    for phase in ("after submit", "after one rerun"):
        for name in APP_OWNED_KEYS:
            if name in at.session_state:
                assert locate(at.session_state[name], name) == [], f"{phase}: {name}"
        at.run()
    assert isinstance(at.session_state["live_session"], LiveSession)


def test_streamlit_framework_may_retain_the_widget_value_and_that_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canary: records the framework behavior so a stronger 'erased' claim is not reintroduced."""
    patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    at = submit_flow(app_test())
    internal = getattr(at.session_state, "_state", None)
    after_submit = locate(internal, "SessionState") if internal is not None else []
    at.run()
    after_rerun = locate(getattr(at.session_state, "_state", None), "SessionState")
    if not after_submit and not after_rerun:
        pytest.skip("This Streamlit version no longer retains the value; revisit the wording.")
    for location in after_submit + after_rerun:  # Only framework widget state, never app state.
        assert "widget_state" in location or "_old_state" in location, location
        assert not any(name in location for name in ("live_view", "live_session", "demo_results"))
    ui = " ".join(APP.read_text(encoding="utf-8").replace('"', " ").split())
    assert "Streamlit may temporarily retain widget state in server memory" in ui


def test_no_file_written_during_a_byok_session_contains_the_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    monkeypatch.chdir(tmp_path)
    patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    submit_flow(app_test())
    contents = [p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()]
    assert all(KEY.encode() not in blob for blob in contents)


def test_no_log_record_contains_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []
    original = logging.Logger.handle

    def spy(self: logging.Logger, record: logging.LogRecord) -> None:
        messages.append(f"{record.getMessage()} {record.exc_text or ''}")
        original(self, record)

    monkeypatch.setattr(logging.Logger, "handle", spy)
    logging.getLogger().setLevel(logging.DEBUG)

    def rejected(kwargs: dict[str, Any]) -> Any:
        request = httpx.Request("POST", "https://fixture.invalid")
        raise openai.AuthenticationError(
            f"invalid key {KEY}", response=httpx.Response(401, request=request),
            body={"error": KEY},
        )

    patch_sdk(monkeypatch, "openai", rejected)
    at = submit_flow(app_test())
    assert at.session_state["live_view"].failure_category == "request_rejected"
    assert all(KEY not in message for message in messages)


def test_no_ui_element_redisplays_the_key_and_no_exception_carries_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejected(kwargs: dict[str, Any]) -> Any:
        request = httpx.Request("POST", "https://fixture.invalid")
        raise openai.AuthenticationError(
            f"invalid key {KEY}", response=httpx.Response(401, request=request),
            body={"error": KEY},
        )

    patch_sdk(monkeypatch, "openai", rejected)
    at = submit_flow(app_test())
    shown = "\n".join(str(getattr(item, "value", "")) for kind in TEXT_KINDS
                      for item in getattr(at, kind))
    assert KEY not in shown and not at.exception
    view = at.session_state["live_view"]
    assert KEY not in view.model_dump_json()
    source = TransientCredentialSource("openai", KEY)
    assert KEY not in f"{source!r}{source!s}{source.resolve('openai')!r}"
    with pytest.raises(Exception) as caught:  # Wrong provider: fixed error, key not echoed.
        source.resolve("anthropic")
    assert KEY not in "".join(traceback.format_exception(caught.value))


def test_the_key_reaches_the_provider_only_at_the_credential_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    from tests.live_seam import live_budget

    budget = live_budget()
    source = TransientCredentialSource("openai", KEY)
    runtime = ProviderRuntime(
        provider=OpenAIProvider("gpt-6-luna"), budget=budget,
        live_config=live_config("openai", budget=budget, credential_source="byok"),
        live_authorization=authorization("openai"), credentials=source,
    )
    assert locate(vars(runtime), "runtime") == []  # Held only inside the opaque source.
    runtime.generate({"prompt": "hello"})
    assert len(calls) == 1 and calls[0]["api_key"] == KEY
    assert KEY not in repr(vars(runtime)) + repr(runtime.audit) + "".join(
        r.model_dump_json() for r in runtime.usage_receipts)
    assert KEY not in repr(provider_readiness()) + repr(REPOSITORY_EVIDENCE)


def test_documents_and_ui_disclose_framework_memory_and_make_no_erasure_claim() -> None:
    ui = " ".join(APP.read_text(encoding="utf-8").replace('"', " ").split())
    assert "Streamlit may temporarily retain widget state in server memory" in ui
    assert "not written to disk, logs, evidence, prompts, or durable application storage" in ui
    overclaims = ("never stored", "cleared after each submit", "erased from server memory",
                  "not stored in `st.session_state`", "absent from all session state",
                  "immediately erased")
    surfaces = [APP, MODULE / "docs" / "RELEASE_READINESS.md", MODULE / "docs" / "TRACEABILITY.md",
                REPO / "README.md", *sorted((MODULE / "src" / "harness_engineering").glob("*.py"))]
    for path in surfaces:
        text = path.read_text(encoding="utf-8-sig").lower()
        for phrase in overclaims:
            assert phrase not in text, f"{path.name} overclaims secret erasure: {phrase}"
    story = " ".join((MODULE / "docs" / "STORY_13.md").read_text(encoding="utf-8-sig").split())
    for required in ("Secret lifecycle (precise)", "Streamlit keeps the value of a widget",
                     "overstated and are superseded",
                     "may exist until Streamlit's rerun or session lifecycle"):
        assert required in story, f"STORY_13 lacks: {required}"
    readiness = " ".join(
        (MODULE / "docs" / "RELEASE_READINESS.md").read_text(encoding="utf-8-sig").split()
    )
    assert "Streamlit may hold the widget value in server memory" in readiness


def test_server_credentials_must_not_be_enabled_on_a_public_deployment_without_a_quota() -> None:
    story = " ".join((MODULE / "docs" / "STORY_13.md").read_text(encoding="utf-8-sig").split())
    readiness = " ".join(
        (MODULE / "docs" / "RELEASE_READINESS.md").read_text(encoding="utf-8-sig").split()
    )
    assert "must not be enabled on a public deployment unless a separate operator-spend " \
        "control or global quota exists" in story
    assert "stays disabled on a public deployment unless a separate operator-spend control " \
        "or global quota exists" in readiness
    source = (MODULE / "src" / "harness_engineering" / "live_session.py").read_text(
        encoding="utf-8")
    assert "Do NOT enable it on a public" in source
