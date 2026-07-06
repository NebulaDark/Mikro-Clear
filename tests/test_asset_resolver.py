from unittest import TestCase

from mikroclear.assets.resolver import AssetResolver, AssetResolverConfig, sanitize_asset_value


class FakeWhere:
    def __init__(self, rows):
        self.rows = rows

    def where(self, *args):
        return self.rows


class FakeLeases:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *keys):
        return FakeWhere(self.rows)


class FakeApi:
    def __init__(self, rows):
        self.rows = rows

    def path(self, path):
        self.path_name = path
        return FakeLeases(self.rows)


class FakeClient:
    def __init__(self, rows):
        self.api = FakeApi(rows)
        self.reconnects = []

    def ensure_connected(self):
        return self.api

    def reconnect(self, reason):
        self.reconnects.append(reason)


class AssetResolverTests(TestCase):
    def test_sanitize_asset_value_compacts_and_truncates(self):
        self.assertEqual(sanitize_asset_value("  host\n name  ", max_len=20), "host name")
        self.assertEqual(sanitize_asset_value("x" * 10, max_len=6), "xxx...")

    def test_private_only_skips_public_ip(self):
        resolver = AssetResolver(
            AssetResolverConfig(private_only=True),
            get_router_client=lambda: None,
            ptr_lookup=lambda ip: "host.local",
        )

        self.assertEqual(resolver.resolve("8.8.8.8"), {})

    def test_resolve_uses_dhcp_before_ptr(self):
        client = FakeClient(
            [
                {
                    "host-name": "host-a",
                    "comment": "desk",
                    "mac-address": "AA:BB",
                    "server": "dhcp1",
                    "status": "bound",
                    "dynamic": "true",
                }
            ]
        )
        resolver = AssetResolver(
            AssetResolverConfig(private_only=True),
            get_router_client=lambda: client,
            ptr_lookup=lambda ip: "ptr.local",
        )

        asset = resolver.resolve("192.168.10.55")

        self.assertEqual(asset["source"], "dhcp")
        self.assertEqual(asset["name"], "host-a")
        self.assertEqual(asset["mac"], "AA:BB")

    def test_resolve_falls_back_to_ptr_and_caches(self):
        calls = []

        def ptr_lookup(ip):
            calls.append(ip)
            return "ptr.local"

        resolver = AssetResolver(
            AssetResolverConfig(private_only=True, dhcp_enable=False),
            get_router_client=lambda: None,
            ptr_lookup=ptr_lookup,
            now=lambda: 100.0,
        )

        first = resolver.resolve("192.168.10.55")
        second = resolver.resolve("192.168.10.55")

        self.assertEqual(first, second)
        self.assertEqual(first["source"], "ptr")
        self.assertEqual(calls, ["192.168.10.55"])
