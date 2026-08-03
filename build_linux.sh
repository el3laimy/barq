#!/bin/bash
set -e

echo "========================================"
echo "  Barq Download Manager - Linux Build"
echo "========================================"

# Clean previous builds
rm -rf dist build

VENV_PYTHON="./.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

echo "[1/2] Installing pyinstaller if needed..."
$VENV_PYTHON -m pip install pyinstaller

echo "[2/2] Building Executable with PyInstaller..."
$VENV_PYTHON -m PyInstaller --clean --noconfirm build_executable.spec

echo ""
echo "Build Successful!"
echo "Executable is located in: $(pwd)/dist/Barq"
