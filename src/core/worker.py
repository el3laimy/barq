import asyncio
import platform
import time
from typing import Mapping, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.resilient_downloader import ResilientDownloader
from core.traffic_control import global_limiter
from core.settings import settings_manager

class DownloadWorker(QThread):
    started = pyqtSignal(str, object) 
    progress_updated = pyqtSignal(object, object, float)
    status_changed = pyqtSignal(str)
    task_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        url,
        dest,
        request_headers: Optional[Mapping[str, str]] = None,
        browser_context_url: Optional[str] = None,
        parts: Optional[int] = None,
        checksum: Optional[tuple[str, str]] = None,
    ):
        super().__init__()
        self.url = url
        self.dest = dest
        self.request_headers = dict(request_headers or {})
        self.browser_context_url = browser_context_url
        self.parts = parts
        self.checksum = checksum
        self.downloader = None
        self._is_running = True
        self.loop = None
        
        self.last_bytes = 0
        self.last_time = time.time()
        self.smoothing_factor = 0.3
        self.current_speed = 0.0
        self._started_emitted = False

    def run(self):
        try:
            if platform.system() == 'Windows':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.task = self.loop.create_task(self.start_download())
            try:
                self.loop.run_until_complete(self.task)
            except asyncio.CancelledError:
                self.status_changed.emit("Stopped")
            finally:
                self.loop.close()
        except Exception as e:
            self.error_occurred.emit(str(e))

    async def start_download(self):
        self.status_changed.emit("Initializing...")
        self.last_time = time.time()
        
        def callback(current, total):
            if not self._is_running:
                raise asyncio.CancelledError("Download stopped")
            
            now = time.time()
            dt = max(now - self.last_time, 0.001)
            
            if dt > 0.1 or current == 0 or current == total:
                db = max(current - self.last_bytes, 0)
                instant_speed = db / dt
                
                self.current_speed = (self.smoothing_factor * instant_speed) + \
                                     ((1 - self.smoothing_factor) * self.current_speed)
                
                self.last_bytes = current
                self.last_time = now
                
                self.progress_updated.emit(current, total, self.current_speed)
                
                if total > 0 and not self._started_emitted:
                     self.started.emit(self.url, total)
                     self._started_emitted = True

        def status_callback(status):
            self.status_changed.emit(status)

        parts = self.parts or settings_manager.get("segments_per_download", 16)
        max_retries = settings_manager.get("max_retries", 10)
        connection_timeout = settings_manager.get("connection_timeout", 30)

        self.downloader = ResilientDownloader(self.url, self.dest, parts=parts,
                                               max_retries=max_retries,
                                               connection_timeout=connection_timeout,
                                               progress_callback=callback,
                                               status_callback=status_callback,
                                               speed_limiter=global_limiter,
                                               request_headers=self.request_headers,
                                               browser_context_url=self.browser_context_url)
        if self.checksum:
            self.downloader.set_hash(*self.checksum)
        try:
            self.status_changed.emit("Downloading...")
            await self.downloader.start()
            
            if self.downloader.status == "Paused":
                 self.status_changed.emit("Paused")
            elif self.downloader.status == "Expired":
                 self.status_changed.emit("Expired")
                 self.error_occurred.emit("Link Expired")
            elif self.downloader.status == "Error":
                 self.error_occurred.emit(self.downloader.last_error)
            else:
                 self.status_changed.emit("Completed")
                 self.task_finished.emit()
                 
        except asyncio.CancelledError:
            self.status_changed.emit("Stopped")
            raise
        except Exception as e:
            self.error_occurred.emit(str(e))

    def update_url(self, new_url):
        if self.downloader:
            self.downloader.update_url(new_url)
            self.url = new_url

    def set_hash(self, algo, hash_value):
        if self.downloader:
            self.downloader.set_hash(algo, hash_value)

    def stop(self):
        self._is_running = False
        if self.downloader:
            self.downloader.pause()
        if hasattr(self, 'task') and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)
