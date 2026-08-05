#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$DIR/bridge.py"
