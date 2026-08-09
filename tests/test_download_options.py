import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.download_options import DownloadOptions, parse_checksum


class TestDownloadOptions(unittest.TestCase):
    def test_checksum_parses_md5_and_sha256(self):
        self.assertEqual(parse_checksum("A" * 32), ("md5", "a" * 32))
        self.assertEqual(parse_checksum("B" * 64), ("sha256", "b" * 64))
        self.assertIsNone(parse_checksum("  "))

    def test_checksum_and_parts_validation_rejects_unsupported_values(self):
        with self.assertRaises(ValueError):
            parse_checksum("not-a-checksum")
        with self.assertRaises(ValueError):
            parse_checksum("a" * 40)
        with self.assertRaises(ValueError):
            DownloadOptions(parts=0)
        with self.assertRaises(ValueError):
            DownloadOptions(parts=33)


if __name__ == "__main__":
    unittest.main()
