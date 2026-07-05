import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from mikroclear.alert_processor import AlertProcessorConfig, process_single_alert
from mikroclear.config import env_str
from mikroclear.routeros.client import RouterOSClient
from mikroclear.settings import Settings
from mikroclear.telegram.formatting import format_alert_message


ROOT = Path(__file__).resolve().parents[1]


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
        with patch.dict(
            os.environ,
            {
                "MIKROCLEAR_ROUTER_IP": "10.0.0.1",
                "MIKROCATA_ROUTER_IP": "192.0.2.1",
            },
        ):
            self.assertEqual(env_str("MIKROCATA_ROUTER_IP"), "10.0.0.1")

    def test_telegram_branding_uses_mikro_clear(self):
        text = format_alert_message(
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

        send_telegram = Mock()
        log = Mock()
        process_single_alert(
            event,
            address_list,
            None,
            config=AlertProcessorConfig(
                severities=("1", "2"),
                listen_interfaces=("tzsp0",),
                whitelist_ips=(),
                block_list_name="Suricata",
                timeout="1d",
            ),
            ignore_predicate=lambda item: False,
            send_telegram=send_telegram,
            log=log,
            debug_log=Mock(),
        )

        address_list.add.assert_called_once()
        send_telegram.assert_called_once()
        self.assertTrue(any("Severity:2" in call.args[0] for call in log.call_args_list))

    def test_routeros_connect_notification_can_be_disabled(self):
        send_system_notification = Mock()
        client = RouterOSClient(
            Settings(
                username="user",
                password="password",
                router_ip="192.168.10.1",
                router_connect_notify_enable=False,
            ),
            log=Mock(),
            send_system_notification=send_system_notification,
            sleep=Mock(),
            time=Mock(return_value=100.0),
        )

        with patch.object(client, "connect_once", return_value=object()):
            client.connect()

        send_system_notification.assert_not_called()
