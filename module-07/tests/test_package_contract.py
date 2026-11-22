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
# Story 6 confines the LangSmith SDK and the adapter-owned requests transport
# to this single adapter (reviewed narrow exception; same basis as Story 5).
LANGSMITH_ADAPTER = SOURCE_ROOT / 'reliability_safety_observability' / 'langsmith_adapter.py'
# Story 7 confines the adapter-owned requests transport to the Helicone
# adapter (reviewed narrow exception; the accepted Story 7 contract's
# pre-adjudicated amendment strengthens confinement for every other file).
HELICONE_ADAPTER = SOURCE_ROOT / 'reliability_safety_observability' / 'helicone_adapter.py'
# Chunk 1B reconciliation: the separately authorized BYOK live slice owns an
# independent OpenAI transport and therefore imports httpx directly.  That
# transport boundary is independent of the Langfuse adapter's; no other module
# gains an httpx allowance and every forbidden root stays forbidden elsewhere.
BYOK_EVALUATION = SOURCE_ROOT / 'reliability_safety_observability' / 'byok_evaluation.py'

# The network and vendor roots no source file may import unless its own
# transport ownership boundary authorizes it.
FORBIDDEN_NETWORK_ROOTS = {
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


def permitted_network_roots(path: Path) -> set[str]:
    """Return the network/vendor import roots one source file may use.

    Args:
        path: Absolute path of the inspected source file.

    Returns:
        The permitted import roots for that file; an empty set for every
        file without an authorized transport ownership boundary.
    """
    return (
        {"guardrails"} if path == GUARDRAILS_ADAPTER
        else {"langfuse", "httpx"} if path == LANGFUSE_ADAPTER
        else {"langsmith", "requests"} if path == LANGSMITH_ADAPTER
        else {"requests"} if path == HELICONE_ADAPTER
        else {"httpx"} if path == BYOK_EVALUATION
        else set()
    )


def forbidden_network_roots(path: Path) -> set[str]:
    """Return the network/vendor roots one source file may not import.

    Args:
        path: Absolute path of the inspected source file.

    Returns:
        The forbidden import roots for that file.
    """
    return FORBIDDEN_NETWORK_ROOTS - permitted_network_roots(path)


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
            permitted = permitted_network_roots(path)
            forbidden = forbidden_roots - permitted
            assert roots.isdisjoint(forbidden), (
                f'Forbidden Story 1 network/vendor import {sorted(roots & forbidden)} '
                f'in {path}'
            )


def test_story_one_network_confinement_keeps_its_protection() -> None:
    """The Chunk 1B allowance stays narrow: only the BYOK transport gains httpx."""
    foundation = SOURCE_ROOT / 'reliability_safety_observability' / 'telemetry.py'
    assert permitted_network_roots(foundation) == set()
    # Every forbidden root stays forbidden for a foundation module.
    assert {'httpx', 'requests', 'openai', 'langfuse', 'langsmith'} <= (
        forbidden_network_roots(foundation))
    # The two authorized httpx owners keep exactly their own roots.
    assert permitted_network_roots(BYOK_EVALUATION) == {'httpx'}
    assert permitted_network_roots(LANGFUSE_ADAPTER) == {'langfuse', 'httpx'}
    # The BYOK transport is not allowed to pull in another vendor SDK.
    assert {'openai', 'requests', 'aiohttp', 'anthropic'} <= (
        forbidden_network_roots(BYOK_EVALUATION))
