"""Streamlit Community Cloud entrypoint for the Module 8 reviewer console."""

from __future__ import annotations

import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = MODULE_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mcp_enterprise_integration.console import main  # noqa: E402

if __name__ == "__main__":
    main()
