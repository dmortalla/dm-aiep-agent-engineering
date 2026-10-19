"""Tests for Story 1 package and isolation contracts."""

import ast
from pathlib import Path

import reliability_safety_observability as module7

MODULE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = MODULE_ROOT / 'src'
# Story 2 confines the mandatory Guardrails AI dependency to this single adapter.
GUARDRAILS_ADAPTER = SOURCE_ROOT / 'reliability_safety_observability' / 'guardrails_adapter.py'
# Story 5 confines the Langfuse SDK to this single adapter (reviewed narrow exception).
LANGFUSE_ADAPTER = SOURCE_ROOT / 'reliability_safety_observability' / 'langfuse_adapter.py'


def test_public_package_imports_independently() -> None:
    """Expose the Story 1 public package without sibling imports."""
    assert module7.RuntimeSettings
    assert module7.WorkflowState
    assert module7.TelemetryRecord


def test_source_has_no_sibling_module_imports() -> None:
    """Prevent runtime dependency on another standalone module."""
    forbidden_fragments = {
        "module_06_5",
        "module06_5",
        "harness_engineering",
    }

    for path in SOURCE_ROOT.rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ''}
            else:
                continue

            for name in names:
                normalized = name.lower().replace('-', '_')
                assert not any(fragment in normalized for fragment in forbidden_fragments), (
                    f'Forbidden sibling-module import {name!r} in {path}'
                )


def test_story_one_source_has_no_network_client_imports() -> None:
    """Keep the Story 1 foundation independent of network clients."""
    forbidden_roots = {
        "aiohttp",
        "httpx",
        "requests",
        "urllib3",
        "langfuse",
        "langsmith",
        "helicone",
        "guardrails",
        "openai",
        "anthropic",
    }

    for path in SOURCE_ROOT.rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ''}
            else:
                continue

            roots = {name.split('.')[0] for name in names if name}
            permitted = (
                {"guardrails"} if path == GUARDRAILS_ADAPTER
                else {"langfuse", "httpx"} if path == LANGFUSE_ADAPTER
                else set()
            )
            forbidden = forbidden_roots - permitted
            assert roots.isdisjoint(forbidden), (
                f'Forbidden Story 1 network/vendor import {sorted(roots & forbidden)} '
                f'in {path}'
            )
