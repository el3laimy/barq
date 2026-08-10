import sys
import os
import unittest
from PyQt6.QtWidgets import QApplication

sys.path.append(os.path.abspath("."))
sys.path.append(os.path.abspath("src"))

class TestGuiLaunch(unittest.TestCase):
    def test_gui_window_instantiation(self):
        app = QApplication.instance() or QApplication([])
        
        from ui.main_window import BarqMainWindow
        window = BarqMainWindow()
        self.assertIsNotNone(window)
        if hasattr(window, 'browser_inbox_watcher') and window.browser_inbox_watcher:
            window.browser_inbox_watcher.stop()
        if hasattr(window, 'ipc_server') and window.ipc_server:
            window.ipc_server.stop()
        if hasattr(window, 'tray_icon'):
            window.tray_icon.hide()
        window.close()
        window.deleteLater()

if __name__ == "__main__":
    unittest.main()
