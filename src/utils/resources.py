# src/utils/resources.py
"""
Centralized resource path resolver and application icon loader for Barq Download Manager.
Works consistently across development mode and PyInstaller frozen bundles.
"""

from pathlib import Path
import os
import sys
from PyQt6.QtGui import QIcon


def resource_path(relative_path: str) -> Path:
    """
    Return an absolute resource path that works both during development
    and inside a PyInstaller bundle.

    When running from source:
        Base = project root (two levels up from src/utils/resources.py)
    When frozen by PyInstaller:
        Base = sys._MEIPASS (temporary extraction directory)
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parents[2]

    return base_path / relative_path


def load_app_icon() -> QIcon:
    """
    Load and return the official Barq application icon.
    Prefers assets/icons/barq.ico on Windows and assets/icons/barq_256.png on Linux/macOS.
    Validates file existence and non-null QIcon, gracefully falling back if needed.
    """
    if sys.platform == "win32":
        candidates = [
            "assets/icons/barq.ico",
            "assets/icons/barq_256.png",
            "logo.png",
        ]
    else:
        candidates = [
            "assets/icons/barq_256.png",
            "assets/icons/barq.ico",
            "logo.png",
        ]

    for relative_path in candidates:
        path = resource_path(relative_path)

        if not path.exists():
            continue

        icon = QIcon(str(path))

        if not icon.isNull():
            if os.environ.get("BARQ_DEBUG_ICON") == "1":
                print(f"[DEBUG_ICON] Loaded icon from: {path} (platform: {sys.platform})")
            return icon

    if os.environ.get("BARQ_DEBUG_ICON") == "1":
        print(f"[WARNING] Failed to load any valid icon from candidates: {candidates}")

    return QIcon()


def print_icon_diagnostics() -> None:
    """
    Print diagnostic information about icon resolution and environment.
    Triggered when BARQ_DEBUG_ICON=1 environment variable is set.
    """
    if os.environ.get("BARQ_DEBUG_ICON") != "1":
        return

    print("========================================")
    print("      BARQ ICON DIAGNOSTICS LOG         ")
    print("========================================")
    print(f"Platform: {sys.platform}")
    print(f"Is Frozen (PyInstaller): {getattr(sys, 'frozen', False)}")
    if getattr(sys, "frozen", False):
        print(f"_MEIPASS: {getattr(sys, '_MEIPASS', 'N/A')}")

    ico_path = resource_path("assets/icons/barq.ico")
    png_path = resource_path("assets/icons/barq_256.png")
    logo_path = resource_path("logo.png")

    print(f"barq.ico path: {ico_path} | Exists: {ico_path.exists()}")
    print(f"barq_256.png path: {png_path} | Exists: {png_path.exists()}")
    print(f"logo.png path: {logo_path} | Exists: {logo_path.exists()}")

    icon = load_app_icon()
    print(f"Loaded QIcon isNull: {icon.isNull()}")
    if sys.platform != "win32":
        desktop_file = Path("/usr/share/applications/barq.desktop")
        icon_sys_file = Path("/usr/share/icons/hicolor/256x256/apps/barq.png")
        print(f"System desktop entry exists: {desktop_file.exists()}")
        print(f"System icon file exists: {icon_sys_file.exists()}")
    print("========================================")
