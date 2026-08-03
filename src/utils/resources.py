# src/utils/resources.py
"""
Unified resource path resolver that works both during development
and inside a PyInstaller bundle.
"""

from pathlib import Path
import sys


def resource_path(relative_path: str) -> Path:
    """
    Return an absolute resource path that works both during development
    and inside a PyInstaller bundle.

    When running from source:
        Base = project root (two levels up from this file)
    When frozen by PyInstaller:
        Base = sys._MEIPASS (temporary extraction directory)
    """
    if getattr(sys, "frozen", False):
        # PyInstaller extracts bundled data to a temp dir stored in _MEIPASS
        base_path = Path(sys._MEIPASS)
    else:
        # Development: this file is at src/utils/resources.py → go up 2 levels
        base_path = Path(__file__).resolve().parents[2]

    return base_path / relative_path
