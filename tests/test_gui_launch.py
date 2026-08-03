import sys
import os
from PyQt6.QtWidgets import QApplication

# Add project root to path
sys.path.append(os.path.abspath("."))
# Add src to path
sys.path.append(os.path.abspath("src"))

try:
    # Need to handle potential QWidget: Must construct a QApplication before a QWidget
    app = QApplication(sys.argv)
    
    print("Importing MainWindow...", flush=True)
    from gui_main import MainWindow
    print("Import MainWindow success", flush=True)
    
    print("Instantiating MainWindow...", flush=True)
    window = MainWindow()
    print("MainWindow instantiated success", flush=True)
    
    print("GUI Test Passed", flush=True)
except Exception as e:
    print(f"GUI Test Failed: {e}", flush=True)
    sys.exit(1)
