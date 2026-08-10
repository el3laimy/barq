import os
import sys
import unittest
import json
import socket
import time

# Ensure src is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.abspath(os.path.join(current_dir, '..', 'src'))
if src_path not in sys.path:
    sys.path.append(src_path)

from PyQt6.QtWidgets import QApplication
from core.ipc_server import IPCServer
from core.database import DatabaseManager

class TestIPCServerAndDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db_file = os.path.join(current_dir, 'test_downloads.db')
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
        self.db = DatabaseManager(self.db_file)

    def tearDown(self):
        del self.db
        if os.path.exists(self.db_file):
            os.remove(self.db_file)

    def test_database_crud(self):
        # Add download
        row_id = self.db.add_download("http://example.com/file.zip", "file.zip", "/downloads/file.zip", "Archives")
        self.assertIsNotNone(row_id)

        # Get downloads
        all_dls = self.db.get_all_downloads()
        self.assertEqual(len(all_dls), 1)
        self.assertEqual(all_dls[0]['filename'], "file.zip")

        # Update status
        self.db.update_status(row_id, "Completed", downloaded=1024, size=1024)
        updated_dls = self.db.get_downloads_by_status("Completed")
        self.assertEqual(len(updated_dls), 1)

        # Update URL safely
        self.db.update_url(row_id, "http://example.com/new_file.zip")
        all_dls = self.db.get_all_downloads()
        self.assertEqual(all_dls[0]['url'], "http://example.com/new_file.zip")

        # Delete download
        self.db.delete_download(row_id)
        self.assertEqual(len(self.db.get_all_downloads()), 0)

    def test_ipc_server(self):
        received_urls = []

        server = IPCServer(port=0)
        server.url_received.connect(lambda url: received_urls.append(url))
        started = server.start()
        self.assertTrue(started)
        port = server.server.serverPort()

        # Send a JSON message over socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(('127.0.0.1', port))
            payload = json.dumps({"url": "http://example.com/ipc_test.mp4"}) + "\n"
            s.sendall(payload.encode('utf-8'))
            s.close()

            # Process Qt events to handle readyRead signal
            t_end = time.time() + 2.0
            while time.time() < t_end and not received_urls:
                self.app.processEvents()
                time.sleep(0.05)

            self.assertEqual(len(received_urls), 1)
            self.assertEqual(received_urls[0], "http://example.com/ipc_test.mp4")
        finally:
            server.stop()

    def test_legacy_browser_payload_is_rejected_without_socket(self):
        for legacy_field in ("cookies", "userAgent", "referrer", "filename", "fileSize"):
            with self.subTest(legacy_field=legacy_field):
                request = json.dumps({"url": "http://example.com/file.zip", legacy_field: "secret"})
                self.assertIsNone(IPCServer.parse_request(request))

    def test_url_only_payload_is_accepted_without_socket(self):
        request = IPCServer.parse_request('{"url":"http://example.com/file.zip"}')

        self.assertEqual(request, {"url": "http://example.com/file.zip"})

if __name__ == '__main__':
    unittest.main()
