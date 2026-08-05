# src/core/browser_installer.py
"""
Automated Browser Integration Manager for Barq Download Manager.
Detects installed browsers and registers Native Messaging Host configurations
for automatic download interception.
"""

import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from utils.resources import resource_path

logger = logging.getLogger(__name__)

HOST_NAME = "com.barq.downloader"

class BrowserIntegrationManager:
    @staticmethod
    def get_browser_integration_dir() -> Path:
        """Returns the absolute path to the browser_integration folder."""
        path = resource_path("browser_integration")
        if not path.exists():
            # Fallback to dev directory
            path = Path(__file__).resolve().parents[2] / "browser_integration"
        return path

    @staticmethod
    def detect_installed_browsers() -> dict:
        """
        Detect installed web browsers on the system.
        Returns a dict: { 'browser_name': { 'installed': bool, 'path': str/Path } }
        """
        results = {}
        home = Path.home()

        if sys.platform == "win32":
            import winreg
            browser_keys = {
                "Chrome": r"Software\Google\Chrome\NativeMessagingHosts",
                "Brave": r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
                "Edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
                "Firefox": r"Software\Mozilla\NativeMessagingHosts",
            }
            for name, reg_path in browser_keys.items():
                installed = False
                try:
                    # Check HKLM or HKCU
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ)
                    winreg.CloseKey(key)
                    installed = True
                except Exception:
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path, 0, winreg.KEY_READ)
                        winreg.CloseKey(key)
                        installed = True
                    except Exception:
                        installed = False
                results[name] = {"installed": installed, "config_dir": reg_path}
        else:
            # Linux / macOS paths
            linux_paths = {
                "Chrome": home / ".config" / "google-chrome" / "NativeMessagingHosts",
                "Brave": home / ".config" / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts",
                "Chromium": home / ".config" / "chromium" / "NativeMessagingHosts",
                "Edge": home / ".config" / "microsoft-edge" / "NativeMessagingHosts",
                "Vivaldi": home / ".config" / "vivaldi" / "NativeMessagingHosts",
                "Firefox": home / ".mozilla" / "native-messaging-hosts",
            }

            for name, host_dir in linux_paths.items():
                # Check parent directory existence (e.g. ~/.config/google-chrome)
                parent_dir = host_dir.parent
                installed = parent_dir.exists()
                results[name] = {"installed": installed, "config_dir": host_dir}

        return results

    @classmethod
    def register_all_native_hosts(cls) -> dict:
        """
        Automatically register Barq Native Messaging Host across all detected browsers.
        Returns a dict summarizing status for each browser.
        """
        integration_dir = cls.get_browser_integration_dir()
        manifest_src = integration_dir / "host.json"
        
        status_report = {}

        if not integration_dir.exists():
            logger.error(f"Browser integration directory not found: {integration_dir}")
            return {"error": f"Directory not found: {integration_dir}"}

        # Select bridge executable based on OS
        if sys.platform == "win32":
            bridge_path = integration_dir / "bridge.bat"
            if not bridge_path.exists():
                bridge_path = integration_dir / "bridge.py"
        else:
            bridge_path = integration_dir / "bridge.sh"
            if bridge_path.exists():
                # Ensure execution permission
                try:
                    os.chmod(bridge_path, 0o755)
                except Exception as e:
                    logger.warning(f"Failed to set executable mode on {bridge_path}: {e}")
            
            bridge_py = integration_dir / "bridge.py"
            if bridge_py.exists():
                try:
                    os.chmod(bridge_py, 0o755)
                except Exception as e:
                    pass

        # Build Host Manifest Content
        host_manifest = {
            "name": HOST_NAME,
            "description": "Barq Downloader Native Host",
            "path": str(bridge_path.resolve()),
            "type": "stdio",
            "allowed_origins": [
                "chrome-extension://*",
                "chrome-extension://REPLACE_WITH_YOUR_EXTENSION_ID/"
            ]
        }

        browsers = cls.detect_installed_browsers()

        if sys.platform == "win32":
            import winreg
            # Temporary manifest file
            win_manifest_path = integration_dir / "host_win.json"
            try:
                with open(win_manifest_path, "w", encoding="utf-8") as f:
                    json.dump(host_manifest, f, indent=4)
            except Exception as e:
                logger.error(f"Failed to write Windows host manifest: {e}")

            for b_name, b_info in browsers.items():
                reg_path = f"Software\\Google\\Chrome\\NativeMessagingHosts\\{HOST_NAME}"
                if b_name == "Edge":
                    reg_path = f"Software\\Microsoft\\Edge\\NativeMessagingHosts\\{HOST_NAME}"
                elif b_name == "Mozilla" or b_name == "Firefox":
                    reg_path = f"Software\\Mozilla\\NativeMessagingHosts\\{HOST_NAME}"
                elif b_name == "Brave":
                    reg_path = f"Software\\BraveSoftware\\Brave-Browser\\NativeMessagingHosts\\{HOST_NAME}"

                try:
                    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path)
                    winreg.SetValue(key, "", winreg.REG_SZ, str(win_manifest_path.resolve()))
                    winreg.CloseKey(key)
                    status_report[b_name] = True
                except Exception as e:
                    logger.error(f"Failed to write registry for {b_name}: {e}")
                    status_report[b_name] = False
        else:
            # Linux / macOS: Write JSON manifest to all target directories
            for b_name, b_info in browsers.items():
                host_dir = b_info["config_dir"]
                try:
                    host_dir.mkdir(parents=True, exist_ok=True)
                    target_file = host_dir / f"{HOST_NAME}.json"
                    
                    # For Firefox, type is stdio, allowed_extensions is used instead of allowed_origins
                    if b_name == "Firefox":
                        ff_manifest = dict(host_manifest)
                        ff_manifest["allowed_extensions"] = ["barq-downloader@barq.project"]
                        if "allowed_origins" in ff_manifest:
                            del ff_manifest["allowed_origins"]
                        with open(target_file, "w", encoding="utf-8") as f:
                            json.dump(ff_manifest, f, indent=4)
                    else:
                        with open(target_file, "w", encoding="utf-8") as f:
                            json.dump(host_manifest, f, indent=4)
                            
                    status_report[b_name] = True
                    logger.info(f"Registered Barq Native Host for {b_name} at {target_file}")
                except Exception as e:
                    logger.error(f"Failed to register Native Host for {b_name}: {e}")
                    status_report[b_name] = False

        return status_report

    @classmethod
    def open_extension_folder(cls) -> bool:
        """Opens the browser extension directory in the system file manager."""
        folder = cls.get_browser_integration_dir()
        if not folder.exists():
            return False

        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return True
        except Exception as e:
            logger.error(f"Failed to open extension folder: {e}")
            return False

    @classmethod
    def launch_browser_extensions_page(cls) -> bool:
        """Opens the default browser extensions URL."""
        import webbrowser
        try:
            # Open general extensions guidance page or local chrome extensions URL
            webbrowser.open("chrome://extensions")
            return True
        except Exception as e:
            logger.error(f"Failed to open browser extensions page: {e}")
            return False
