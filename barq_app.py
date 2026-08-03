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

# ──── Fix WM_CLASS for X11 taskbar icon matching ────
# On X11, Qt uses sys.argv[0] as the WM_CLASS instance name.
# We must set it to "barq" BEFORE QApplication() is constructed,
# so the WM_CLASS matches StartupWMClass=barq in barq.desktop.
sys.argv[0] = "barq"

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
if src_path not in sys.path:
    sys.path.append(src_path)

# Enable High DPI scaling (must be set before QApplication)
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from ui.main_window import BarqMainWindow

if __name__ == "__main__":
    initial_url = ""
    for arg in sys.argv[1:]:
        if arg.startswith("http"):
            initial_url = arg
            break

    # If application is already running, focus existing window and exit
    if send_to_existing_instance(initial_url):
        print("Barq is already running. Focus request sent to active instance.")
        sys.exit(0)

    # Fix Taskbar icon grouping on Windows
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("barq.project.downloadmanager.1.0")
        except Exception:
            pass

    app = QApplication(sys.argv)
    # Prevent Qt from auto-quitting when main window is hidden to tray
    app.setQuitOnLastWindowClosed(False)
    
    # Set Desktop File Name & Application Name for Linux Taskbar / Window Manager matching
    app.setApplicationName("Barq Download Manager")
    app.setDesktopFileName("barq")
    
    # Set Global App Icon for Taskbar, Dock & Window Manager
    logo_path = os.path.join(current_dir, "logo.png")
    app_icon = None
    if os.path.exists(logo_path):
        app_icon = QIcon(logo_path)
        app.setWindowIcon(app_icon)

    window = BarqMainWindow(initial_url)
    if app_icon:
        window.setWindowIcon(app_icon)
    window.show()
    
    sys.exit(app.exec())
