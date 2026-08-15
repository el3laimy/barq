"""Unit tests for Linux Multi-Browser Native Messaging Registration and Registry."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.browser_registry import (
    BROWSER_REGISTRY,
    BROWSER_SPECS,
    HOST_NAME,
    MANIFEST_FILENAME,
    BrowserSpec,
    detect_installed_browsers,
    discover_existing_chromium_origins,
    extension_id_to_origin,
    get_browser_spec,
    get_state_file_path,
    load_registered_manifest_paths,
    resolve_manifest_dirs,
    resolve_manifest_paths,
    save_registered_manifest_paths,
    validate_chromium_extension_id,
    validate_custom_manifest_dir,
    validate_on_disk_manifest,
)
from scripts.setup_browser_integration import (
    command_register,
    generate_chromium_manifest,
    parse_target_arg,
    write_manifest_atomic,
)

VALID_ID_A = "abcdefghijklmnopabcdefghijklmnop"
VALID_ID_B = "ponmlkjihgfedcbaponmlkjihgfedcba"
VALID_ID_BRAVE = "fafdcomcphjhenkfoeomiikdifdmiean"


class TestBrowserRegistryAndValidation(unittest.TestCase):
    """Test registry specifications, extension ID validation, and path resolution."""

    def test_registry_contains_all_expected_browsers(self):
        expected_keys = {"chrome", "brave", "edge", "chromium", "opera", "vivaldi", "firefox"}
        actual_keys = set(BROWSER_REGISTRY.keys())
        self.assertEqual(expected_keys, actual_keys)

        for key in expected_keys:
            spec = get_browser_spec(key)
            self.assertIsNotNone(spec)
            self.assertEqual(spec.key, key)
            self.assertTrue(len(spec.executable_candidates) > 0)
            self.assertTrue(len(spec.linux_manifest_dirs) > 0)

    def test_browser_manifest_paths_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home = Path(temp_dir)
            resolved_paths = {}
            for key, spec in BROWSER_REGISTRY.items():
                paths = resolve_manifest_paths(spec, fake_home)
                self.assertTrue(len(paths) >= 1)
                for p in paths:
                    self.assertNotIn(p, resolved_paths, f"Duplicate manifest path between {key} and {resolved_paths.get(p)}")
                    resolved_paths[p] = key

    def test_valid_chromium_extension_ids(self):
        self.assertEqual(validate_chromium_extension_id(VALID_ID_A), VALID_ID_A)
        self.assertEqual(validate_chromium_extension_id(VALID_ID_B), VALID_ID_B)
        self.assertEqual(validate_chromium_extension_id(VALID_ID_BRAVE), VALID_ID_BRAVE)

    def test_invalid_chromium_extension_ids(self):
        invalid_ids = [
            "",  # empty
            "   ",  # whitespace
            "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEF",  # uppercase
            "abcdefghijklmnopabcdefghijklmnoP",  # mixed case
            f"chrome-extension://{VALID_ID_A}/",  # full url
            f"chrome-extension://{VALID_ID_A}",  # url without trailing slash
            "abcdefghijklmnop",  # too short (16 chars)
            VALID_ID_A + "a",  # too long (33 chars)
            "abcdefghijklmnopabcdefghijklmnoq",  # 'q' is outside [a-p]
            "abcdefghijklmnopabcdefghijklmnoz",  # 'z' is outside [a-p]
            "abcdefghijklmnopabcdefghijklmno0",  # '0' digit
            "*",  # wildcard
            f"{VALID_ID_A[:31]}*",  # wildcard in id
            "../../etc/passwd",  # path traversal
        ]
        for invalid_id in invalid_ids:
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(ValueError):
                    validate_chromium_extension_id(invalid_id)

    def test_extension_id_to_origin_conversion(self):
        origin = extension_id_to_origin(VALID_ID_BRAVE)
        self.assertEqual(origin, f"chrome-extension://{VALID_ID_BRAVE}/")
        self.assertTrue(origin.startswith("chrome-extension://"))
        self.assertTrue(origin.endswith("/"))
        self.assertNotIn("*", origin)

    def test_custom_manifest_dir_validation_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home = Path(temp_dir).resolve()
            custom_dir = fake_home / ".config" / "thorium" / "NativeMessagingHosts"

            validated = validate_custom_manifest_dir(str(custom_dir), home_dir=fake_home)
            self.assertEqual(validated, custom_dir.resolve())

    def test_custom_manifest_dir_validation_rejections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home = Path(temp_dir).resolve()

            # Relative path
            with self.assertRaises(ValueError):
                validate_custom_manifest_dir("relative/path", home_dir=fake_home)

            # Home directory root itself
            with self.assertRaises(ValueError):
                validate_custom_manifest_dir(str(fake_home), home_dir=fake_home)

            # Path outside home (system root)
            with self.assertRaises(ValueError):
                validate_custom_manifest_dir("/etc/chromium/native-messaging-hosts", home_dir=fake_home)

            # Directory traversal outside home
            with self.assertRaises(ValueError):
                validate_custom_manifest_dir(str(fake_home / ".." / "other_user"), home_dir=fake_home)


class TestManifestGenerationAndSafety(unittest.TestCase):
    """Test manifest content generation and atomic writing."""

    def test_generate_chromium_manifest_least_privilege(self):
        fake_binary = Path("/opt/barq/barq-native-host")
        origins = [extension_id_to_origin(VALID_ID_BRAVE)]
        manifest = generate_chromium_manifest(fake_binary, origins)

        self.assertEqual(manifest["name"], HOST_NAME)
        self.assertEqual(manifest["type"], "stdio")
        self.assertEqual(manifest["path"], str(fake_binary.resolve()))
        self.assertEqual(manifest["allowed_origins"], [f"chrome-extension://{VALID_ID_BRAVE}/"])

        # Must not contain Firefox fields or wildcards
        self.assertNotIn("allowed_extensions", manifest)
        self.assertNotIn("*", json.dumps(manifest))
        self.assertNotIn("firefox-extension://", json.dumps(manifest))

    def test_write_manifest_atomic_creates_valid_json_and_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_manifest = Path(temp_dir) / "sub" / MANIFEST_FILENAME
            manifest_data = {
                "name": HOST_NAME,
                "description": "Barq Native Messaging Host",
                "path": "/opt/barq/bin",
                "type": "stdio",
                "allowed_origins": [f"chrome-extension://{VALID_ID_A}/"],
            }

            # First write
            write_manifest_atomic(target_manifest, manifest_data)
            self.assertTrue(target_manifest.is_file())

            parsed = json.loads(target_manifest.read_text(encoding="utf-8"))
            self.assertEqual(parsed["name"], HOST_NAME)
            self.assertEqual(parsed["allowed_origins"], [f"chrome-extension://{VALID_ID_A}/"])

            # Second write with update -> should create .bak backup
            updated_data = dict(manifest_data)
            updated_data["allowed_origins"] = [f"chrome-extension://{VALID_ID_B}/"]
            write_manifest_atomic(target_manifest, updated_data)

            backup_file = target_manifest.with_suffix(target_manifest.suffix + ".bak")
            self.assertTrue(backup_file.is_file())
            backup_parsed = json.loads(backup_file.read_text(encoding="utf-8"))
            self.assertEqual(backup_parsed["allowed_origins"], [f"chrome-extension://{VALID_ID_A}/"])

            new_parsed = json.loads(target_manifest.read_text(encoding="utf-8"))
            self.assertEqual(new_parsed["allowed_origins"], [f"chrome-extension://{VALID_ID_B}/"])


class TestSetupBrowserIntegrationLifecycle(unittest.TestCase):
    """Test registration lifecycle, multi-browser isolation, state tracking, and discovery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fake_home = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("scripts.setup_browser_integration.build_native_host")
    def test_brave_only_registration_writes_brave_only(self, mock_build):
        mock_build.return_value = Path("/fake/bin/barq-native-host")

        code = command_register(
            targets=[f"brave:{VALID_ID_BRAVE}"],
            home_dir=self.fake_home,
        )
        self.assertEqual(code, 0)

        # Brave manifest must exist
        brave_spec = BROWSER_REGISTRY["brave"]
        brave_manifests = resolve_manifest_paths(brave_spec, self.fake_home)
        self.assertTrue(brave_manifests[0].is_file())

        brave_data = json.loads(brave_manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(brave_data["allowed_origins"], [f"chrome-extension://{VALID_ID_BRAVE}/"])

        # Chrome and Edge must NOT exist
        chrome_manifests = resolve_manifest_paths(BROWSER_REGISTRY["chrome"], self.fake_home)
        self.assertFalse(chrome_manifests[0].exists())
        edge_manifests = resolve_manifest_paths(BROWSER_REGISTRY["edge"], self.fake_home)
        self.assertFalse(edge_manifests[0].exists())

        # Native host built with Brave origin
        mock_build.assert_called_once_with([f"chrome-extension://{VALID_ID_BRAVE}/"], dry_run=False)

    @patch("scripts.setup_browser_integration.build_native_host")
    def test_multi_target_registration_preserves_per_browser_least_privilege(self, mock_build):
        mock_build.return_value = Path("/fake/bin/barq-native-host")

        code = command_register(
            targets=[f"brave:{VALID_ID_BRAVE}", f"chrome:{VALID_ID_A}"],
            home_dir=self.fake_home,
        )
        self.assertEqual(code, 0)

        # Brave manifest must contain ONLY Brave origin
        brave_manifest = resolve_manifest_paths(BROWSER_REGISTRY["brave"], self.fake_home)[0]
        self.assertTrue(brave_manifest.is_file())
        brave_data = json.loads(brave_manifest.read_text(encoding="utf-8"))
        self.assertEqual(brave_data["allowed_origins"], [f"chrome-extension://{VALID_ID_BRAVE}/"])

        # Chrome manifest must contain ONLY Chrome origin
        chrome_manifest = resolve_manifest_paths(BROWSER_REGISTRY["chrome"], self.fake_home)[0]
        self.assertTrue(chrome_manifest.is_file())
        chrome_data = json.loads(chrome_manifest.read_text(encoding="utf-8"))
        self.assertEqual(chrome_data["allowed_origins"], [f"chrome-extension://{VALID_ID_A}/"])

        # Native host built with UNION of both origins
        expected_union = sorted([f"chrome-extension://{VALID_ID_BRAVE}/", f"chrome-extension://{VALID_ID_A}/"])
        mock_build.assert_called_once_with(expected_union, dry_run=False)

    @patch("scripts.setup_browser_integration.build_native_host")
    def test_consecutive_registrations_preserve_existing_callers(self, mock_build):
        mock_build.return_value = Path("/fake/bin/barq-native-host")

        # 1. Register Brave first
        command_register(targets=[f"brave:{VALID_ID_BRAVE}"], home_dir=self.fake_home)
        brave_manifest = resolve_manifest_paths(BROWSER_REGISTRY["brave"], self.fake_home)[0]
        self.assertTrue(brave_manifest.is_file())

        # 2. Later register Chrome in a separate invocation
        mock_build.reset_mock()
        command_register(targets=[f"chrome:{VALID_ID_A}"], home_dir=self.fake_home)

        # Second build must contain UNION (Brave + Chrome)
        expected_union = sorted([f"chrome-extension://{VALID_ID_BRAVE}/", f"chrome-extension://{VALID_ID_A}/"])
        mock_build.assert_called_once_with(expected_union, dry_run=False)

        # Brave manifest still contains ONLY Brave origin
        brave_data = json.loads(brave_manifest.read_text(encoding="utf-8"))
        self.assertEqual(brave_data["allowed_origins"], [f"chrome-extension://{VALID_ID_BRAVE}/"])

        # Chrome manifest contains ONLY Chrome origin
        chrome_manifest = resolve_manifest_paths(BROWSER_REGISTRY["chrome"], self.fake_home)[0]
        chrome_data = json.loads(chrome_manifest.read_text(encoding="utf-8"))
        self.assertEqual(chrome_data["allowed_origins"], [f"chrome-extension://{VALID_ID_A}/"])

    @patch("scripts.setup_browser_integration.build_native_host")
    def test_custom_chromium_registration_and_state_preservation(self, mock_build):
        mock_build.return_value = Path("/fake/bin/barq-native-host")
        custom_dir = self.fake_home / ".config" / "thorium" / "NativeMessagingHosts"

        # 1. Register Custom Chromium browser
        command_register(
            targets=[],
            custom_manifest_dir=str(custom_dir),
            custom_extension_id=VALID_ID_A,
            home_dir=self.fake_home,
        )

        custom_manifest = custom_dir / MANIFEST_FILENAME
        self.assertTrue(custom_manifest.is_file())
        custom_data = json.loads(custom_manifest.read_text(encoding="utf-8"))
        self.assertEqual(custom_data["allowed_origins"], [f"chrome-extension://{VALID_ID_A}/"])

        # Verify state file recorded the custom manifest path
        state_entries = load_registered_manifest_paths(self.fake_home)
        self.assertTrue(any(path == custom_manifest for _, path in state_entries))

        # 2. Later register Brave in a separate invocation
        mock_build.reset_mock()
        command_register(
            targets=[f"brave:{VALID_ID_BRAVE}"],
            home_dir=self.fake_home,
        )

        # Host rebuilt with union (Custom + Brave)
        expected_union = sorted([f"chrome-extension://{VALID_ID_A}/", f"chrome-extension://{VALID_ID_BRAVE}/"])
        mock_build.assert_called_once_with(expected_union, dry_run=False)

        # Custom manifest untouched
        custom_data_after = json.loads(custom_manifest.read_text(encoding="utf-8"))
        self.assertEqual(custom_data_after["allowed_origins"], [f"chrome-extension://{VALID_ID_A}/"])

    @patch("scripts.setup_browser_integration.build_native_host")
    def test_missing_or_malformed_manifests_do_not_inject_stale_origins(self, mock_build):
        mock_build.return_value = Path("/fake/bin/barq-native-host")

        # 1. Write an unrelated manifest
        unrelated_dir = self.fake_home / ".config" / "google-chrome" / "NativeMessagingHosts"
        unrelated_dir.mkdir(parents=True, exist_ok=True)
        unrelated_file = unrelated_dir / "com.other.host.json"
        unrelated_file.write_text(json.dumps({"name": "com.other.host", "allowed_origins": [f"chrome-extension://{VALID_ID_A}/"]}))

        # 2. Write a malformed Barq manifest in an untargeted location
        corrupt_dir = self.fake_home / ".config" / "chromium" / "NativeMessagingHosts"
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        corrupt_file = corrupt_dir / MANIFEST_FILENAME
        corrupt_file.write_text("NOT_JSON")

        # Register Brave
        command_register(targets=[f"brave:{VALID_ID_BRAVE}"], home_dir=self.fake_home)

        # Only Brave origin should be built; unrelated & corrupt manifests ignored
        mock_build.assert_called_once_with([f"chrome-extension://{VALID_ID_BRAVE}/"], dry_run=False)

    @patch("scripts.setup_browser_integration.build_native_host")
    def test_malformed_targeted_manifest_fails_registration_clearly(self, mock_build):
        mock_build.return_value = Path("/fake/bin/barq-native-host")
        brave_dir = self.fake_home / ".config" / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts"
        brave_dir.mkdir(parents=True, exist_ok=True)
        brave_manifest = brave_dir / MANIFEST_FILENAME
        brave_manifest.write_text("{corrupt_json")

        with self.assertRaises(ValueError) as ctx:
            command_register(targets=[f"brave:{VALID_ID_BRAVE}"], home_dir=self.fake_home)

        self.assertIn("corrupt/malformed", str(ctx.exception))

    @patch("scripts.setup_browser_integration.build_native_host")
    def test_dry_run_writes_nothing_and_does_not_modify_state(self, mock_build):
        mock_build.return_value = Path("/fake/bin/barq-native-host")

        code = command_register(
            targets=[f"brave:{VALID_ID_BRAVE}"],
            dry_run=True,
            home_dir=self.fake_home,
        )
        self.assertEqual(code, 0)

        # No manifests written
        brave_manifest = resolve_manifest_paths(BROWSER_REGISTRY["brave"], self.fake_home)[0]
        self.assertFalse(brave_manifest.exists())

        # No state file created
        state_file = get_state_file_path(self.fake_home)
        self.assertFalse(state_file.exists())

    def test_firefox_target_rejected_with_clear_message(self):
        with self.assertRaises(ValueError) as ctx:
            parse_target_arg("firefox:integration@barq.app")
        self.assertIn("Firefox uses a different Native Messaging manifest format", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
