import asyncio
import aiohttp
import os
import time
import json
import hashlib
import errno
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Callable, Dict, List, Mapping
from urllib.parse import urljoin, urlsplit


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
NON_RANGE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MAX_BROWSER_REDIRECTS = 10
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CONTENT_RANGE_PATTERN = re.compile(r'^bytes (\d+)-(\d+)/(\d+)$')


class DownloadIntegrityError(RuntimeError):
    """Raised when a server response cannot safely complete the requested file."""


class RangeNotSupportedError(DownloadIntegrityError):
    """Raised when a server accepts a request but declines byte-range semantics."""


class DownloadExpiredError(RuntimeError):
    """Raised when a download URL can no longer be used."""


def _parse_content_range(content_range: object) -> tuple[int, int, int]:
    if not isinstance(content_range, str):
        raise DownloadIntegrityError('Missing Content-Range response header')

    match = _CONTENT_RANGE_PATTERN.fullmatch(content_range.strip())
    if match is None:
        raise DownloadIntegrityError('Malformed Content-Range response header')

    range_start, range_end, total_size = (int(value) for value in match.groups())
    if range_start > range_end or total_size <= range_end:
        raise DownloadIntegrityError('Invalid Content-Range response bounds')
    return range_start, range_end, total_size


def _is_strong_etag(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    return len(normalized) >= 2 and normalized.startswith('"') and normalized.endswith('"')


def _validate_content_range(
    content_range: object,
    requested_start: int,
    requested_end: int,
    expected_size: int,
) -> int:
    range_start, range_end, total_size = _parse_content_range(content_range)
    if range_start != requested_start or range_end != requested_end:
        raise DownloadIntegrityError('Content-Range did not match the requested byte range')
    if expected_size > 0 and total_size != expected_size:
        raise DownloadIntegrityError('Content-Range did not match the expected file size')
    return total_size


def _segments_cover_file(segments: object, file_size: int) -> bool:
    if (
        not isinstance(segments, list)
        or type(file_size) is not int
        or file_size <= 0
        or any(not isinstance(segment, dict) for segment in segments)
    ):
        return False

    expected_start = 0
    for segment in sorted(segments, key=lambda candidate: candidate.get('start', -1)):
        start = segment.get('start')
        end = segment.get('end')
        current = segment.get('current')
        completed = segment.get('done')
        if any(type(value) is not int for value in (start, end, current)):
            return False
        if type(completed) is not bool or start != expected_start or end < start:
            return False
        if current < start or current > end + 1:
            return False
        if completed and current != end + 1:
            return False
        if not completed and current > end:
            return False
        expected_start = end + 1

    return expected_start == file_size


def _sync_parent_directory(file_path: str) -> None:
    if os.name == 'nt' or not hasattr(os, 'O_DIRECTORY'):
        return
    directory_fd = os.open(os.path.dirname(os.path.abspath(file_path)), os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            os.fsync(directory_fd)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(directory_fd)


def _durably_replace_file(source_file: str, destination_file: str) -> None:
    with open(source_file, 'r+b') as source_handle:
        os.fsync(source_handle.fileno())
    os.replace(source_file, destination_file)
    _sync_parent_directory(destination_file)


class ResilientDownloader:
    """High-Throughput Resilient Multi-Segment Downloader with Smart Resume & Non-Range Stream Rescue."""
    
    def __init__(self, url: str, destination: str, parts: int = 16, 
                 max_retries: int = 10, connection_timeout: int = 30,
                 progress_callback: Optional[Callable[[int, int], None]] = None,
                 status_callback: Optional[Callable[[str], None]] = None,
                 speed_limiter=None,
                 request_headers: Optional[Mapping[str, str]] = None,
                 browser_context_url: Optional[str] = None):
        self.url = url
        self.parts = parts
        self.max_retries = max_retries
        self.connection_timeout = connection_timeout
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.speed_limiter = speed_limiter
        # Browser credentials are intentionally memory-only and never written to resume state.
        self.request_headers = dict(request_headers or {})
        self.browser_context_origin = (
            _request_origin(browser_context_url or url)
            if self.request_headers
            else None
        )

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

    def _request_headers(
        self,
        byte_range: Optional[str] = None,
        if_range: Optional[str] = None,
        default_user_agent: str = DEFAULT_USER_AGENT,
        target_url: Optional[str] = None,
    ) -> Dict[str, str]:
        headers = (
            dict(self.request_headers)
            if self._may_forward_browser_context(target_url or self.url)
            else {}
        )
        for header_name in tuple(headers):
            if header_name.lower() in {'range', 'if-range'}:
                del headers[header_name]
        headers.setdefault("User-Agent", default_user_agent)
        if byte_range:
            headers['Range'] = byte_range
        if if_range:
            headers['If-Range'] = if_range
        return headers

    def _may_forward_browser_context(self, target_url: str) -> bool:
        return (
            self.browser_context_origin is not None
            and self.browser_context_origin == _request_origin(target_url)
        )

    @asynccontextmanager
    async def _open_request(
        self,
        method: str,
        url: str,
        *,
        byte_range: Optional[str] = None,
        if_range: Optional[str] = None,
        default_user_agent: str = DEFAULT_USER_AGENT,
        timeout=None,
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        if self.session is None:
            raise RuntimeError("Download session is not available")

        request_url = url
        for _ in range(MAX_BROWSER_REDIRECTS + 1):
            response = await self.session.request(
                method,
                request_url,
                headers=self._request_headers(
                    byte_range,
                    if_range,
                    default_user_agent,
                    target_url=request_url,
                ),
                timeout=timeout,
                allow_redirects=False,
            )
            if response.status not in _REDIRECT_STATUSES:
                try:
                    yield response
                finally:
                    response.release()
                return

            location = response.headers.get('Location')
            response.release()
            if not location:
                raise RuntimeError("Redirect response did not contain a destination")
            request_url = _http_redirect_target(request_url, location)

        raise RuntimeError("Download exceeded the redirect limit")

    async def _load_state(self) -> bool:
        if not os.path.exists(self.state_file) or not os.path.exists(self.temp_file):
            return False

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)

            if not isinstance(state, dict):
                return False
            file_size = state.get('file_size')
            segments = state.get('segments')
            etag = state.get('etag')
            last_modified = state.get('last_modified')
            supports_range = state.get('supports_range')
            if (
                state.get('url') != self.url
                or not _segments_cover_file(segments, file_size)
                or not isinstance(etag, (str, type(None)))
                or not isinstance(last_modified, (str, type(None)))
                or type(supports_range) is not bool
            ):
                return False

            downloaded_bytes = sum(segment['current'] - segment['start'] for segment in segments)
            if state.get('downloaded_bytes') not in (None, downloaded_bytes):
                return False
            if os.path.getsize(self.temp_file) != file_size:
                print("Warning: Disk file size mismatch. Resetting state.")
                return False

            self.file_size = file_size
            self.segments = segments
            self.parts = len(segments)
            self.etag = etag
            self.last_modified = last_modified
            self.supports_range = supports_range
            self.downloaded_bytes = downloaded_bytes
            return True
        except (OSError, TypeError, ValueError) as error:
            print(f"Failed to load state: {error}")
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
            self._sync_temp_file()
            temp_state = self.state_file + ".tmp"
            with open(temp_state, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_state, self.state_file)
            _sync_parent_directory(self.state_file)
        except (OSError, TypeError, ValueError) as error:
            print(f"Failed to save state: {error}")

    def _sync_temp_file(self) -> None:
        if not os.path.exists(self.temp_file):
            return
        with open(self.temp_file, 'r+b') as temp_handle:
            os.fsync(temp_handle.fileno())

    def _resume_identity_matches(
        self,
        file_size: int,
        etag: Optional[str],
        last_modified: Optional[str],
    ) -> bool:
        if file_size != self.file_size or file_size <= 0:
            return False
        return _is_strong_etag(self.etag) and _is_strong_etag(etag) and etag == self.etag

    def _range_validator(self) -> Optional[str]:
        if _is_strong_etag(self.etag):
            return self.etag
        return None

    def _validate_response_identity(self, response_headers: Mapping[str, str]) -> None:
        if not _is_strong_etag(self.etag):
            return
        response_etag = response_headers.get('ETag')
        if not _is_strong_etag(response_etag) or response_etag != self.etag:
            raise DownloadIntegrityError('Response ETag changed or is missing during the download')

    async def get_file_info(self) -> tuple[int, bool, Optional[str], Optional[str]]:
        """Query server for Content-Length, Range support (206), ETag, and Last-Modified."""
        file_size = 0
        supports_range = False
        etag = None
        last_mod = None

        try:
            async with self._open_request('HEAD', self.url) as response:
                if response.status in [403, 410]:
                    raise DownloadExpiredError(f"Link Expired (HTTP {response.status})")
                if response.status == 200:
                    file_size = int(response.headers.get('Content-Length', 0))
                    etag = response.headers.get('ETag')
                    last_mod = response.headers.get('Last-Modified')
        except DownloadExpiredError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as error:
            print(f"HEAD request failed: {error}")

        try:
            async with self._open_request('GET', self.url, byte_range='bytes=0-0') as response:
                if response.status in [403, 410]:
                    raise DownloadExpiredError(f"Link Expired (HTTP {response.status})")
                if response.status == 206:
                    probed_size = _validate_content_range(
                        response.headers.get('Content-Range'),
                        requested_start=0,
                        requested_end=0,
                        expected_size=file_size,
                    )
                    file_size = probed_size
                    supports_range = True
                    if not etag: etag = response.headers.get('ETag')
                    if not last_mod: last_mod = response.headers.get('Last-Modified')
                elif response.status == 200:
                    if file_size == 0:
                        file_size = int(response.headers.get('Content-Length', 0))
                    if not etag: etag = response.headers.get('ETag')
                    if not last_mod: last_mod = response.headers.get('Last-Modified')
        except DownloadExpiredError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, DownloadIntegrityError) as error:
            print(f"Range probe failed: {error}")

        return file_size, supports_range, etag, last_mod

    def _verify_header_fingerprint(self, incoming_header_bytes: bytes) -> bool:
        """Verify the first 256KB fingerprint of incoming stream against local disk file."""
        if not os.path.exists(self.temp_file) or os.path.getsize(self.temp_file) < len(incoming_header_bytes):
            return False
            
        try:
            with open(self.temp_file, 'rb') as f:
                disk_header = f.read(len(incoming_header_bytes))
            return hashlib.sha256(disk_header).hexdigest() == hashlib.sha256(incoming_header_bytes).hexdigest()
        except OSError:
            return False

    async def download_non_range_stream(self):
        """Smart Fast-Drain Rescue Engine for servers that do NOT support Range HTTP 206."""
        loop = asyncio.get_running_loop()
        timeout = aiohttp.ClientTimeout(total=None, connect=self.connection_timeout, sock_read=self.connection_timeout * 2)
        
        async with self._open_request(
            'GET',
            self.url,
            default_user_agent=NON_RANGE_USER_AGENT,
            timeout=timeout,
        ) as response:
            if response.status in [403, 410]:
                self.status = "Expired"
                raise DownloadExpiredError(f"HTTP {response.status}: Link Expired")

            response.raise_for_status()
            self._validate_response_identity(response.headers)

            # Read first 256KB to check header fingerprint
            header_sample = b''
            async for chunk in response.content.iter_chunked(256 * 1024):
                header_sample += chunk
                if len(header_sample) >= 256 * 1024:
                    break

            if len(header_sample) > self.file_size:
                raise DownloadIntegrityError('Server returned more bytes than the expected file size')

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
                    raise DownloadIntegrityError('Non-range response ended before the resume position')
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

                if current_pos + len(chunk) > self.file_size:
                    raise DownloadIntegrityError('Server returned more bytes than the expected file size')

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

            if current_pos != self.file_size:
                raise DownloadIntegrityError('Non-range response ended before the expected file size')
            if self.segments:
                self.segments[0]['current'] = current_pos
                self.segments[0]['done'] = True
            self.downloaded_bytes = current_pos

    async def download_segment(self, segment: Dict):
        if segment['done']:
            return

        part_id = segment['id']
        start = segment['current']
        end = segment['end']
        
        retries = 0
        max_retries = self.max_retries
        base_delay = 1.0
        loop = asyncio.get_running_loop()
        
        def write_chunk(chunk_data, write_pos):
            with open(self.temp_file, 'r+b') as f:
                f.seek(write_pos)
                f.write(chunk_data)
                
        while retries < max_retries:
            if self._shutdown_event.is_set(): return
            
            start = segment['current']
            try:
                timeout = aiohttp.ClientTimeout(total=None, connect=self.connection_timeout, sock_read=self.connection_timeout * 2)
                range_validator = self._range_validator()
                async with self._open_request(
                    'GET',
                    self.url,
                    byte_range=f'bytes={start}-{end}',
                    if_range=range_validator,
                    timeout=timeout,
                ) as response:
                    if response.status in [403, 410]:
                        self.status = "Expired"
                        raise DownloadExpiredError(f"HTTP {response.status}: Link Expired")

                    if response.status == 200:
                        if range_validator:
                            self._validate_response_identity(response.headers)
                        raise RangeNotSupportedError('Server ignored the requested byte range')
                    if response.status != 206:
                        response.raise_for_status()
                        raise DownloadIntegrityError(
                            f'Unexpected status {response.status} for a byte-range response'
                        )

                    _validate_content_range(
                        response.headers.get('Content-Range'),
                        requested_start=start,
                        requested_end=end,
                        expected_size=self.file_size,
                    )
                    self._validate_response_identity(response.headers)
                    response.raise_for_status()

                    current_pos = start
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        if self._shutdown_event.is_set(): return

                        if current_pos + len(chunk) > end + 1:
                            raise DownloadIntegrityError(
                                'Byte-range response contained more data than requested'
                            )

                        if self.speed_limiter:
                            await self.speed_limiter.acquire(len(chunk))

                        await loop.run_in_executor(None, write_chunk, chunk, current_pos)
                        len_chunk = len(chunk)

                        async with self._lock:
                            segment['current'] = current_pos + len_chunk
                            self.downloaded_bytes = sum(s['current'] - s['start'] for s in self.segments)

                            if self.progress_callback:
                                self.progress_callback(self.downloaded_bytes, self.file_size)

                        current_pos += len_chunk

                    if current_pos != end + 1:
                        raise DownloadIntegrityError(
                            'Byte-range response ended before the requested byte range completed'
                        )
                    segment['done'] = True
                    return

            except (DownloadIntegrityError, DownloadExpiredError):
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
                retries += 1
                delay = min(base_delay * (2 ** retries), 30)
                print(f"Part {part_id} error: {error}. Retrying in {delay}s...")
                await asyncio.sleep(delay)

        raise Exception(f"Part {part_id} failed after {max_retries} retries")

    async def _download_segments_with_non_range_fallback(self) -> None:
        tasks = [
            asyncio.create_task(self.download_segment(segment))
            for segment in self.segments
            if not segment['done']
        ]
        try:
            await asyncio.gather(*tasks)
        except RangeNotSupportedError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.supports_range = False
            self.parts = 1
            self.segments = []
            self.downloaded_bytes = 0
            await self.download_non_range_stream()
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def start(self):
        if self._shutdown_event.is_set():
            self._shutdown_event = asyncio.Event()
        connector = aiohttp.TCPConnector(limit=self.parts + 5, ssl=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            self.session = session
            
            resuming = await self._load_state()
            file_size, supports_range, etag, last_mod = await self.get_file_info()
            
            if resuming and not self._resume_identity_matches(file_size, etag, last_mod):
                print("Server identity changed or cannot be verified. Resetting resume state...")
                resuming = False
                self.segments = []
                self.downloaded_bytes = 0

            if supports_range and not _is_strong_etag(etag):
                print("Server did not provide a strong ETag. Using a single safe stream.")
                supports_range = False

            if resuming:
                print("Resuming download from verified state file...")
                self.file_size = file_size
                self.supports_range = supports_range
                self.etag = etag
                self.last_modified = last_mod

            if resuming and not self.supports_range and len(self.segments) != 1:
                print("Server no longer permits a safe multi-part resume. Resetting resume state...")
                resuming = False
                self.segments = []
                self.downloaded_bytes = 0

            if not resuming:
                self.file_size = file_size
                self.supports_range = supports_range
                self.etag = etag
                self.last_modified = last_mod
                
                if self.file_size <= 0:
                    raise Exception("Could not determine file size.")
                
                if not self.supports_range:
                    self.parts = 1
                    
                self.parts = max(1, min(self.parts, self.file_size))
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
                    await self._download_segments_with_non_range_fallback()

                if self._shutdown_event.is_set():
                    if self.status == "Paused":
                        self._save_state()
                        return
                    raise asyncio.CancelledError()

                self.status = "Verifying"
                await self.finalize()
                
                self.status = "Completed"
                if os.path.exists(self.state_file):
                    try:
                        os.remove(self.state_file)
                    except OSError as error:
                        print(f"Completed download but could not remove resume state: {error}")
            except Exception as e:
                self.status = "Error"
                self.last_error = str(e)
                print(f"Download failed: {e}")
                self._save_state()
                raise
            finally:
                self._shutdown_event.set()
                await saver
                self.session = None

    async def finalize(self):
        if self.status_callback:
            self.status_callback("Verifying...")

        self._assert_complete_transfer()

        if self.expected_hash:
            algo, expected = self.expected_hash
            valid = await self._verify_hash(algo, expected)
            if not valid:
                raise Exception("Hash Mismatch! File corrupted.")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            _durably_replace_file,
            self.temp_file,
            self.destination,
        )

    def _assert_complete_transfer(self) -> None:
        if not _segments_cover_file(self.segments, self.file_size):
            raise DownloadIntegrityError('Download segment map is incomplete or invalid')
        if any(
            not segment['done'] or segment['current'] != segment['end'] + 1
            for segment in self.segments
        ):
            raise DownloadIntegrityError('Download did not complete every byte range')
        if self.downloaded_bytes != self.file_size:
            raise DownloadIntegrityError('Downloaded byte count does not match the expected file size')
        try:
            disk_size = os.path.getsize(self.temp_file)
        except OSError as error:
            raise DownloadIntegrityError('Temporary download file is unavailable') from error
        if disk_size != self.file_size:
            raise DownloadIntegrityError('Temporary download file size does not match the expected size')

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


def _request_origin(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        if scheme not in {'http', 'https'} or hostname is None:
            return None
        port = parsed.port or (443 if scheme == 'https' else 80)
    except ValueError:
        return None
    return scheme, hostname.lower(), port


def _http_redirect_target(source_url: str, location: str) -> str:
    try:
        target_url = urljoin(source_url, location)
        if _request_origin(target_url) is None:
            raise ValueError('redirect target must be HTTP or HTTPS')
    except ValueError as error:
        raise RuntimeError('Redirect response contained an invalid destination') from error
    return target_url
