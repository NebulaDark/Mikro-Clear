from unittest import TestCase
from unittest.mock import Mock

from mikroclear.suricata.whitelist_policy import WhitelistPolicy


class WhitelistPolicyTests(TestCase):
    def test_policy_merges_system_cidr_and_current_managed_snapshot(self):
        store = Mock()
        store.snapshot.side_effect = [
            ("192.168.98.200",),
            ("192.168.98.200", "10.0.0.9"),
        ]
        policy = WhitelistPolicy(("172.16.0.0/12",), store)

        self.assertEqual(
            policy.snapshot(),
            ("172.16.0.0/12", "192.168.98.200"),
        )
        self.assertTrue(policy.contains("10.0.0.9"))

    def test_policy_snapshot_preserves_system_order_and_removes_duplicates(self):
        store = Mock()
        store.snapshot.return_value = ("10.0.0.9", "192.168.98.200")
        policy = WhitelistPolicy(
            ("172.16.0.0/12", "10.0.0.9", "172.16.0.0/12"),
            store,
        )

        self.assertEqual(
            policy.snapshot(),
            ("172.16.0.0/12", "10.0.0.9", "192.168.98.200"),
        )
