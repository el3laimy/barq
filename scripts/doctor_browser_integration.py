#!/usr/bin/env python3
"""Barq Browser Integration Doctor.

Checks the health of the browser extension build pipeline,
native messaging host, and integration configuration per browser product.

Usage:
    python scripts/doctor_browser_integration.py
    python scripts/doctor_browser_integration.py --browser brave
    python scripts/doctor_browser_integration.py --browser brave --extension-id <ID>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.browser_registry import (
    BROWSER_REGISTRY,
    BROWSER_SPECS,
    HOST_NAME,
    MANIFEST_FILENAME,
    BrowserSpec,
    detect_installed_browsers,
    extension_id_to_origin,
    load_registered_manifest_paths,
    resolve_manifest_paths,
    validate_chromium_extension_id,
    validate_on_disk_manifest,
)

EXTENSION_DIR = REPO_ROOT / "apps" / "extension"
NATIVE_HOST_DIR = REPO_ROOT / "apps" / "native-host"
CHROME_OUTPUT = EXTENSION_DIR / ".output" / "chrome-mv3"
FIREFOX_OUTPUT = EXTENSION_DIR / ".output" / "firefox-mv3"

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


def check_browser_status(
    spec: BrowserSpec,
    expected_origin: str | None = None,
    home_dir: Path | None = None,
) -> bool:
    """Inspect and report native messaging status for a specific browser product."""
    base_home = (home_dir or Path.home()).resolve()
    print(f"Browser: {spec.display_name} ({spec.key})")

    # 1. Executable detection
    exe_found = None
    for cand in spec.executable_candidates:
        p = shutil.which(cand)
        if p:
            exe_found = p
            break
    check("detected", exe_found is not None, exe_found or "not found on PATH")

    # 2. Manifest check
    manifest_paths = resolve_manifest_paths(spec, base_home)
    browser_ok = True

    for manifest_path in manifest_paths:
        manifest_exists = manifest_path.is_file()
        check("manifest exists", manifest_exists, str(manifest_path))
        if not manifest_exists:
            browser_ok = False
            continue

        # Parse JSON
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            json_valid = isinstance(manifest_data, dict)
        except Exception as e:
            json_valid = False
            manifest_data = {}

        check("JSON valid", json_valid)
        if not json_valid:
            browser_ok = False
            continue

        # Host name check
        host_name_match = manifest_data.get("name") == HOST_NAME
        check("host name", host_name_match, f"expected '{HOST_NAME}', got '{manifest_data.get('name')}'")
        browser_ok &= host_name_match

        # Type check
        type_stdio = manifest_data.get("type") == "stdio"
        check("type stdio", type_stdio)
        browser_ok &= type_stdio

        # Origins check
        if spec.family == "chromium":
            allowed_origins = manifest_data.get("allowed_origins", [])
            has_origins = isinstance(allowed_origins, list) and len(allowed_origins) > 0
            check("allowed_origins present", has_origins, f"{len(allowed_origins)} origin(s)")
            browser_ok &= has_origins

            if expected_origin:
                origin_match = expected_origin in allowed_origins
                check("extension origin match", origin_match, f"expected '{expected_origin}'")
                browser_ok &= origin_match

        # Target binary check from manifest
        bin_path_str = manifest_data.get("path")
        if bin_path_str:
            bin_path = Path(bin_path_str)
            bin_exists = bin_path.is_file()
            check("binary exists", bin_exists, str(bin_path))
            browser_ok &= bin_exists

            if bin_exists:
                is_executable = os.access(bin_path, os.X_OK)
                check("binary executable", is_executable)
                browser_ok &= is_executable
        else:
            check("binary path specified", False)
            browser_ok = False

    return browser_ok


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

    ok &= check("manifest_version == 3", manifest.get("manifest_version") == 3)

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
    ok &= check("No source-tree paths in manifest", not has_entrypoints)

    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Barq Browser Integration Doctor")
    parser.add_argument(
        "--browser",
        type=str,
        default=None,
        help="Filter checks to a specific browser product (e.g., brave, chrome, edge)",
    )
    parser.add_argument(
        "--extension-id",
        type=str,
        default=None,
        help="Validate that the specified Chromium extension ID is registered in allowed_origins",
    )

    args = parser.parse_args(argv)

    print()
    print("═" * 50)
    print("  Barq Browser Integration Doctor")
    print("═" * 50)
    print()

    all_ok = True

    # ── Prerequisites ─────────────────────────────────
    print("── Prerequisites ──")

    pnpm = shutil.which("pnpm")
    all_ok &= check("pnpm available", pnpm is not None, pnpm or "not found")

    node = shutil.which("node")
    all_ok &= check("Node.js available", node is not None)

    if node:
        try:
            ver = subprocess.check_output([node, "--version"], text=True).strip()
            check("Node.js version", True, ver)
        except Exception:
            pass

    cargo = shutil.which("cargo")
    check("Rust toolchain (cargo)", cargo is not None, "optional, needed for Native Host")

    print()

    # ── Extension Dependencies ────────────────────────
    print("── Extension Dependencies ──")

    node_modules = EXTENSION_DIR / "node_modules"
    all_ok &= check("Extension node_modules installed", node_modules.is_dir())

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

    client_ts = REPO_ROOT / "packages" / "browser-core" / "src" / "native" / "client.ts"
    if client_ts.exists():
        content = client_ts.read_text()
        ts_host = None
        for line in content.splitlines():
            if "HOST_NAME" in line and "=" in line and "'" in line:
                ts_host = line.split("'")[1] if "'" in line else None
                break
        if ts_host:
            check("Extension HOST_NAME", ts_host == HOST_NAME, f"'{ts_host}'")
            if ts_host != HOST_NAME:
                warn("Host name mismatch — extension and host must agree")
        else:
            warn("Could not extract HOST_NAME from client.ts")
    else:
        warn("client.ts not found", str(client_ts))

    cargo_toml = NATIVE_HOST_DIR / "Cargo.toml"
    check("Native Host Cargo.toml", cargo_toml.exists())

    host_bin = NATIVE_HOST_DIR / "target" / "debug" / "barq-native-host"
    host_bin_release = NATIVE_HOST_DIR / "target" / "release" / "barq-native-host"
    has_bin = host_bin.exists() or host_bin_release.exists()
    check(
        "Native Host binary compiled",
        has_bin,
        "run: python scripts/setup_browser_integration.py register --target <browser>:<id>"
        if not has_bin
        else (str(host_bin_release) if host_bin_release.exists() else str(host_bin)),
    )
    if not has_bin:
        all_ok = False

    print()

    # ── Multi-Browser Native Messaging ────────────────
    print("── Native Messaging Registrations (Linux) ──")

    expected_origin = None
    if args.extension_id:
        try:
            expected_origin = extension_id_to_origin(args.extension_id)
        except ValueError as err:
            check(f"Extension ID validation", False, str(err))
            all_ok = False

    if args.browser:
        target_key = args.browser.strip().lower()
        spec = BROWSER_REGISTRY.get(target_key)
        if not spec:
            check(f"Browser '{target_key}' supported", False, "unrecognized browser key")
            all_ok = False
        else:
            target_ok = check_browser_status(spec, expected_origin=expected_origin)
            all_ok &= target_ok
            print()
    else:
        # Check all detected and configured browsers
        detected_browsers = detect_installed_browsers()
        found_any_manifest = False
        for b in detected_browsers:
            if b.existing_manifest_paths or b.executable_path:
                b_ok = check_browser_status(b.spec, expected_origin=expected_origin)
                if b.existing_manifest_paths:
                    found_any_manifest = True
                print()

        # Also inspect custom state registrations
        state_registrations = load_registered_manifest_paths()
        if state_registrations:
            print("── State-Tracked Custom Registrations ──")
            for label, m_path in state_registrations:
                if label == "custom":
                    m_exists = m_path.is_file()
                    check(f"Custom manifest: {m_path}", m_exists)
                    if m_exists:
                        origins = validate_on_disk_manifest(m_path)
                        check("  valid Barq manifest", origins is not None, f"{len(origins or [])} origin(s)")
            print()

        if not found_any_manifest and not state_registrations:
            warn("No Native Messaging manifests found for any detected browser.")
            warn("Run: python scripts/setup_browser_integration.py register --target <browser>:<id>")
            all_ok = False

    # ── Summary ───────────────────────────────────────
    print("═" * 50)
    if all_ok:
        print(f"  {PASS} All critical checks passed!")
    else:
        print(f"  {FAIL} Some checks failed — review above.")
    print("═" * 50)
    print()

    if all_ok and CHROME_OUTPUT.exists():
        print("  Load this directory in Browser Developer Mode:")
        print(f"  {CHROME_OUTPUT.resolve()}")
        print()

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
