"""Vendor SDK constructor compatibility: the adapters pass only options the SDK accepts.

Regression for the OpenAI SDK 2.15.0 defect: the adapter passed ``admin_api_key``, which
that SDK's constructor rejects (``TypeError: ... unexpected keyword argument``). The
2.15.0 signature is represented by a keyword-narrowed subclass of the installed client
(evidence: the no-network probe showed ``organization``, ``project`` and
``webhook_secret`` accepted and ``admin_api_key`` rejected). The installed SDK's real
signature is checked as well, so future drift fails here instead of in deployment.
No request is ever sent: ``responses.create``/``messages.create`` are replaced and the
sockets are denied. Keys are dummy literals.
"""

import copy
import inspect
import socket
from collections.abc import Iterator
from typing import Any

import anthropic
import openai
import pytest

from harness_engineering.errors import ContractValidationError
from harness_engineering.live_session import LiveSession, run_live_check
from tests.test_live_response_compat import anthropic_body, openai_body
from tests.test_story13_dual_mode import patch_sdk

REAL_CLIENTS = {"openai": openai.OpenAI, "anthropic": anthropic.Anthropic}  # Before any patching.
KEY = "dummy-byok-session-key-0001"
ENV_ALTERNATES = {
    "OPENAI_API_KEY": "dummy-env-api-key-0002", "OPENAI_ADMIN_KEY": "dummy-env-admin-key-0003",
    "OPENAI_ORG_ID": "org-dummy", "OPENAI_PROJECT_ID": "proj-dummy",
    "OPENAI_WEBHOOK_SECRET": "dummy-webhook-secret-0004",
    "ANTHROPIC_API_KEY": "dummy-env-anthropic-0005", "ANTHROPIC_AUTH_TOKEN": "dummy-token-0006",
}
FIELDS: dict[str, Any] = {"live_mode": True, "acknowledged_charges": True,
                          "prompt_id": "budgets", "path": "byok", "byok_key": KEY}


@pytest.fixture(autouse=True)
def sealed(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    external: list[object] = []
    original = socket.socket.connect

    def guard(self: socket.socket, address: object, *args: object) -> object:
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
            return original(self, address, *args)
        external.append(address)
        raise OSError("external network denied")

    monkeypatch.setattr(socket.socket, "connect", guard)
    yield external
    assert external == []


def record_clients(monkeypatch: pytest.MonkeyPatch, vendor: str) -> list[Any]:
    """Wrap the installed client class so each constructed instance and its options are kept."""
    module, name = (openai, "OpenAI") if vendor == "openai" else (anthropic, "Anthropic")
    real = REAL_CLIENTS[vendor]
    made: list[Any] = []

    class Recording(real):  # type: ignore[valid-type, misc]
        def __init__(self, **options: Any) -> None:
            super().__init__(**options)
            self._recorded_options = options
            made.append(self)

    monkeypatch.setattr(module, name, Recording)
    return made


def run(vendor: str) -> None:
    model = "gpt-6-luna" if vendor == "openai" else "claude-haiku-5-5"
    run_live_check(**FIELDS, provider=vendor, model=model, session=LiveSession())


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_adapter_options_are_accepted_by_the_installed_sdk_constructor(
    vendor: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = record_clients(monkeypatch, vendor)
    body = openai_body() if vendor == "openai" else anthropic_body()
    calls = patch_sdk(monkeypatch, vendor, lambda _: copy.deepcopy(body))
    run(vendor)
    assert len(made) == 1 and len(calls) == 1  # Constructed and used once, no network.
    options = made[0]._recorded_options
    accepted = set(inspect.signature(REAL_CLIENTS[vendor].__init__).parameters) - {"self"}
    assert set(options) <= accepted, f"unsupported options: {set(options) - accepted}"


def test_openai_adapter_passes_no_admin_api_key_and_keeps_every_safe_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = record_clients(monkeypatch, "openai")
    patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    run("openai")
    options = made[0]._recorded_options
    assert "admin_api_key" not in options
    assert options["api_key"] == KEY  # The explicit application-resolved credential.
    assert options["max_retries"] == 0 and 0 < options["timeout"] <= 20.0 + 1e-6
    assert options["base_url"] == "https://api.openai.com/v1"
    # Ancillary routing settings remain explicitly empty so environment cannot re-route.
    assert (options["organization"], options["project"], options["webhook_secret"]) == ("", "", "")
    assert made[0]._client.trust_env is False  # Application-owned HTTP client ignores env proxies.
    assert made[0]._client.follow_redirects is False


def test_openai_adapter_constructs_with_the_2_15_0_constructor_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails on the published defect: the narrowed signature has no ``admin_api_key``."""

    class Openai215(openai.OpenAI):
        def __init__(
            self, *, api_key: str | None = None, organization: str | None = None,
            project: str | None = None, webhook_secret: str | None = None,
            base_url: Any = None, timeout: Any = None, max_retries: int = 2,
            default_headers: Any = None, default_query: Any = None, http_client: Any = None,
        ) -> None:
            super().__init__(
                api_key=api_key, organization=organization, project=project,
                webhook_secret=webhook_secret, base_url=base_url, timeout=timeout,
                max_retries=max_retries, default_headers=default_headers,
                default_query=default_query, http_client=http_client,
            )

    monkeypatch.setattr(openai, "OpenAI", Openai215)
    calls = patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    view = run_live_check(**FIELDS, provider="openai", model="gpt-6-luna", session=LiveSession())
    assert view.status == "succeeded" and calls[0]["api_key"] == KEY


def test_explicit_byok_key_cannot_be_replaced_by_environment_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in ENV_ALTERNATES.items():
        monkeypatch.setenv(name, value)
    made = record_clients(monkeypatch, "openai")
    calls = patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    run("openai")
    client = made[0]
    assert client.api_key == KEY and calls[0]["api_key"] == KEY
    assert client.api_key != ENV_ALTERNATES["OPENAI_API_KEY"]
    # The SDK may read OPENAI_ADMIN_KEY into an attribute, but it is only used for admin-only
    # endpoints and never replaces the explicit key, even when both schemes are requested.
    assert client.auth_headers == {"Authorization": f"Bearer {KEY}"}
    for security in ({"bearer_auth": True}, {"bearer_auth": True, "admin_api_key_auth": True}):
        assert client._auth_headers(security) == {"Authorization": f"Bearer {KEY}"}
    # Routing identifiers from the environment are suppressed by the explicit empty strings.
    assert (client.organization, client.project, client.webhook_secret) == ("", "", "")


def test_anthropic_behavior_is_unaffected_and_uses_only_the_explicit_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in ENV_ALTERNATES.items():
        monkeypatch.setenv(name, value)
    made = record_clients(monkeypatch, "anthropic")
    calls = patch_sdk(monkeypatch, "anthropic", lambda _: copy.deepcopy(anthropic_body()))
    view = run_live_check(
        **FIELDS, provider="anthropic", model="claude-haiku-5-5", session=LiveSession())
    options = made[0]._recorded_options
    assert view.status == "succeeded" and calls[0]["api_key"] == KEY
    assert options["api_key"] == KEY and options["max_retries"] == 0
    assert options["webhook_key"] == "" and "admin_api_key" not in options
    assert made[0].auth_token is None  # Environment token cannot supplement the explicit key.


def test_a_constructor_incompatibility_is_a_defect_not_a_provider_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported-argument TypeError stays a programming defect (never mislabeled)."""

    class Strict(openai.OpenAI):
        def __init__(self, *, api_key: str | None = None) -> None:
            super().__init__(api_key=api_key)

    monkeypatch.setattr(openai, "OpenAI", Strict)
    patch_sdk(monkeypatch, "openai", lambda _: copy.deepcopy(openai_body()))
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        run_live_check(**FIELDS, provider="openai", model="gpt-6-luna", session=LiveSession())
    assert not issubclass(TypeError, ContractValidationError)
