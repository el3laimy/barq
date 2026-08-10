import os
import unittest
from core.queue_manager import QueueManager


class TestQueueManager(unittest.TestCase):

    def setUp(self):
        from PyQt6.QtCore import QCoreApplication
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.test_file = "/tmp/barq_test_queues.json"
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
        self.qm = QueueManager(filename=self.test_file)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_default_queues(self):
        main_q = self.qm.get_queue("main")
        self.assertIsNotNone(main_q)
        self.assertEqual(main_q.name, "Main Queue")

        media_q = self.qm.get_queue("media")
        self.assertIsNotNone(media_q)
        self.assertEqual(media_q.name, "Media Queue")

        docs_q = self.qm.get_queue("documents")
        self.assertIsNotNone(docs_q)
        self.assertEqual(docs_q.max_concurrent, 5)

    def test_create_and_delete_queue(self):
        new_q = self.qm.create_queue("audio", "Audio Queue", max_concurrent=4)
        self.assertEqual(new_q.name, "Audio Queue")
        self.assertEqual(new_q.max_concurrent, 4)

        retrieved = self.qm.get_queue("audio")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "Audio Queue")

        deleted = self.qm.delete_queue("audio")
        self.assertTrue(deleted)

        # After deletion, getting the queue should fallback to main
        fallback = self.qm.get_queue("audio")
        self.assertEqual(fallback.id, "main")

    def test_cannot_delete_main_queue(self):
        deleted = self.qm.delete_queue("main")
        self.assertFalse(deleted)
        # Verify main queue still exists
        main_q = self.qm.get_queue("main")
        self.assertIsNotNone(main_q)
        self.assertEqual(main_q.id, "main")

    def test_delete_nonexistent_queue(self):
        deleted = self.qm.delete_queue("nonexistent_queue_xyz")
        self.assertFalse(deleted)

    def test_persistence_save_and_reload(self):
        """Verify that queues persist to disk and can be restored."""
        # Create a custom queue
        self.qm.create_queue("video", "Video Queue", max_concurrent=2, speed_limit_kbps=500)

        # Verify file was actually created
        self.assertTrue(os.path.exists(self.test_file))

        # Load a completely new QueueManager from the same file
        qm2 = QueueManager(filename=self.test_file)

        # Verify the custom queue survived the round-trip
        video_q = qm2.get_queue("video")
        self.assertIsNotNone(video_q)
        self.assertEqual(video_q.name, "Video Queue")
        self.assertEqual(video_q.max_concurrent, 2)
        self.assertEqual(video_q.speed_limit_kbps, 500)

        # Verify default queues also persisted
        main_q = qm2.get_queue("main")
        self.assertIsNotNone(main_q)
        self.assertEqual(main_q.name, "Main Queue")

    def test_persistence_after_delete(self):
        """Verify that deletions persist to disk."""
        self.qm.create_queue("temp", "Temp Queue")
        self.qm.delete_queue("temp")

        qm2 = QueueManager(filename=self.test_file)
        # Should fallback to main because 'temp' was deleted
        fallback = qm2.get_queue("temp")
        self.assertEqual(fallback.id, "main")

    def test_queue_settings_update_persistence(self):
        """Verify that updated queue settings persist correctly."""
        q = self.qm.get_queue("main")
        q.max_concurrent = 10
        q.speed_limit_kbps = 1024
        self.qm.save()

        qm2 = QueueManager(filename=self.test_file)
        reloaded = qm2.get_queue("main")
        self.assertEqual(reloaded.max_concurrent, 10)
        self.assertEqual(reloaded.speed_limit_kbps, 1024)


if __name__ == "__main__":
    unittest.main()
