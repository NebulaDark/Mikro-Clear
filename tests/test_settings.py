import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from mikroclear.settings import Settings, load_settings


class SettingsTests(TestCase):
    def test_default_ca_file_uses_mikroclear_config_tree(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()

        self.assertEqual(
            settings.ca_file,
            "/etc/mikroclear/certs/mikrotik-ca.crt",
        )

    def test_telegram_long_poll_seconds_default_and_env(self):
        self.assertEqual(Settings().telegram_long_poll_seconds, 25)

        with patch.dict(
            os.environ,
            {"MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS": "40"},
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.telegram_long_poll_seconds, 40)

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

    def test_load_settings_is_runtime_loader_boundary(self):
        with patch.object(Settings, "from_env", return_value=Settings(router_ip="10.9.0.1")) as from_env:
            settings = load_settings()

        from_env.assert_called_once_with()
        self.assertEqual(settings.router_ip, "10.9.0.1")

    def test_computed_paths_use_state_dir(self):
        with patch.dict(os.environ, {"MIKROCLEAR_STATE_DIR": "/tmp/mikroclear-state"}, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.state_dir, str(Path("/tmp/mikroclear-state").resolve()))
        self.assertFalse(settings.telegram_whitelist_control_enable)
        self.assertEqual(
            settings.dynamic_whitelist_file,
            str(Path("/tmp/mikroclear-state/dynamic-whitelist.json").resolve()),
        )
        self.assertEqual(
            settings.telegram_whitelist_state_file,
            str(Path("/tmp/mikroclear-state/telegram-whitelist-actions.json").resolve()),
        )
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

    def test_settings_object_is_runtime_config_boundary(self):
        settings = Settings(router_ip="10.9.0.1", block_list_name="Threats", filepath="/tmp/eve.json")

        self.assertEqual(settings.router_ip, "10.9.0.1")
        self.assertEqual(settings.block_list_name, "Threats")
        self.assertEqual(settings.filepath, "/tmp/eve.json")

    def test_settings_loader_uses_canonical_mikroclear_names(self):
        source = Path("src/mikroclear/settings.py").read_text(encoding="utf-8")

        self.assertIn("MIKROCLEAR_ROUTER_IP", source)
        self.assertNotIn("MIKROCATA_ROUTER_IP", source)

    def test_mangle_control_settings_defaults_and_env(self):
        with patch.dict(
            os.environ,
            {
                "MIKROCLEAR_MANGLE_CONTROL_ENABLE": "true",
                "MIKROCLEAR_MANGLE_COMMENT_PREFIX": "MC:",
                "MIKROCLEAR_MANGLE_ALLOWED_CHAINS": "prerouting,forward",
                "MIKROCLEAR_MANGLE_ALLOWED_ACTIONS": "mark-routing,accept",
                "MIKROCLEAR_MANGLE_REQUIRE_CONFIRMATION": "false",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertTrue(settings.mangle_control_enable)
        self.assertEqual(settings.mangle_comment_prefix, "MC:")
        self.assertEqual(settings.mangle_allowed_chains, ("prerouting", "forward"))
        self.assertEqual(settings.mangle_allowed_actions, ("mark-routing", "accept"))
        self.assertFalse(settings.mangle_require_confirmation)

    def test_mangle_control_settings_default_allowlist_is_narrow(self):
        settings = Settings()

        self.assertEqual(settings.mangle_allowed_chains, ("prerouting",))
        self.assertEqual(settings.mangle_allowed_actions, ("mark-routing",))
