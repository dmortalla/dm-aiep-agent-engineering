"""Story 9.7 architecture, offline, and authority tests for streaming and the WebSocket gateway."""

import ast
import asyncio
import os
import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest
from stream_builders import AsgiWebSocket, app, coordinator, fixture_turn

SRC = Path(__file__).resolve().parents[1] / "src" / "multimodal_voice_platform"
STREAMING = sorted((SRC / "streaming").glob("*.py"))
INTERFACE = sorted((SRC / "interface").glob("*.py"))
FORBIDDEN_MODULES = {
    "subprocess",
    "multiprocessing",
    "os",
    "shutil",
    "pathlib",
    "tempfile",
    "ftplib",
    "smtplib",
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "http",
    "ssl",
    "pickle",
    "importlib",
}
LATER_STORY_IMPORTS = {"streamlit", "fastapi", "anthropic", "openai", "google", "langchain"}
FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__"}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _blocked(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("deterministic streaming attempted network access")


def test_business_logic_stays_outside_the_transport_layer() -> None:
    for path in STREAMING:
        roots = {name.split(".")[0] for name in _imports(path)}
        assert not roots & {"starlette", "uvicorn", "websockets"}, path
        assert not any("multimodal_voice_platform.interface" in n for n in _imports(path)), path
    for path in INTERFACE:
        modules = _imports(path)
        assert not any(".adapters" in name for name in modules), f"{path}: no adapters"
        assert not any(".speech" in name for name in modules), f"{path}: no speech pipeline"
        assert not any(".crossmodal" in name for name in modules), f"{path}: no reasoning"
        assert not any(name.endswith("voice.state") for name in modules), f"{path}: no state"
        text = path.read_text("utf-8")
        assert ".store.commit" not in text and "begin_turn" not in text, path


def test_streaming_code_has_no_command_filesystem_or_later_story_path() -> None:
    for path in [*STREAMING, *INTERFACE]:
        roots = {name.split(".")[0] for name in _imports(path)}
        assert not roots & FORBIDDEN_MODULES, path
        assert not roots & LATER_STORY_IMPORTS, path
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in FORBIDDEN_CALLS, f"{path}: {node.func.id}"
    assert (SRC / "ui" / "app.py").is_file()
    assert not (SRC / "adapters" / "live").exists()
    for path in [*STREAMING, *INTERFACE]:
        assert not any("multimodal_voice_platform.ui" in name for name in _imports(path)), path


def test_streaming_code_swallows_no_exception_silently() -> None:
    broad = 0
    for path in [*STREAMING, *INTERFACE]:
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.ExceptHandler):
                assert node.type is not None, f"{path}: bare except"
                names = {n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)}
                if names & {"Exception", "BaseException"}:
                    broad += 1
                    assert path.name == "websocket.py", path
                    source = ast.unparse(node)
                    assert "_LOG.error" in source and "INTERNAL_ERROR" in source, path
                assert "BaseException" not in names, path
    assert broad == 1, "exactly one logged boundary handler"


def test_deterministic_websocket_session_runs_offline_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in list(os.environ):
        if any(marker in name.upper() for marker in ("API_KEY", "TOKEN", "SECRET")):
            monkeypatch.delenv(name)
    loop = asyncio.new_event_loop()  # The Windows loop's self-pipe is created before blocking.
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    streaming = coordinator()

    async def body() -> list[dict[str, Any]]:
        client = await AsgiWebSocket(app(streaming)).connect()
        await client.event()
        await client.event()
        await client.send(fixture_turn("turn-1", "voice-remember"))
        events = await client.until("turn_complete")
        await client.disconnect()
        return events

    try:
        events = loop.run_until_complete(body())
    finally:
        loop.close()
    done = events[-1]
    assert done["committed"] and done["execution_mode"] == "deterministic"
    assert done["evidence_class"] == "automated_test"
