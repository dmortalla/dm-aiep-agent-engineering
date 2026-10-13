"""Tests for the Module 8 package contract."""

from mcp_enterprise_integration import __version__


def test_package_exposes_version() -> None:
    """Verify that the standalone package exposes its version."""
    assert __version__ == "0.1.0"
