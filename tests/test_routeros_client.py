import socket
from unittest import TestCase

from mikroclear.routeros_client import (
    RouterOsClientConfig,
    RouterOsConnectionManager,
    add_to_address_list,
    remove_from_address_list,
)


class FakeWhere:
    def __init__(self, rows):
        self.rows = rows
        self.where_args = None

    def where(self, *args):
        self.where_args = args
        return self.rows


class FakeAddressList:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.removed = []
        self.added = []
        self.last_select = None

    def select(self, *keys):
        self.last_select = keys
        return FakeWhere(self.rows)

    def remove(self, row_id):
        self.removed.append(row_id)

    def add(self, **kwargs):
        self.added.append(kwargs)


class RouterOsAddressListTests(TestCase):
    def test_remove_from_address_list_removes_matching_rows_and_returns_count(self):
        address_list = FakeAddressList(
            [
                {".id": "*1", "list": "Suricata", "address": "1.1.1.1"},
                {".id": "*2", "list": "Suricata", "address": "1.1.1.1"},
            ]
        )

        removed = remove_from_address_list(address_list, "Suricata", "1.1.1.1")

        self.assertEqual(removed, 2)
        self.assertEqual(address_list.removed, ["*1", "*2"])
        self.assertEqual(len(address_list.last_select), 3)

    def test_add_to_address_list_passes_routeros_fields(self):
        address_list = FakeAddressList()

        add_to_address_list(address_list, "Suricata", "1.1.1.1", "comment", "30d")

        self.assertEqual(
            address_list.added,
            [{"list": "Suricata", "address": "1.1.1.1", "comment": "comment", "timeout": "30d"}],
        )


class RouterOsConnectionManagerTests(TestCase):
    def test_run_with_reconnect_retries_transient_errors_once(self):
        events = []
        attempts = {"count": 0}

        manager = RouterOsConnectionManager(
            RouterOsClientConfig(reconnect_sleep_seconds=0),
            heartbeat=lambda force=False: events.append(("heartbeat", force)) or True,
            reconnect=lambda reason="": events.append(("reconnect", reason)),
            log=lambda message: events.append(("log", message)),
            sleep=lambda seconds: events.append(("sleep", seconds)),
        )

        def operation():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise socket.timeout("read timed out")
            return "ok"

        self.assertEqual(manager.run_with_reconnect("test operation", operation), "ok")
        self.assertEqual(attempts["count"], 2)
        self.assertIn(("heartbeat", False), events)
        self.assertIn(("reconnect", "test operation failed"), events)
