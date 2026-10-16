"""Security, isolation, and story-boundary tests for the deterministic foundation (Story 9.2)."""

import ast
import asyncio
import os
import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest
from pydantic import SecretStr

from multimodal_voice_platform.adapters.deterministic import (
    DeterministicFoundation,
    DeterministicInputError,
)
from multimodal_voice_platform.contracts.modality import TrustLevel
from multimodal_voice_platform.contracts.session import (
    ExecutionMode,
    LiveCredential,
    SessionConfig,
)

FIXTURES = ("text-brief", "image-quadrants", "audio-tone", "document-brief")
SRC = Path(__file__).resolve().parents[1] / "src" / "multimodal_voice_platform"
DETERMINISTIC_SRC = SRC / "adapters" / "deterministic"
NETWORK_AND_PROCESS_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "asyncio",
    "subprocess",
    "multiprocessing",
    "os",
    "shutil",
    "ftplib",
    "smtplib",
    "websockets",
}


def _deterministic_trees() -> list[tuple[Path, ast.Module]]:
    return [(p, ast.parse(p.read_text("utf-8"))) for p in sorted(DETERMINISTIC_SRC.rglob("*.py"))]


def _blocked(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("deterministic execution attempted network access")


def test_all_fixtures_run_with_network_blocked_and_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in list(os.environ):
        if any(marker in name.upper() for marker in ("API_KEY", "TOKEN", "SECRET")):
            monkeypatch.delenv(name)
    loop = asyncio.new_event_loop()
    try:
        monkeypatch.setattr(socket.socket, "connect", _blocked)
        monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
        monkeypatch.setattr(socket, "create_connection", _blocked)
        monkeypatch.setattr(socket, "getaddrinfo", _blocked)
        foundation = DeterministicFoundation()
        session = SessionConfig(session_id="sess-offline")
        assert session.credential is None
        for fixture_id in FIXTURES:
            record = loop.run_until_complete(foundation.run(session, fixture_id))
            assert record.live_provider_called is False
    finally:
        loop.close()


def test_deterministic_package_imports_no_network_process_or_env_modules() -> None:
    for path, tree in _deterministic_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in NETWORK_AND_PROCESS_MODULES, f"{path}: {name}"


def test_deterministic_package_never_swallows_exceptions_broadly() -> None:
    for path, tree in _deterministic_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                assert node.type is not None, f"{path}: bare except"
                caught = ast.unparse(node.type)
                names = {n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)}
                assert not names & {"Exception", "BaseException"}, f"{path}: broad {caught}"
                assert any(isinstance(stmt, ast.Raise) for stmt in node.body), (
                    f"{path}: handler for {caught} does not re-raise"
                )


def test_deterministic_package_has_no_filesystem_path_access() -> None:
    forbidden_calls = {"open", "Path", "read_text", "write_bytes", "write_text", "unlink"}
    for path, tree in _deterministic_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                assert name not in forbidden_calls, f"{path}: {name}"


def test_live_sessions_cannot_run_deterministic_fixtures() -> None:
    live = SessionConfig(
        session_id="sess-live",
        mode=ExecutionMode.LIVE,
        live_opt_in=True,
        credential=LiveCredential(provider_id="example", api_key=SecretStr("placeholder-0000")),
        allowed_live_providers=frozenset({"example"}),
    )
    foundation = DeterministicFoundation()
    with pytest.raises(DeterministicInputError, match="deterministic session"):
        foundation.stage(live, "text-brief")
    assert foundation.store.reference_count("sess-live") == 0


def test_embedded_instructions_in_content_grant_no_authority() -> None:
    session = SessionConfig(session_id="sess-trust")
    before = session.model_dump()
    foundation = DeterministicFoundation()
    record = asyncio.run(foundation.run(session, "document-brief"))
    assert record.document is not None
    injected = [s for s in record.document.sections if "Ignore all previous" in s.text]
    assert injected, "fixture must carry its embedded instruction as data"
    assert record.document.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    assert record.input.trust is TrustLevel.UNTRUSTED_EXTERNAL
    assert session.model_dump() == before
    assert session.mode is ExecutionMode.DETERMINISTIC
    assert record.provider is not None
    assert record.provider.mode is ExecutionMode.DETERMINISTIC
    assert record.evidence.execution_mode is ExecutionMode.DETERMINISTIC


def test_deterministic_adapters_expose_no_authority_or_execution_operations() -> None:
    foundation = DeterministicFoundation()
    allowed = {"descriptor", "analyze", "understand", "transcribe"}
    for adapter in (foundation.vision, foundation.document, foundation.speech_to_text):
        public = {name for name in dir(adapter) if not name.startswith("_")}
        assert public <= allowed, public


def test_later_story_capabilities_are_not_implemented() -> None:
    packages = {p.name for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert packages == {
        "adapters",
        "audio",
        "contracts",
        "crossmodal",
        "ingestion",
        "speech",
        "understanding",
        "voice",
        "streaming",
        "interface",
    }
    adapters = {p.name for p in (SRC / "adapters").iterdir() if p.is_dir()} - {"__pycache__"}
    assert adapters == {"deterministic", "local", "reasoning", "speech"}
    reasoning_adapters = {
        SRC / "adapters" / "reasoning" / "rule_reasoner.py",
        SRC / "adapters" / "reasoning" / "conversation.py",
    }
    later_imports = {"streamlit", "websockets", "fastapi", "starlette", "aiohttp", "httpx"}
    later_imports |= {"uvicorn"}
    transport_owners = {
        "starlette": SRC / "interface" / "websocket.py",
        "uvicorn": SRC / "interface" / "server.py",
    }
    """Story 9.7: the WebSocket framework and server, each in exactly one interface module."""
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == "stream_reason"
                and "contracts" not in path.parts
            ):
                assert path in reasoning_adapters, f"{path}: only reasoning adapters reason"
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == "stream_reply"
                and "contracts" not in path.parts
            ):
                assert path in reasoning_adapters, f"{path}: only reasoning adapters reason"
            if isinstance(node, ast.Import | ast.ImportFrom):
                module = getattr(node, "module", None) or ""
                names = {module, *(alias.name for alias in node.names)}
                for root in {n.split(".")[0] for n in names} & later_imports:
                    assert transport_owners.get(root) == path, f"{path}: {root}"
