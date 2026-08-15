"""Linux Multi-Browser Native Messaging Registry and State Store for Barq.

Provides browser specifications, manifest path resolution, extension ID
validation, manifest security verification, state tracking, and discovery logic
without side effects during import.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

logger = logging.getLogger(__name__)

HOST_NAME = "app.barq.browser"
MANIFEST_FILENAME = f"{HOST_NAME}.json"
CHROMIUM_EXTENSION_PREFIX = "chrome-extension://"
FIREFOX_EXTENSION_PREFIX = "firefox-extension://"
EXTENSION_ID_REGEX = re.compile(r"^[a-p]{32}$")
CANONICAL_ORIGIN_REGEX = re.compile(r"^chrome-extension://[a-p]{32}/$")
STATE_FILE_REL_PATH = Path(".config/barq/browser-integrations.json")


@dataclass(frozen=True)
class BrowserSpec:
    key: str
    display_name: str
    family: str  # "chromium" or "firefox"
    executable_candidates: tuple[str, ...]
    linux_manifest_dirs: tuple[Path, ...]


@dataclass(frozen=True)
class DetectedBrowser:
    spec: BrowserSpec
    executable_path: Path | None
    manifest_paths: tuple[Path, ...]
    existing_manifest_paths: tuple[Path, ...]


BROWSER_SPECS: tuple[BrowserSpec, ...] = (
    BrowserSpec(
        key="chrome",
        display_name="Google Chrome",
        family="chromium",
        executable_candidates=(
            "google-chrome",
            "google-chrome-stable",
            "google-chrome-unstable",
            "google-chrome-beta",
            "chrome",
        ),
        linux_manifest_dirs=(
            Path(".config/google-chrome/NativeMessagingHosts"),
        ),
    ),
    BrowserSpec(
        key="brave",
        display_name="Brave",
        family="chromium",
        executable_candidates=(
            "brave-browser",
            "brave-browser-stable",
            "brave-browser-beta",
            "brave-browser-nightly",
            "brave",
        ),
        linux_manifest_dirs=(
            Path(".config/BraveSoftware/Brave-Browser/NativeMessagingHosts"),
        ),
    ),
    BrowserSpec(
        key="edge",
        display_name="Microsoft Edge",
        family="chromium",
        executable_candidates=(
            "microsoft-edge",
            "microsoft-edge-stable",
            "microsoft-edge-beta",
            "microsoft-edge-dev",
        ),
        linux_manifest_dirs=(
            Path(".config/microsoft-edge/NativeMessagingHosts"),
        ),
    ),
    BrowserSpec(
        key="chromium",
        display_name="Chromium",
        family="chromium",
        executable_candidates=(
            "chromium",
            "chromium-browser",
        ),
        linux_manifest_dirs=(
            Path(".config/chromium/NativeMessagingHosts"),
        ),
    ),
    BrowserSpec(
        key="opera",
        display_name="Opera",
        family="chromium",
        executable_candidates=(
            "opera",
            "opera-beta",
            "opera-developer",
        ),
        linux_manifest_dirs=(
            Path(".config/opera/NativeMessagingHosts"),
        ),
    ),
    BrowserSpec(
        key="vivaldi",
        display_name="Vivaldi",
        family="chromium",
        executable_candidates=(
            "vivaldi",
            "vivaldi-stable",
            "vivaldi-snapshot",
        ),
        linux_manifest_dirs=(
            Path(".config/vivaldi/NativeMessagingHosts"),
        ),
    ),
    BrowserSpec(
        key="firefox",
        display_name="Mozilla Firefox",
        family="firefox",
        executable_candidates=(
            "firefox",
            "firefox-esr",
            "firefox-bin",
        ),
        linux_manifest_dirs=(
            Path(".mozilla/native-messaging-hosts"),
        ),
    ),
)

BROWSER_REGISTRY: Mapping[str, BrowserSpec] = {
    spec.key: spec for spec in BROWSER_SPECS
}


def get_browser_spec(key: str) -> BrowserSpec | None:
    """Return the BrowserSpec for a given key, or None if unrecognized."""
    return BROWSER_REGISTRY.get(key.strip().lower())


def resolve_manifest_dirs(
    spec: BrowserSpec, home_dir: Path | None = None
) -> tuple[Path, ...]:
    """Resolve manifest directories for a BrowserSpec against a home directory."""
    base_home = (home_dir or Path.home()).resolve()
    return tuple((base_home / rel_dir).resolve() for rel_dir in spec.linux_manifest_dirs)


def resolve_manifest_paths(
    spec: BrowserSpec, home_dir: Path | None = None
) -> tuple[Path, ...]:
    """Return expected manifest file paths for a BrowserSpec."""
    dirs = resolve_manifest_dirs(spec, home_dir)
    return tuple(d / MANIFEST_FILENAME for d in dirs)


def validate_chromium_extension_id(extension_id: str) -> str:
    """Validate a 32-character lowercase Chromium extension ID [a-p]{32}.

    Raises ValueError on empty, uppercase, URL, wildcard, or invalid characters.
    """
    if not extension_id or not isinstance(extension_id, str):
        raise ValueError("Extension ID cannot be empty.")

    cleaned = extension_id.strip()
    if not EXTENSION_ID_REGEX.fullmatch(cleaned):
        raise ValueError(
            f"Invalid Chromium extension ID '{extension_id}'. "
            "Extension ID must be exactly 32 lowercase letters between 'a' and 'p' (no wildcards or URLs)."
        )
    return cleaned


def extension_id_to_origin(extension_id: str) -> str:
    """Convert a validated extension ID to canonical chrome-extension origin."""
    valid_id = validate_chromium_extension_id(extension_id)
    return f"{CHROMIUM_EXTENSION_PREFIX}{valid_id}/"


def validate_custom_manifest_dir(
    path_input: str | Path, home_dir: Path | None = None
) -> Path:
    """Validate that a custom manifest directory is an absolute path within the user's home."""
    if not path_input:
        raise ValueError("Custom manifest directory path cannot be empty.")

    raw_str = str(path_input).strip()
    if not raw_str:
        raise ValueError("Custom manifest directory path cannot be empty.")

    user_home = (home_dir or Path.home()).resolve()

    # Reject relative paths that do not start with ~ or /
    if not raw_str.startswith("~") and not Path(raw_str).is_absolute():
        raise ValueError(
            f"Custom manifest directory must be an absolute path: '{raw_str}'"
        )

    expanded = Path(os.path.expanduser(raw_str))
    resolved = expanded.resolve()

    # Must be strictly inside user's home directory
    try:
        rel = resolved.relative_to(user_home)
        if str(rel) == ".":
            raise ValueError(
                f"Custom manifest directory cannot be the user home directory itself: {resolved}"
            )
    except ValueError:
        raise ValueError(
            f"Custom manifest directory must reside inside user home directory ({user_home}): {resolved}"
        )

    # Reject system paths
    system_roots = (
        "/etc",
        "/usr",
        "/var",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/opt",
        "/sys",
        "/proc",
        "/dev",
        "/root",
    )
    for sys_dir in system_roots:
        if str(resolved) == sys_dir or str(resolved).startswith(sys_dir + "/"):
            raise ValueError(
                f"Custom manifest directory cannot be a system path: {resolved}"
            )

    return resolved


def get_state_file_path(home_dir: Path | None = None) -> Path:
    """Return the location of the Barq registration state file."""
    base_home = (home_dir or Path.home()).resolve()
    return base_home / STATE_FILE_REL_PATH


def load_registered_manifest_paths(
    home_dir: Path | None = None,
) -> list[tuple[str, Path]]:
    """Safely load registered browser manifest paths from the state file.

    Returns a list of (browser_label, manifest_path) pairs.
    Paths pointing outside the user home directory are safely ignored.
    """
    state_file = get_state_file_path(home_dir)
    if not state_file.is_file():
        return []

    user_home = (home_dir or Path.home()).resolve()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        logger.warning("Could not read registration state file %s: %s", state_file, err)
        return []

    if not isinstance(data, dict):
        return []

    registrations = data.get("chromiumRegistrations", [])
    if not isinstance(registrations, list):
        return []

    results: list[tuple[str, Path]] = []
    for entry in registrations:
        if not isinstance(entry, dict):
            continue
        browser_label = entry.get("browser", "unknown")
        manifest_path_str = entry.get("manifestPath")
        if not isinstance(manifest_path_str, str) or not manifest_path_str.strip():
            continue

        candidate_path = Path(manifest_path_str).resolve()
        # Verify path resides strictly within the user's home directory
        try:
            candidate_path.relative_to(user_home)
        except ValueError:
            logger.warning(
                "Ignored unsafe manifest path outside user home in state file: %s",
                candidate_path,
            )
            continue

        results.append((str(browser_label), candidate_path))

    return results


def save_registered_manifest_paths(
    registrations: Sequence[tuple[str, Path]],
    home_dir: Path | None = None,
) -> None:
    """Atomically write registered manifest paths to the Barq state file.

    Deduplicates registrations by resolved manifest path.
    """
    state_file = get_state_file_path(home_dir)
    user_home = (home_dir or Path.home()).resolve()

    # Load existing valid state entries to preserve all past registrations
    existing = load_registered_manifest_paths(home_dir)
    all_entries: dict[Path, str] = {}
    for browser, path in existing:
        all_entries[path.resolve()] = browser
    for browser, path in registrations:
        all_entries[path.resolve()] = browser

    reg_list: list[dict[str, str]] = []
    for path, browser in sorted(all_entries.items(), key=lambda item: str(item[0])):
        # Verify within home directory
        try:
            path.relative_to(user_home)
        except ValueError:
            continue
        reg_list.append({
            "browser": browser,
            "manifestPath": str(path),
        })

    payload = {
        "version": 1,
        "chromiumRegistrations": reg_list,
    }
    content = json.dumps(payload, indent=2) + "\n"

    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = state_file.parent / f"{state_file.name}.tmp.{os.getpid()}"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, state_file)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def validate_on_disk_manifest(manifest_path: Path) -> list[str] | None:
    """Inspect and validate a physical Native Messaging manifest on disk.

    Only returns a list of valid canonical Chromium extension origins if:
    - name == "app.barq.browser"
    - type == "stdio"
    - allowed_origins is a list of strings strictly matching ^chrome-extension://[a-p]{32}/$

    Returns None if file is missing, malformed, unrelated, or unsafe.
    """
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(manifest, dict):
        return None

    if manifest.get("name") != HOST_NAME or manifest.get("type") != "stdio":
        return None

    raw_origins = manifest.get("allowed_origins")
    if not isinstance(raw_origins, list):
        return None

    valid_origins: list[str] = []
    for origin in raw_origins:
        if isinstance(origin, str) and CANONICAL_ORIGIN_REGEX.fullmatch(origin):
            valid_origins.append(origin)
        else:
            # If an invalid/unsafe origin exists, reject entire manifest
            return None

    return valid_origins


def discover_existing_chromium_origins(
    home_dir: Path | None = None,
    extra_manifest_paths: Sequence[Path] = (),
) -> set[str]:
    """Discover existing valid Barq Chromium origins across known and state-tracked paths.

    Zero-trust: never trusts origins from state directly; always validates on-disk files.
    """
    base_home = (home_dir or Path.home()).resolve()
    candidate_paths: set[Path] = set()

    # 1. Known standard browser manifest paths
    for spec in BROWSER_SPECS:
        if spec.family == "chromium":
            for m_path in resolve_manifest_paths(spec, base_home):
                candidate_paths.add(m_path.resolve())

    # 2. State-tracked manifest paths (custom or past registrations)
    for _, state_path in load_registered_manifest_paths(base_home):
        candidate_paths.add(state_path.resolve())

    # 3. Any extra paths supplied
    for extra in extra_manifest_paths:
        candidate_paths.add(extra.resolve())

    discovered_origins: set[str] = set()
    for path in candidate_paths:
        valid_origins = validate_on_disk_manifest(path)
        if valid_origins:
            discovered_origins.update(valid_origins)

    return discovered_origins


def detect_installed_browsers(
    home_dir: Path | None = None,
    path_lookup: Mapping[str, str] | None = None,
) -> list[DetectedBrowser]:
    """Detect available browsers and existing Native Messaging manifests on Linux."""
    detected: list[DetectedBrowser] = []
    base_home = (home_dir or Path.home()).resolve()

    for spec in BROWSER_SPECS:
        exe_path: Path | None = None
        for candidate in spec.executable_candidates:
            if path_lookup is not None:
                found = path_lookup.get(candidate)
            else:
                found = shutil.which(candidate)
            if found:
                exe_path = Path(found).resolve()
                break

        manifest_paths = resolve_manifest_paths(spec, base_home)
        existing = tuple(p for p in manifest_paths if p.is_file())

        detected.append(
            DetectedBrowser(
                spec=spec,
                executable_path=exe_path,
                manifest_paths=manifest_paths,
                existing_manifest_paths=existing,
            )
        )

    return detected
