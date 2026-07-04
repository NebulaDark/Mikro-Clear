from unittest import TestCase
from unittest.mock import Mock

from mikroclear.alert_processor import AlertProcessorConfig, process_single_alert


def alert_event(src_ip="9.9.9.9", dest_ip="192.168.10.15"):
    return {
        "src_ip": src_ip,
        "dest_ip": dest_ip,
        "dest_port": 443,
        "proto": "TCP",
        "in_iface": "tzsp0",
        "timestamp": "2026-07-02T12:00:00.000000+0300",
        "alert": {
            "signature_id": 2402000,
            "gid": 1,
            "severity": 2,
            "signature": "ET DROP test",
        },
    }


class AlertProcessorTests(TestCase):
    def test_process_single_alert_blocks_external_source(self):
        address_list = Mock()
        send_telegram = Mock()
        log = Mock()
        config = AlertProcessorConfig(
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            whitelist_ips=("192.168.10.0/24",),
            block_list_name="Suricata",
            timeout="1d",
            comment_time_format="%-d %b %Y %H:%M:%S.%f",
        )

        process_single_alert(
            alert_event(),
            address_list,
            None,
            config=config,
            ignore_predicate=lambda event: False,
            send_telegram=send_telegram,
            log=log,
            debug_log=Mock(),
        )

        address_list.add.assert_called_once()
        self.assertEqual(address_list.add.call_args.kwargs["list"], "Suricata")
        self.assertEqual(address_list.add.call_args.kwargs["address"], "9.9.9.9")
        send_telegram.assert_called_once()
        self.assertEqual(send_telegram.call_args.kwargs["wanted_ip"], "9.9.9.9")
        self.assertEqual(send_telegram.call_args.kwargs["action_type"], "BLOCKED")
        self.assertTrue(any("Severity:2" in call.args[0] for call in log.call_args_list))

    def test_process_single_alert_monitor_only_does_not_add_address(self):
        address_list = Mock()
        send_telegram = Mock()
        config = AlertProcessorConfig(
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            whitelist_ips=("192.168.10.0/24",),
            block_list_name="Suricata",
            timeout="1d",
            monitor_only=True,
        )

        process_single_alert(
            alert_event(),
            address_list,
            None,
            config=config,
            ignore_predicate=lambda event: False,
            send_telegram=send_telegram,
            log=Mock(),
            debug_log=Mock(),
        )

        address_list.add.assert_not_called()
        send_telegram.assert_called_once()
        self.assertEqual(send_telegram.call_args.kwargs["action_type"], "MONITOR")

    def test_process_single_alert_skips_when_both_sides_whitelisted(self):
        address_list = Mock()
        config = AlertProcessorConfig(
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            whitelist_ips=("192.168.10.0/24",),
            block_list_name="Suricata",
            timeout="1d",
        )

        process_single_alert(
            alert_event(src_ip="192.168.10.9", dest_ip="192.168.10.15"),
            address_list,
            None,
            config=config,
            ignore_predicate=lambda event: False,
            send_telegram=Mock(),
            log=Mock(),
            debug_log=Mock(),
        )

        address_list.add.assert_not_called()
