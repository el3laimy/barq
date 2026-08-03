import sys
import os

# ──── Fix WM_CLASS for X11 taskbar icon matching ────
# On X11, Qt uses sys.argv[0] as the WM_CLASS instance name.
# We must set it to "barq" BEFORE QApplication() is constructed,
# so the WM_CLASS matches StartupWMClass=barq in barq.desktop.
# This is the definitive fix for the gear icon on GNOME/X11.
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
    # Fix Taskbar icon grouping on Windows
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("barq.project.downloadmanager.1.0")
        except Exception:
            pass

    app = QApplication(sys.argv)
    
    # Set Desktop File Name & Application Name for Linux Taskbar / Window Manager matching
    app.setApplicationName("Barq Download Manager")
    app.setDesktopFileName("barq")
    
    # Set Global App Icon for Taskbar, Dock & Window Manager
    logo_path = os.path.join(current_dir, "logo.png")
    app_icon = None
    if os.path.exists(logo_path):
        app_icon = QIcon(logo_path)
        app.setWindowIcon(app_icon)
    
    initial_url = None
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        initial_url = sys.argv[1]

    window = BarqMainWindow(initial_url)
    if app_icon:
        window.setWindowIcon(app_icon)
    window.show()
    
    sys.exit(app.exec())
