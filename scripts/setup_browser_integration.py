#!/usr/bin/env python3
"""Barq Development Browser Integration Setup Tool.

Registers Barq Native Messaging manifests for Chromium-based browsers on Linux
with per-browser least-privilege manifests, lifecycle preservation of existing
callers, and scoped Rust Native Host compilation.

Usage:
    python scripts/setup_browser_integration.py detect
    python scripts/setup_browser_integration.py register --target brave:<ID>
    python scripts/setup_browser_integration.py register --target brave:<ID> --target chrome:<ID>
    python scripts/setup_browser_integration.py register --target brave:<ID> --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

# Ensure repository root is on sys.path so scripts can import sibling modules
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
    discover_existing_chromium_origins,
    extension_id_to_origin,
    load_registered_manifest_paths,
    resolve_manifest_paths,
    save_registered_manifest_paths,
    validate_chromium_extension_id,
    validate_custom_manifest_dir,
    validate_on_disk_manifest,
)

NATIVE_HOST_DIR = REPO_ROOT / "apps" / "native-host"
CARGO_TOML = NATIVE_HOST_DIR / "Cargo.toml"


def parse_target_arg(target_str: str) -> tuple[str, str]:
    """Parse a --target string in the format 'browser:extension_id'."""
    parts = target_str.split(":", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid target format '{target_str}'. Expected format: '<browser>:<extension_id>'"
        )
    browser_key, extension_id = parts[0].strip().lower(), parts[1].strip()
    if not browser_key:
        raise ValueError(f"Browser key cannot be empty in target '{target_str}'")

    if browser_key == "firefox":
        raise ValueError(
            "Firefox uses a different Native Messaging manifest format ('allowed_extensions') "
            "and separate caller-validation architecture. Firefox registration is not supported "
            "in this milestone and is deferred to a dedicated follow-up."
        )

    spec = BROWSER_REGISTRY.get(browser_key)
    if spec is None:
        valid_keys = ", ".join(k for k, s in BROWSER_REGISTRY.items() if s.family == "chromium")
        raise ValueError(
            f"Unrecognized browser '{browser_key}'. Supported Chromium browsers: {valid_keys}"
        )

    valid_id = validate_chromium_extension_id(extension_id)
    return browser_key, valid_id


def build_native_host(
    allowed_origins: Sequence[str],
    dry_run: bool = False,
    cargo_path: str | None = None,
) -> Path:
    """Build the Rust Native Messaging Host with compile-time BARQ_ALLOWED_ORIGINS."""
    target_debug_bin = NATIVE_HOST_DIR / "target" / "debug" / "barq-native-host"
    target_release_bin = NATIVE_HOST_DIR / "target" / "release" / "barq-native-host"

    origins_str = ",".join(sorted(set(allowed_origins)))
    if dry_run:
        print(f"  [DRY-RUN] Would clean package: barq-native-host")
        print(f"  [DRY-RUN] Would build Native Host with BARQ_ALLOWED_ORIGINS=\"{origins_str}\"")
        if target_release_bin.is_file():
            return target_release_bin.resolve()
        return target_debug_bin.resolve()

    cargo = cargo_path or shutil.which("cargo")
    if not cargo:
        raise RuntimeError("Cargo not found on PATH. Rust toolchain is required to build Native Host.")

    # 1. Scoped clean of native host package only
    clean_cmd = [
        cargo,
        "clean",
        "--manifest-path",
        str(CARGO_TOML),
        "-p",
        "barq-native-host",
    ]
    subprocess.run(clean_cmd, check=True)

    # 2. Compile with BARQ_ALLOWED_ORIGINS environment variable
    build_env = os.environ.copy()
    build_env["BARQ_ALLOWED_ORIGINS"] = origins_str

    build_cmd = [
        cargo,
        "build",
        "--manifest-path",
        str(CARGO_TOML),
    ]
    subprocess.run(build_cmd, env=build_env, check=True)

    if not target_debug_bin.is_file():
        raise RuntimeError(f"Native host compilation completed but binary not found at {target_debug_bin}")

    # Make sure binary has executable permissions
    try:
        current_mode = target_debug_bin.stat().st_mode
        target_debug_bin.chmod(current_mode | 0o755)
    except OSError:
        pass

    return target_debug_bin.resolve()


def generate_chromium_manifest(
    host_binary_path: Path,
    allowed_origins: Sequence[str],
) -> dict[str, object]:
    """Generate a least-privilege Chromium Native Messaging manifest dictionary."""
    sorted_origins = sorted(set(allowed_origins))
    return {
        "name": HOST_NAME,
        "description": "Barq Native Messaging Host",
        "path": str(host_binary_path.resolve()),
        "type": "stdio",
        "allowed_origins": sorted_origins,
    }


def write_manifest_atomic(
    target_manifest_path: Path,
    manifest_data: dict[str, object],
    dry_run: bool = False,
) -> None:
    """Atomically write a Native Messaging manifest with backup and safe permissions."""
    content = json.dumps(manifest_data, indent=2) + "\n"

    if dry_run:
        print(f"  [DRY-RUN] Would write manifest: {target_manifest_path}")
        print(f"  [DRY-RUN] Manifest content:\n{content.strip()}")
        return

    # Check if existing manifest is present and malformed
    if target_manifest_path.is_file():
        try:
            existing_data = json.loads(target_manifest_path.read_text(encoding="utf-8"))
            if not isinstance(existing_data, dict) or existing_data.get("name") != HOST_NAME:
                # Could be a non-barq file or corrupt barq file
                if existing_data.get("name") is not None:
                    raise ValueError(
                        f"Existing manifest at '{target_manifest_path}' belongs to a different host "
                        f"('{existing_data.get('name')}'). Aborting."
                    )
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ValueError(
                f"Existing manifest at '{target_manifest_path}' is corrupt/malformed ({err}). "
                "Fix or remove it manually before registering."
            )

    parent_dir = target_manifest_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    temp_file = parent_dir / f"{target_manifest_path.name}.tmp.{os.getpid()}"
    backup_file = target_manifest_path.with_suffix(target_manifest_path.suffix + ".bak")

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # Create backup of existing file before replacement
        if target_manifest_path.is_file():
            shutil.copy2(target_manifest_path, backup_file)

        os.replace(temp_file, target_manifest_path)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def command_detect(home_dir: Path | None = None) -> int:
    """Execute the 'detect' command: inspect installed browsers and manifests."""
    print("═" * 60)
    print("  Barq Browser Integration — Detection Report (Linux)")
    print("═" * 60)
    print()

    browsers = detect_installed_browsers(home_dir)
    for b in browsers:
        status_exe = "FOUND" if b.executable_path else "NOT DETECTED"
        print(f"Browser: {b.spec.display_name} ({b.spec.key})")
        print(f"  Family:      {b.spec.family}")
        print(f"  Executable:  {status_exe} ({b.executable_path or 'none'})")
        for m_path in b.manifest_paths:
            manifest_exists = m_path.is_file()
            valid_origins = validate_on_disk_manifest(m_path) if manifest_exists else None
            status_manifest = "REGISTERED" if manifest_exists else "NOT REGISTERED"
            print(f"  Manifest:    {status_manifest} -> {m_path}")
            if manifest_exists:
                if valid_origins:
                    print(f"               Origins: {', '.join(valid_origins)}")
                else:
                    print(f"               Status:  MALFORMED / UNVERIFIED")
        print()

    # Also display state file registrations
    state_entries = load_registered_manifest_paths(home_dir)
    if state_entries:
        print("── State-Tracked Registrations ──")
        for browser_label, path in state_entries:
            valid_origins = validate_on_disk_manifest(path)
            status_val = "VALID" if valid_origins else "MISSING / INVALID"
            print(f"  [{browser_label}] {path} -> {status_val}")
        print()

    return 0


def command_register(
    targets: Sequence[str],
    custom_manifest_dir: str | None = None,
    custom_extension_id: str | None = None,
    dry_run: bool = False,
    home_dir: Path | None = None,
) -> int:
    """Execute the 'register' command: build Native Host and write per-browser manifests."""
    base_home = (home_dir or Path.home()).resolve()

    # 1. Parse and group target browser specifications
    browser_targets: dict[str, set[str]] = {}
    for target_arg in targets:
        browser_key, extension_id = parse_target_arg(target_arg)
        browser_targets.setdefault(browser_key, set()).add(extension_id)

    # 2. Parse custom target if specified
    custom_dir_resolved: Path | None = None
    custom_id_valid: str | None = None
    if custom_manifest_dir or custom_extension_id:
        if not (custom_manifest_dir and custom_extension_id):
            raise ValueError(
                "Both --custom-chromium-manifest-dir and --custom-extension-id must be provided together."
            )
        custom_dir_resolved = validate_custom_manifest_dir(custom_manifest_dir, base_home)
        custom_id_valid = validate_chromium_extension_id(custom_extension_id)

    if not browser_targets and not custom_dir_resolved:
        raise ValueError("No targets specified. Use --target <browser>:<id> or --custom-* flags.")

    print()
    print("═" * 60)
    print("  Barq Browser Integration — Native Messaging Registration")
    print("═" * 60)
    print()

    # 3. Collect new caller origins
    new_origins: set[str] = set()
    for browser_key, ext_ids in browser_targets.items():
        for ext_id in ext_ids:
            new_origins.add(extension_id_to_origin(ext_id))
    if custom_id_valid:
        new_origins.add(extension_id_to_origin(custom_id_valid))

    # 4. Discover existing valid Barq Chromium origins for lifecycle preservation
    extra_paths: list[Path] = []
    if custom_dir_resolved:
        extra_paths.append(custom_dir_resolved / MANIFEST_FILENAME)
    existing_origins = discover_existing_chromium_origins(base_home, extra_paths)

    # 5. Compute the union for the Rust Native Host allowlist
    union_origins = sorted(existing_origins | new_origins)

    print("── Caller Origin Lifecycle ──")
    print(f"  Existing preserved origins: {len(existing_origins)}")
    for orig in sorted(existing_origins):
        print(f"    - {orig}")
    print(f"  New requested origins:      {len(new_origins)}")
    for orig in sorted(new_origins):
        print(f"    - {orig}")
    print(f"  Union allowlist for Host:   {len(union_origins)}")
    for orig in union_origins:
        print(f"    - {orig}")
    print()

    # 6. Build the Rust Native Host once with the full union allowlist
    print("── Building Native Host ──")
    host_binary_path = build_native_host(union_origins, dry_run=dry_run)
    print(f"  Native Host binary: {host_binary_path}")
    print()

    # 7. Write per-browser least-privilege manifests
    print("── Registering Browser Manifests (Least Privilege) ──")
    new_state_entries: list[tuple[str, Path]] = []

    for browser_key, ext_ids in browser_targets.items():
        spec = BROWSER_REGISTRY[browser_key]
        browser_origins = [extension_id_to_origin(ext_id) for ext_id in sorted(ext_ids)]
        manifest_payload = generate_chromium_manifest(host_binary_path, browser_origins)

        manifest_paths = resolve_manifest_paths(spec, base_home)
        for m_path in manifest_paths:
            print(f"Target: {spec.display_name} ({browser_key})")
            print(f"  Manifest path:    {m_path}")
            print(f"  Allowed origins:  {', '.join(browser_origins)}")
            write_manifest_atomic(m_path, manifest_payload, dry_run=dry_run)
            new_state_entries.append((browser_key, m_path))
            print("  Status:           SUCCESS")
            print()

    if custom_dir_resolved and custom_id_valid:
        custom_manifest_path = custom_dir_resolved / MANIFEST_FILENAME
        custom_origins = [extension_id_to_origin(custom_id_valid)]
        custom_payload = generate_chromium_manifest(host_binary_path, custom_origins)

        print("Target: Custom Chromium-compatible browser")
        print(f"  Manifest path:    {custom_manifest_path}")
        print(f"  Allowed origins:  {', '.join(custom_origins)}")
        write_manifest_atomic(custom_manifest_path, custom_payload, dry_run=dry_run)
        new_state_entries.append(("custom", custom_manifest_path))
        print("  Status:           SUCCESS")
        print()

    # 8. Atomically update Barq state file (only after build and manifest writes succeed)
    if not dry_run:
        save_registered_manifest_paths(new_state_entries, base_home)
        print("── State Store ──")
        print(f"  Updated registration index: {load_registered_manifest_paths(base_home)}")
        print()

    print("═" * 60)
    print("  Registration complete.")
    print("═" * 60)
    print()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Barq Browser Integration Setup & Native Messaging Registration Tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # detect command
    subparsers.add_parser(
        "detect",
        help="Detect installed browsers and existing Native Messaging manifests",
    )

    # register command
    register_parser = subparsers.add_parser(
        "register",
        help="Register Native Messaging Host for one or more Chromium browsers",
    )
    register_parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Target browser and extension ID in the format '<browser>:<extension_id>' (repeatable)",
    )
    register_parser.add_argument(
        "--custom-chromium-manifest-dir",
        type=str,
        default=None,
        help="Custom Chromium NativeMessagingHosts directory path (inside user home)",
    )
    register_parser.add_argument(
        "--custom-extension-id",
        type=str,
        default=None,
        help="Extension ID for the custom Chromium browser",
    )
    register_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without modifying filesystem or rebuilding Native Host",
    )

    args = parser.parse_args(argv)

    if args.command == "detect":
        return command_detect()
    elif args.command == "register":
        try:
            return command_register(
                targets=args.target,
                custom_manifest_dir=args.custom_chromium_manifest_dir,
                custom_extension_id=args.custom_extension_id,
                dry_run=args.dry_run,
            )
        except Exception as e:
            print(f"Error during registration: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
