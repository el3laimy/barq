import unittest
from utils.security import redact_sensitive_data, sanitize_headers

class TestSecurityRedaction(unittest.TestCase):

    def test_redact_sensitive_dict(self):
        payload = {
            "url": "https://example.com/file.zip",
            "cookies": "session_id=123456789; user=admin",
            "authorization": "Bearer secret_token_xyz",
            "filename": "file.zip"
        }
        redacted = redact_sensitive_data(payload)
        self.assertEqual(redacted["cookies"], "[REDACTED]")
        self.assertEqual(redacted["authorization"], "[REDACTED]")
        self.assertEqual(redacted["url"], "https://example.com/file.zip")
        self.assertEqual(redacted["filename"], "file.zip")

    def test_redact_url_query_tokens(self):
        url = "https://cdn.example.com/video.mp4?token=secret123&user=john"
        redacted = redact_sensitive_data(url)
        self.assertEqual(redacted, "https://cdn.example.com/video.mp4?token=[REDACTED]&user=john")

    def test_sanitize_headers(self):
        headers = {
            "User-Agent": "Barq/1.0",
            "Cookie": "sess=abc",
            "Authorization": "Bearer 123"
        }
        sanitized = sanitize_headers(headers)
        self.assertEqual(sanitized["Cookie"], "[REDACTED_HEADER]")
        self.assertEqual(sanitized["Authorization"], "[REDACTED_HEADER]")
        self.assertEqual(sanitized["User-Agent"], "Barq/1.0")

if __name__ == "__main__":
    unittest.main()
