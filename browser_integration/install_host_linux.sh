#!/bin/bash

# Define paths
DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_NAME="com.titan.downloader"
CHROME_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
CHROMIUM_DIR="$HOME/.config/chromium/NativeMessagingHosts"
HOST_FILE_SRC="$DIR/host.json"
BRIDGE_SCRIPT="$DIR/bridge.sh"

# Make bridge script executable
chmod +x "$BRIDGE_SCRIPT"

# Ensure target directories exist
mkdir -p "$CHROME_DIR"
mkdir -p "$CHROMIUM_DIR"

# Copy and modify host.json for Chrome
cp "$HOST_FILE_SRC" "$CHROME_DIR/$HOST_NAME.json"
sed -i "s|bridge.sh|$BRIDGE_SCRIPT|g" "$CHROME_DIR/$HOST_NAME.json"

# Copy and modify host.json for Chromium
cp "$HOST_FILE_SRC" "$CHROMIUM_DIR/$HOST_NAME.json"
sed -i "s|bridge.sh|$BRIDGE_SCRIPT|g" "$CHROMIUM_DIR/$HOST_NAME.json"

echo "Native messaging host installed for Chrome and Chromium."
echo "Note: You still need to replace REPLACE_WITH_YOUR_EXTENSION_ID in the host.json files located at:"
echo "  $CHROME_DIR/$HOST_NAME.json"
echo "  $CHROMIUM_DIR/$HOST_NAME.json"
