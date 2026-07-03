import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from mikroclear.config import env_bool, env_csv, env_int, env_name_candidates, env_str


ENV_EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "mikroclear.env.example"


class ConfigEnvTests(TestCase):
    def test_mikroclear_name_precedes_legacy_mikrocata_name(self):
        self.assertEqual(
            env_name_candidates("MIKROCATA_ROUTER_IP"),
            ("MIKROCLEAR_ROUTER_IP", "MIKROCATA_ROUTER_IP"),
        )
        self.assertEqual(env_name_candidates("CUSTOM_NAME"), ("CUSTOM_NAME",))

    def test_env_str_prefers_mikroclear_value_over_legacy_value(self):
        with patch.dict(
            os.environ,
            {
                "MIKROCLEAR_ROUTER_IP": " 10.0.0.1 ",
                "MIKROCATA_ROUTER_IP": "192.0.2.1",
            },
            clear=True,
        ):
            self.assertEqual(env_str("MIKROCATA_ROUTER_IP", "default"), "10.0.0.1")

    def test_env_bool_parses_truthy_values_and_default(self):
        with patch.dict(os.environ, {"MIKROCLEAR_TELEGRAM_ENABLE": " yes "}, clear=True):
            self.assertTrue(env_bool("MIKROCATA_TELEGRAM_ENABLE", False))

        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(env_bool("MIKROCATA_TELEGRAM_ENABLE", True))

    def test_env_int_returns_default_for_empty_or_invalid_values(self):
        with patch.dict(os.environ, {"MIKROCLEAR_ROUTER_PORT": " 8729 "}, clear=True):
            self.assertEqual(env_int("MIKROCATA_ROUTER_PORT", 1), 8729)

        with patch.dict(os.environ, {"MIKROCLEAR_ROUTER_PORT": "not-int"}, clear=True):
            self.assertEqual(env_int("MIKROCATA_ROUTER_PORT", 8728), 8728)

    def test_env_csv_splits_commas_semicolons_newlines_and_strips_quotes(self):
        with patch.dict(
            os.environ,
            {"MIKROCLEAR_WHITELIST_IPS": " '1.1.1.1', \"8.8.8.8\";9.9.9.9\n4.4.4.4 "},
            clear=True,
        ):
            self.assertEqual(
                env_csv("MIKROCATA_WHITELIST_IPS", ("default",)),
                ("1.1.1.1", "8.8.8.8", "9.9.9.9", "4.4.4.4"),
            )

        with patch.dict(os.environ, {"MIKROCLEAR_WHITELIST_IPS": ""}, clear=True):
            self.assertEqual(env_csv("MIKROCATA_WHITELIST_IPS", ("default",)), ("default",))

    def test_env_example_uses_mikroclear_names_and_state_dir(self):
        text = ENV_EXAMPLE.read_text(encoding="utf-8")

        self.assertIn("MIKROCLEAR_STATE_DIR=/var/lib/mikroclear", text)
        self.assertIn("MIKROCLEAR_TELEGRAM_TOKEN=", text)
        self.assertNotIn("MIKROCATA_", text)
