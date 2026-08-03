import re
import urllib.parse
import urllib.request
import aiohttp
import asyncio

class URLResolver:
    """Smart Cloud & Web Link Grabber / Direct Download Resolver."""

    @classmethod
    def resolve_url(cls, url: str) -> str:
        """Synchronously converts common preview/share URLs to direct download links."""
        url_clean = url.strip()

        # 1. Google Drive (/file/d/FILE_ID/view or /open?id=FILE_ID)
        gdrive_match = re.search(r'drive\.google\.com/(?:file/d/|open\?id=)([a-zA-Z0-9_-]+)', url_clean)
        if gdrive_match:
            file_id = gdrive_match.group(1)
            return f"https://drive.google.com/uc?export=download&confirm=t&id={file_id}"

        # 2. Dropbox (dl=0 -> dl=1)
        if 'dropbox.com' in url_clean:
            if 'dl=0' in url_clean:
                return url_clean.replace('dl=0', 'dl=1')
            elif not 'dl=1' in url_clean:
                delimiter = '&' if '?' in url_clean else '?'
                return f"{url_clean}{delimiter}dl=1"

        # 3. Pixeldrain (pixeldrain.com/u/FILE_ID -> pixeldrain.com/api/file/FILE_ID)
        pixel_match = re.search(r'pixeldrain\.com/u/([a-zA-Z0-9_-]+)', url_clean)
        if pixel_match:
            file_id = pixel_match.group(1)
            return f"https://pixeldrain.com/api/file/{file_id}"

        # 4. OneDrive (embed/view -> download)
        if 'onedrive.live.com' in url_clean or '1drv.ms' in url_clean:
            if 'embed' in url_clean:
                return url_clean.replace('embed', 'download')

        return url_clean

    @classmethod
    async def resolve_url_async(cls, url: str) -> str:
        """Asynchronously resolves direct URLs, follows redirects, and handles MediaFire HTML parsing."""
        direct_url = cls.resolve_url(url)

        # Handle MediaFire page parsing
        if 'mediafire.com/file/' in direct_url:
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(direct_url) as resp:
                        html = await resp.text()
                        mf_match = re.search(r'href="([^"]+mediafire\.com/download/[^"]+)"', html)
                        if mf_match:
                            return mf_match.group(1)
            except Exception as e:
                print(f"MediaFire resolution error: {e}")

        return direct_url
