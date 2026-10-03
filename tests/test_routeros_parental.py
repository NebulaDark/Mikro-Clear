import unittest

from mikroclear.routeros.parental import list_parental_devices


class Resource:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *fields):
        return self

    def where(self, *args):
        return self.rows


class Api:
    def __init__(self, rows):
        self.resource = Resource(rows)
        self.write_calls = []

    def path(self, value):
        self.path_value = value
        return self.resource

    def add(self, *args, **kwargs):
        self.write_calls.append("add")
        raise AssertionError("RouterOS parental inventory attempted add")

    update = remove = delete = set = add


class RouterOsParentalTests(unittest.TestCase):
    def test_only_configured_address_list_is_exposed_and_comments_are_parsed(self):
        api = Api([
            {".id": "*1", "list": "MC-Parental", "address": "192.168.10.50", "comment": "Tablet"},
            {".id": "*2", "list": "Suricata", "address": "192.168.10.51", "comment": "hidden"},
            {".id": "*3", "list": "MC-Parental", "address": "not-an-ip", "comment": "bad"},
        ])
        devices = list_parental_devices(api, "MC-Parental")
        self.assertEqual([(item.ip, item.comment) for item in devices], [("192.168.10.50", "Tablet")])
        self.assertEqual(api.path_value, "/ip/firewall/address-list")

    def test_inventory_has_no_routeros_write_operations(self):
        api = Api([{"list": "MC-Parental", "address": "192.168.10.50"}])
        devices = list_parental_devices(api, "MC-Parental")
        self.assertEqual([device.ip for device in devices], ["192.168.10.50"])
        self.assertEqual(api.write_calls, [])


if __name__ == "__main__":
    unittest.main()
