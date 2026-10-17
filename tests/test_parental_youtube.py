import unittest
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
from unittest.mock import Mock

from mikroclear.parental.models import ParentalDevice
from mikroclear.parental.youtube import YouTubePolicyService, YouTubePolicyError
from mikroclear.pihole.models import PiholeClientRecord, PiholeGroup
from mikroclear.pihole.client import PiholeClient, PiholeClientError


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


class YouTubePiholeRoundTripTests(unittest.TestCase):
    def test_two_televisions_can_be_blocked_and_allowed_independently(self):
        devices = [ParentalDevice("192.168.10.50", "TV 1", ""),
                   ParentalDevice("192.168.10.51", "TV 2", "")]
        records = {}

        def response(payload, status=200):
            return SimpleNamespace(status_code=status, json=lambda: deepcopy(payload), text="")

        def get(url, **kwargs):
            path = urlsplit(url).path
            if path == "/api/groups":
                return response({"groups": [{"id": 7, "name": "YouTube"}]})
            self.assertEqual(path, "/api/clients")
            return response({"clients": list(records.values())})

        def post(url, *, json, **kwargs):
            if urlsplit(url).path == "/api/auth":
                return response({"session": {"sid": "test-session"}})
            self.assertEqual(urlsplit(url).path, "/api/clients")
            ip = json["client"]
            records[ip] = {"id": len(records) + 10, "client": ip, "groups": [0], "comment": None}
            return response({"clients": [records[ip]]}, 201)

        def put(url, *, json, **kwargs):
            ip = unquote(urlsplit(url).path.removeprefix("/api/clients/"))
            if ip not in records:
                # Pi-hole's batch-style response may report an item error with HTTP 200.
                return response({"processed": {"success": [], "errors": [{"item": ip}]}})
            records[ip].update(json)
            return response({"clients": [records[ip]]})

        inventory = Mock()
        inventory.is_parental_device.side_effect = lambda ip: ip in {d.ip for d in devices}
        client = PiholeClient("https://pihole.test", "test-password",
                              request_get=get, request_post=post, request_put=put)
        service = YouTubePolicyService(inventory, client, group_name="YouTube")
        for device in devices:
            self.assertTrue(service.block(device).blocked)
        self.assertFalse(service.allow(devices[0]).blocked)
        self.assertTrue(service.get_state(devices[1]).blocked)
        self.assertFalse(service.allow(devices[1]).blocked)
        for device in devices:
            self.assertEqual(records[device.ip]["groups"], [0])
            self.assertFalse(service.allow(device).blocked)
            self.assertTrue(service.block(device).blocked)
            self.assertFalse(service.allow(device).blocked)


if __name__ == "__main__":
    unittest.main()
