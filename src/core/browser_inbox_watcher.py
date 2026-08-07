import json
import logging
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)

class BrowserInboxWatcher(QObject):
    envelope_received = pyqtSignal(dict)
    
    def __init__(self, inbox_dir: Path, parent=None):
        super().__init__(parent)
        self.inbox_dir = inbox_dir
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._drain)
        
    def start(self):
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.timer.start()
        
    def _drain(self):
        for path in sorted(self.inbox_dir.glob('*.json')):
            processing = path.with_suffix('.processing')
            try:
                path.replace(processing)  # claim atomically
                envelope = json.loads(processing.read_text('utf-8'))
                self.envelope_received.emit(envelope)
                processing.unlink(missing_ok=True)
            except Exception:
                logger.exception('Failed to process browser envelope %s', path.name)
