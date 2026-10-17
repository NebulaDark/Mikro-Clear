import ssl
import unittest
from unittest.mock import Mock, patch

from mikroclear.settings import Settings
from mikroclear.web.router_gateway import RouterWebGateway


class RouterWebGatewayTests(unittest.TestCase):
    def setUp(self):
        self.client_patch = patch("mikroclear.web.router_gateway.RouterOSClient")
        self.client_type = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.client = self.client_type.return_value
        self.api = self.client.lifecycle.ensure_connected.return_value
        self.gateway = RouterWebGateway(
            Settings(monitor_only=False, mangle_control_enable=True)
        )

    def test_mangle_timeout_does_not_retry_mutation(self):
        with patch(
            "mikroclear.web.router_gateway.set_mangle_rule_disabled",
            side_effect=TimeoutError("test timeout"),
        ) as update:
            with self.assertRaises(TimeoutError):
                self.gateway.set_mangle_disabled("*1", True)
        update.assert_called_once()
        self.client.run_with_reconnect.assert_not_called()

    def test_unblock_timeout_does_not_retry_mutation(self):
        with patch(
            "mikroclear.web.router_gateway.remove_from_address_list",
            side_effect=TimeoutError("test timeout"),
        ) as remove:
            with self.assertRaises(TimeoutError):
                self.gateway.unblock("192.0.2.4")
        remove.assert_called_once()
        self.client.run_with_reconnect.assert_not_called()

    def test_monitor_only_blocks_all_router_writes(self):
        gateway = RouterWebGateway(
            Settings(monitor_only=True, mangle_control_enable=True)
        )
        with self.assertRaises(PermissionError):
            gateway.set_mangle_disabled("*1", True)
        with self.assertRaises(PermissionError):
            gateway.unblock("192.0.2.4")
        self.client.lifecycle.ensure_connected.assert_not_called()

    def test_monitor_only_inventory_reads_only_known_router_resources(self):
        gateway = RouterWebGateway(Settings(monitor_only=True, mangle_control_enable=False))
        self.client.run_with_reconnect.side_effect = lambda _name, operation: operation()

        def resource(path):
            if path == "/system/resource":
                return iter([{"version": "test-version", "uptime": "1h"}])
            if path == "/ip/firewall/address-list":
                return iter([
                    {".id": "*1", "list": "Suricata", "address": "198.51.100.7"},
                    {".id": "*2", "list": "unmanaged", "address": "198.51.100.8"},
                ])
            self.fail(f"Unexpected RouterOS path: {path}")

        self.api.path.side_effect = resource
        self.assertEqual(gateway.status()["version"], "test-version")
        self.assertEqual(
            [row["address"] for row in gateway.block_entries()],
            ["198.51.100.7"],
        )
        self.assertEqual(gateway.managed_mangle(), [])
        self.assertEqual(
            [call.args[0] for call in self.api.path.call_args_list],
            ["/system/resource", "/ip/firewall/address-list"],
        )
        self.client.lifecycle.heartbeat.assert_not_called()

    def test_read_errors_are_reported_without_router_mutation(self):
        for error in (TimeoutError("test timeout"), ssl.SSLError("test TLS"), PermissionError("test denied")):
            with self.subTest(error=type(error).__name__):
                self.client.run_with_reconnect.side_effect = error
                with self.assertRaises(type(error)):
                    self.gateway.status()
                self.client.lifecycle.ensure_connected.assert_not_called()
                self.client.lifecycle.heartbeat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
