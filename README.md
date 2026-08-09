# ⚡ Barq Download Manager

> **Barq** is a modern, open-source download manager designed for fast parallel downloads, media handling, smart link resolution, and resilient download recovery.

![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)
![UI Framework](https://img.shields.io/badge/GUI-PyQt6-cyan.svg)

---

## 📌 Development Status Notice
Barq Download Manager is actively under development. Core multi-segment HTTP/HTTPS acceleration, resilient stream recovery, and video link extraction are under active verification.

---

## ✨ Features

### Implemented Features
- **⚡ Multi-Segment Download Engine**: Dynamic chunk allocation with up to 32 parallel HTTP/HTTPS connections per file.
- **🛡️ Resilient Recovery & Resume**: Resume is enabled only when a server supplies the same strong ETag; otherwise Barq safely starts a single stream from the beginning.
- **🎥 Media & Video Extraction Engine**: Integrated video stream detection powered by `yt-dlp` and `ffmpeg`.
- **🔌 Inter-Process Communication (IPC)**: Local TCP socket server (`19375`) allowing single-instance URL dispatch.
- **🎨 Dark Glass UI Theme**: High-contrast PyQt6 user interface with real-time speed graphs (`pyqtgraph`).
- **💾 Local SQLite Telemetry**: Persistent SQLite database storage for download state, history, and category organization.

### Planned & Experimental Features
- **🌐 Secure Browser Integration**: Source implementation of the `app.barq.browser` native-host and browser extension, under integration testing.
- **🔄 Bandwidth Scheduling & Speed Limit Rules**: Dynamic time-based bandwidth capping.

---

## 🖼️ Screenshots

*UI screenshots will be updated with upcoming production releases.*

---

## 🖥️ Supported Operating Systems

- **Windows**: Windows 10 / 11 (64-bit) — packaging definitions are present; signed-release validation is pending.
- **Linux**: Ubuntu / Debian / Fedora / Arch Linux — source-runtime validation is ongoing.

- **macOS**: *Planned following Windows & Linux stabilization*.

---

## 🚀 Running from Source

### Prerequisites
- Python 3.10 or higher
- `ffmpeg` is resolved through `imageio-ffmpeg` when available; an external installation may still be needed for some media workflows.

### Quickstart

1. **Clone the repository**:
   ```bash
   git clone https://github.com/el3laimy/barq.git
   cd barq
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate    # On Linux / macOS
   # .venv\Scripts\activate     # On Windows (PowerShell / CMD)
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the application**:
   ```bash
   python barq_app.py
   ```

---

## 📦 Building Executables & Installers

### Windows Build Instructions

1. Install development dependencies:
   ```cmd
   pip install -r requirements-dev.txt
   ```

2. Run the Windows build script in Command Prompt or PowerShell:
   ```cmd
   build.bat
   ```
   *In PowerShell:*
   ```powershell
   .\build.bat
   ```

3. Compile the standalone installer (requires [NSIS](https://nsis.sourceforge.io/)):
   Right-click `barq_installer.nsi` and select **Compile NSIS Script** to generate `BarqSetup_v1.0.0.exe`.

### Linux Build Instructions

1. Ensure build tools and dependencies are installed:
   ```bash
   pip install -r requirements-dev.txt
   ```

2. Run the Linux build script:
   ```bash
   chmod +x build_linux.sh
   ./build_linux.sh
   ```
   The standalone executable will be located in `dist/BarqDownloader/barq_app`.

---

## 🌐 Browser Integration

The retired Python browser bridge is not bundled or registered by current desktop builds. At startup, Barq removes only verified `com.barq.downloader` manifests at known legacy locations and, on Windows, only the matching per-user host keys. If Barq reports that it removed one, manually disable or remove **Barq Download Manager Integration** from the browser's Extensions page before starting browser downloads; Barq does not modify browser extensions automatically. The secure `app.barq.browser` source is not yet included in a signed installer or browser-store package; setup instructions will be published with those artifacts.

---

## 🛠️ Project Structure

```
barq/
├── barq_app.py                 # Application Entry Point
├── barq_installer.nsi          # NSIS Installer Script for Windows
├── build.bat                   # Windows PyInstaller packaging script
├── build_linux.sh              # Linux PyInstaller packaging script
├── build_executable.spec       # PyInstaller Spec configuration
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt        # Development dependencies
├── src/
│   ├── core/                   # Downloader logic, database, IPC, settings, & constants
│   │   ├── constants.py        # Centralized application metadata
│   │   ├── database.py         # SQLite download database manager
│   │   ├── downloader.py       # Basic segmented downloader
│   │   ├── ipc_server.py       # Local TCP IPC server
│   │   ├── resilient_downloader.py # Resilient multi-part downloader engine
│   │   ├── settings.py         # App settings manager
│   │   ├── url_resolver.py     # Link and media stream resolver
│   │   └── video_engine.py     # Video extraction via yt-dlp
│   └── ui/                     # PyQt6 User Interface components
│       ├── main_window.py      # Main Application Window
│       ├── sidebar.py          # Custom vector sidebar navigation
│       ├── dashboard_page.py   # Telemetry & speed graphs
│       ├── downloads_page.py   # Main downloads manager hub
│       └── styles.py           # Dark Glass theme stylesheet
└── tests/                      # Automated test suite
```

---

## ⚠️ Known Limitations

- **Browser Integration Packaging**: Signed installer and browser-store artifacts for the secure integration are not available yet.
- **Server Side Limits**: Download acceleration depends on remote server support for HTTP `Range` requests.

---

## 🎨 Icon Cache Cleanup & Troubleshooting

If the taskbar or dock displays a generic icon after building or updating:

### On Windows
1. Unpin any old Barq shortcuts from the taskbar.
2. Delete previous installer shortcuts from Desktop / Start Menu.
3. Clean build: `pyinstaller --clean --noconfirm build_executable.spec`
4. Reinstall using `BarqSetup_v1.0.0.exe` or run `dist/Barq.exe`.
5. Pin the newly launched app to the taskbar.
6. If Windows icon cache persists, restart Windows Explorer:
   ```cmd
   taskkill /f /im explorer.exe
   start explorer.exe
   ```

### On Linux (GNOME / KDE / X11 / Wayland)
1. Build the executable: `./build_linux.sh`
2. Install system-wide desktop integration and icon:
   ```bash
   sudo ./install_linux.sh
   ```
3. Launch from the applications menu or via `gtk-launch barq`.
4. If using Wayland / GNOME Dock, unpin old launcher and re-pin the new **Barq** launcher from the Applications menu.

> **Note**: Running `./dist/Barq` directly from a terminal without running `./install_linux.sh` may prevent GNOME/KDE from matching the running process to the system `.desktop` launcher.

### Debugging Icon Loading
Enable diagnostic logging by setting `BARQ_DEBUG_ICON=1`:
```bash
BARQ_DEBUG_ICON=1 python3 barq_app.py
```
```bash
BARQ_DEBUG_ICON=1 ./dist/Barq
```
```cmd
set BARQ_DEBUG_ICON=1
dist\Barq.exe
```

---

## ⚖️ Security and Legal Notice

Barq Download Manager is a general-purpose download tool intended for personal, lawful use. Users are responsible for complying with the terms of service of content providers and applicable copyright laws when using media downloading features.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests on GitHub.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See the `LICENSE` file for details.

Developed with ❤️ by **Barq Project**.
