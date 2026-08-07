"""
Smart Auto-Updater & Verification Module for Barq Download Manager.
Handles semantic version parsing, SHA-256 release checksum verification, and update checking.
"""

import hashlib
import json
import os
import re
import threading
import urllib.request
from typing import Dict, Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal

def parse_version(version_str: str) -> Tuple[int, ...]:
    """Parse version string into integer tuple for comparison (e.g. 'v1.2.0' -> (1, 2, 0))."""
    clean_str = re.sub(r'^[vV]', '', version_str.strip())
    parts = re.split(r'[-+.]', clean_str)
    num_parts = []
    for p in parts:
        if p.isdigit():
            num_parts.append(int(p))
    return tuple(num_parts) if num_parts else (0, 0, 0)


def verify_sha256(filepath: str, expected_hash: str) -> bool:
    """Verify SHA-256 checksum of release artifact prior to execution/installation."""
    if not os.path.exists(filepath):
        return False
    
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        calculated = sha256.hexdigest().lower()
        return calculated == expected_hash.strip().lower()
    except Exception as e:
        print(f"Checksum verification failed: {e}")
        return False


class UpdateChecker(QObject):
    update_available = pyqtSignal(dict) # release_info
    no_update_found = pyqtSignal()
    update_error = pyqtSignal(str)

    DEFAULT_UPDATE_URL = "https://api.github.com/repos/el3laimy/barq/releases/latest"

    def __init__(self, current_version: str = "1.0.0", parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def check_for_updates(self, update_url: Optional[str] = None):
        """Check for updates in a background thread to avoid blocking the UI."""
        thread = threading.Thread(
            target=self._check_for_updates_sync,
            args=(update_url,),
            daemon=True
        )
        thread.start()

    def _check_for_updates_sync(self, update_url: Optional[str] = None):
        """Internal sync method that performs the actual HTTP request."""
        url = update_url or self.DEFAULT_UPDATE_URL
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Barq-Auto-Updater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    self.update_error.emit(f"Server returned HTTP {response.status}")
                    return

                data = json.loads(response.read().decode('utf-8'))
                remote_version_tag = data.get("tag_name") or data.get("version", "0.0.0")

                if parse_version(remote_version_tag) > parse_version(self.current_version):
                    release_info = {
                        "version": remote_version_tag,
                        "release_notes": data.get("body") or data.get("description", ""),
                        "download_url": data.get("html_url") or data.get("tarball_url", ""),
                        "assets": data.get("assets", [])
                    }
                    self.update_available.emit(release_info)
                else:
                    self.no_update_found.emit()

        except Exception as e:
            self.update_error.emit(str(e))
