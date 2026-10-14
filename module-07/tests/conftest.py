"""Shared hermetic test configuration for Module 7."""

import os

import pytest


@pytest.fixture(autouse=True)
def clear_module7_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient Module 7 configuration before every test.

    Args:
        monkeypatch: Pytest environment-isolation fixture.
    """
    for key in tuple(os.environ):
        if key.startswith("MODULE7_"):
            monkeypatch.delenv(key, raising=False)
