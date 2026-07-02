import os
from pathlib import Path
import sys
import types
from unittest import TestCase
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_legacy():
    fake_pyinotify = types.SimpleNamespace(ProcessEvent=object)
    with patch.dict(sys.modules, {"pyinotify": fake_pyinotify}):
        from mikroclear import legacy
    return legacy


class RebrandTests(TestCase):
    def test_mikroclear_package_is_primary_import(self):
        import mikroclear.alert_logic
        import mikroclear.events
        import mikroclear.telegram_unblock

        self.assertTrue(mikroclear.alert_logic.is_valid_ip("1.1.1.1"))

    def test_old_mikrocata_imports_still_work(self):
        import mikrocata.alert_logic

        self.assertTrue(mikrocata.alert_logic.is_valid_ip("1.1.1.1"))

    def test_mikroclear_env_takes_precedence_over_legacy_env(self):
        legacy = load_legacy()
        with patch.dict(
            os.environ,
            {
                "MIKROCLEAR_ROUTER_IP": "10.0.0.1",
                "MIKROCATA_ROUTER_IP": "192.0.2.1",
            },
        ):
            self.assertEqual(legacy.env_str("MIKROCATA_ROUTER_IP"), "10.0.0.1")

    def test_telegram_branding_uses_mikro_clear(self):
        legacy = load_legacy()
        text = legacy.format_telegram_message_safe(
            {
                "timestamp": "2026-07-02T12:00:00.000000+0300",
                "proto": "TCP",
                "in_iface": "tzsp0",
                "alert": {
                    "signature_id": 1,
                    "gid": 1,
                    "severity": 2,
                    "category": "test",
                    "signature": "test alert",
                },
            },
            "9.9.9.9",
            "8.8.4.4",
            443,
            "BLOCKED",
        )

        self.assertIn("Mikro-Clear Alert", text)
        self.assertIn("#mikroclear", text)
        self.assertNotIn("Mikrocata Alert", text)

    def test_new_unit_and_env_example_names_exist(self):
        self.assertTrue((ROOT / "systemd" / "mikroclear.service").exists())
        self.assertTrue((ROOT / "config" / "mikroclear.env.example").exists())

    def test_process_single_alert_logs_severity_without_name_error(self):
        legacy = load_legacy()
        address_list = Mock()
        event = {
            "src_ip": "9.9.9.9",
            "dest_ip": "8.8.4.4",
            "dest_port": 443,
            "proto": "TCP",
            "in_iface": "tzsp0",
            "alert": {
                "signature_id": 2402000,
                "gid": 1,
                "severity": 2,
                "signature": "ET DROP test",
            },
        }

        with (
            patch.object(legacy, "SEVERITY", ("1", "2")),
            patch.object(legacy, "LISTEN_INTERFACES", ("tzsp0",)),
            patch.object(legacy, "ENABLE_IPV6", False),
            patch.object(legacy, "WHITELIST_IPS", ()),
            patch.object(legacy, "MONITOR_ONLY", False),
            patch.object(legacy, "ignore_list", []),
            patch.object(legacy, "sendTelegram") as send_telegram,
            patch.object(legacy, "log") as log,
        ):
            legacy.process_single_alert(event, address_list, None)

        address_list.add.assert_called_once()
        send_telegram.assert_called_once()
        self.assertTrue(any("Severity:2" in call.args[0] for call in log.call_args_list))
