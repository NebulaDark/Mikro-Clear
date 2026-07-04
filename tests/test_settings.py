import os
from pathlib import Path
import sys
import types
from unittest import TestCase
from unittest.mock import patch

from mikroclear.settings import Settings


def load_legacy():
    fake_pyinotify = types.SimpleNamespace(ProcessEvent=object)
    with patch.dict(sys.modules, {"pyinotify": fake_pyinotify}):
        from mikroclear import legacy
    return legacy


class SettingsTests(TestCase):
    def test_mikroclear_env_overrides_legacy_env(self):
        with patch.dict(
            os.environ,
            {
                "MIKROCLEAR_ROUTER_IP": "10.0.0.1",
                "MIKROCATA_ROUTER_IP": "192.0.2.1",
                "MIKROCLEAR_ROUTER_PORT": "8729",
                "MIKROCLEAR_USE_SSL": "true",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.router_ip, "10.0.0.1")
        self.assertEqual(settings.port, 8729)
        self.assertTrue(settings.use_ssl)

    def test_computed_paths_use_state_dir(self):
        with patch.dict(os.environ, {"MIKROCLEAR_STATE_DIR": "/tmp/mikroclear-state"}, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.state_dir, str(Path("/tmp/mikroclear-state").resolve()))
        self.assertEqual(
            settings.telegram_unblock_state_file,
            str(Path("/tmp/mikroclear-state/telegram-unblock-actions.json").resolve()),
        )
        self.assertEqual(
            settings.save_lists_location,
            str(Path("/tmp/mikroclear-state/savelists-tzsp0.json").resolve()),
        )

    def test_default_whitelist_includes_wan_and_local_prefix(self):
        with patch.dict(
            os.environ,
            {
                "MIKROCLEAR_WAN_IP": "203.0.113.7",
                "MIKROCLEAR_LOCAL_IP_PREFIX": "10.7.0.0/16",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertIn("203.0.113.7", settings.whitelist_ips)
        self.assertIn("10.7.0.0/16", settings.whitelist_ips)
        self.assertIn("127.0.0.1", settings.whitelist_ips)

    def test_legacy_constants_are_assigned_from_settings(self):
        legacy = load_legacy()

        self.assertIsInstance(legacy.SETTINGS, Settings)
        self.assertEqual(legacy.ROUTER_IP, legacy.SETTINGS.router_ip)
        self.assertEqual(legacy.BLOCK_LIST_NAME, legacy.SETTINGS.block_list_name)
        self.assertEqual(legacy.FILEPATH, legacy.SETTINGS.filepath)
