import unittest
from unittest.mock import Mock

from mikroclear.pihole.groups import find_group, set_group_membership
from mikroclear.pihole.models import PiholeClientRecord, PiholeGroup


class PiholeGroupTests(unittest.TestCase):
    def test_membership_update_preserves_unrelated_groups(self):
        client = Mock()
        record = PiholeClientRecord(4, "192.168.10.50", (2, 9))
        group = PiholeGroup(9, "MikroClear-YouTube-Blocked")
        set_group_membership(client, record, group, False)
        client.request.assert_called_once_with("PUT", "/api/clients/4", json={"groups": [2]})

    def test_only_configured_group_is_selected(self):
        client = Mock()
        client.request.return_value = {"groups": [{"id": 1, "name": "Other"}, {"id": 7, "name": "MikroClear-YouTube-Blocked"}]}
        self.assertEqual(find_group(client, "MikroClear-YouTube-Blocked"), PiholeGroup(7, "MikroClear-YouTube-Blocked"))
        client.request.assert_called_once_with("GET", "/api/groups")


if __name__ == "__main__":
    unittest.main()
