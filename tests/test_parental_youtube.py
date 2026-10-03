import unittest
from unittest.mock import Mock

from mikroclear.parental.models import ParentalDevice
from mikroclear.parental.youtube import YouTubePolicyService, YouTubePolicyError
from mikroclear.pihole.models import PiholeClientRecord, PiholeGroup
from mikroclear.pihole.client import PiholeClientError


class YouTubePolicyTests(unittest.TestCase):
    def setUp(self):
        self.device = ParentalDevice("192.168.10.50", "Tablet", "Tablet")
        self.inventory = Mock()
        self.inventory.is_parental_device.side_effect = lambda ip: ip == self.device.ip
        self.pihole = Mock()
        self.service = YouTubePolicyService(
            self.inventory,
            self.pihole,
            group_name="MikroClear-YouTube-Blocked",
        )

    def test_block_preserves_unrelated_groups(self):
        self.pihole.find_group.return_value = PiholeGroup(7, "MikroClear-YouTube-Blocked")
        record = PiholeClientRecord(9, self.device.ip, (1,))
        self.pihole.find_client.side_effect = lambda _ip: record

        def add_membership(current, group, enabled):
            nonlocal record
            record = PiholeClientRecord(current.id, current.client, tuple(set(current.groups) | {group.id}))

        self.pihole.set_group_membership.side_effect = add_membership
        self.service.block(self.device)
        self.pihole.set_group_membership.assert_called_once_with(
            PiholeClientRecord(9, self.device.ip, (1,)),
            self.pihole.find_group.return_value,
            True,
        )

    def test_unmanaged_device_is_rejected_before_pihole_call(self):
        with self.assertRaises(YouTubePolicyError):
            self.service.block(ParentalDevice("192.168.10.99", "", ""))
        self.pihole.find_group.assert_not_called()

    def test_missing_group_is_controlled_and_does_not_create_client(self):
        self.pihole.find_group.return_value = None
        with self.assertRaises(YouTubePolicyError):
            self.service.block(self.device)
        self.pihole.add_client.assert_not_called()

    def test_block_already_blocked_is_idempotent(self):
        self.pihole.find_group.return_value = PiholeGroup(7, "MikroClear-YouTube-Blocked")
        self.pihole.find_client.return_value = PiholeClientRecord(9, self.device.ip, (1, 7))
        self.service.block(self.device)
        self.pihole.set_group_membership.assert_not_called()

    def test_allow_already_allowed_is_idempotent(self):
        self.pihole.find_group.return_value = PiholeGroup(7, "MikroClear-YouTube-Blocked")
        self.pihole.find_client.return_value = PiholeClientRecord(9, self.device.ip, (1,))
        self.service.allow(self.device)
        self.pihole.set_group_membership.assert_not_called()

    def test_ambiguous_create_is_confirmed_by_readback(self):
        group = PiholeGroup(7, "MikroClear-YouTube-Blocked")
        record = PiholeClientRecord(9, self.device.ip, ())
        confirmed = PiholeClientRecord(9, self.device.ip, (7,))
        self.pihole.find_group.return_value = group
        self.pihole.find_client.side_effect = [None, record, confirmed]
        self.pihole.add_client.side_effect = PiholeClientError("ambiguous", ambiguous=True)
        self.pihole.set_group_membership.side_effect = lambda *_args: None
        self.service.block(self.device)
        self.pihole.add_client.assert_called_once_with(self.device.ip)
        self.pihole.set_group_membership.assert_called_once()

    def test_ambiguous_create_without_readback_is_failure(self):
        self.pihole.find_group.return_value = PiholeGroup(7, "MikroClear-YouTube-Blocked")
        self.pihole.find_client.side_effect = [None, None]
        self.pihole.add_client.side_effect = PiholeClientError("ambiguous", ambiguous=True)
        with self.assertRaises(YouTubePolicyError):
            self.service.block(self.device)
        self.pihole.add_client.assert_called_once_with(self.device.ip)

    def test_ambiguous_membership_update_is_confirmed_by_readback(self):
        group = PiholeGroup(7, "MikroClear-YouTube-Blocked")
        before = PiholeClientRecord(9, self.device.ip, ())
        after = PiholeClientRecord(9, self.device.ip, (7,))
        self.pihole.find_group.return_value = group
        self.pihole.find_client.side_effect = [before, after, after]
        self.pihole.set_group_membership.side_effect = PiholeClientError("ambiguous", ambiguous=True)
        self.service.block(self.device)
        self.pihole.set_group_membership.assert_called_once()

    def test_ambiguous_membership_update_not_reconciled_is_failure(self):
        group = PiholeGroup(7, "MikroClear-YouTube-Blocked")
        before = PiholeClientRecord(9, self.device.ip, ())
        self.pihole.find_group.return_value = group
        self.pihole.find_client.side_effect = [before, before]
        self.pihole.set_group_membership.side_effect = PiholeClientError("ambiguous", ambiguous=True)
        with self.assertRaises(YouTubePolicyError):
            self.service.block(self.device)
        self.pihole.set_group_membership.assert_called_once()


if __name__ == "__main__":
    unittest.main()
