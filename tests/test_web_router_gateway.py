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


if __name__ == "__main__":
    unittest.main()
