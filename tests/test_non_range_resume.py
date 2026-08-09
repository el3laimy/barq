import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import asyncio
import socket
import shutil
import unittest
from aiohttp import web
from core.resilient_downloader import ResilientDownloader

class TestNonRangeResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = "/tmp/barq_non_range_test"
        os.makedirs(cls.test_dir, exist_ok=True)
        cls.dummy_data = b"BARQ_HEADER_FINGERPRINT_" + b"X" * (1024 * 1024 * 2) # 2MB dummy payload

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)

    async def run_server(self):
        async def handle_download(request):
            # Non-range server: Always returns 200 OK with full content, ignores Range header
            headers = {
                'Content-Length': str(len(self.dummy_data)),
                'Content-Type': 'application/octet-stream',
                'ETag': '"nonrange-v1"',
            }
            return web.Response(body=self.dummy_data, status=200, headers=headers)

        app = web.Application()
        app.router.add_get('/nonrange_file.bin', handle_download)
        runner = web.AppRunner(app)
        await runner.setup()
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(('127.0.0.1', 0))
        server_socket.listen()
        site = web.SockSite(runner, server_socket)
        await site.start()
        return runner, server_socket.getsockname()[1]

    def test_non_range_resume_rescue(self):
        async def _test():
            runner, port = await self.run_server()
            try:
                url = f"http://127.0.0.1:{port}/nonrange_file.bin"
                dest = os.path.join(self.test_dir, "nonrange_file.bin")

                downloader = ResilientDownloader(url, dest, parts=1)

                # Simulate initial 1MB partial download on disk
                temp_file = dest + ".part"
                state_file = dest + ".state.json"

                partial_len = 1024 * 1024 # 1MB
                with open(temp_file, 'wb') as f:
                    f.write(self.dummy_data[:partial_len])
                    f.seek(len(self.dummy_data) - 1)
                    f.write(b'\0')

                import json
                state = {
                    "url": url,
                    "file_size": len(self.dummy_data),
                    "downloaded_bytes": partial_len,
                    "status": "Paused",
                    "etag": '"nonrange-v1"',
                    "supports_range": False,
                    "segments": [{"id": 0, "start": 0, "end": len(self.dummy_data) - 1, "current": partial_len, "done": False}]
                }
                with open(state_file, 'w') as f:
                    json.dump(state, f)

                # A matching validator permits the fingerprint + fast-drain rescue path.
                await downloader.start()

                self.assertTrue(os.path.exists(dest))
                self.assertEqual(os.path.getsize(dest), len(self.dummy_data))

                with open(dest, 'rb') as f:
                    downloaded_content = f.read()
                self.assertEqual(downloaded_content, self.dummy_data)
            finally:
                await runner.cleanup()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_test())
        loop.close()

    def test_range_server_without_strong_etag_uses_one_safe_stream(self):
        async def _test():
            requested_ranges = []
            data = b"safe single stream without a strong validator"

            async def handle_download(request):
                requested_range = request.headers.get('Range')
                requested_ranges.append(requested_range)
                headers = {
                    'Content-Length': str(len(data)),
                    'Accept-Ranges': 'bytes',
                    'Content-Type': 'application/octet-stream',
                }
                if requested_range == 'bytes=0-0':
                    headers['Content-Range'] = f'bytes 0-0/{len(data)}'
                    headers['Content-Length'] = '1'
                    return web.Response(body=data[:1], status=206, headers=headers)
                return web.Response(body=data, status=200, headers=headers)

            app = web.Application()
            app.router.add_get('/range_file.bin', handle_download)
            runner = web.AppRunner(app)
            await runner.setup()
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.bind(('127.0.0.1', 0))
            server_socket.listen()
            site = web.SockSite(runner, server_socket)
            await site.start()

            try:
                url = f"http://127.0.0.1:{server_socket.getsockname()[1]}/range_file.bin"
                destination = os.path.join(self.test_dir, "range_file.bin")
                await ResilientDownloader(url, destination, parts=4).start()

                with open(destination, 'rb') as output:
                    self.assertEqual(output.read(), data)
                self.assertEqual(requested_ranges, [None, 'bytes=0-0', None])
            finally:
                await runner.cleanup()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_test())
        loop.close()

if __name__ == '__main__':
    unittest.main()
