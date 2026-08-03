import asyncio
import aiohttp
import os
import time
from typing import Optional, Callable

class SegmentedDownloader:
    """
    High-performance async downloader that splits files into multiple segments.
    Uses aiohttp for concurrent downloads and standard file I/O.
    """
    def __init__(self, url: str, destination: str, parts: int = 32, 
                 progress_callback: Optional[Callable[[int, int], None]] = None):
        self.url = url
        self.destination = destination
        self.parts = parts
        self.progress_callback = progress_callback
        self.session: Optional[aiohttp.ClientSession] = None
        self.file_size = 0
        self.downloaded_bytes = 0
        self._lock = asyncio.Lock()

    async def get_file_info(self) -> int:
        """Fetch Content-Length and check server support."""
        try:
            async with self.session.head(self.url, allow_redirects=True) as response:
                if response.status == 200:
                    size = int(response.headers.get('Content-Length', 0))
                    if size > 0: return size
        except Exception as e:
            print(f"HEAD request failed: {e}")

        try:
            headers = {'Range': 'bytes=0-0'} 
            async with self.session.get(self.url, headers=headers, allow_redirects=True) as response:
                if response.status in [200, 206]:
                    content_range = response.headers.get('Content-Range')
                    if content_range:
                        return int(content_range.split('/')[-1])
                    return int(response.headers.get('Content-Length', 0))
        except Exception as e:
            print(f"GET check failed: {e}")
            
        return 0

    async def download_segment(self, start: int, end: int, part_id: int):
        """Download a specific byte range of the file."""
        headers = {'Range': f'bytes={start}-{end}'}
        retries = 3
        loop = asyncio.get_running_loop()
        
        def write_chunk(chunk_data, write_pos):
            with open(self.destination, 'r+b') as f:
                f.seek(write_pos)
                f.write(chunk_data)
                
        while retries > 0:
            try:
                timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)
                async with self.session.get(self.url, headers=headers, timeout=timeout) as response:
                    if response.status not in [200, 206]:
                        raise aiohttp.ClientError(f"HTTP {response.status}")
                        
                    if response.status != 206 and end - start + 1 < self.file_size:
                        raise aiohttp.ClientError("Server does not support partial content (HTTP 206 expected)")
                        
                    response.raise_for_status()
                    
                    current_pos = start
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        if not chunk:
                            break
                        
                        await loop.run_in_executor(None, write_chunk, chunk, current_pos)
                        current_pos += len(chunk)
                        
                        async with self._lock:
                            self.downloaded_bytes += len(chunk)
                            if self.progress_callback:
                                self.progress_callback(self.downloaded_bytes, self.file_size)
                    return
            except (aiohttp.ClientError, asyncio.TimeoutError, IOError) as e:
                print(f"Part {part_id} failed ({e}), retrying... ({retries} left)")
                retries -= 1
                await asyncio.sleep(1 * (4 - retries))
        
        raise Exception(f"Failed to download part {part_id} after multiple retries")

    async def start(self):
        """Main entry point to start the download."""
        connector = aiohttp.TCPConnector(limit=self.parts + 5, ssl=True)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            self.session = session
            
            self.file_size = await self.get_file_info()
            if self.file_size == 0:
                raise Exception("Could not determine file size or file is empty.")

            self.parts = min(self.parts, self.file_size)

            print(f"File Size: {self.file_size / (1024*1024):.2f} MB")

            os.makedirs(os.path.dirname(os.path.abspath(self.destination)), exist_ok=True)
            
            def preallocate():
                with open(self.destination, 'wb') as f:
                    f.seek(self.file_size - 1)
                    f.write(b'\0')
                    
            await asyncio.get_running_loop().run_in_executor(None, preallocate)
            
            chunk_size = self.file_size // self.parts
            tasks = []
            
            start_time = time.time()
            
            for i in range(self.parts):
                start = i * chunk_size
                end = start + chunk_size - 1 if i < self.parts - 1 else self.file_size - 1
                tasks.append(self.download_segment(start, end, i))
            
            await asyncio.gather(*tasks)
            
            duration = time.time() - start_time
            print(f"Download completed in {duration:.2f} seconds.")

if __name__ == "__main__":
    async def main():
        url = "http://speedtest.tele2.net/100MB.zip"
        dest = "downloads/test_100MB.zip"
        
        def progress(current, total):
            percent = (current / total) * 100
            print(f"\rProgress: {percent:.2f}%", end="")

        downloader = SegmentedDownloader(url, dest, parts=8, progress_callback=progress)
        await downloader.start()
        print("\nDone.")
