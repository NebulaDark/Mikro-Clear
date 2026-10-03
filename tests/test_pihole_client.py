import unittest
from unittest.mock import Mock

import requests

from mikroclear.pihole.client import PiholeClient, PiholeClientError


class Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class PiholeClientTests(unittest.TestCase):
    def test_auth_stores_sid_and_sends_it_on_following_request(self):
        post = Mock(side_effect=[Response(payload={"session": {"sid": "sid-1"}})])
        get = Mock(return_value=Response(payload={"groups": []}))
        client = PiholeClient(
            "https://pihole.example",
            "app-secret",
            request_get=get,
            request_post=post,
        )

        self.assertEqual(client.request("GET", "/api/groups"), {"groups": []})
        self.assertEqual(post.call_args.kwargs["json"], {"password": "app-secret"})
        self.assertEqual(get.call_args.kwargs["headers"]["X-FTL-SID"], "sid-1")

    def test_401_reauthenticates_once_and_retries(self):
        post = Mock(side_effect=[
            Response(payload={"session": {"sid": "old"}}),
            Response(payload={"session": {"sid": "new"}}),
        ])
        get = Mock(side_effect=[Response(401, {"error": "expired"}), Response(payload={"ok": True})])
        client = PiholeClient("https://pihole.example", "secret", request_get=get, request_post=post)

        self.assertEqual(client.request("GET", "/api/groups"), {"ok": True})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(get.call_args_list[-1].kwargs["headers"]["X-FTL-SID"], "new")

    def test_secret_is_not_exposed_in_errors(self):
        get = Mock(side_effect=RuntimeError("request failed secret-value"))
        client = PiholeClient("https://pihole.example", "secret-value", request_get=get)

        with self.assertRaises(PiholeClientError) as raised:
            client.request("GET", "/api/groups")
        self.assertNotIn("secret-value", str(raised.exception))

    def test_response_text_masks_application_password_and_sid(self):
        password = "APP_PASSWORD_TEST_SECRET_123"
        sid = "SID_TEST_SECRET_456"
        post = Mock(return_value=Response(payload={"session": {"sid": sid}}))
        get = Mock(return_value=Response(500, {"error": "failed"}, text=f"{password} {sid}"))
        client = PiholeClient("https://pihole.example", password, request_get=get, request_post=post, retry_count=0)

        with self.assertRaises(PiholeClientError) as raised:
            client.request("GET", "/api/groups")
        self.assertNotIn(password, str(raised.exception))
        self.assertNotIn(sid, str(raised.exception))

    def test_transport_exception_masks_application_password_and_sid(self):
        password = "APP_PASSWORD_TEST_SECRET_789"
        sid = "SID_TEST_SECRET_012"
        post = Mock(return_value=Response(payload={"session": {"sid": sid}}))
        get = Mock(side_effect=requests.ConnectionError(f"{password} {sid}"))
        client = PiholeClient("https://pihole.example", password, request_get=get, request_post=post, retry_count=0)
        client._sid = sid

        with self.assertRaises(PiholeClientError) as raised:
            client.request("GET", "/api/groups")
        self.assertNotIn(password, str(raised.exception))
        self.assertNotIn(sid, str(raised.exception))

    def test_malformed_json_is_controlled_error(self):
        client = PiholeClient(
            "https://pihole.example",
            "secret",
            request_get=Mock(return_value=Response(payload=ValueError("bad json"))),
        )

        with self.assertRaises(PiholeClientError):
            client.request("GET", "/api/groups")

    def test_get_retries_once_after_server_error(self):
        post = Mock(return_value=Response(payload={"session": {"sid": "sid"}}))
        get = Mock(side_effect=[Response(500, {"error": "busy"}), Response(payload={"ok": True})])
        client = PiholeClient("https://pihole.example", "secret", request_get=get, request_post=post)

        self.assertEqual(client.request("GET", "/api/groups"), {"ok": True})
        self.assertEqual(get.call_count, 2)

    def test_get_timeout_and_connection_error_are_bounded(self):
        for error in (requests.Timeout("timeout"), requests.ConnectionError("connection")):
            with self.subTest(error=type(error).__name__):
                post = Mock(return_value=Response(payload={"session": {"sid": "sid"}}))
                get = Mock(side_effect=[error, Response(payload={"ok": True})])
                client = PiholeClient("https://pihole.example", "secret", request_get=get, request_post=post)
                self.assertEqual(client.request("GET", "/api/groups"), {"ok": True})
                self.assertEqual(get.call_count, 2)

    def test_get_429_after_retry_is_controlled_error(self):
        post = Mock(return_value=Response(payload={"session": {"sid": "sid"}}))
        get = Mock(side_effect=[Response(429, {"error": "rate"}), Response(429, {"error": "rate"})])
        client = PiholeClient("https://pihole.example", "secret", request_get=get, request_post=post)

        with self.assertRaises(PiholeClientError):
            client.request("GET", "/api/groups")
        self.assertEqual(get.call_count, 2)

    def test_second_401_is_controlled_error_after_one_reauth(self):
        post = Mock(side_effect=[
            Response(payload={"session": {"sid": "old"}}),
            Response(payload={"session": {"sid": "new"}}),
        ])
        get = Mock(side_effect=[Response(401, {"error": "expired"}), Response(401, {"error": "still expired"})])
        client = PiholeClient("https://pihole.example", "secret", request_get=get, request_post=post)

        with self.assertRaises(PiholeClientError):
            client.request("GET", "/api/groups")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(get.call_count, 2)

    def test_mutating_post_is_not_retried_after_server_error(self):
        post = Mock(side_effect=[
            Response(payload={"session": {"sid": "sid"}}),
            Response(500, {"error": "ambiguous"}),
        ])
        client = PiholeClient("https://pihole.example", "secret", request_post=post)

        with self.assertRaises(PiholeClientError) as raised:
            client.request("POST", "/api/clients", json={"client": "192.168.10.50"})
        self.assertTrue(raised.exception.ambiguous)
        self.assertEqual(post.call_count, 2)

    def test_mutating_put_is_not_retried_after_timeout(self):
        post = Mock(return_value=Response(payload={"session": {"sid": "sid"}}))
        put = Mock(side_effect=requests.Timeout("ambiguous"))
        client = PiholeClient("https://pihole.example", "secret", request_post=post, request_put=put)

        with self.assertRaises(PiholeClientError) as raised:
            client.request("PUT", "/api/clients/9", json={"groups": [7]})
        self.assertTrue(raised.exception.ambiguous)
        self.assertEqual(put.call_count, 1)

    def test_mutating_post_is_not_retried_after_timeout_or_tls_error(self):
        for error in (requests.Timeout("timeout"), requests.exceptions.SSLError("tls")):
            with self.subTest(error=type(error).__name__):
                post = Mock(side_effect=[Response(payload={"session": {"sid": "sid"}}), error])
                client = PiholeClient("https://pihole.example", "APP_PASSWORD_TEST_SECRET_POST", request_post=post)
                with self.assertRaises(PiholeClientError):
                    client.request("POST", "/api/clients", json={"client": "192.168.10.50"})
                self.assertEqual(post.call_count, 2)

    def test_mutating_put_is_not_retried_after_server_error(self):
        post = Mock(return_value=Response(payload={"session": {"sid": "sid"}}))
        put = Mock(return_value=Response(500, {"error": "busy"}))
        client = PiholeClient("https://pihole.example", "secret", request_post=post, request_put=put)

        with self.assertRaises(PiholeClientError) as raised:
            client.request("PUT", "/api/clients/9", json={"groups": [7]})
        self.assertTrue(raised.exception.ambiguous)
        self.assertEqual(put.call_count, 1)


if __name__ == "__main__":
    unittest.main()
