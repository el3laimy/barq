import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch
import tempfile

from PyQt6.QtWidgets import QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.task_start_queue import QueuedDownload, TaskStartQueue
from core.download_options import DownloadOptions
from ui.downloads_page import DownloadsPage, recover_startup_status


class TestTaskStartQueue(unittest.TestCase):
    def test_task_is_enqueued_only_once(self):
        queue = TaskStartQueue()
        item = QueuedDownload(7, "https://example.test/file", "/tmp/file")

        self.assertTrue(queue.enqueue(item))
        self.assertFalse(queue.enqueue(item))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue.pop_next(), item)

    def test_discard_removes_a_deleted_task_and_preserves_order(self):
        queue = TaskStartQueue()
        first = QueuedDownload(1, "https://example.test/one", "/tmp/one")
        deleted = QueuedDownload(2, "https://example.test/two", "/tmp/two")
        third = QueuedDownload(3, "https://example.test/three", "/tmp/three")
        for item in (first, deleted, third):
            queue.enqueue(item)

        self.assertTrue(queue.discard(deleted.task_id))
        self.assertNotIn(deleted.task_id, queue)
        self.assertEqual(queue.pop_next(), first)
        self.assertEqual(queue.pop_next(), third)
        self.assertIsNone(queue.pop_next())

    def test_drain_returns_tasks_in_order_and_clears_membership(self):
        queue = TaskStartQueue()
        items = (
            QueuedDownload(1, "https://example.test/one", "/tmp/one"),
            QueuedDownload(2, "https://example.test/two", "/tmp/two"),
        )
        for item in items:
            queue.enqueue(item)

        self.assertEqual(queue.drain(), items)
        self.assertEqual(len(queue), 0)
        self.assertNotIn(1, queue)

    def test_page_queues_a_blocked_task_once_and_starts_it_once(self):
        page = type("Page", (), {})()
        page.downloads_info = {
            1: {"status": "Pending"},
            2: {"status": "Pending"},
        }
        page.workers = {1: object()}
        page.max_concurrent = 1
        page.scheduling_suspended = False
        page.download_queue = TaskStartQueue()
        page.task_options = {}
        page.update_status = Mock()
        page.start_worker = Mock()

        DownloadsPage.attempt_start_download(page, 2, "https://example.test/file", "/tmp/file")
        DownloadsPage.attempt_start_download(page, 2, "https://example.test/file", "/tmp/file")

        self.assertEqual(len(page.download_queue), 1)
        page.update_status.assert_called_once_with(2, "Queued")

        page.workers.clear()
        DownloadsPage.process_queue(page)

        page.start_worker.assert_called_once_with(
            2,
            "https://example.test/file",
            "/tmp/file",
            is_video=False,
            format_id="bestvideo+bestaudio/best",
            options=DownloadOptions(),
        )

    def test_pause_all_drains_the_queue_before_stopping_workers(self):
        page = type("Page", (), {})()
        page.scheduling_suspended = False
        page.download_queue = TaskStartQueue()
        queued = QueuedDownload(2, "https://example.test/two", "/tmp/two")
        page.download_queue.enqueue(queued)
        page.downloads_info = {2: {"status": "Queued"}}
        page.update_status = Mock()
        page.workers = {1: object()}
        page.stop_download = Mock()

        DownloadsPage.pause_all(page)

        self.assertTrue(page.scheduling_suspended)
        self.assertEqual(len(page.download_queue), 0)
        page.update_status.assert_called_once_with(2, "Paused")
        page.stop_download.assert_called_once_with(1)

    def test_worker_start_failure_releases_the_slot_and_marks_the_task_error(self):
        page = type("Page", (), {})()
        page.downloads_info = {2: {"status": "Queued"}}
        page.workers = {}
        page.worker_speeds = {}
        page.task_options = {}
        page.download_queue = TaskStartQueue()
        page.browser_request_headers = {}
        page.browser_request_context_urls = {}
        page.is_video_stream_url = Mock(return_value=False)
        page.update_status = Mock()

        with patch("ui.downloads_page.DownloadWorker", side_effect=RuntimeError("cannot start")):
            DownloadsPage.start_worker(page, 2, "https://example.test/file", "/tmp/file")

        self.assertNotIn(2, page.workers)
        self.assertEqual(page.worker_speeds[2], 0)
        page.update_status.assert_called_once_with(2, "Error")

    def test_startup_never_claims_an_in_memory_queue_or_worker_survived(self):
        for interrupted in ("Pending", "Queued", "Initializing", "Downloading"):
            with self.subTest(status=interrupted):
                self.assertEqual(recover_startup_status(interrupted), "Paused")
        self.assertEqual(recover_startup_status("Completed"), "Completed")
        self.assertEqual(recover_startup_status("Error"), "Error")

    def test_removing_task_from_list_keeps_its_downloaded_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "download.zip"
            destination.write_bytes(b"finished")
            page = self._removal_page(destination)

            DownloadsPage.delete_download(page, 2)

            self.assertTrue(destination.exists())
            page.db.delete_download.assert_called_once_with(2)
            self.assertNotIn(2, page.downloads_info)

    def test_permanent_delete_requires_confirmation_then_removes_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "download.zip"
            destination.write_bytes(b"finished")
            Path(f"{destination}.part").write_bytes(b"partial")
            Path(f"{destination}.state.json").write_text("{}", encoding="utf-8")
            page = self._removal_page(destination)

            with patch(
                "ui.downloads_page.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                DownloadsPage.delete_download_files(page, 2)

            self.assertFalse(destination.exists())
            self.assertFalse(Path(f"{destination}.part").exists())
            self.assertFalse(Path(f"{destination}.state.json").exists())

    @staticmethod
    def _removal_page(destination):
        page = type("Page", (), {})()
        page.download_queue = TaskStartQueue()
        page.workers = {}
        page.db = Mock()
        page.browser_request_headers = {}
        page.browser_request_context_urls = {}
        page.task_options = {}
        page.downloads_info = {2: {"dest": str(destination)}}
        page.get_row_by_id = Mock(return_value=None)
        page._remove_download = lambda db_id, delete_files: DownloadsPage._remove_download(
            page,
            db_id,
            delete_files,
        )
        return page


if __name__ == "__main__":
    unittest.main()
