import socket
from unittest import TestCase

from mikroclear.routeros.address_list import add_to_address_list, remove_from_address_list
from mikroclear.routeros.client import (
    RouterOsApiLifecycle,
    RouterOsConnectConfig,
    RouterOsClientConfig,
    RouterOsConnectionManager,
    RouterOsLifecycleConfig,
    build_routeros_connect_kwargs,
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


class RouterOsConnectBoundaryTests(TestCase):
    def test_build_routeros_connect_kwargs_uses_ssl_wrapper_when_ssl_enabled(self):
        config = RouterOsConnectConfig(
            username="user",
            password="pass",
            host="192.0.2.1",
            port=8729,
            use_ssl=True,
            tls_server_name="router.local",
        )

        kwargs = build_routeros_connect_kwargs(
            config,
            ssl_context="ctx",
            ssl_wrapper_factory=lambda context, server_name: f"{context}:{server_name}",
            login_method="plain-login",
        )

        self.assertEqual(kwargs["username"], "user")
        self.assertEqual(kwargs["password"], "pass")
        self.assertEqual(kwargs["host"], "192.0.2.1")
        self.assertEqual(kwargs["port"], 8729)
        self.assertEqual(kwargs["login_method"], "plain-login")
        self.assertEqual(kwargs["ssl_wrapper"], "ctx:router.local")

    def test_build_routeros_connect_kwargs_omits_ssl_wrapper_for_plain_api(self):
        config = RouterOsConnectConfig(
            username="user",
            password="pass",
            host="192.0.2.1",
            port=8728,
            use_ssl=False,
            tls_server_name="router.local",
        )

        kwargs = build_routeros_connect_kwargs(
            config,
            ssl_context=None,
            ssl_wrapper_factory=lambda context, server_name: "unexpected",
            login_method=None,
        )

        self.assertNotIn("ssl_wrapper", kwargs)
        self.assertNotIn("login_method", kwargs)


class FakeApi:
    def __init__(self):
        self.closed = False
        self.path_calls = []

    def close(self):
        self.closed = True

    def path(self, name):
        self.path_calls.append(name)
        return [f"resource:{name}"]


class RouterOsApiLifecycleTests(TestCase):
    def test_lifecycle_close_closes_current_api(self):
        api = FakeApi()
        lifecycle = RouterOsApiLifecycle(
            RouterOsLifecycleConfig(),
            connect=lambda: api,
            log=lambda message: None,
            sleep=lambda seconds: None,
            time=lambda: 10.0,
        )
        lifecycle.mark_connected(api)

        lifecycle.close()

        self.assertTrue(api.closed)
        self.assertIsNone(lifecycle.api)

    def test_lifecycle_ensure_connected_connects_once_and_tracks_timestamp(self):
        api = FakeApi()
        lifecycle = RouterOsApiLifecycle(
            RouterOsLifecycleConfig(),
            connect=lambda: api,
            log=lambda message: None,
            sleep=lambda seconds: None,
            time=lambda: 12.0,
        )

        self.assertIs(lifecycle.ensure_connected(), api)
        self.assertEqual(lifecycle.connected_at, 12.0)
        self.assertEqual(lifecycle.last_heartbeat, 0.0)

    def test_lifecycle_paths_returns_ipv4_ipv6_and_resources(self):
        api = FakeApi()
        lifecycle = RouterOsApiLifecycle(
            RouterOsLifecycleConfig(enable_ipv6=True),
            connect=lambda: api,
            log=lambda message: None,
            sleep=lambda seconds: None,
            time=lambda: 12.0,
        )
        lifecycle.mark_connected(api)

        address_list, address_list_v6, resources = lifecycle.paths()

        self.assertEqual(address_list, ["resource:/ip/firewall/address-list"])
        self.assertEqual(address_list_v6, ["resource:/ipv6/firewall/address-list"])
        self.assertEqual(resources, ["resource:/system/resource"])

    def test_lifecycle_reconnect_closes_sleeps_and_reconnects(self):
        old_api = FakeApi()
        new_api = FakeApi()
        events = []
        apis = iter([new_api])
        lifecycle = RouterOsApiLifecycle(
            RouterOsLifecycleConfig(reconnect_sleep_seconds=2),
            connect=lambda: next(apis),
            log=lambda message: events.append(("log", message)),
            sleep=lambda seconds: events.append(("sleep", seconds)),
            time=lambda: 20.0,
        )
        lifecycle.mark_connected(old_api)

        lifecycle.reconnect("test reason")

        self.assertTrue(old_api.closed)
        self.assertIs(lifecycle.api, new_api)
        self.assertEqual(events, [("log", "RouterOS API reconnect requested: test reason"), ("sleep", 2)])
