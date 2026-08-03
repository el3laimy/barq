#!/usr/bin/env bash
set -euo pipefail

# Change to repository root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  Barq Download Manager - Linux Build"
echo "========================================"

# Clean previous builds
rm -rf build dist

VENV_PYTHON="./.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

echo "[1/2] Installing pyinstaller if needed..."
$VENV_PYTHON -m pip install pyinstaller > /dev/null 2>&1 || true

echo "[2/2] Building Executable with PyInstaller..."
$VENV_PYTHON -m PyInstaller --clean --noconfirm build_executable.spec

if [[ -f "dist/Barq" ]]; then
    echo ""
    echo "========================================"
    echo "Build Successful!"
    echo "Executable is located in: $(pwd)/dist/Barq"
    echo ""
    echo "To install system-wide with taskbar icon registration, run:"
    echo "  sudo ./install_linux.sh"
    echo "========================================"
else
    echo "Error: Build failed, dist/Barq binary was not generated."
    exit 1
fi
