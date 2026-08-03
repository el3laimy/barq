import sys
import os

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
sys.path.append(src_path)

from PyQt6.QtWidgets import QApplication
from ui.main_window import TitanMainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Optional: Enable High DPI scaling
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
    initial_url = None
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        initial_url = sys.argv[1]

    window = TitanMainWindow(initial_url)
    window.show()
    
    sys.exit(app.exec())
