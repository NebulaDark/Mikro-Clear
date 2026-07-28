from unittest import TestCase
from unittest.mock import Mock

from mikroclear.alert_processor import AlertProcessorConfig, process_alert_batch, process_single_alert


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
    def test_dynamic_whitelist_suppresses_routeros_and_blocked_notification(self):
        effective = {"values": ()}
        config = AlertProcessorConfig(
            severities=("2",),
            listen_interfaces=("tzsp0",),
            whitelist_ips=(),
            whitelist_provider=lambda: tuple(effective["values"]),
            block_list_name="Suricata",
            timeout="1d",
        )
        effective["values"] = ("192.168.98.200",)
        address_list = Mock()
        send = Mock()

        process_single_alert(
            alert_event(src_ip="192.168.98.200"),
            address_list,
            None,
            config=config,
            ignore_predicate=lambda _event: False,
            send_telegram=send,
            log=Mock(),
            debug_log=Mock(),
        )

        address_list.add.assert_not_called()
        send.assert_not_called()

    def test_process_single_alert_uses_one_effective_whitelist_snapshot(self):
        provider = Mock(
            side_effect=[
                ("192.168.98.200",),
                (),
            ]
        )
        config = AlertProcessorConfig(
            severities=("2",),
            listen_interfaces=("tzsp0",),
            whitelist_ips=(),
            whitelist_provider=provider,
            block_list_name="Suricata",
            timeout="1d",
        )
        address_list = Mock()

        process_single_alert(
            alert_event(src_ip="192.168.98.200"),
            address_list,
            None,
            config=config,
            ignore_predicate=lambda _event: False,
            send_telegram=Mock(),
            log=Mock(),
            debug_log=Mock(),
        )

        provider.assert_called_once_with()
        address_list.add.assert_not_called()

    def test_process_alert_batch_selects_with_system_and_suppresses_with_one_effective_snapshot(self):
        provider = Mock(return_value=("192.168.98.200",))
        config = AlertProcessorConfig(
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            whitelist_ips=(),
            whitelist_provider=provider,
            block_list_name="Suricata",
            timeout="1d",
        )
        client = Mock()
        client.paths.return_value = (Mock(), None, object())
        client.run_with_reconnect.side_effect = lambda _name, func: func()
        processed = []
        external = alert_event(src_ip="8.8.8.8", dest_ip="1.1.1.1")
        managed = alert_event(
            src_ip="192.168.98.200",
            dest_ip="8.8.8.8",
        )

        process_alert_batch(
            [external, managed],
            client=client,
            config=config,
            validate_event=lambda event: event,
            process_single=lambda event, _address_list, _address_list_v6: processed.append(event),
            save_restore=Mock(),
            last_save_time=0,
            save_interval=300,
            now=lambda: 100,
            log=Mock(),
            debug_log=Mock(),
        )

        provider.assert_called_once_with()
        self.assertEqual(processed, [external])

    def test_process_alert_batch_deduplicates_by_target_and_runs_save_callback(self):
        client = Mock()
        address_list = Mock()
        client.paths.return_value = (address_list, None, object())
        client.run_with_reconnect.side_effect = lambda _name, func: func()
        processed = []
        save_restore = Mock()
        config = AlertProcessorConfig(
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            whitelist_ips=("192.168.10.0/24",),
            block_list_name="Suricata",
            timeout="1d",
        )
        first = alert_event(src_ip="192.168.10.9", dest_ip="8.8.8.8")
        second = alert_event(src_ip="192.168.10.10", dest_ip="8.8.8.8")

        last_save_time = process_alert_batch(
            [first, second],
            client=client,
            config=config,
            validate_event=lambda event: event,
            process_single=lambda event, _address_list, _address_list_v6: processed.append(event),
            save_restore=save_restore,
            last_save_time=0,
            save_interval=300,
            now=lambda: 500,
            log=Mock(),
            debug_log=Mock(),
        )

        self.assertEqual(processed, [second])
        save_restore.assert_called_once_with(client)
        self.assertEqual(last_save_time, 500)
        self.assertEqual(
            [call.args[0] for call in client.run_with_reconnect.call_args_list],
            ["processing alerts", "saving/restoring lists"],
        )

    def test_process_alert_batch_returns_existing_save_time_when_no_alerts(self):
        client = Mock()
        config = AlertProcessorConfig(
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            whitelist_ips=(),
            block_list_name="Suricata",
            timeout="1d",
        )

        result = process_alert_batch(
            [],
            client=client,
            config=config,
            validate_event=lambda event: event,
            process_single=Mock(),
            save_restore=Mock(),
            last_save_time=123,
            save_interval=300,
            now=lambda: 500,
            log=Mock(),
            debug_log=Mock(),
        )

        self.assertEqual(result, 123)
        client.run_with_reconnect.assert_not_called()

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
