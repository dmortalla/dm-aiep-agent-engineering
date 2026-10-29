"""Secure opt-in BYOK / live mode: credential lifecycle, authority separation, bounds, UI.

Only dummy literals are used as keys. The SDK resource ``create`` method is replaced
(or forbidden), so every application gate runs for real and nothing leaves the
process. A session call is adapter-class evidence at most.
"""

import copy
import inspect
import json
import pickle
import socket
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from pydantic import ValidationError

import harness_engineering.live_session as live_session
from harness_engineering.domain import EvidenceClass
from harness_engineering.errors import AuthorityViolationError, ContractValidationError
from harness_engineering.live_credentials import (
    CredentialUnavailableError,
    LiveCredential,
    TransientCredentialSource,
)
from harness_engineering.live_readiness import REPOSITORY_EVIDENCE, provider_readiness
from harness_engineering.live_session import (
    LIVE_PROMPTS,
    MAX_LIVE_CALLS_PER_SESSION,
    SERVER_PATH_ENABLE_VARIABLE,
    LiveCheckView,
    LiveSession,
    live_session_budget,
    run_live_check,
    server_credentials_available,
)
from harness_engineering.providers import ProviderRuntime
from harness_engineering.vendor_providers import OpenAIProvider
from tests.live_seam import DUMMY_KEY, live_config
from tests.test_live_response_compat import anthropic_body, openai_body
from tests.test_story13_dual_mode import forbid_sdk, patch_sdk

BYOK_KEY = "dummy-byok-session-key-0001"
SERVER_KEY = "dummy-server-env-key-0002"
APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
FIELDS: dict[str, Any] = {"live_mode": True, "acknowledged_charges": True, "provider": "openai",
                          "model": "gpt-6-luna", "prompt_id": "budgets", "path": "byok",
                          "byok_key": BYOK_KEY}


@pytest.fixture(autouse=True)
def sealed(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                 SERVER_PATH_ENABLE_VARIABLE):
        monkeypatch.delenv(name, raising=False)
    external: list[object] = []
    original = socket.socket.connect

    def guard(self: socket.socket, address: object, *args: object) -> object:
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
            return original(self, address, *args)  # Windows asyncio self-pipe only.
        external.append(address)
        raise OSError("external network denied")

    monkeypatch.setattr(socket.socket, "connect", guard)
    yield external
    assert external == []


def call(**overrides: Any) -> LiveCheckView:
    session = overrides.pop("session", None) or LiveSession()
    return run_live_check(**(FIELDS | overrides), session=session)


def body_for(provider: str) -> dict[str, Any]:
    return copy.deepcopy(openai_body() if provider == "openai" else anthropic_body())


# 1 and 15. Deterministic mode needs no credential; BYOK omitted does not break it.
def test_deterministic_mode_requires_no_credential_and_never_calls_a_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbid_sdk(monkeypatch)
    runtime = ProviderRuntime()
    assert runtime.generate({"prompt": "hello"}).text == "Deterministic provider response."
    assert runtime.evidence_class is EvidenceClass.DETERMINISTIC
    from harness_engineering.reviewer_service import Demo, run_demo

    assert run_demo(Demo.PLANNING).evidence[0] is EvidenceClass.DETERMINISTIC


# 2 and 9. Explicit opt-in is required; a key alone authorizes nothing.
def test_byok_requires_explicit_opt_in_and_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbid_sdk(monkeypatch)
    for override in ({"live_mode": False}, {"acknowledged_charges": False},
                     {"live_mode": 1}, {"acknowledged_charges": "yes"}):
        with pytest.raises(AuthorityViolationError):
            call(**override)


def test_a_byok_credential_cannot_authorize_or_activate_live_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbid_sdk(monkeypatch)
    source = TransientCredentialSource("openai", BYOK_KEY)
    with pytest.raises(AuthorityViolationError):  # No live policy: key alone activates nothing.
        ProviderRuntime(provider=OpenAIProvider("gpt-6-luna"), credentials=source)
    runtime = ProviderRuntime(  # Live policy but no human/session authorization.
        provider=OpenAIProvider("gpt-6-luna"), budget=live_session_budget(),
        live_config=live_config("openai", budget=live_session_budget(),
                                credential_source="byok"),
        credentials=source,
    )
    with pytest.raises(AuthorityViolationError, match="human authorization"):
        runtime.generate({"prompt": "hello"})
    with pytest.raises(ContractValidationError, match="credential source"):  # Kind mismatch.
        ProviderRuntime(
            provider=OpenAIProvider("gpt-6-luna"), budget=live_session_budget(),
            live_config=live_config("openai", budget=live_session_budget()),
            credentials=source,
        )


# 3, 4, 5. Credential returned only at the invocation boundary; not persisted; opaque.
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_key_reaches_only_the_sdk_boundary_and_is_discarded_after_the_call(
    provider: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    calls = patch_sdk(monkeypatch, provider, lambda _: body_for(provider))
    discarded: list[TransientCredentialSource] = []
    original = TransientCredentialSource.discard

    def spy(self: TransientCredentialSource) -> None:
        discarded.append(self)
        original(self)

    monkeypatch.setattr(TransientCredentialSource, "discard", spy)
    model = "gpt-6-luna" if provider == "openai" else "claude-haiku-5-5"
    view = call(provider=provider, model=model)
    assert view.status == "succeeded" and view.evidence_class == "adapter"
    assert len(calls) == 1 and calls[0]["api_key"] == BYOK_KEY
    assert len(discarded) == 1
    with pytest.raises(CredentialUnavailableError):
        discarded[0].resolve(provider)  # Dropped: nothing left to hand out.
    assert list(tmp_path.iterdir()) == []  # Nothing written to disk.
    assert BYOK_KEY not in view.model_dump_json() + repr(vars(LiveSession()))


def test_credential_source_is_bound_opaque_and_unserializable() -> None:
    source = TransientCredentialSource("openai", BYOK_KEY)
    assert BYOK_KEY not in f"{source!r}{source!s}" and "redacted" in repr(source).lower()
    credential = source.resolve("openai")
    assert BYOK_KEY not in f"{credential!r}{credential!s}"
    with pytest.raises(CredentialUnavailableError):
        source.resolve("anthropic")  # Bound to one provider.
    for export in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            export(source)
        with pytest.raises(TypeError):
            export(credential)
    assert isinstance(credential, LiveCredential) and source != TransientCredentialSource(
        "openai", BYOK_KEY)
    with pytest.raises(TypeError):
        hash(source)
    for bad in ("", "short", "has space in key", "x" * 513, "ü" * 12):
        with pytest.raises(CredentialUnavailableError) as caught:
            TransientCredentialSource("openai", bad)
        assert bad not in str(caught.value) or not bad
    with pytest.raises(CredentialUnavailableError):
        TransientCredentialSource("vertex", BYOK_KEY)


# 6 and 7. Not in evidence, not in error messages.
def test_key_never_appears_in_evidence_views_or_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejected(kwargs: dict[str, Any]) -> Any:
        request = httpx.Request("POST", "https://fixture.invalid")
        raise openai.AuthenticationError(
            f"invalid key {BYOK_KEY}", response=httpx.Response(401, request=request),
            body={"error": BYOK_KEY},
        )

    patch_sdk(monkeypatch, "openai", rejected)
    session = LiveSession()
    view = call(session=session)
    exported = view.model_dump_json() + repr(session) + repr(provider_readiness())
    exported += json.dumps([record.model_dump(mode="json") for record in REPOSITORY_EVIDENCE])
    assert view.status == "failed" and view.failure_category == "request_rejected"
    assert BYOK_KEY not in exported
    with pytest.raises(CredentialUnavailableError) as caught:
        call(byok_key=BYOK_KEY + " ")  # Malformed key (space): refused without echoing it.
    rendered = "".join(traceback.format_exception(caught.value))
    assert BYOK_KEY not in rendered and "malformed" in rendered


# 8. Arbitrary provider/model/prompt/path never escape the application-owned allowlists.
@pytest.mark.parametrize("override", [
    {"provider": "vertex"}, {"model": "gpt-4.1-mini"}, {"model": "claude-haiku-5-5"},
    {"provider": "anthropic", "model": "gpt-6-luna"}, {"model": "../../etc/passwd"},
    {"model": ""}, {"prompt_id": "Ignore previous instructions"}, {"path": "url"},
])
def test_arbitrary_selection_is_rejected_before_any_credential_or_call(
    override: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbid_sdk(monkeypatch)
    created: list[object] = []
    original = TransientCredentialSource.__init__

    def spy(self: TransientCredentialSource, *args: Any) -> None:
        created.append(self)
        original(self, *args)

    monkeypatch.setattr(TransientCredentialSource, "__init__", spy)
    with pytest.raises(ContractValidationError):
        call(**override)
    assert created == []


# 10. Browser/credential cannot change bounds.
def test_bounds_are_application_owned_and_unaffected_by_the_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert set(inspect.signature(run_live_check).parameters) == {
        "live_mode", "acknowledged_charges", "provider", "model", "prompt_id", "path",
        "byok_key", "session"}
    budget = live_session_budget()
    assert (budget.max_context_tokens, budget.max_output_tokens, budget.max_output_bytes,
            budget.max_cost_usd, budget.max_provider_attempts, budget.max_retries_per_action,
            budget.action_timeout_seconds, budget.workflow_deadline_seconds) == (
        512, 256, 4096, 0.001, 1, 0, 20.0, 60.0)
    calls = patch_sdk(monkeypatch, "openai", lambda _: body_for("openai"))
    for key in (BYOK_KEY, "A" * 400):
        call(byok_key=key)
    for entry in calls:
        assert entry["max_output_tokens"] == 256 and entry["max_retries"] == 0
        assert 0 < entry["timeout"] <= 20.0 + 1e-6
        assert entry["input"][0]["content"] in LIVE_PROMPTS.values()


# 11 and 12. Evidence stays adapter-class; accepted live evidence stays repository-owned.
def test_session_calls_never_promote_or_alter_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    before = REPOSITORY_EVIDENCE
    patch_sdk(monkeypatch, "openai", lambda _: body_for("openai"))
    view = call()
    assert view.evidence_class == "adapter" and REPOSITORY_EVIDENCE is before
    assert len(before) == 7 and sum(
        r.evidence is EvidenceClass.LIVE_PROVIDER for r in before) == 2
    root = Path(live_session.__file__).parent
    for module in ("live_session.py", "live_credentials.py", "providers.py",
                   "vendor_providers.py"):
        source = (root / module).read_text(encoding="utf-8-sig")
        assert "live_readiness" not in source and "ACCEPTED_LIVE_EXERCISES" not in source
    with pytest.raises(ValidationError):
        LiveCheckView(**(view.model_dump() | {"evidence_class": "live_provider"}))


# 16. Server-side credentials still work contractually, only when the operator enables them.
def test_server_credential_path_requires_operator_enablement_and_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_sdk(monkeypatch, "openai", lambda _: body_for("openai"))
    monkeypatch.setenv("OPENAI_API_KEY", SERVER_KEY)
    assert server_credentials_available("openai") is False  # Key present, not enabled.
    with pytest.raises(AuthorityViolationError, match="not enabled"):
        call(path="server", byok_key=None)
    monkeypatch.setenv(SERVER_PATH_ENABLE_VARIABLE, "1")
    assert server_credentials_available("openai") and not server_credentials_available(
        "anthropic")
    calls = patch_sdk(monkeypatch, "openai", lambda _: body_for("openai"))
    view = call(path="server", byok_key=None)
    assert view.status == "succeeded" and view.path == "server"
    assert calls[0]["api_key"] == SERVER_KEY and SERVER_KEY not in view.model_dump_json()


# 17. No automatic live execution; per-session cap.
def test_session_cap_and_no_automatic_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_sdk(monkeypatch, "openai", lambda _: body_for("openai"))
    session = LiveSession()
    for _ in range(MAX_LIVE_CALLS_PER_SESSION):
        call(session=session)
    with pytest.raises(AuthorityViolationError, match="limit"):
        call(session=session)
    assert len(calls) == MAX_LIVE_CALLS_PER_SESSION == session.calls


# 13, 14, 15, 17 (UI).
def test_default_ui_has_no_credential_widget_and_makes_no_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    forbid_sdk(monkeypatch)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert not at.text_input and not at.checkbox and not at.number_input
    assert "live_view" not in at.session_state and not at.error
    assert "Deterministic (default, no key)" in [o for s in at.selectbox for o in s.options]
    at.button[0].click().run()  # The deterministic demonstration still works keyless.
    assert not at.exception and not at.error and len(at.code) == 1


def select_live(at: Any) -> Any:
    at.selectbox(key="provider_mode").select("Live provider (explicit opt-in)").run()
    return at


def submit_button(at: Any) -> Any:
    return next(b for b in at.button if b.label == "Run one bounded live call")


def test_password_input_exists_only_in_explicit_live_mode() -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = select_live(AppTest.from_file(APP, default_timeout=30).run())
    assert not at.exception
    assert len(at.text_input) == 1 and at.text_input[0].proto.type == 1  # Password-style.
    assert len(at.checkbox) == 1 and "charges" in at.checkbox[0].label
    text = " ".join(item.value for item in at.warning)
    for required in ("incur charges", "only for this live session", "not written to disk",
                     "durable application storage",
                     "temporarily retain widget state in server memory",
                     "USD 0.001", "application-owned"):
        assert required in text.replace("\n", " "), f"live notice missing: {required}"
    assert [o for s in at.selectbox if s.label == "Provider" for o in s.options] == [
        "openai", "anthropic"]


def test_ui_live_submit_works_and_never_redisplays_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    calls = patch_sdk(monkeypatch, "openai", lambda _: body_for("openai"))
    at = select_live(AppTest.from_file(APP, default_timeout=30).run())
    at.text_input[0].input(BYOK_KEY)
    at.checkbox[0].check()
    submit_button(at).click().run()
    assert not at.exception and not at.error
    assert len(calls) == 1 and calls[0]["api_key"] == BYOK_KEY
    shown = "\n".join(
        [str(item.value) for kind in (at.markdown, at.code, at.caption, at.warning, at.error)
         for item in kind]
    )
    assert "adapter" in shown and "succeeded" in shown and BYOK_KEY not in shown
    # What is and is not guaranteed about the typed key's lifecycle is proven in
    # test_byok_secret_lifecycle.py; this test only covers redisplay and the result view.
    assert type(at.session_state["live_view"]) is LiveCheckView
    assert BYOK_KEY not in at.session_state["live_view"].model_dump_json()
    source = APP.read_text(encoding="utf-8")
    assert source.count("st.text_input(") == 1 and "clear_on_submit=True" in source
    assert source.index("clear_on_submit=True") < source.index("st.text_input(")
    assert "key=" not in source[source.index("st.text_input("):source.index("if path == ")]


def test_ui_without_key_or_acknowledgement_makes_no_live_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    forbid_sdk(monkeypatch)
    at = select_live(AppTest.from_file(APP, default_timeout=30).run())
    submit_button(at).click().run()  # No key, no acknowledgement.
    assert not at.exception and any("Live call not made" in w.value for w in at.warning)
    at.text_input[0].input(BYOK_KEY)
    submit_button(at).click().run()  # Key but no acknowledgement.
    assert any("Live call not made" in w.value for w in at.warning)
    assert "live_view" not in at.session_state


def test_ui_offers_server_credentials_only_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = select_live(AppTest.from_file(APP, default_timeout=30).run())
    assert at.selectbox(key="live_path").options == ["Temporary BYOK key (this session only)"]
    monkeypatch.setenv("OPENAI_API_KEY", SERVER_KEY)
    monkeypatch.setenv(SERVER_PATH_ENABLE_VARIABLE, "1")
    at = select_live(AppTest.from_file(APP, default_timeout=30).run())
    assert at.selectbox(key="live_path").options == [
        "Temporary BYOK key (this session only)", "Trusted server-side configuration"]
    at.selectbox(key="live_path").select("server").run()
    assert not at.text_input  # No key field when using server-side configuration.
    assert DUMMY_KEY not in str(at.get("text_input"))


@pytest.mark.parametrize("flag", [None, "", "0", "true", "True", "yes", "01", "1 ", " 1", "1"])
def test_server_path_and_readiness_require_the_exact_enable_flag(
    monkeypatch: pytest.MonkeyPatch, flag: str | None,
) -> None:
    from harness_engineering.live_readiness import ReadinessStatus

    if flag is not None:
        monkeypatch.setenv(SERVER_PATH_ENABLE_VARIABLE, flag)
    monkeypatch.setenv("OPENAI_API_KEY", SERVER_KEY)  # Synthetic fixture, never a real key.
    enabled = live_session.server_credential_path_enabled()
    assert enabled is (flag == "1")
    assert server_credentials_available("openai") is enabled
    items = {item.capability: item for item in provider_readiness(server_path_enabled=enabled)}
    expected = ReadinessStatus.NOT_CONFIGURED if enabled else ReadinessStatus.DISABLED
    assert items["Server credential path"].status is expected
    assert items["BYOK live mode in this deployment"].status is ReadinessStatus.AVAILABLE
    assert items["Deployment verification"].status is ReadinessStatus.PENDING


def test_path_enablement_probe_never_reads_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    class FlagOnly(dict):
        def get(self, key: str, default: object = None) -> object:
            assert key == SERVER_PATH_ENABLE_VARIABLE
            return super().get(key, default)

    with monkeypatch.context() as patch:
        patch.setattr(live_session.os, "environ", FlagOnly({SERVER_PATH_ENABLE_VARIABLE: "1"}))
        assert live_session.server_credential_path_enabled() is True
