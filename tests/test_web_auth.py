import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.web.app import create_app
from mikroclear.web.config import WebSettings


class WebAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.gateway_patch = patch("mikroclear.web.app.RouterWebGateway")
        self.gateway = self.gateway_patch.start()
        self.addCleanup(self.gateway_patch.stop)
        bot = BotSettings(audit_log=str(Path(self.temp.name) / "audit.jsonl"))
        with patch("mikroclear.web.app.BotSettings.from_env", return_value=bot):
            self.app = create_app(
                core_settings=Settings(monitor_only=True),
                web_settings=WebSettings(
                    admin_username="admin",
                    admin_password="test-only-password",
                    session_secret="test-only-session-secret-32-characters",
                    secure_cookie=False,
                    static_dir=self.temp.name,
                ),
            )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_unauthenticated_api_request_is_rejected(self):
        self.assertEqual(self.client.get("/api/settings").status_code, 401)
        self.assertEqual(self.client.post("/api/router/unblock/request", json={"address": "192.0.2.4"}).status_code, 401)

    def test_login_cookie_csrf_and_logout(self):
        denied = self.client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

        accepted = self.client.post("/api/auth/login", json={"username": "admin", "password": "test-only-password"})
        self.assertEqual(accepted.status_code, 200)
        csrf = accepted.json()["csrf"]
        cookie = accepted.headers["set-cookie"]
        self.assertIn("httponly", cookie.lower())
        self.assertIn("samesite=strict", cookie.lower())
        self.assertEqual(self.client.get("/api/auth/me").json()["user"], "admin")
        self.assertEqual(self.client.post("/api/router/unblock/request", json={"address": "192.0.2.4"}).status_code, 403)
        self.assertEqual(self.client.post("/api/router/unblock/request", json={"address": "192.0.2.4"}, headers={"X-CSRF-Token": csrf}).status_code, 409)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_expired_session_cookie_is_rejected(self):
        with patch("itsdangerous.timed.time.time", return_value=100):
            accepted = self.client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "test-only-password"},
            )
        self.assertEqual(accepted.status_code, 200)
        cookie = self.client.cookies.get("mikroclear_session")
        self.assertTrue(cookie)
        with patch("itsdangerous.timed.time.time", return_value=100 + 8 * 3600 + 1):
            response = self.client.get(
                "/api/auth/me",
                headers={"Cookie": f"mikroclear_session={cookie}"},
            )
        self.assertEqual(response.status_code, 401)

    def test_confirmation_cannot_cross_login_sessions_or_replay(self):
        self.gateway.return_value.managed_mangle.return_value = [
            {"id": "*1", "name": "managed-rule"}
        ]
        bot = BotSettings(audit_log=str(Path(self.temp.name) / "actions-audit.jsonl"))
        with patch("mikroclear.web.app.BotSettings.from_env", return_value=bot):
            app = create_app(
                core_settings=Settings(monitor_only=False, mangle_control_enable=True),
                web_settings=WebSettings(
                    admin_password="test-only-password",
                    session_secret="test-only-session-secret-32-characters",
                    secure_cookie=False,
                    static_dir=self.temp.name,
                ),
            )
        with TestClient(app) as owner, TestClient(app) as other:
            owner_csrf = owner.post("/api/auth/login", json={"username": "admin", "password": "test-only-password"}).json()["csrf"]
            other_csrf = other.post("/api/auth/login", json={"username": "admin", "password": "test-only-password"}).json()["csrf"]
            requested = owner.post(
                "/api/router/mangle/*1/request",
                json={"disabled": True},
                headers={"X-CSRF-Token": owner_csrf},
            )
            self.assertEqual(requested.status_code, 200)
            token = requested.json()["token"]
            self.assertEqual(
                other.post("/api/router/mangle/confirm", json={"token": token}, headers={"X-CSRF-Token": other_csrf}).status_code,
                409,
            )
            self.assertEqual(
                owner.post("/api/router/mangle/confirm", json={"token": token}, headers={"X-CSRF-Token": owner_csrf}).status_code,
                200,
            )
            self.assertEqual(
                owner.post("/api/router/mangle/confirm", json={"token": token}, headers={"X-CSRF-Token": owner_csrf}).status_code,
                409,
            )
        self.gateway.return_value.set_mangle_disabled.assert_called_once_with("*1", True)

    def test_router_timeout_is_reported_without_secret_and_audited(self):
        self.gateway.return_value.managed_mangle.return_value = [
            {"id": "*1", "name": "managed-rule"}
        ]
        self.gateway.return_value.set_mangle_disabled.side_effect = TimeoutError(
            "ROUTER_PASSWORD_TEST_ONLY_123"
        )
        audit_path = Path(self.temp.name) / "failure-audit.jsonl"
        with patch(
            "mikroclear.web.app.BotSettings.from_env",
            return_value=BotSettings(audit_log=str(audit_path)),
        ):
            app = create_app(
                core_settings=Settings(monitor_only=False, mangle_control_enable=True),
                web_settings=WebSettings(
                    admin_password="test-only-password",
                    session_secret="test-only-session-secret-32-characters",
                    secure_cookie=False,
                    static_dir=self.temp.name,
                ),
            )
        with TestClient(app) as client:
            csrf = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "test-only-password"},
            ).json()["csrf"]
            token = client.post(
                "/api/router/mangle/*1/request",
                json={"disabled": True},
                headers={"X-CSRF-Token": csrf},
            ).json()["token"]
            response = client.post(
                "/api/router/mangle/confirm",
                json={"token": token},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("ROUTER_PASSWORD_TEST_ONLY_123", response.text)
            self.assertEqual(
                client.post(
                    "/api/router/mangle/confirm",
                    json={"token": token},
                    headers={"X-CSRF-Token": csrf},
                ).status_code,
                409,
            )
        self.gateway.return_value.set_mangle_disabled.assert_called_once()
        audit_text = audit_path.read_text(encoding="utf-8")
        self.assertIn("web.mangle.confirm", audit_text)
        self.assertIn('"outcome": "error"', audit_text)
        self.assertNotIn("ROUTER_PASSWORD_TEST_ONLY_123", audit_text)


if __name__ == "__main__":
    unittest.main()
