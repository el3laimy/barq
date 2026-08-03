import asyncio
import os
import sys

# Add src to path so we can import the downloader
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from core.downloader import SegmentedDownloader

async def main():
    # Use a 10MB test file for a quick but meaningful test
    url = "http://speedtest.tele2.net/10MB.zip"
    dest = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'downloads', 'test_10MB.zip'))
    
    print(f"Starting download test...")
    print(f"URL: {url}")
    print(f"Destination: {dest}")
    
    def progress(current, total):
        # precise progress bar
        percent = (current / total) * 100
        sys.stdout.write(f"\rProgress: {percent:.1f}% [{current}/{total}]")
        sys.stdout.flush()

    downloader = SegmentedDownloader(url, dest, parts=4, progress_callback=progress)
    
    try:
        await downloader.start()
        print("\nDownload finished.")
        
        # Verify file existence and size
        if os.path.exists(dest):
            size = os.path.getsize(dest)
            print(f"File exists. Size: {size} bytes")
            # 10MB = 10 * 1024 * 1024 = 10485760 bytes
            expected_size = 10 * 1024 * 1024
            if size == expected_size:
                 print("SUCCESS: File size matches expected 10MB.")
            else:
                 print(f"WARNING: File size {size} does not match expected {expected_size} (approx).")
        else:
            print("FAILURE: File not found.")
            
    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
