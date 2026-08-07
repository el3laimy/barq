import json
import os
import threading
from PyQt6.QtCore import QObject, pyqtSignal

DEFAULT_SETTINGS = {
    "download_path": os.path.expanduser("~/Downloads"),
    "max_concurrent_downloads": 3,
    "speed_limit": 0,
    "max_retries": 10,
    "connection_timeout": 30,
    "theme": "Dark Glass",
    "segments_per_download": 16,
    "auto_start_clipboard": False,
    "minimize_to_tray": False,
    "notification_sound": True,
    "use_rust_engine": False
}

class SettingsManager(QObject):
    settings_changed = pyqtSignal(dict)
    
    def __init__(self, filename="settings.json"):
        super().__init__()
        self.filename = filename
        self.settings = DEFAULT_SETTINGS.copy()
        self._lock = threading.Lock()
        self.load()
        
    def load(self):
        with self._lock:
            if os.path.exists(self.filename):
                try:
                    with open(self.filename, 'r') as f:
                        data = json.load(f)
                        self.settings.update(data)
                except Exception as e:
                    print(f"Failed to load settings: {e}")
            else:
                self._save_internal()
            
    def _save_internal(self):
        try:
            temp_filename = self.filename + ".tmp"
            with open(temp_filename, 'w') as f:
                json.dump(self.settings, f, indent=4)
            os.replace(temp_filename, self.filename)
        except Exception as e:
            print(f"Failed to save settings: {e}")
            
    def save(self):
        with self._lock:
            self._save_internal()
            
    def get(self, key, default=None):
        with self._lock:
            val = self.settings.get(key, DEFAULT_SETTINGS.get(key))
            return val if val is not None else default
        
    def set(self, key, value):
        with self._lock:
            self.settings[key] = value
            self._save_internal()
            settings_copy = self.settings.copy()
        self.settings_changed.emit(settings_copy)

_settings_manager = None

def get_settings_manager():
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager

# Backward-compatible module-level access
# Code that does `from core.settings import settings_manager` will get the lazy instance
class _SettingsProxy:
    """Lazy proxy so settings_manager can be imported at module level without
    requiring QApplication to exist at import time."""
    def __getattr__(self, name):
        return getattr(get_settings_manager(), name)

settings_manager = _SettingsProxy()
