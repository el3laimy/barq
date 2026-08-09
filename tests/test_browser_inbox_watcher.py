import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from core.browser_inbox_watcher import BrowserInboxWatcher, browser_inbox_dir, parse_browser_envelope
from core.resilient_downloader import ResilientDownloader


def _valid_envelope():
    return {
        'protocol': 'barq.browser.v1',
        'requestId': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
        'idempotencyKey': 'idem-a1b2c3d4e5f6789012345678901234567890',
        'createdAt': '2026-08-08T01:00:00.000Z',
        'source': 'auto-download',
        'request': {
            'url': 'https://example.com/files/archive.zip',
            'finalUrl': 'https://example.com/files/archive.zip',
            'method': 'GET',
            'referrer': 'https://example.com/downloads',
            'headers': {
                'Accept': 'application/octet-stream',
                'Authorization': 'Bearer browser-secret',
                'Range': 'bytes=100-200',
            },
            'cookieHeader': 'session=browser-cookie',
        },
        'file': {
            'suggestedName': 'archive.zip',
            'size': 4096,
        },
        'browser': {
            'family': 'chrome',
            'version': '146.0',
            'profileMode': 'normal',
        },
    }


class _Response:
    def __init__(self, status, headers):
        self.status = status
        self.headers = headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def release(self):
        pass


class _RecordingSession:
    def __init__(self):
        self.calls = []

    async def request(self, method, url, *, headers, timeout, allow_redirects):
        self.calls.append((method, url, dict(headers)))
        if method == 'HEAD':
            return _Response(200, {'Content-Length': '4096', 'Accept-Ranges': 'bytes'})
        return _Response(206, {'Content-Range': 'bytes 0-0/4096'})


class _RedirectRecordingSession(_RecordingSession):
    async def request(self, method, url, *, headers, timeout, allow_redirects):
        self.calls.append((method, url, dict(headers)))
        if url == 'https://example.com/files/archive.zip':
            return _Response(302, {'Location': 'https://cdn.example.com/files/archive.zip'})
        if method == 'HEAD':
            return _Response(200, {'Content-Length': '4096', 'Accept-Ranges': 'bytes'})
        return _Response(206, {'Content-Range': 'bytes 0-0/4096'})


class TestBrowserInboxWatcher(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.inbox_dir = Path(self.temporary_directory.name) / 'inbox'
        self.watcher = BrowserInboxWatcher(self.inbox_dir)

    def tearDown(self):
        self.watcher.stop()
        self.temporary_directory.cleanup()

    def test_valid_envelope_is_delivered_once_with_authenticated_context(self):
        received_requests = []
        self.watcher.envelope_received.connect(received_requests.append)
        self._write_envelope(_valid_envelope())

        self.watcher.drain()
        self.watcher.drain()

        self.assertEqual(len(received_requests), 1)
        browser_request = received_requests[0]
        self.assertEqual(browser_request.url, 'https://example.com/files/archive.zip')
        self.assertEqual(browser_request.context_url, 'https://example.com/files/archive.zip')
        self.assertEqual(browser_request.request_headers['Authorization'], 'Bearer browser-secret')
        self.assertEqual(browser_request.request_headers['Referer'], 'https://example.com/downloads')
        self.assertEqual(browser_request.request_headers['Cookie'], 'session=browser-cookie')
        self.assertNotIn('Range', browser_request.request_headers)
        self.assertEqual(list(self.inbox_dir.glob('*.json')), [])
        self.assertEqual(list(self.inbox_dir.glob('*.processing')), [])

    def test_invalid_cookie_is_quarantined_without_logging_its_value(self):
        envelope = _valid_envelope()
        envelope['request']['cookieHeader'] = 'session=super-secret\r\nInjected: header'
        self._write_envelope(envelope)

        with self.assertLogs('core.browser_inbox_watcher', level='WARNING') as logs:
            self.watcher.drain()

        log_output = '\n'.join(logs.output)
        self.assertNotIn('super-secret', log_output)
        self.assertEqual(len(list((self.inbox_dir / 'quarantine').glob('*.json'))), 1)
        self.assertEqual(list(self.inbox_dir.glob('*.json')), [])

    def test_case_insensitive_duplicate_headers_are_quarantined(self):
        envelope = _valid_envelope()
        envelope['request']['headers']['accept'] = 'application/zip'
        self._write_envelope(envelope)

        self.watcher.drain()

        self.assertEqual(len(list((self.inbox_dir / 'quarantine').glob('*.json'))), 1)
        self.assertEqual(list(self.inbox_dir.glob('*.json')), [])

    def test_non_newline_control_header_value_is_quarantined(self):
        envelope = _valid_envelope()
        envelope['request']['headers']['Accept'] = 'application\x00octet-stream'
        self._write_envelope(envelope)

        self.watcher.drain()

        self.assertEqual(len(list((self.inbox_dir / 'quarantine').glob('*.json'))), 1)

    def test_year_zero_timestamp_is_quarantined(self):
        envelope = _valid_envelope()
        envelope['createdAt'] = '0000-01-01T01:00:00Z'
        self._write_envelope(envelope)

        self.watcher.drain()

        self.assertEqual(len(list((self.inbox_dir / 'quarantine').glob('*.json'))), 1)

    def test_malformed_ipv6_url_is_quarantined_without_breaking_drain(self):
        envelope = _valid_envelope()
        envelope['request']['finalUrl'] = 'https://[::1'
        self._write_envelope(envelope)

        self.watcher.drain()

        self.assertEqual(len(list((self.inbox_dir / 'quarantine').glob('*.json'))), 1)

    def test_stranded_claim_is_recovered_after_a_restart(self):
        received_requests = []
        self.watcher.envelope_received.connect(received_requests.append)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        claimed_path = self.inbox_dir / 'interrupted.processing'
        claimed_path.write_text(json.dumps(_valid_envelope()), encoding='utf-8')

        self.watcher.drain()

        self.assertEqual(len(received_requests), 1)
        self.assertFalse(claimed_path.exists())

    def test_unacknowledged_desktop_delivery_is_retained_for_retry(self):
        attempts = []

        def reject_delivery(_request):
            attempts.append('rejected')
            return False

        watcher = BrowserInboxWatcher(self.inbox_dir, delivery_handler=reject_delivery)
        self.addCleanup(watcher.stop)
        self._write_envelope(_valid_envelope())

        watcher.drain()

        self.assertEqual(attempts, ['rejected'])
        self.assertEqual(len(list(self.inbox_dir.glob('*.processing'))), 1)

        watcher.delivery_handler = lambda _request: True
        watcher.drain()

        self.assertEqual(list(self.inbox_dir.glob('*.processing')), [])
        self.assertEqual(list(self.inbox_dir.glob('*.json')), [])

    def test_configured_inbox_path_takes_precedence(self):
        configured_path = Path(self.temporary_directory.name) / 'configured-inbox'

        with patch.dict(os.environ, {'BARQ_BROWSER_INBOX_DIR': str(configured_path)}):
            self.assertEqual(browser_inbox_dir(), configured_path)

    def test_relative_configured_inbox_path_is_rejected(self):
        with patch.dict(os.environ, {'BARQ_BROWSER_INBOX_DIR': 'relative-inbox'}):
            with self.assertRaisesRegex(ValueError, 'absolute path'):
                browser_inbox_dir()

    def test_relative_xdg_state_home_uses_the_standard_durable_location(self):
        with patch.dict(
            os.environ,
            {'XDG_STATE_HOME': 'relative-state'},
            clear=False,
        ):
            os.environ.pop('BARQ_BROWSER_INBOX_DIR', None)
            self.assertEqual(
                browser_inbox_dir(),
                Path.home() / '.local' / 'state' / 'barq' / 'inbox',
            )

    def _write_envelope(self, envelope):
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        envelope_path = self.inbox_dir / 'incoming.json'
        envelope_path.write_text(json.dumps(envelope), encoding='utf-8')


class TestBrowserDownloadContext(unittest.TestCase):
    def test_validated_context_reaches_head_and_range_probe(self):
        browser_request = parse_browser_envelope(_valid_envelope())
        downloader = ResilientDownloader(
            browser_request.url,
            '/tmp/browser-context-test.zip',
            request_headers=browser_request.request_headers,
            browser_context_url=browser_request.context_url,
        )
        recording_session = _RecordingSession()
        downloader.session = recording_session

        file_size, supports_range, _, _ = asyncio.run(downloader.get_file_info())

        self.assertEqual((file_size, supports_range), (4096, True))
        head_headers = recording_session.calls[0][2]
        probe_headers = recording_session.calls[1][2]
        self.assertEqual(head_headers['Authorization'], 'Bearer browser-secret')
        self.assertEqual(head_headers['Cookie'], 'session=browser-cookie')
        self.assertEqual(head_headers['Referer'], 'https://example.com/downloads')
        self.assertEqual(probe_headers['Range'], 'bytes=0-0')

    def test_cross_origin_final_url_drops_browser_context(self):
        envelope = _valid_envelope()
        envelope['request']['finalUrl'] = 'https://cdn.example.com/files/archive.zip'
        browser_request = parse_browser_envelope(envelope)
        downloader = ResilientDownloader(
            browser_request.url,
            '/tmp/browser-context-test.zip',
            request_headers=browser_request.request_headers,
            browser_context_url=browser_request.context_url,
        )
        recording_session = _RecordingSession()
        downloader.session = recording_session

        file_size, supports_range, _, _ = asyncio.run(downloader.get_file_info())

        self.assertEqual((file_size, supports_range), (4096, True))
        for _, request_url, headers in recording_session.calls:
            self.assertEqual(request_url, 'https://cdn.example.com/files/archive.zip')
            self.assertNotIn('Authorization', headers)
            self.assertNotIn('Cookie', headers)
            self.assertNotIn('Referer', headers)

    def test_cross_origin_redirect_drops_browser_context_after_the_first_hop(self):
        envelope = _valid_envelope()
        envelope['request'].pop('finalUrl')
        browser_request = parse_browser_envelope(envelope)
        downloader = ResilientDownloader(
            browser_request.url,
            '/tmp/browser-context-test.zip',
            request_headers=browser_request.request_headers,
            browser_context_url=browser_request.context_url,
        )
        recording_session = _RedirectRecordingSession()
        downloader.session = recording_session

        file_size, supports_range, _, _ = asyncio.run(downloader.get_file_info())

        self.assertEqual((file_size, supports_range), (4096, True))
        origin_calls = [call for call in recording_session.calls if call[1].startswith('https://example.com/')]
        redirected_calls = [call for call in recording_session.calls if call[1].startswith('https://cdn.example.com/')]
        self.assertEqual(len(origin_calls), 2)
        self.assertEqual(len(redirected_calls), 2)
        for _, _, headers in origin_calls:
            self.assertEqual(headers['Authorization'], 'Bearer browser-secret')
            self.assertEqual(headers['Cookie'], 'session=browser-cookie')
        for _, _, headers in redirected_calls:
            self.assertNotIn('Authorization', headers)
            self.assertNotIn('Cookie', headers)
            self.assertNotIn('Referer', headers)
