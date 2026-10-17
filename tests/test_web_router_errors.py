import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.web.app import create_app
from mikroclear.web.config import WebSettings


class WebRouterErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        gateway_patch = patch("mikroclear.web.app.RouterWebGateway")
        self.gateway = gateway_patch.start().return_value
        self.addCleanup(gateway_patch.stop)

    def client(self, *, monitor_only=False, mangle_enabled=True):
        with patch("mikroclear.web.app.BotSettings.from_env", return_value=BotSettings(audit_log=str(Path(self.temp.name) / "audit.jsonl"))):
            app = create_app(core_settings=Settings(monitor_only=monitor_only, mangle_control_enable=mangle_enabled), web_settings=WebSettings(
                admin_password="test-only-password", session_secret="test-only-session-secret-32-characters",
                secure_cookie=False, static_dir=self.temp.name,
            ))
        client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(client.close)
        csrf = client.post("/api/auth/login", json={"username": "admin", "password": "test-only-password"}).json()["csrf"]
        return client, {"X-CSRF-Token": csrf}

    def test_inventory_failures_return_controlled_503(self):
        client, headers = self.client()
        for exception in (TimeoutError, ssl.SSLError, PermissionError, ConnectionError):
            for method in (self.gateway.block_entries, self.gateway.managed_mangle):
                method.side_effect = exception("private-router-secret")
            for verb, path, body in (
                ("get", "/api/router/blocks", None),
                ("get", "/api/router/mangle", None),
                ("post", "/api/router/unblock/request", {"address": "192.0.2.4"}),
                ("post", "/api/router/mangle/*1/request", {"disabled": True}),
            ):
                with self.subTest(exception=exception, path=path):
                    kwargs = {"headers": headers}
                    if body is not None:
                        kwargs["json"] = body
                    response = getattr(client, verb)(path, **kwargs)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json(), {"detail": "RouterOS inventory is unavailable"})
                    self.assertNotIn("private-router-secret", response.text)
        self.gateway.unblock.assert_not_called()
        self.gateway.set_mangle_disabled.assert_not_called()

    def test_monitor_only_and_disabled_mangle_skip_inventory(self):
        client, headers = self.client(monitor_only=True)
        self.assertEqual(client.post("/api/router/unblock/request", json={"address": "192.0.2.4"}, headers=headers).status_code, 409)
        self.assertEqual(client.post("/api/router/mangle/*1/request", json={"disabled": True}, headers=headers).status_code, 409)
        client, headers = self.client(mangle_enabled=False)
        self.assertEqual(client.post("/api/router/mangle/*1/request", json={"disabled": True}, headers=headers).status_code, 403)
        self.gateway.block_entries.assert_not_called()
        self.gateway.managed_mangle.assert_not_called()
