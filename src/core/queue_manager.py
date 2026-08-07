"""
Advanced Queue Manager for Barq Download Manager.
Handles multi-queue organization, independent concurrency caps, and speed limit policies.
"""

import json
import os
import threading
from typing import Dict, List, Optional
from PyQt6.QtCore import QObject, pyqtSignal

DEFAULT_QUEUES = [
    {
        "id": "main",
        "name": "Main Queue",
        "max_concurrent": 3,
        "speed_limit_kbps": 0,
        "auto_start": True,
    },
    {
        "id": "media",
        "name": "Media Queue",
        "max_concurrent": 2,
        "speed_limit_kbps": 0,
        "auto_start": False,
    },
    {
        "id": "documents",
        "name": "Documents Queue",
        "max_concurrent": 5,
        "speed_limit_kbps": 0,
        "auto_start": True,
    }
]

class DownloadQueue:
    def __init__(self, id: str, name: str, max_concurrent: int = 3, speed_limit_kbps: int = 0, auto_start: bool = True):
        self.id = id
        self.name = name
        self.max_concurrent = max_concurrent
        self.speed_limit_kbps = speed_limit_kbps
        self.auto_start = auto_start
        self.active_tasks: List[str] = []
        self.queued_tasks: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "max_concurrent": self.max_concurrent,
            "speed_limit_kbps": self.speed_limit_kbps,
            "auto_start": self.auto_start,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'DownloadQueue':
        return cls(
            id=data.get("id", "main"),
            name=data.get("name", "Queue"),
            max_concurrent=data.get("max_concurrent", 3),
            speed_limit_kbps=data.get("speed_limit_kbps", 0),
            auto_start=data.get("auto_start", True),
        )


class QueueManager(QObject):
    queues_updated = pyqtSignal()

    def __init__(self, filename: str = "queues.json"):
        super().__init__()
        self.filename = filename
        self.queues: Dict[str, DownloadQueue] = {}
        self._lock = threading.Lock()
        self.load()

    def load(self):
        with self._lock:
            if os.path.exists(self.filename):
                try:
                    with open(self.filename, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for item in data:
                            q = DownloadQueue.from_dict(item)
                            self.queues[q.id] = q
                except Exception as e:
                    print(f"Error loading queues: {e}")
                    self._init_defaults()
            else:
                self._init_defaults()

    def _init_defaults(self):
        self.queues.clear()
        for item in DEFAULT_QUEUES:
            q = DownloadQueue.from_dict(item)
            self.queues[q.id] = q
        self._save_internal()

    def _save_internal(self):
        try:
            temp = self.filename + ".tmp"
            data = [q.to_dict() for q in self.queues.values()]
            with open(temp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            os.replace(temp, self.filename)
        except Exception as e:
            print(f"Error saving queues: {e}")

    def save(self):
        with self._lock:
            self._save_internal()
        self.queues_updated.emit()

    def get_queue(self, queue_id: str) -> Optional[DownloadQueue]:
        with self._lock:
            return self.queues.get(queue_id, self.queues.get("main"))

    def create_queue(self, id: str, name: str, max_concurrent: int = 3, speed_limit_kbps: int = 0) -> DownloadQueue:
        with self._lock:
            q = DownloadQueue(id=id, name=name, max_concurrent=max_concurrent, speed_limit_kbps=speed_limit_kbps)
            self.queues[id] = q
            self._save_internal()
        self.queues_updated.emit()
        return q

    def delete_queue(self, queue_id: str) -> bool:
        if queue_id == "main":
            return False # Cannot delete main queue
        with self._lock:
            if queue_id in self.queues:
                del self.queues[queue_id]
                self._save_internal()
            else:
                return False
        self.queues_updated.emit()
        return True
