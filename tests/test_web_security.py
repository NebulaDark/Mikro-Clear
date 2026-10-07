import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.web.app import create_app
from mikroclear.web.config import WebSettings


class WebSecretBoundaryTests(unittest.TestCase):
    def test_login_audit_masks_known_secret_in_supplied_username(self):
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            router_password = "ROUTER_PASSWORD_TEST_ONLY_123"
            bot = BotSettings(audit_log=str(audit_path))
            with patch("mikroclear.web.app.BotSettings.from_env", return_value=bot), patch(
                "mikroclear.web.app.RouterWebGateway"
            ):
                app = create_app(
                    core_settings=Settings(password=router_password),
                    web_settings=WebSettings(
                        admin_password="WEB_PASSWORD_TEST_ONLY_012",
                        session_secret="WEB_SESSION_SECRET_TEST_ONLY_345678901234567890",
                        secure_cookie=False,
                        static_dir=directory,
                    ),
                )
                with TestClient(app) as client:
                    response = client.post(
                        "/api/auth/login",
                        json={"username": router_password, "password": "wrong"},
                    )
                    self.assertEqual(response.status_code, 401)
            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertIn("web.login", audit_text)
            self.assertNotIn(router_password, audit_text)

    def test_log_and_audit_responses_mask_configured_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "service.log"
            audit_path = Path(directory) / "audit.jsonl"
            secrets = (
                "ROUTER_PASSWORD_TEST_ONLY_123",
                "TELEGRAM_TOKEN_TEST_ONLY_456",
                "PIHOLE_PASSWORD_TEST_ONLY_789",
                "WEB_PASSWORD_TEST_ONLY_012",
                "WEB_SESSION_SECRET_TEST_ONLY_345678901234567890",
            )
            log_path.write_text("error " + " ".join(secrets) + "\n", encoding="utf-8")
            audit_path.write_text(
                json.dumps({"detail": " ".join(secrets)}) + "\n", encoding="utf-8"
            )
            bot = BotSettings(audit_log=str(audit_path))
            with patch("mikroclear.web.app.BotSettings.from_env", return_value=bot), patch(
                "mikroclear.web.app.RouterWebGateway"
            ):
                app = create_app(
                    core_settings=Settings(
                        password=secrets[0],
                        telegram_token=secrets[1],
                        pihole_app_password=secrets[2],
                    ),
                    web_settings=WebSettings(
                        admin_password=secrets[3],
                        session_secret=secrets[4],
                        secure_cookie=False,
                        service_log_file=str(log_path),
                        static_dir=directory,
                    ),
                )
                with TestClient(app) as client:
                    login = client.post(
                        "/api/auth/login",
                        json={"username": "admin", "password": secrets[3]},
                    )
                    self.assertEqual(login.status_code, 200)
                    for endpoint in ("/api/logs", "/api/audit"):
                        response = client.get(endpoint)
                        self.assertEqual(response.status_code, 200)
                        for secret in secrets:
                            self.assertNotIn(secret, response.text)


if __name__ == "__main__":
    unittest.main()
