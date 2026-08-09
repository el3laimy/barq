import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from core.resilient_downloader import (
    DownloadIntegrityError,
    RangeNotSupportedError,
    ResilientDownloader,
    _durably_replace_file,
)


class _MemoryContent:
    def __init__(self, data: bytes):
        self._data = data
        self._position = 0

    async def iter_chunked(self, chunk_size: int):
        while self._position < len(self._data):
            next_position = min(self._position + chunk_size, len(self._data))
            chunk = self._data[self._position:next_position]
            self._position = next_position
            yield chunk

    async def read(self, chunk_size: int = -1) -> bytes:
        if self._position >= len(self._data):
            return b''
        if chunk_size < 0:
            chunk_size = len(self._data) - self._position
        next_position = min(self._position + chunk_size, len(self._data))
        chunk = self._data[self._position:next_position]
        self._position = next_position
        return chunk


class _MemoryResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.content = _MemoryContent(body)
        self.released = False

    def raise_for_status(self) -> None:
        if not 200 <= self.status < 300:
            raise RuntimeError(f'Unexpected test HTTP status: {self.status}')

    def release(self) -> None:
        self.released = True


class _SingleResponseSession:
    def __init__(self, response: _MemoryResponse):
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    async def request(self, method, url, *, headers, timeout, allow_redirects):
        self.calls.append((method, url, dict(headers)))
        return self.response


class TestResilientDownloaderIntegrity(unittest.TestCase):
    def _run_async(self, coroutine):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coroutine)
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def _segment_downloader(self, directory: str, size: int = 4):
        destination = os.path.join(directory, 'download.bin')
        temp_file = destination + '.part'
        with open(temp_file, 'wb') as output:
            output.write(b'\0' * size)

        downloader = ResilientDownloader('https://example.test/download.bin', destination, parts=1)
        downloader.file_size = size
        downloader.segments = [
            {'id': 0, 'start': 0, 'end': size - 1, 'current': 0, 'done': False}
        ]
        return downloader, Path(destination)

    def test_ignored_range_response_switches_to_non_range_instead_of_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            downloader.etag = '"version-one"'
            response = _MemoryResponse(200, {
                'Content-Length': '4',
                'ETag': '"version-one"',
            }, b'data')
            session = _SingleResponseSession(response)
            downloader.session = session

            with self.assertRaises(RangeNotSupportedError):
                self._run_async(downloader.download_segment(downloader.segments[0]))

            self.assertEqual(destination.with_suffix('.bin.part').read_bytes(), b'\0' * 4)
            self.assertEqual(downloader.segments[0]['current'], 0)
            self.assertFalse(downloader.segments[0]['done'])
            self.assertEqual(session.calls[0][2]['If-Range'], '"version-one"')
            self.assertTrue(response.released)

    def test_mismatched_content_range_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            response = _MemoryResponse(206, {'Content-Range': 'bytes 1-3/4'}, b'ata')
            downloader.session = _SingleResponseSession(response)

            with self.assertRaisesRegex(DownloadIntegrityError, 'did not match'):
                self._run_async(downloader.download_segment(downloader.segments[0]))

            self.assertEqual(destination.with_suffix('.bin.part').read_bytes(), b'\0' * 4)
            self.assertFalse(downloader.segments[0]['done'])

    def test_range_validator_blocks_changed_resource_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            downloader.etag = '"version-one"'
            response = _MemoryResponse(206, {
                'Content-Range': 'bytes 0-3/4',
                'ETag': '"version-two"',
            }, b'data')
            session = _SingleResponseSession(response)
            downloader.session = session

            with self.assertRaisesRegex(DownloadIntegrityError, 'ETag changed'):
                self._run_async(downloader.download_segment(downloader.segments[0]))

            self.assertEqual(session.calls[0][2]['If-Range'], '"version-one"')
            self.assertEqual(destination.with_suffix('.bin.part').read_bytes(), b'\0' * 4)
            self.assertFalse(downloader.segments[0]['done'])

    def test_resume_requires_an_unchanged_strong_validator(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, 'download.bin')
            temp_file = destination + '.part'
            state_file = destination + '.state.json'
            with open(temp_file, 'wb') as output:
                output.write(b'\0' * 4)
            with open(state_file, 'w', encoding='utf-8') as output:
                json.dump(
                    {
                        'url': 'https://example.test/download.bin',
                        'file_size': 4,
                        'downloaded_bytes': 2,
                        'etag': '"version-one"',
                        'last_modified': None,
                        'supports_range': True,
                        'segments': [
                            {'id': 0, 'start': 0, 'end': 3, 'current': 2, 'done': False}
                        ],
                    },
                    output,
                )

            downloader = ResilientDownloader('https://example.test/download.bin', destination)

            self.assertTrue(self._run_async(downloader._load_state()))
            self.assertTrue(downloader._resume_identity_matches(4, '"version-one"', None))
            self.assertFalse(downloader._resume_identity_matches(4, '"version-two"', None))
            self.assertFalse(downloader._resume_identity_matches(4, None, None))
            downloader.etag = 'W/"version-one"'
            downloader.last_modified = None
            self.assertFalse(downloader._resume_identity_matches(4, 'W/"version-one"', None))

    def test_premature_range_eof_never_marks_the_segment_done(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            response = _MemoryResponse(206, {'Content-Range': 'bytes 0-3/4'}, b'')
            downloader.session = _SingleResponseSession(response)

            with self.assertRaisesRegex(DownloadIntegrityError, 'ended before'):
                self._run_async(downloader.download_segment(downloader.segments[0]))

            self.assertEqual(destination.with_suffix('.bin.part').read_bytes(), b'\0' * 4)
            self.assertEqual(downloader.segments[0]['current'], 0)
            self.assertFalse(downloader.segments[0]['done'])

    def test_premature_non_range_eof_never_marks_the_segment_done(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            response = _MemoryResponse(200, {'Content-Length': '4'}, b'da')
            downloader.session = _SingleResponseSession(response)

            with self.assertRaisesRegex(DownloadIntegrityError, 'ended before'):
                self._run_async(downloader.download_non_range_stream())

            self.assertEqual(destination.with_suffix('.bin.part').read_bytes()[:2], b'da')
            self.assertEqual(downloader.segments[0]['current'], 2)
            self.assertFalse(downloader.segments[0]['done'])

    def test_resumed_non_range_stream_requires_the_matching_etag_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            downloader.etag = '"version-one"'
            response = _MemoryResponse(200, {'Content-Length': '4'}, b'data')
            downloader.session = _SingleResponseSession(response)

            with self.assertRaisesRegex(DownloadIntegrityError, 'missing'):
                self._run_async(downloader.download_non_range_stream())

            self.assertEqual(destination.with_suffix('.bin.part').read_bytes(), b'\0' * 4)
            self.assertEqual(downloader.segments[0]['current'], 0)
            self.assertFalse(downloader.segments[0]['done'])

    def test_incomplete_transfer_cannot_replace_an_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            destination.write_bytes(b'previous')
            downloader.segments[0]['current'] = 2
            downloader.downloaded_bytes = 2

            with self.assertRaisesRegex(DownloadIntegrityError, 'complete'):
                self._run_async(downloader.finalize())

            self.assertEqual(destination.read_bytes(), b'previous')
            self.assertTrue(Path(downloader.temp_file).exists())

    def test_verified_transfer_atomically_replaces_an_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader, destination = self._segment_downloader(directory)
            destination.write_bytes(b'previous')
            Path(downloader.temp_file).write_bytes(b'data')
            downloader.segments[0]['current'] = 4
            downloader.segments[0]['done'] = True
            downloader.downloaded_bytes = 4

            downloader._assert_complete_transfer()
            _durably_replace_file(downloader.temp_file, downloader.destination)

            self.assertEqual(destination.read_bytes(), b'data')
            self.assertFalse(Path(downloader.temp_file).exists())


if __name__ == '__main__':
    unittest.main()
