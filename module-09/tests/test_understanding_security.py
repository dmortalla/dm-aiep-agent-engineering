"""Story 9.3 security and architecture tests for ingestion, local adapters, and the service."""

import ast
import asyncio
import os
import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest
from media_builders import build_pdf, encode, quadrant_image

from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.session import SessionConfig
from multimodal_voice_platform.understanding import UnderstandingService, UnderstandingStatus

SRC = Path(__file__).resolve().parents[1] / "src" / "multimodal_voice_platform"
STORY_9_3_DIRS = (SRC / "ingestion", SRC / "adapters" / "local", SRC / "understanding")
NETWORK_AND_PROCESS_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "subprocess",
    "multiprocessing",
    "os",
    "shutil",
    "ftplib",
    "smtplib",
    "websockets",
    "requests",
    "httpx",
    "aiohttp",
}
LATER_STORY_IMPORTS = {"streamlit", "websockets", "fastapi", "starlette", "anthropic", "openai"}


def _trees() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text("utf-8")))
        for directory in STORY_9_3_DIRS
        for path in sorted(directory.rglob("*.py"))
    ]


def _imports(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _blocked(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("Story 9.3 processing attempted network access")


def test_uploads_process_with_network_blocked_and_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in list(os.environ):
        if any(marker in name.upper() for marker in ("API_KEY", "TOKEN", "SECRET")):
            monkeypatch.delenv(name)
    markdown = (
        b"# Links\n\n[remote](https://example.invalid/x) ![img](http://example.invalid/i.png)\n"
    )
    loop = asyncio.new_event_loop()
    try:
        monkeypatch.setattr(socket.socket, "connect", _blocked)
        monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
        monkeypatch.setattr(socket, "create_connection", _blocked)
        monkeypatch.setattr(socket, "getaddrinfo", _blocked)
        service = UnderstandingService()
        session = SessionConfig(session_id="sess-offline")
        uploads = [
            (Modality.IMAGE, "image/png", "a.png", encode(quadrant_image(), "PNG")),
            (Modality.IMAGE, "image/jpeg", "a.jpg", encode(quadrant_image(), "JPEG")),
            (Modality.IMAGE, "image/webp", "a.webp", encode(quadrant_image(), "WEBP")),
            (Modality.DOCUMENT, "application/pdf", "a.pdf", build_pdf([["offline"]])),
            (Modality.DOCUMENT, "text/markdown", "a.md", markdown),
            (Modality.DOCUMENT, "text/plain", "a.txt", b"plain"),
        ]
        for modality, media_type, name, data in uploads:
            record = loop.run_until_complete(
                service.understand_upload(
                    session,
                    modality=modality,
                    media_type=media_type,
                    display_name=name,
                    data=data,
                    evidence_class=EvidenceClass.AUTOMATED_TEST,
                )
            )
            assert record.status is UnderstandingStatus.SUCCEEDED, record.error
    finally:
        loop.close()


def test_story_9_3_code_imports_no_network_process_env_or_later_story_modules() -> None:
    for path, tree in _trees():
        imported = _imports(tree)
        assert not imported & NETWORK_AND_PROCESS_MODULES, path
        assert not imported & LATER_STORY_IMPORTS, path
        if "asyncio" in imported:
            assert path.name == "providers.py", f"{path}: asyncio is only for bounded execution"


def test_story_9_3_code_never_swallows_exceptions_broadly() -> None:
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                assert node.type is not None, f"{path}: bare except"
                names = {n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)}
                assert not names & {"Exception", "BaseException"}, path
                assert any(isinstance(stmt, ast.Raise | ast.Return) for stmt in node.body), path


def test_story_9_3_code_has_no_filesystem_access_and_parses_only_memory_buffers() -> None:
    forbidden = {"open", "Path", "read_text", "read_bytes", "write_bytes", "write_text", "unlink"}
    for path, tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            target = ast.unparse(func)
            if target in {"Image.open", "PdfReader"}:
                assert node.args and ast.unparse(node.args[0]).startswith("io.BytesIO("), path
                continue
            assert name not in forbidden, f"{path}: {target}"


def test_decoders_are_imported_only_by_their_parsing_modules() -> None:
    for path, tree in _trees():
        imported = _imports(tree)
        if "PIL" in imported:
            assert path.name == "image_analysis.py", path
        if "pypdf" in imported:
            assert path.name == "document_parsing.py", path


def test_presentation_and_later_story_methods_are_absent() -> None:
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                assert node.name not in {"synthesize", "stream_reason", "transcribe"}, path


def test_no_command_or_dynamic_code_execution_path() -> None:
    forbidden_calls = {"eval", "exec", "compile", "system", "popen", "spawn", "__import__"}
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name == "compile" and isinstance(func, ast.Attribute):
                    assert ast.unparse(func) == "re.compile", path
                    continue
                assert name not in forbidden_calls, f"{path}: {name}"
