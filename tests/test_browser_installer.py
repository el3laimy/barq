# tests/test_browser_installer.py
import unittest
import os
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton
from barq_app import (
    legacy_extension_remediation_message,
    main,
    show_legacy_extension_remediation,
)
from core import settings as settings_module
from core.browser_installer import (
    BrowserIntegrationManager,
    LEGACY_HOST_NAME,
    LegacyBridgeRetirementReport,
)
from ui.settings_page import SettingsPage

class TestBrowserInstaller(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_legacy_registration_reports_retired(self):
        status = BrowserIntegrationManager.register_all_native_hosts()

        self.assertFalse(status["enabled"])
        self.assertIn("retired", status["reason"])

    def test_release_configuration_excludes_legacy_browser_bridge(self):
        project_root = Path(__file__).resolve().parents[1]
        release_files = [
            project_root / "build_executable.spec",
            project_root / "barq_app.py",
        ]

        for release_file in release_files:
            release_configuration = release_file.read_text(encoding="utf-8")
            self.assertNotIn("browser_integration", release_configuration)
            self.assertNotIn("com.barq.downloader", release_configuration)

        entrypoint_source = (project_root / "barq_app.py").read_text(encoding="utf-8")
        self.assertIn("retire_legacy_browser_bridge()", entrypoint_source)

        installer_configuration = (project_root / "barq_installer.nsi").read_text(encoding="utf-8")
        self.assertNotIn('File /r "browser_integration\\*.*"', installer_configuration)
        self.assertNotIn("nsExec::Exec", installer_configuration)

    def test_retired_install_scripts_cannot_register_the_legacy_host(self):
        project_root = Path(__file__).resolve().parents[1]
        retired_installers = {
            "install_host.bat": "exit /b 1",
            "install_host_linux.sh": "exit 1",
        }

        for filename, expected_exit in retired_installers.items():
            installer_source = (
                project_root / "browser_integration" / filename
            ).read_text(encoding="utf-8").lower()
            self.assertIn(expected_exit, installer_source)
            self.assertNotIn("reg add", installer_source)
            self.assertNotIn("mkdir -p", installer_source)

    def test_manifest_migration_removes_only_matching_legacy_manifest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_home = Path(temporary_directory)
            legacy_path, nonmatching_path, *_ = BrowserIntegrationManager.legacy_manifest_paths(
                temporary_home
            )
            unrelated_path = legacy_path.with_name("other-native-host.json")
            legacy_path.parent.mkdir(parents=True)
            nonmatching_path.parent.mkdir(parents=True)
            legacy_path.write_text(json.dumps({"name": LEGACY_HOST_NAME}), encoding="utf-8")
            nonmatching_path.write_text(json.dumps({"name": "app.barq.browser"}), encoding="utf-8")
            unrelated_path.write_text(json.dumps({"name": "other.native.host"}), encoding="utf-8")

            removed_manifests = BrowserIntegrationManager.retire_legacy_manifests(temporary_home)

            self.assertEqual(removed_manifests, (legacy_path,))
            self.assertFalse(legacy_path.exists())
            self.assertTrue(nonmatching_path.exists())
            self.assertTrue(unrelated_path.exists())

    def test_retired_bridge_and_extension_do_not_handoff_downloads(self):
        project_root = Path(__file__).resolve().parents[1]
        bridge_path = project_root / "browser_integration" / "bridge.py"
        bridge_run = subprocess.run(
            [sys.executable, str(bridge_path)],
            capture_output=True,
            check=False,
            text=True,
        )
        background_source = (
            project_root / "browser_integration" / "background.js"
        ).read_text(encoding="utf-8")

        self.assertEqual(bridge_run.returncode, 1)
        self.assertIn("retired", bridge_run.stderr)
        self.assertNotIn("chrome.", background_source)
        self.assertNotIn("connectNative", background_source)
        self.assertNotIn("downloads.cancel", background_source)

    def test_remediation_message_requires_manual_extension_removal(self):
        no_cleanup = LegacyBridgeRetirementReport((), ())
        cleanup_report = LegacyBridgeRetirementReport((Path("legacy.json"),), ())

        self.assertIsNone(legacy_extension_remediation_message(no_cleanup))
        remediation_message = legacy_extension_remediation_message(cleanup_report)
        self.assertIsNotNone(remediation_message)
        self.assertIn("Barq Download Manager Integration", remediation_message)
        self.assertIn("disable or remove", remediation_message)
        self.assertIn("cannot disable", remediation_message)

    def test_cleanup_report_shows_one_manual_remediation_warning(self):
        cleanup_report = LegacyBridgeRetirementReport((Path("legacy.json"),), ())

        with patch("barq_app.QMessageBox.warning") as show_warning:
            show_legacy_extension_remediation(cleanup_report)

        show_warning.assert_called_once()
        warning_title = show_warning.call_args.args[1]
        warning_message = show_warning.call_args.args[2]
        self.assertEqual(warning_title, "Disable the legacy Barq browser extension")
        self.assertIn("Barq Download Manager Integration", warning_message)

    def test_second_invocation_leaves_retirement_for_the_ui_owner(self):
        with (
            patch("barq_app.send_to_existing_instance", return_value=True),
            patch("barq_app.BrowserIntegrationManager.retire_legacy_browser_bridge") as retire_bridge,
            patch.object(sys, "argv", ["barq_app.py"]),
        ):
            self.assertEqual(main(), 0)

        retire_bridge.assert_not_called()

    def test_settings_reports_retired_bridge_without_install_controls(self):
        original_directory = Path.cwd()
        original_settings_manager = settings_module._settings_manager
        with tempfile.TemporaryDirectory() as temporary_directory:
            os.chdir(temporary_directory)
            try:
                page = SettingsPage()
                try:
                    button_texts = [button.text() for button in page.findChildren(QPushButton)]
                    checkbox_texts = [checkbox.text() for checkbox in page.findChildren(QCheckBox)]
                    label_texts = [label.text() for label in page.findChildren(QLabel)]
                finally:
                    page.close()
                    page.deleteLater()
            finally:
                settings_module._settings_manager = original_settings_manager
                os.chdir(original_directory)

        self.assertNotIn("⚡ Auto-Install Integration", button_texts)
        self.assertNotIn("📂 Open Extension Folder", button_texts)
        self.assertNotIn("🌐 Extensions Page", button_texts)
        self.assertNotIn(
            "⚡ Enable Experimental Rust Engine Daemon (barq-engine v0.1.0)",
            checkbox_texts,
        )
        self.assertTrue(
            any("No browser native host is registered from Settings." in text for text in label_texts)
        )

if __name__ == "__main__":
    unittest.main()
