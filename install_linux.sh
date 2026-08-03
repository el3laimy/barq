#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/barq"
DESKTOP_FILE="/usr/share/applications/barq.desktop"
ICON_FILE="/usr/share/icons/hicolor/256x256/apps/barq.png"

if [[ ! -f "dist/Barq" ]]; then
    echo "Error: dist/Barq was not found."
    echo "Run ./build_linux.sh first."
    exit 1
fi

if [[ ! -f "assets/icons/barq_256.png" ]]; then
    echo "Error: assets/icons/barq_256.png was not found."
    exit 1
fi

if [[ ! -f "packaging/linux/barq.desktop" ]]; then
    echo "Error: packaging/linux/barq.desktop was not found."
    exit 1
fi

echo "[1/4] Installing application executable to $APP_DIR/Barq..."
sudo install -d "$APP_DIR"
sudo install -m 755 "dist/Barq" "$APP_DIR/Barq"

echo "[2/4] Installing application icon to $ICON_FILE..."
sudo install -d "$(dirname "$ICON_FILE")"
sudo install -m 644 \
    "assets/icons/barq_256.png" \
    "$ICON_FILE"

echo "[3/4] Installing desktop launcher to $DESKTOP_FILE..."
sudo install -m 644 \
    "packaging/linux/barq.desktop" \
    "$DESKTOP_FILE"

echo "[4/4] Refreshing desktop and icon caches..."
if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    sudo gtk-update-icon-cache -f -t /usr/share/icons/hicolor
fi

echo ""
echo "========================================"
echo "Barq installed successfully!"
echo "Launch it from the applications menu or run: gtk-launch barq"
echo "========================================"
