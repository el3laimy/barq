import unittest
from unittest.mock import MagicMock, patch

from core.browser_inbox_watcher import (
    BrowserDownloadRequest,
    BrowserEnvelopeError,
    parse_browser_envelope,
)
from core.video_engine import (
    build_common_ydl_options,
    sanitize_media_request_headers,
)


def _base_envelope() -> dict:
    return {
        "protocol": "barq.browser.v1",
        "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "idempotencyKey": "a" * 32,
        "createdAt": "2026-08-08T12:00:00Z",
        "source": "auto-download",
        "request": {
            "url": "https://example.com/file.zip",
            "method": "GET",
        },
        "file": {},
        "browser": {
            "family": "chrome",
            "version": "128.0",
            "profileMode": "normal",
        },
    }


class TestBrowserMediaHandoff(unittest.TestCase):

    def test_preserve_media_source(self):
        env = _base_envelope()
        env["source"] = "media"
        env["request"]["url"] = "https://www.youtube.com/watch?v=test"
        env["request"]["pageUrl"] = "https://www.youtube.com/watch?v=test"
        env["media"] = {"pageTitle": "Test Video"}

        req = parse_browser_envelope(env)

        self.assertEqual(req.source, "media")
        self.assertTrue(req.is_media)
        self.assertEqual(req.page_url, "https://www.youtube.com/watch?v=test")
        self.assertEqual(req.media_page_title, "Test Video")

    def test_normal_download_unchanged(self):
        env = _base_envelope()
        req = parse_browser_envelope(env)

        self.assertEqual(req.source, "auto-download")
        self.assertFalse(req.is_media)
        self.assertIsNone(req.page_url)
        self.assertIsNone(req.media_page_title)

    def test_drm_rejected(self):
        env = _base_envelope()
        env["media"] = {"drmDetected": True}

        with self.assertRaises(BrowserEnvelopeError) as ctx:
            parse_browser_envelope(env)

        self.assertEqual(ctx.exception.code, "drm_protected")

    def test_invalid_page_url(self):
        env = _base_envelope()
        env["request"]["pageUrl"] = "javascript:alert(1)"

        with self.assertRaises(BrowserEnvelopeError) as ctx:
            parse_browser_envelope(env)

        self.assertEqual(ctx.exception.code, "invalid_page_url")

    def test_blob_page_url_rejected(self):
        env = _base_envelope()
        env["request"]["pageUrl"] = "blob:https://example.com/123"

        with self.assertRaises(BrowserEnvelopeError) as ctx:
            parse_browser_envelope(env)

        self.assertEqual(ctx.exception.code, "invalid_page_url")

    def test_sanitize_media_request_headers(self):
        raw_headers = {
            "User-Agent": "Barq-Test-UA",
            "Cookie": "session=test-cookie",
            "Referer": "https://example.com/",
            "Authorization": "Bearer secret-token",
            "X-Injected-Header": "injected",
            "Accept": "text/html",
            "CRLF-Header": "line1\r\nline2",
        }

        sanitized = sanitize_media_request_headers(raw_headers)

        self.assertIn("User-Agent", sanitized)
        self.assertIn("Cookie", sanitized)
        self.assertIn("Referer", sanitized)
        self.assertIn("Accept", sanitized)
        self.assertNotIn("Authorization", sanitized)
        self.assertNotIn("X-Injected-Header", sanitized)
        self.assertNotIn("CRLF-Header", sanitized)

    def test_build_common_ydl_options(self):
        headers = {
            "User-Agent": "TestUA",
            "Cookie": "session=123",
        }

        opts = build_common_ydl_options(headers)

        self.assertTrue(opts.get("quiet"))
        self.assertTrue(opts.get("no_warnings"))
        self.assertEqual(opts.get("http_headers"), headers)


if __name__ == "__main__":
    unittest.main()
