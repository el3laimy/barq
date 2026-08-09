import asyncio
import io
import os
import sys
import unittest

# Unbuffered output if supported
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, io.UnsupportedOperation):
        pass

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from core.downloader import SegmentedDownloader

async def main():
    print("Debug: Main started", flush=True)
    
    # 1MB file for speed
    url = "http://speedtest.tele2.net/1MB.zip"
    dest = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'downloads', 'test_1MB.zip'))
    
    print(f"URL: {url}", flush=True)
    print(f"Dest: {dest}", flush=True)
    
    if os.path.exists(dest):
        try:
            os.remove(dest)
            print("Debug: Removed existing file", flush=True)
        except Exception as e:
            print(f"Debug: Failed to remove file: {e}", flush=True)

    def progress(current, total):
        # minimal output to avoid spamming buffer if that's the issue
        sys.stdout.write(".")
        sys.stdout.flush()

    print("Debug: Initializing downloader...", flush=True)
    downloader = SegmentedDownloader(url, dest, parts=4, progress_callback=progress)
    
    print("Debug: Starting download...", flush=True)
    try:
        await downloader.start()
        print("\nDebug: Download finished.", flush=True)
        
        if os.path.exists(dest):
            size = os.path.getsize(dest)
            print(f"File size: {size}", flush=True)
            if size > 0:
                print("SUCCESS: File downloaded.", flush=True)
            else:
                print("FAILURE: File is empty.", flush=True)
        else:
            print("FAILURE: File not found.", flush=True)
            
    except Exception as e:
        print(f"\nError in start: {e}", flush=True)
        import traceback
        traceback.print_exc()

class TestDownloaderV2ScriptImport(unittest.TestCase):
    def test_segmented_downloader_v2_importable(self):
        from core.downloader import SegmentedDownloader
        self.assertIsNotNone(SegmentedDownloader)


if __name__ == "__main__":
    print("Debug: Script entry", flush=True)
    # Use default event loop policy (Proactor on Windows usually)
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error in asyncio.run: {e}", flush=True)
