import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import asyncio
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
                'Content-Type': 'application/octet-stream'
            }
            return web.Response(body=self.dummy_data, status=200, headers=headers)

        app = web.Application()
        app.router.add_get('/nonrange_file.bin', handle_download)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 8899)
        await site.start()
        return runner

    def test_non_range_resume_rescue(self):
        async def _test():
            runner = await self.run_server()
            url = "http://127.0.0.1:8899/nonrange_file.bin"
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
                "supports_range": False,
                "segments": [{"id": 0, "start": 0, "end": len(self.dummy_data) - 1, "current": partial_len, "done": False}]
            }
            with open(state_file, 'w') as f:
                json.dump(state, f)
                
            # Now start downloader which should RESCUE via fingerprint + fast drain
            await downloader.start()
            
            self.assertTrue(os.path.exists(dest))
            self.assertEqual(os.path.getsize(dest), len(self.dummy_data))
            
            with open(dest, 'rb') as f:
                downloaded_content = f.read()
            self.assertEqual(downloaded_content, self.dummy_data)
            
            await runner.cleanup()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_test())
        loop.close()

if __name__ == '__main__':
    unittest.main()
