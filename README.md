# Titan Download Manager

![Titan Logo](icon.ico) <!-- If icon exists -->

Titan is a high-performance, resilient, and multi-segmented download manager for Windows. Built with Python and PyQt6, it offers a "Dark Glass" aesthetic combined with heavy-duty downloading capabilities.

## 🚀 Key Features

- **Multi-Segmented Downloading**: Split files into up to 32 parallel segments for maximum speed.
- **Resilient Engine**: Automatic retries with exponential backoff and state serialization (resume anything, anytime).
- **Dark Glass UI**: Modern, premium interface with real-time speed analytics.
- **Browser Integration**: Seamlessly intercept downloads from Google Chrome.
- **Smart Categorization**: Automatically organizes downloads into Video, Audio, Documents, etc.
- **Traffic Control**: Global speed limits and concurrent download management.

## 🛠 Installation

### 1. Standard Installation
Download and run the latest `TitanSetup.exe`. This will:
- Install Titan to your Program Files.
- Register the Native Messaging Host for browser integration.
- Create Desktop and Start Menu shortcuts.

### 2. Browser Integration (Chrome)
To intercept downloads from Chrome:
1.  Go to `chrome://extensions`.
2.  Enable **Developer Mode**.
3.  Click **Load unpacked** and select the `browser_integration/extension` folder (or install from the companion zip).
4.  Titan will now automatically take over downloads from your browser.

## ⚙️ Configuration

- **Default Download Path**: Change it in the **Settings** tab.
- **Speed Limits**: Set global limits to save bandwidth.
- **Concurrency**: Group downloads into a queue.

## 🏗 Developer Info

- **Language**: Python 3.10+
- **Framework**: PyQt6
- **Networking**: aiohttp, asyncio
- **Database**: SQLite3

### Building from source
```bash
pip install -r requirements.txt
python build.bat
# Then use NSIS to compile titan_installer.nsi
```

---
Developed with ❤️ by Titan Labs.
