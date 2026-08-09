"""A unique FIFO queue for download tasks waiting for a worker slot."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from core.download_options import DownloadOptions


@dataclass(frozen=True)
class QueuedDownload:
    """The immutable data needed to start a task once a slot is available."""

    task_id: int
    url: str
    destination: str
    is_video: bool = False
    format_id: str = "bestvideo+bestaudio/best"
    options: DownloadOptions = field(default_factory=DownloadOptions)


class TaskStartQueue:
    """Keep at most one pending start request for each task ID."""

    def __init__(self) -> None:
        self._items: deque[QueuedDownload] = deque()
        self._task_ids: set[int] = set()

    def enqueue(self, item: QueuedDownload) -> bool:
        """Add *item* once, returning whether it was newly queued."""
        if item.task_id in self._task_ids:
            return False
        self._items.append(item)
        self._task_ids.add(item.task_id)
        return True

    def pop_next(self) -> QueuedDownload | None:
        """Return the oldest queued item, or ``None`` when the queue is empty."""
        if not self._items:
            return None
        item = self._items.popleft()
        self._task_ids.remove(item.task_id)
        return item

    def discard(self, task_id: int) -> bool:
        """Remove a pending task without disturbing the remaining FIFO order."""
        if task_id not in self._task_ids:
            return False
        self._items = deque(item for item in self._items if item.task_id != task_id)
        self._task_ids.remove(task_id)
        return True

    def drain(self) -> tuple[QueuedDownload, ...]:
        """Remove and return all queued tasks in FIFO order."""
        items = tuple(self._items)
        self._items.clear()
        self._task_ids.clear()
        return items

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._task_ids

    def __len__(self) -> int:
        return len(self._items)
