import asyncio
import aiohttp
import os
import time
import json
import hashlib
import shutil
from typing import Optional, Callable, Dict, List

class ResilientDownloader:
    """High-Throughput Resilient Multi-Segment Downloader with Smart Resume & Non-Range Stream Rescue."""
    
    def __init__(self, url: str, destination: str, parts: int = 16, 
                 progress_callback: Optional[Callable[[int, int], None]] = None,
                 status_callback: Optional[Callable[[str], None]] = None,
                 speed_limiter=None):
        self.url = url
        self.parts = parts
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.speed_limiter = speed_limiter

        # Ensure destination is a complete file path
        if os.path.isdir(destination):
            filename = os.path.basename(url.split('?')[0]) or "downloaded_file"
            self.destination = os.path.join(destination, filename)
        else:
            self.destination = destination
            
        self.temp_file = self.destination + ".part"
        self.state_file = f"{self.destination}.state.json"
        self.expected_hash = None
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.file_size = 0
        self.downloaded_bytes = 0
        self.etag = None
        self.last_modified = None
        self.supports_range = True
        
        self._lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        
        self.segments: List[Dict] = []
        self.status = "Pending"
        self.last_error = None

    async def _load_state(self) -> bool:
        if not os.path.exists(self.state_file) or not os.path.exists(self.temp_file):
            return False
            
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                
            self.file_size = state.get('file_size', 0)
            self.segments = state.get('segments', [])
            self.parts = len(self.segments)
            self.etag = state.get('etag')
            self.last_modified = state.get('last_modified')
            self.supports_range = state.get('supports_range', True)
            
            # Recalculate downloaded bytes from segments
            self.downloaded_bytes = sum(seg['current'] - seg['start'] for seg in self.segments)
            
            disk_size = os.path.getsize(self.temp_file)
            if self.file_size > 0 and disk_size != self.file_size:
                print("Warning: Disk file size mismatch. Resetting state.")
                return False
                
            return True
        except Exception as e:
            print(f"Failed to load state: {e}")
            return False

    def _save_state(self):
        state = {
            "url": self.url,
            "file_size": self.file_size,
            "downloaded_bytes": self.downloaded_bytes,
            "status": self.status,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "supports_range": self.supports_range,
            "segments": self.segments,
            "last_updated": time.time()
        }
        try:
            temp_state = self.state_file + ".tmp"
            with open(temp_state, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            os.replace(temp_state, self.state_file)
        except Exception as e:
            print(f"Failed to save state: {e}")

    async def get_file_info(self) -> tuple[int, bool, Optional[str], Optional[str]]:
        """Query server for Content-Length, Range support (206), ETag, and Last-Modified."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        file_size = 0
        supports_range = False
        etag = None
        last_mod = None

        try:
            async with self.session.head(self.url, headers=headers, allow_redirects=True) as response:
                if response.status in [403, 410]:
                    raise Exception(f"Link Expired (HTTP {response.status})")
                if response.status == 200:
                    file_size = int(response.headers.get('Content-Length', 0))
                    etag = response.headers.get('ETag')
                    last_mod = response.headers.get('Last-Modified')
                    if response.headers.get('Accept-Ranges') == 'bytes':
                        supports_range = True
        except Exception:
            pass

        try:
            headers['Range'] = 'bytes=0-0'
            async with self.session.get(self.url, headers=headers, allow_redirects=True) as response:
                if response.status in [403, 410]:
                    raise Exception(f"Link Expired (HTTP {response.status})")
                if response.status == 206:
                    supports_range = True
                    content_range = response.headers.get('Content-Range')
                    if content_range:
                        file_size = int(content_range.split('/')[-1])
                    if not etag: etag = response.headers.get('ETag')
                    if not last_mod: last_mod = response.headers.get('Last-Modified')
                elif response.status == 200 and file_size == 0:
                    file_size = int(response.headers.get('Content-Length', 0))
        except Exception as e:
            if "Expired" in str(e): raise

        return file_size, supports_range, etag, last_mod

    def _verify_header_fingerprint(self, incoming_header_bytes: bytes) -> bool:
        """Verify the first 256KB fingerprint of incoming stream against local disk file."""
        if not os.path.exists(self.temp_file) or os.path.getsize(self.temp_file) < len(incoming_header_bytes):
            return False
            
        try:
            with open(self.temp_file, 'rb') as f:
                disk_header = f.read(len(incoming_header_bytes))
            return hashlib.md5(disk_header).hexdigest() == hashlib.md5(incoming_header_bytes).hexdigest()
        except Exception:
            return False

    async def download_non_range_stream(self):
        """Smart Fast-Drain Rescue Engine for servers that do NOT support Range HTTP 206."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        loop = asyncio.get_running_loop()
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)
        
        async with self.session.get(self.url, headers=headers, timeout=timeout) as response:
            if response.status in [403, 410]:
                self.status = "Expired"
                raise Exception(f"HTTP {response.status}: Link Expired")
                
            response.raise_for_status()
            
            # Read first 256KB to check header fingerprint
            header_sample = b''
            async for chunk in response.content.iter_chunked(256 * 1024):
                header_sample += chunk
                if len(header_sample) >= 256 * 1024:
                    break

            previous_downloaded = self.segments[0]['current'] if self.segments else 0
            
            # Fingerprint check
            if previous_downloaded > 0 and self._verify_header_fingerprint(header_sample):
                print(f"✅ Header Fingerprint Matched! Fast-Draining stream to byte {previous_downloaded}...")
                current_pos = len(header_sample)
            else:
                print("Header fingerprint fresh/different. Starting stream from byte 0...")
                current_pos = 0
                previous_downloaded = 0
                # Write header sample to disk start
                with open(self.temp_file, 'wb') as f:
                    f.write(header_sample)
                current_pos = len(header_sample)
                self.downloaded_bytes = current_pos
                self.segments = [{"id": 0, "start": 0, "end": self.file_size - 1, "current": current_pos, "done": False}]

            # Fast-Drain loop until we reach previous_downloaded
            while current_pos < previous_downloaded:
                if self._shutdown_event.is_set(): return
                needed = min(1024 * 1024, previous_downloaded - current_pos)
                drain_chunk = await response.content.read(needed)
                if not drain_chunk:
                    break
                current_pos += len(drain_chunk)

            # Stream remaining bytes and write to disk
            def append_chunk(chunk_data, pos):
                with open(self.temp_file, 'r+b') as f:
                    f.seek(pos)
                    f.write(chunk_data)

            while True:
                if self._shutdown_event.is_set(): return
                chunk = await response.content.read(1024 * 1024)
                if not chunk:
                    break
                    
                if self.speed_limiter:
                    await self.speed_limiter.acquire(len(chunk))
                    
                await loop.run_in_executor(None, append_chunk, chunk, current_pos)
                len_chunk = len(chunk)
                current_pos += len_chunk
                
                async with self._lock:
                    self.downloaded_bytes = current_pos
                    if self.segments: self.segments[0]['current'] = current_pos
                    if self.progress_callback:
                        self.progress_callback(self.downloaded_bytes, self.file_size)

            if self.segments: self.segments[0]['done'] = True

    async def download_segment(self, segment: Dict):
        if segment['done']:
            return

        part_id = segment['id']
        start = segment['current']
        end = segment['end']
        
        headers = {
            'Range': f'bytes={start}-{end}',
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        retries = 0
        max_retries = 10
        base_delay = 1.0
        loop = asyncio.get_running_loop()
        
        def write_chunk(chunk_data, write_pos):
            with open(self.temp_file, 'r+b') as f:
                f.seek(write_pos)
                f.write(chunk_data)
                
        while retries < max_retries:
            if self._shutdown_event.is_set(): return
            
            start = segment['current']
            headers['Range'] = f'bytes={start}-{end}'

            try:
                timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)
                async with self.session.get(self.url, headers=headers, timeout=timeout) as response:
                    if response.status in [403, 410]:
                        self.status = "Expired"
                        raise Exception(f"HTTP {response.status}: Link Expired")
                        
                    response.raise_for_status()
                    
                    current_pos = start
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        if self._shutdown_event.is_set(): return
                        
                        if self.speed_limiter:
                            await self.speed_limiter.acquire(len(chunk))
                            
                        await loop.run_in_executor(None, write_chunk, chunk, current_pos)
                        len_chunk = len(chunk)
                        
                        async with self._lock:
                            segment['current'] += len_chunk
                            self.downloaded_bytes = sum(s['current'] - s['start'] for s in self.segments)
                            
                            if self.progress_callback:
                                self.progress_callback(self.downloaded_bytes, self.file_size)
                                
                        current_pos += len_chunk
                        
                    segment['done'] = True
                    return

            except Exception as e:
                if "Link Expired" in str(e):
                    raise
                    
                retries += 1
                delay = min(base_delay * (2 ** retries), 30)
                print(f"Part {part_id} error: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)

        raise Exception(f"Part {part_id} failed after {max_retries} retries")

    async def start(self):
        connector = aiohttp.TCPConnector(limit=self.parts + 5, ssl=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            self.session = session
            
            resuming = await self._load_state()
            file_size, supports_range, etag, last_mod = await self.get_file_info()
            
            if resuming:
                if file_size > 0 and self.file_size > 0 and file_size != self.file_size:
                    print("Server file size changed! Resetting resume state...")
                    resuming = False
                else:
                    print("Resuming download from state file...")
                    
            if not resuming:
                self.file_size = file_size
                self.supports_range = supports_range
                self.etag = etag
                self.last_modified = last_mod
                
                if self.file_size == 0:
                    raise Exception("Could not determine file size.")
                
                if not self.supports_range:
                    self.parts = 1
                    
                self.parts = min(self.parts, self.file_size)
                os.makedirs(os.path.dirname(os.path.abspath(self.temp_file)), exist_ok=True)
                
                def preallocate():
                    if hasattr(os, 'statvfs'):
                        st = os.statvfs(os.path.dirname(os.path.abspath(self.temp_file)))
                        free_space = st.f_bavail * st.f_frsize
                        if free_space < self.file_size:
                            raise Exception("Not enough disk space available.")
                    with open(self.temp_file, 'wb') as f:
                        f.seek(self.file_size - 1)
                        f.write(b'\0')
                        
                await asyncio.get_running_loop().run_in_executor(None, preallocate)
                
                chunk_size = self.file_size // self.parts
                self.segments = []
                for i in range(self.parts):
                    start = i * chunk_size
                    end = start + chunk_size - 1 if i < self.parts - 1 else self.file_size - 1
                    self.segments.append({
                        "id": i, "start": start, "end": end, 
                        "current": start, "done": False
                    })
                self.downloaded_bytes = 0

            if self.progress_callback:
                self.progress_callback(self.downloaded_bytes, self.file_size)

            saver = asyncio.create_task(self._auto_save())
            
            try:
                self.status = "Downloading"
                if not self.supports_range:
                    await self.download_non_range_stream()
                else:
                    tasks = [self.download_segment(seg) for seg in self.segments if not seg['done']]
                    await asyncio.gather(*tasks)
                    
                self.status = "Verifying"
                await self.finalize()
                
                self.status = "Completed"
                if os.path.exists(self.state_file):
                    os.remove(self.state_file)
            except Exception as e:
                self.status = "Error"
                self.last_error = str(e)
                print(f"Download failed: {e}")
                self._save_state()
                raise
            finally:
                self._shutdown_event.set()
                await saver

    async def finalize(self):
        if self.status_callback:
            self.status_callback("Verifying...")
            
        if self.expected_hash:
            algo, expected = self.expected_hash
            valid = await self._verify_hash(algo, expected)
            if not valid:
                raise Exception("Hash Mismatch! File corrupted.")
        
        loop = asyncio.get_running_loop()
        def atomic_rename():
            if os.path.isdir(self.destination):
                filename = os.path.basename(self.url.split('?')[0]) or "downloaded_file"
                self.destination = os.path.join(self.destination, filename)
            if os.path.exists(self.destination) and not os.path.isdir(self.destination):
                os.remove(self.destination)
            shutil.move(self.temp_file, self.destination)
        await loop.run_in_executor(None, atomic_rename)

    async def _verify_hash(self, algo, expected):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._calc_hash_sync, algo, expected)

    def _calc_hash_sync(self, algo, expected):
        h = hashlib.new(algo)
        with open(self.temp_file, 'rb') as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return h.hexdigest().lower() == expected.lower()

    def set_hash(self, algo, hash_value):
        self.expected_hash = (algo, hash_value)

    def pause(self):
        self.status = "Paused"
        self._shutdown_event.set()

    async def _auto_save(self):
        while not self._shutdown_event.is_set():
            self._save_state()
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    def update_url(self, new_url):
        self.url = new_url
        self._save_state()
