import sys
import os
import socket
import json

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Enable High DPI scaling (must be set before QApplication)
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PyQt6.QtWidgets import QApplication, QMessageBox
from core.browser_installer import BrowserIntegrationManager, LegacyBridgeRetirementReport
from ui.main_window import BarqMainWindow
from utils.resources import load_app_icon, print_icon_diagnostics


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


# ──── Step 4: Fix Windows Taskbar Identity (AppUserModelID) ────
def configure_windows_app_id() -> None:
    """Set explicit AppUserModelID BEFORE QApplication on Windows.
    This controls taskbar icon grouping and ensures Windows uses our icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "El3laimy.Barq.DownloadManager.1"
        )
    except Exception as exc:
        print(f"Failed to set Windows AppUserModelID: {exc}")


def legacy_extension_remediation_message(
    retirement_report: LegacyBridgeRetirementReport,
) -> str | None:
    if not retirement_report.removed_manifests and not retirement_report.removed_registry_entries:
        return None
    return (
        "A legacy Barq browser registration was removed. Before downloading from "
        "your browser, disable or remove ‘Barq Download Manager Integration’ from "
        "that browser's Extensions page. Barq cannot disable browser extensions for you."
    )


def show_legacy_extension_remediation(
    retirement_report: LegacyBridgeRetirementReport,
) -> None:
    remediation_message = legacy_extension_remediation_message(retirement_report)
    if remediation_message:
        QMessageBox.warning(
            None,
            "Disable the legacy Barq browser extension",
            remediation_message,
        )


def main() -> int:
    # Print diagnostics if BARQ_DEBUG_ICON=1
    print_icon_diagnostics()

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

    # Do this only in the process that owns the UI, so any manual-remediation
    # warning cannot be lost when a second invocation forwards to an existing app.
    legacy_retirement_report = BrowserIntegrationManager.retire_legacy_browser_bridge()

    # Step 4: Set AppUserModelID BEFORE QApplication
    configure_windows_app_id()

    # Step 5: Configure QApplication
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    app.setApplicationName("Barq")
    app.setApplicationDisplayName("Barq Download Manager")
    app.setOrganizationName("Barq Project")
    show_legacy_extension_remediation(legacy_retirement_report)

    # Set desktop file name on Linux / Wayland / GNOME for window manager matching
    if sys.platform != "win32":
        app.setDesktopFileName("barq")

    # Step 6: Load and set global application icon
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # Create main window (passes app_icon or uses load_app_icon internally)
    window = BarqMainWindow(initial_url=initial_url, app_icon=app_icon)
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)

    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
