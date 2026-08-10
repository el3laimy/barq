import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from core.updater import parse_version, verify_sha256, UpdateChecker


class TestParseVersion(unittest.TestCase):

    def test_standard_versions(self):
        self.assertEqual(parse_version("v1.0.0"), (1, 0, 0))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("0.0.1"), (0, 0, 1))

    def test_prerelease_tags(self):
        self.assertEqual(parse_version("v2.1.0-alpha"), (2, 1, 0))
        self.assertEqual(parse_version("1.0.0-beta.1"), (1, 0, 0, 1))
        self.assertEqual(parse_version("3.2.1+build.42"), (3, 2, 1, 42))

    def test_comparisons(self):
        self.assertGreater(parse_version("1.1.0"), parse_version("1.0.0"))
        self.assertGreater(parse_version("2.0.0"), parse_version("1.9.9"))
        self.assertGreater(parse_version("1.0.1"), parse_version("1.0.0"))
        self.assertEqual(parse_version("1.0.0"), parse_version("v1.0.0"))

    def test_malformed_versions(self):
        self.assertEqual(parse_version("latest"), (0, 0, 0))
        self.assertEqual(parse_version("abc"), (0, 0, 0))
        self.assertEqual(parse_version(""), (0, 0, 0))

    def test_short_versions(self):
        self.assertEqual(parse_version("v1.0"), (1, 0))
        self.assertEqual(parse_version("5"), (5,))


class TestVerifySHA256(unittest.TestCase):

    def test_valid_hash(self):
        content = b"Barq release binary test payload"
        expected_hash = hashlib.sha256(content).hexdigest()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            self.assertTrue(verify_sha256(temp_path, expected_hash))
            self.assertTrue(verify_sha256(temp_path, expected_hash.upper()))
        finally:
            os.unlink(temp_path)

    def test_invalid_hash(self):
        content = b"Barq release binary test payload"

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            self.assertFalse(verify_sha256(temp_path, "wrong_hash_12345"))
        finally:
            os.unlink(temp_path)

    def test_nonexistent_file(self):
        self.assertFalse(verify_sha256("/tmp/nonexistent_barq_test_file.bin", "abc123"))

    def test_large_file_chunked(self):
        """Verify that chunked reading works for files larger than the 64KB read buffer."""
        content = os.urandom(256 * 1024)  # 256 KB
        expected_hash = hashlib.sha256(content).hexdigest()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            self.assertTrue(verify_sha256(temp_path, expected_hash))
        finally:
            os.unlink(temp_path)


class TestUpdateChecker(unittest.TestCase):

    def setUp(self):
        from PyQt6.QtCore import QCoreApplication
        self.app = QCoreApplication.instance() or QCoreApplication([])

    def _make_mock_response(self, data_dict, status=200):
        """Create a mock urllib response context manager."""
        mock_response = MagicMock()
        mock_response.status = status
        mock_response.read.return_value = json.dumps(data_dict).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        return mock_response

    @patch('core.updater.urllib.request.urlopen')
    def test_update_available(self, mock_urlopen):
        release_data = {
            "tag_name": "v2.0.0",
            "body": "New major release",
            "html_url": "https://github.com/el3laimy/barq/releases/v2.0.0",
            "assets": []
        }
        mock_urlopen.return_value = self._make_mock_response(release_data)

        checker = UpdateChecker(current_version="1.0.0")
        handler = MagicMock()
        checker.update_available.connect(handler)

        checker._check_for_updates_sync()
        handler.assert_called_once()
        call_args = handler.call_args[0][0]
        self.assertEqual(call_args["version"], "v2.0.0")

    @patch('core.updater.urllib.request.urlopen')
    def test_no_update(self, mock_urlopen):
        release_data = {"tag_name": "v1.0.0", "body": "Current version"}
        mock_urlopen.return_value = self._make_mock_response(release_data)

        checker = UpdateChecker(current_version="1.0.0")
        handler = MagicMock()
        checker.no_update_found.connect(handler)

        checker._check_for_updates_sync()
        handler.assert_called_once()

    @patch('core.updater.urllib.request.urlopen')
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")

        checker = UpdateChecker(current_version="1.0.0")
        handler = MagicMock()
        checker.update_error.connect(handler)

        checker._check_for_updates_sync()
        handler.assert_called_once()
        self.assertIn("Connection refused", handler.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
