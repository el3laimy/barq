# tests/test_browser_installer.py
import unittest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.browser_installer import BrowserIntegrationManager

class TestBrowserInstaller(unittest.TestCase):
    def test_get_browser_integration_dir(self):
        folder = BrowserIntegrationManager.get_browser_integration_dir()
        self.assertTrue(folder.exists(), f"Browser integration dir should exist: {folder}")
        self.assertTrue((folder / "manifest.json").exists(), "manifest.json should exist")

    def test_detect_browsers(self):
        browsers = BrowserIntegrationManager.detect_installed_browsers()
        self.assertIsInstance(browsers, dict)
        self.assertIn("Chrome", browsers)

    def test_register_all_native_hosts(self):
        results = BrowserIntegrationManager.register_all_native_hosts()
        self.assertIsInstance(results, dict)

if __name__ == "__main__":
    unittest.main()
