"""Retirement migration for Barq's unsafe legacy browser bridge."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)

LEGACY_HOST_NAME = "com.barq.downloader"
LEGACY_MANIFEST_FILENAME = f"{LEGACY_HOST_NAME}.json"
LEGACY_MANIFEST_DIRECTORIES = (
    Path(".config/google-chrome/NativeMessagingHosts"),
    Path(".config/BraveSoftware/Brave-Browser/NativeMessagingHosts"),
    Path(".config/chromium/NativeMessagingHosts"),
    Path(".config/microsoft-edge/NativeMessagingHosts"),
    Path(".config/vivaldi/NativeMessagingHosts"),
    Path(".mozilla/native-messaging-hosts"),
)
LEGACY_WINDOWS_REGISTRY_PATHS = (
    rf"Software\Google\Chrome\NativeMessagingHosts\{LEGACY_HOST_NAME}",
    rf"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\{LEGACY_HOST_NAME}",
    rf"Software\Microsoft\Edge\NativeMessagingHosts\{LEGACY_HOST_NAME}",
    rf"Software\Mozilla\NativeMessagingHosts\{LEGACY_HOST_NAME}",
)
RETIRED_REASON = (
    "The legacy browser integration is retired and cannot be registered. "
    "Install a release that includes the secure app.barq.browser integration."
)


@dataclass(frozen=True)
class LegacyBridgeRetirementReport:
    removed_manifests: tuple[Path, ...]
    removed_registry_entries: tuple[str, ...]


class BrowserIntegrationManager:
    """Retire the legacy bridge without changing the new native-host flow."""

    @staticmethod
    def register_all_native_hosts() -> dict[str, object]:
        """Report the retired state without registering a browser host."""
        logger.warning("%s", RETIRED_REASON)
        return {"enabled": False, "reason": RETIRED_REASON}

    @staticmethod
    def legacy_manifest_paths(home_directory: Path) -> tuple[Path, ...]:
        """Return only paths previously written by the legacy installers."""
        return tuple(
            home_directory / directory / LEGACY_MANIFEST_FILENAME
            for directory in LEGACY_MANIFEST_DIRECTORIES
        )

    @classmethod
    def retire_legacy_manifests(cls, home_directory: Path) -> tuple[Path, ...]:
        """Remove verified legacy manifests beneath the supplied home directory."""
        removed_manifests = []
        for manifest_path in cls.legacy_manifest_paths(home_directory):
            if _remove_verified_legacy_manifest(manifest_path):
                removed_manifests.append(manifest_path)
        return tuple(removed_manifests)

    @classmethod
    def retire_legacy_browser_bridge(cls) -> LegacyBridgeRetirementReport:
        """Remove known legacy registrations at startup without touching new hosts."""
        removed_manifests = cls.retire_legacy_manifests(Path.home())
        removed_registry_entries = _remove_legacy_windows_registry_entries()
        report = LegacyBridgeRetirementReport(removed_manifests, removed_registry_entries)
        if report.removed_manifests or report.removed_registry_entries:
            logger.info("Retired legacy browser bridge registrations")
        return report


def _remove_verified_legacy_manifest(manifest_path: Path) -> bool:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return False

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.warning("Could not inspect legacy browser manifest %s: %s", manifest_path, error)
        return False

    if not isinstance(manifest, dict) or manifest.get("name") != LEGACY_HOST_NAME:
        return False

    try:
        manifest_path.unlink()
    except OSError as error:
        logger.warning("Could not remove legacy browser manifest %s: %s", manifest_path, error)
        return False
    return True


def _remove_legacy_windows_registry_entries() -> tuple[str, ...]:
    if sys.platform != "win32":
        return ()

    import winreg

    removed_registry_entries = []
    for registry_path in LEGACY_WINDOWS_REGISTRY_PATHS:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry_path)
        except FileNotFoundError:
            continue
        except OSError as error:
            logger.warning("Could not remove legacy browser registry entry %s: %s", registry_path, error)
        else:
            removed_registry_entries.append(registry_path)
    return tuple(removed_registry_entries)
