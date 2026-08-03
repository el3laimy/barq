import sys
import os
import socket
import json

# ──── Single Instance Check & Focus Existing Instance ────
def send_to_existing_instance(url=""):
    """Try connecting to IPC server on port 19375. If running, notify it and return True."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.8)
        sock.connect(("127.0.0.1", 19375))
        payload = json.dumps({"url": url or ""}) + "\n"
        sock.sendall(payload.encode("utf-8"))
        sock.close()
        return True
    except Exception:
        return False


# ──── Level 3: Windows Taskbar Identity (AppUserModelID) ────
def set_windows_app_id() -> None:
    """Set explicit AppUserModelID BEFORE QApplication on Windows.
    This controls taskbar icon grouping and ensures Windows uses our icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "El3laimy.Barq.DownloadManager.1"
        )
    except Exception:
        pass


# ──── Fix WM_CLASS for X11 taskbar icon matching ────
# On X11, Qt uses sys.argv[0] as the WM_CLASS instance name.
# We must set it to "barq" BEFORE QApplication() is constructed,
# so the WM_CLASS matches StartupWMClass=barq in barq.desktop.
sys.argv[0] = "barq"

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Enable High DPI scaling (must be set before QApplication)
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from ui.main_window import BarqMainWindow
from utils.resources import resource_path


def main() -> int:
    # Parse initial URL from command line
    initial_url = ""
    for arg in sys.argv[1:]:
        if arg.startswith("http"):
            initial_url = arg
            break

    # If application is already running, focus existing window and exit
    if send_to_existing_instance(initial_url):
        print("Barq is already running. Focus request sent to active instance.")
        return 0

    # Level 3: Set AppUserModelID BEFORE QApplication
    set_windows_app_id()

    app = QApplication(sys.argv)

    # Prevent Qt from auto-quitting when main window is hidden to tray
    app.setQuitOnLastWindowClosed(False)

    # Set Desktop File Name & Application Name for Linux Taskbar / Window Manager
    app.setApplicationName("Barq Download Manager")
    app.setDesktopFileName("barq")

    # ──── Level 1: Application-wide icon (Qt runtime) ────
    # Try ICO first (preferred on Windows), fall back to PNG
    icon = QIcon()
    ico_path = resource_path("assets/icons/barq.ico")
    png_path = resource_path("logo.png")

    if ico_path.exists():
        icon = QIcon(str(ico_path))
    elif png_path.exists():
        icon = QIcon(str(png_path))

    if icon.isNull():
        print(f"[WARNING] Failed to load icon from: {ico_path} or {png_path}")
    else:
        # Set on QApplication → default icon for ALL windows, dialogs, tray
        app.setWindowIcon(icon)

    # Create and show main window
    window = BarqMainWindow(initial_url)

    # Level 1 continued: Also set directly on the main window
    if not icon.isNull():
        window.setWindowIcon(icon)

    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
