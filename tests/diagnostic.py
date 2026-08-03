print("Diagnostic: Hello World")
import sys
print(f"Python version: {sys.version}")
try:
    import aiohttp
    print(f"aiohttp imported: {aiohttp.__version__}")
except ImportError:
    print("aiohttp not found")
except Exception as e:
    print(f"Error importing aiohttp: {e}")
