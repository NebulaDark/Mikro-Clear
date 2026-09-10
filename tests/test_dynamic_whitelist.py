import stat
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mikroclear.state.dynamic_whitelist import (
    DynamicWhitelistError,
    DynamicWhitelistStore,
    is_managed_private_ipv4,
)


class ManagedPrivateIpv4Tests(TestCase):
    def test_accepts_only_rfc1918_exact_ipv4(self):
        for value in ("10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.98.200"):
            self.assertTrue(is_managed_private_ipv4(value), value)
        for value in (
            "172.32.0.1",
            "8.8.8.8",
            "127.0.0.1",
            "169.254.1.1",
            "192.168.1.0/24",
            "fe80::1",
            "",
        ):
            self.assertFalse(is_managed_private_ipv4(value), value)


class DynamicWhitelistStoreTests(TestCase):
    def test_add_remove_are_sorted_persistent_and_idempotent(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            store = DynamicWhitelistStore(path)
            self.assertTrue(store.add("192.168.98.200"))
            self.assertFalse(store.add("192.168.98.200"))
            self.assertTrue(store.add("10.0.0.9"))
            self.assertEqual(store.snapshot(), ("10.0.0.9", "192.168.98.200"))
            self.assertEqual(DynamicWhitelistStore(path).snapshot(), store.snapshot())
            self.assertTrue(store.remove("192.168.98.200"))
            self.assertFalse(store.remove("192.168.98.200"))

    def test_invalid_existing_document_fails_closed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            path.write_text('{"version":1,"addresses":["8.8.8.8"]}', encoding="utf-8")
            with self.assertRaises(DynamicWhitelistError):
                DynamicWhitelistStore(path)

    def test_boolean_version_fails_closed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            path.write_text('{"version":true,"addresses":[]}', encoding="utf-8")
            with self.assertRaises(DynamicWhitelistError):
                DynamicWhitelistStore(path)

    def test_invalid_utf8_fails_closed_without_exposing_content(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            path.write_bytes(b'{"version":1,"addresses":["\xff"]}')
            with self.assertRaises(DynamicWhitelistError) as raised:
                DynamicWhitelistStore(path)
            self.assertEqual(
                str(raised.exception),
                "cannot read managed whitelist: UnicodeDecodeError",
            )

    def test_write_is_private_and_leaves_no_temp_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            DynamicWhitelistStore(path).add("10.0.0.8")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_concurrent_adds_do_not_lose_entries(self):
        with TemporaryDirectory() as tmp:
            store = DynamicWhitelistStore(Path(tmp, "dynamic-whitelist.json"))
            addresses = tuple(f"10.0.0.{index}" for index in range(1, 17))
            threads = [
                threading.Thread(target=store.add, args=(address,))
                for address in addresses
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(store.snapshot(), tuple(sorted(addresses)))
