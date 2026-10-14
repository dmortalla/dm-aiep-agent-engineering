"""Tests for session, execution-mode, and credential contracts."""

import pytest
from pydantic import SecretStr, ValidationError

from multimodal_voice_platform.contracts.modality import TrustLevel
from multimodal_voice_platform.contracts.session import (
    ConversationRole,
    ConversationTurn,
    ExecutionMode,
    LiveCredential,
    SessionConfig,
)

SECRET = "sk-test-not-a-real-key-0000"


def _credential() -> LiveCredential:
    return LiveCredential(provider_id="example-provider", api_key=SecretStr(SECRET))


def test_deterministic_mode_is_the_default() -> None:
    config = SessionConfig(session_id="sess-1")
    assert config.mode is ExecutionMode.DETERMINISTIC
    assert config.live_opt_in is False
    assert config.allowed_live_providers == frozenset()


def test_live_mode_requires_opt_in_credential_and_allowlist() -> None:
    with pytest.raises(ValidationError, match="live_opt_in"):
        SessionConfig(
            session_id="sess-1",
            mode=ExecutionMode.LIVE,
            credential=_credential(),
            allowed_live_providers=frozenset({"example-provider"}),
        )
    with pytest.raises(ValidationError, match="credential"):
        SessionConfig(session_id="sess-1", mode=ExecutionMode.LIVE, live_opt_in=True)
    with pytest.raises(ValidationError, match="allowlist"):
        SessionConfig(
            session_id="sess-1",
            mode=ExecutionMode.LIVE,
            live_opt_in=True,
            credential=_credential(),
        )
    config = SessionConfig(
        session_id="sess-1",
        mode=ExecutionMode.LIVE,
        live_opt_in=True,
        credential=_credential(),
        allowed_live_providers=frozenset({"example-provider"}),
    )
    assert config.mode is ExecutionMode.LIVE


def test_credential_presence_alone_never_selects_live_mode() -> None:
    with pytest.raises(ValidationError, match="deterministic mode"):
        SessionConfig(session_id="sess-1", credential=_credential())
    with pytest.raises(ValidationError, match="deterministic mode"):
        SessionConfig(session_id="sess-1", live_opt_in=True)


def test_credentials_never_appear_in_dumps_or_repr() -> None:
    config = SessionConfig(
        session_id="sess-1",
        mode=ExecutionMode.LIVE,
        live_opt_in=True,
        credential=_credential(),
        allowed_live_providers=frozenset({"example-provider"}),
    )
    assert SECRET not in config.model_dump_json()
    assert SECRET not in repr(config)
    assert SECRET not in str(config.model_dump())
    assert SECRET not in repr(_credential())
    assert "credential" not in config.model_dump()


@pytest.mark.parametrize("key", ["short", "x" * 513])
def test_credential_length_is_bounded(key: str) -> None:
    with pytest.raises(ValidationError, match="length"):
        LiveCredential(provider_id="example-provider", api_key=SecretStr(key))


def test_conversation_turn_trust_is_bound_to_role() -> None:
    ConversationTurn(role=ConversationRole.USER, text="hi", trust=TrustLevel.UNTRUSTED_EXTERNAL)
    ConversationTurn(
        role=ConversationRole.ASSISTANT, text="hello", trust=TrustLevel.UNTRUSTED_MODEL_OUTPUT
    )
    with pytest.raises(ValidationError):
        ConversationTurn(role=ConversationRole.ASSISTANT, text="x", trust=TrustLevel.APPLICATION)
    with pytest.raises(ValidationError):
        ConversationTurn(
            role=ConversationRole.USER, text="x", trust=TrustLevel.UNTRUSTED_MODEL_OUTPUT
        )
