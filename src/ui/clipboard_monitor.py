from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
import re

class ClipboardMonitor(QObject):
    url_detected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self.check_clipboard)
        self.last_text = ""
        self.is_enabled = True
        self.recently_detected = set()
        
        # Supported extensions regex
        self.extensions = r'\.(exe|zip|rar|7z|mp4|mkv|avi|iso|pdf|msi|dmg|pkg|tar|gz|apk|docx|xlsx|deb|AppImage|mp3|flac|bin|xz)'
        # Fix regex to handle query parameters and FTP
        self.pattern = re.compile(r'(https?|ftp)://[^\s]+' + self.extensions + r'(\?[^\s]*)?', re.IGNORECASE)

    def set_enabled(self, enabled):
        self.is_enabled = enabled

    def check_clipboard(self):
        if not self.is_enabled:
            return
            
        text = self.clipboard.text().strip()
        if text == self.last_text:
            return
            
        self.last_text = text
        if self.pattern.match(text):
            if text not in self.recently_detected:
                self.recently_detected.add(text)
                self.url_detected.emit(text)

