import unittest
from unittest.mock import Mock

from mikroclear.pihole.groups import add_client, find_client, find_group, set_group_membership
from mikroclear.pihole.models import PiholeClientRecord, PiholeGroup


class PiholeGroupTests(unittest.TestCase):
    def test_allow_targets_client_address_instead_of_database_id(self):
        client = Mock()
        record = PiholeClientRecord(4, "192.168.10.50", (0, 9))
        set_group_membership(client, record, PiholeGroup(9, "YouTube"), False)
        self.assertEqual(client.request.call_args.args, ("PUT", "/api/clients/192.168.10.50"))

    def test_membership_update_preserves_existing_comment(self):
        client = Mock()
        client.request.return_value = {"clients": [
            {"id": 4, "client": "192.168.10.50", "groups": [0, 9], "comment": "Living room TV"}
        ]}
        record = find_client(client, "192.168.10.50")
        client.request.reset_mock()
        set_group_membership(client, record, PiholeGroup(9, "YouTube"), False)
        self.assertEqual(client.request.call_args.kwargs["json"], {"groups": [0], "comment": "Living room TV"})

    def test_created_client_retains_default_group_from_nested_api_response(self):
        client = Mock()
        client.request.return_value = {"clients": [
            {"id": 4, "client": "192.168.10.50", "groups": [0], "comment": None}
        ], "processed": {"success": [{"item": "192.168.10.50"}], "errors": []}}
        record = add_client(client, "192.168.10.50")
        self.assertEqual((record.id, record.client, record.groups), (4, "192.168.10.50", (0,)))

    def test_membership_update_preserves_unrelated_groups(self):
        client = Mock()
        record = PiholeClientRecord(4, "192.168.10.50", (2, 9))
        group = PiholeGroup(9, "MikroClear-YouTube-Blocked")
        set_group_membership(client, record, group, False)
        client.request.assert_called_once_with("PUT", "/api/clients/192.168.10.50", json={"groups": [2], "comment": None})

    def test_only_configured_group_is_selected(self):
        client = Mock()
        client.request.return_value = {"groups": [{"id": 1, "name": "Other"}, {"id": 7, "name": "MikroClear-YouTube-Blocked"}]}
        self.assertEqual(find_group(client, "MikroClear-YouTube-Blocked"), PiholeGroup(7, "MikroClear-YouTube-Blocked"))
        client.request.assert_called_once_with("GET", "/api/groups")


if __name__ == "__main__":
    unittest.main()
