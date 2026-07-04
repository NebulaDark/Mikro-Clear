import os
from pathlib import Path
import tempfile
from unittest import TestCase

from mikroclear.state_store import (
    StateStoreConfig,
    add_saved_lists,
    check_tik_uptime,
    parse_routeros_uptime,
    save_lists,
)


class FakeWhere:
    def __init__(self, rows):
        self.rows = rows

    def where(self, *args):
        return self.rows


class FakeAddressList:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []

    def select(self, *keys):
        return FakeWhere(self.rows)

    def add(self, **kwargs):
        self.added.append(kwargs)


class StateStoreTests(TestCase):
    def test_parse_routeros_uptime(self):
        self.assertEqual(parse_routeros_uptime("1w2d3h4m5s"), 788645)

    def test_check_tik_uptime_records_bookmark_and_detects_reboot(self):
        with tempfile.TemporaryDirectory() as tmp:
            bookmark = Path(tmp) / "uptime.bookmark"
            config = StateStoreConfig(uptime_bookmark=str(bookmark))

            self.assertFalse(check_tik_uptime([{"uptime": "2h"}], config=config, debug_log=lambda _message: None))
            self.assertTrue(check_tik_uptime([{"uptime": "20m"}], config=config, debug_log=lambda _message: None))
            self.assertEqual(oct(bookmark.stat().st_mode & 0o777), "0o600")

    def test_save_lists_writes_private_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "lists.json"
            config = StateStoreConfig(save_lists_location=str(path), save_lists=("Suricata",))
            address_list = FakeAddressList(
                [
                    {
                        "list": "Suricata",
                        "address": "9.9.9.9",
                        "timeout": "1d",
                        "comment": "test",
                    }
                ]
            )

            save_lists(address_list, config=config, debug_log=lambda _message: None)

            self.assertIn('"address":"9.9.9.9"', path.read_text(encoding="utf-8"))
            self.assertEqual(oct(path.parent.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_add_saved_lists_skips_whitelisted_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lists.json"
            path.write_text(
                '{"list":"Suricata","address":"192.168.10.1","timeout":"1d","comment":"router"}\n'
                '{"list":"Suricata","address":"9.9.9.9","timeout":"1d","comment":"external"}\n',
                encoding="utf-8",
            )
            config = StateStoreConfig(
                save_lists_location=str(path),
                block_list_name="Suricata",
                timeout="1d",
                whitelist_ips=("192.168.10.0/24",),
            )
            address_list = FakeAddressList()

            add_saved_lists(address_list, config=config, debug_log=lambda _message: None)

            self.assertEqual(len(address_list.added), 1)
            self.assertEqual(address_list.added[0]["address"], "9.9.9.9")
