import sys
import os
import time

print("Debug: Script started", flush=True)
try:
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
    print(f"Debug: Adding src path: {src_path}", flush=True)
    sys.path.append(src_path)
    
    print("Debug: Importing SegmentedDownloader...", flush=True)
    from core.downloader import SegmentedDownloader
    print("Debug: Import successful", flush=True)
    
    print("Debug: Creating instance...", flush=True)
    d = SegmentedDownloader("http://example.com", "dummy")
    print("Debug: Instance created", flush=True)
    
except Exception as e:
    print(f"Debug: Error: {e}", flush=True)
