"""
Barq Performance & Benchmark Test Suite (Gate G5 Validation).
Measures redaction throughput, semver parsing speed, and queue manager operations.
"""

import sys
import os
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from utils.security import redact_sensitive_data
from core.queue_manager import QueueManager, DownloadQueue
from core.updater import parse_version


class PerformanceBenchmarkSuite(unittest.TestCase):

    def test_redaction_performance(self):
        """Benchmark 100,000 security redaction operations on fresh dicts."""
        iterations = 100_000
        start_time = time.perf_counter()
        for i in range(iterations):
            sample_data = {
                "url": f"https://cdn.example.com/file_{i}.zip?token=secret123456789&key=abcdef",
                "cookies": "session_id=987654321; user=admin",
                "authorization": "Bearer token_xyz",
                "filename": "large_file.iso"
            }
            result = redact_sensitive_data(sample_data)
            assert result["cookies"] == "[REDACTED]"
        elapsed = time.perf_counter() - start_time
        print(f"\n⚡ Redaction Benchmark: {iterations:,} operations completed in {elapsed:.4f} seconds "
              f"({iterations / elapsed:,.0f} ops/sec)")
        self.assertLess(elapsed, 5.0, "Redaction performance is unexpectedly slow")

    def test_version_parse_performance(self):
        """Benchmark 100,000 semver parsing operations."""
        iterations = 100_000
        versions = ["v1.2.3-release+build100", "2.0.0-alpha", "v0.9.1", "3.14.159"]
        start_time = time.perf_counter()
        for i in range(iterations):
            _ = parse_version(versions[i % len(versions)])
        elapsed = time.perf_counter() - start_time
        print(f"⚡ Semver Benchmark: {iterations:,} operations completed in {elapsed:.4f} seconds "
              f"({iterations / elapsed:,.0f} ops/sec)")
        self.assertLess(elapsed, 2.0, "Version parsing performance is unexpectedly slow")

    def test_queue_crud_performance(self):
        """Benchmark queue creation, lookup, and deletion throughput."""
        iterations = 1_000
        test_file = "/tmp/barq_bench_queues.json"

        try:
            qm = QueueManager(filename=test_file)
            start_time = time.perf_counter()
            for i in range(iterations):
                qm.create_queue(f"bench_{i}", f"Bench Queue {i}", max_concurrent=4)
            create_elapsed = time.perf_counter() - start_time

            start_time = time.perf_counter()
            for i in range(iterations):
                qm.get_queue(f"bench_{i}")
            lookup_elapsed = time.perf_counter() - start_time

            start_time = time.perf_counter()
            for i in range(iterations):
                qm.delete_queue(f"bench_{i}")
            delete_elapsed = time.perf_counter() - start_time

            print(f"⚡ Queue CRUD Benchmark ({iterations:,} ops each):")
            print(f"   Create: {create_elapsed:.4f}s | Lookup: {lookup_elapsed:.4f}s | Delete: {delete_elapsed:.4f}s")
            self.assertLess(create_elapsed, 10.0, "Queue creation performance is unexpectedly slow")
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)


if __name__ == "__main__":
    unittest.main()
