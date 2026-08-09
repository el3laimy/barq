#!/usr/bin/env python3
"""
Barq Browser Integration Doctor

Checks the health of the browser extension build pipeline,
native messaging host, and integration configuration.

Usage:
    python scripts/doctor_browser_integration.py
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = REPO_ROOT / "apps" / "extension"
NATIVE_HOST_DIR = REPO_ROOT / "apps" / "native-host"
CHROME_OUTPUT = EXTENSION_DIR / ".output" / "chrome-mv3"
FIREFOX_OUTPUT = EXTENSION_DIR / ".output" / "firefox-mv3"
HOST_NAME = "app.barq.browser"

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    msg = f"  {status} {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return condition


def warn(label: str, detail: str = ""):
    msg = f"  {WARN} {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)


def main():
    print()
    print("═" * 50)
    print("  Barq Browser Integration Doctor")
    print("═" * 50)
    print()

    all_ok = True

    # ── Prerequisites ─────────────────────────────────
    print("── Prerequisites ──")

    pnpm = shutil.which("pnpm")
    all_ok &= check("pnpm available", pnpm is not None,
                     pnpm or "not found")

    node = shutil.which("node")
    all_ok &= check("Node.js available", node is not None)

    if node:
        try:
            ver = subprocess.check_output([node, "--version"],
                                          text=True).strip()
            check("Node.js version", True, ver)
        except Exception:
            pass

    cargo = shutil.which("cargo")
    check("Rust toolchain (cargo)", cargo is not None,
          "optional, needed for Native Host")

    print()

    # ── Extension Dependencies ────────────────────────
    print("── Extension Dependencies ──")

    node_modules = EXTENSION_DIR / "node_modules"
    all_ok &= check("Extension node_modules installed",
                     node_modules.is_dir())

    wxt_pkg = node_modules / "wxt" / "package.json" if node_modules.is_dir() else None
    if wxt_pkg and wxt_pkg.exists():
        wxt_version = json.loads(wxt_pkg.read_text()).get("version", "?")
        check("WXT version", True, wxt_version)
    else:
        all_ok &= check("WXT package found", False)

    print()

    # ── Chrome Build ──────────────────────────────────
    print("── Chrome MV3 Build ──")
    all_ok &= validate_build(CHROME_OUTPUT, "chrome")

    print()

    # ── Firefox Build ─────────────────────────────────
    print("── Firefox MV3 Build ──")
    validate_build(FIREFOX_OUTPUT, "firefox")  # Non-blocking

    print()

    # ── Native Host ───────────────────────────────────
    print("── Native Messaging Host ──")

    # Check host name in client.ts
    client_ts = (REPO_ROOT / "packages" / "browser-core"
                 / "src" / "native" / "client.ts")
    if client_ts.exists():
        content = client_ts.read_text()
        ts_host = None
        for line in content.splitlines():
            if "HOST_NAME" in line and "=" in line and "'" in line:
                ts_host = line.split("'")[1] if "'" in line else None
                break
        if ts_host:
            check("Extension HOST_NAME", ts_host == HOST_NAME,
                  f"'{ts_host}'")
            if ts_host != HOST_NAME:
                warn("Host name mismatch — extension and host must agree")
        else:
            warn("Could not extract HOST_NAME from client.ts")
    else:
        warn("client.ts not found", str(client_ts))

    # Check Cargo.toml for native host
    cargo_toml = NATIVE_HOST_DIR / "Cargo.toml"
    check("Native Host Cargo.toml", cargo_toml.exists())

    # Check for compiled binary
    host_bin = NATIVE_HOST_DIR / "target" / "debug" / "barq-native-host"
    host_bin_release = NATIVE_HOST_DIR / "target" / "release" / "barq-native-host"
    has_bin = host_bin.exists() or host_bin_release.exists()
    check("Native Host binary compiled", has_bin,
          "run: cargo build --manifest-path apps/native-host/Cargo.toml"
          if not has_bin else "")

    # Check platform-specific native messaging manifest locations
    if sys.platform == "linux":
        nm_dirs = [
            Path.home() / ".config" / "google-chrome" / "NativeMessagingHosts",
            Path.home() / ".config" / "chromium" / "NativeMessagingHosts",
            Path.home() / ".config" / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts",
            Path.home() / ".mozilla" / "native-messaging-hosts",
        ]
        found_any = False
        for nm_dir in nm_dirs:
            manifest_file = nm_dir / f"{HOST_NAME}.json"
            if manifest_file.exists():
                check(f"NM manifest registered", True,
                      str(manifest_file))
                found_any = True
                # Validate the manifest content
                try:
                    nm_manifest = json.loads(manifest_file.read_text())
                    check("  Host name matches",
                          nm_manifest.get("name") == HOST_NAME)
                    allowed = nm_manifest.get("allowed_origins", [])
                    check("  allowed_origins present",
                          len(allowed) > 0,
                          f"{len(allowed)} origins")
                except Exception as e:
                    warn(f"  Could not parse NM manifest: {e}")

        if not found_any:
            warn("No Native Messaging manifests found in standard locations")
            warn("Extension will work but cannot connect to desktop app")

    elif sys.platform == "win32":
        warn("Windows NM registry check not implemented in this script")

    print()

    # ── Summary ───────────────────────────────────────
    print("═" * 50)
    if all_ok:
        print(f"  {PASS} All critical checks passed!")
    else:
        print(f"  {FAIL} Some checks failed — review above.")
    print("═" * 50)
    print()

    if all_ok and CHROME_OUTPUT.exists():
        print("  Load this directory in Chrome Developer Mode:")
        print(f"  {CHROME_OUTPUT.resolve()}")
        print()

    return 0 if all_ok else 1


def validate_build(output_dir: Path, browser: str) -> bool:
    ok = True

    ok &= check(f"{browser} output directory exists", output_dir.is_dir())
    if not output_dir.is_dir():
        return False

    manifest_path = output_dir / "manifest.json"
    ok &= check("manifest.json exists", manifest_path.exists())
    if not manifest_path.exists():
        return False

    manifest = json.loads(manifest_path.read_text())

    ok &= check("manifest_version == 3",
                 manifest.get("manifest_version") == 3)

    # Background
    bg = manifest.get("background", {})
    bg_file = bg.get("service_worker") or (bg.get("scripts", [None])[0])
    if bg_file:
        bg_path = output_dir / bg_file
        ok &= check(f"background: {bg_file}", bg_path.exists())
    else:
        ok &= check("background entry defined", False)

    # Popup
    popup = manifest.get("action", {}).get("default_popup")
    if popup:
        popup_path = output_dir / popup
        ok &= check(f"popup: {popup}", popup_path.exists())

    # Icons
    icons = manifest.get("icons", {})
    for size, icon_path in icons.items():
        full_path = output_dir / icon_path
        ok &= check(f"icon {size}: {icon_path}", full_path.exists())

    # Check for prohibited source-tree paths
    manifest_text = manifest_path.read_text()
    has_entrypoints = "entrypoints/" in manifest_text
    ok &= check("No source-tree paths in manifest",
                 not has_entrypoints)

    return ok


if __name__ == "__main__":
    sys.exit(main())
