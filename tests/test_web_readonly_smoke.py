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


class WebReadOnlySmokeTests(unittest.TestCase):
    def test_login_dashboard_alerts_and_router_reads_in_monitor_only(self):
        with tempfile.TemporaryDirectory() as directory:
            eve_path = Path(directory) / "eve.json"
            eve_path.write_text(
                "\n".join(
                    json.dumps(event) for event in (
                        {"event_type": "alert", "src_ip": "192.0.2.10", "alert": {"signature": "SSH probe", "severity": 2}},
                        {"event_type": "alert", "src_ip": "192.0.2.11", "alert": {"signature": "DNS probe", "severity": 3}},
                    )
                ) + "\n",
                encoding="utf-8",
            )
            bot = BotSettings(audit_log=str(Path(directory) / "audit.jsonl"))
            with patch("mikroclear.web.app.BotSettings.from_env", return_value=bot), patch(
                "mikroclear.web.app.RouterWebGateway"
            ) as gateway_type:
                gateway = gateway_type.return_value
                gateway.status.return_value = {"connected": True, "version": "test-version"}
                gateway.block_entries.return_value = [
                    {"id": "*1", "address": "198.51.100.7", "list": "Suricata"}
                ]
                app = create_app(
                    core_settings=Settings(monitor_only=True, mangle_control_enable=False),
                    web_settings=WebSettings(
                        admin_password="test-only-password",
                        session_secret="test-only-session-secret-32-characters",
                        secure_cookie=False,
                        eve_json=str(eve_path),
                        static_dir=directory,
                    ),
                )
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/overview").status_code, 401)
                    login = client.post(
                        "/api/auth/login",
                        json={"username": "admin", "password": "test-only-password"},
                    )
                    self.assertEqual(login.status_code, 200)
                    csrf = login.json()["csrf"]

                    overview = client.get("/api/overview")
                    self.assertEqual(overview.status_code, 200)
                    self.assertTrue(overview.json()["router"]["connected"])
                    self.assertEqual(overview.json()["blocked_count"], 1)
                    self.assertTrue(overview.json()["monitor_only"])

                    alerts = client.get("/api/alerts", params={"q": "SSH"})
                    self.assertEqual(alerts.status_code, 200)
                    self.assertEqual(alerts.json()["count"], 1)
                    self.assertEqual(alerts.json()["items"][0]["src_ip"], "192.0.2.10")

                    blocks = client.get("/api/router/blocks")
                    self.assertEqual(blocks.status_code, 200)
                    self.assertEqual(blocks.json()["count"], 1)
                    self.assertEqual(client.get("/api/router/mangle").json()["items"], [])
                    denied = client.post(
                        "/api/router/unblock/request",
                        json={"address": "198.51.100.7"},
                        headers={"X-CSRF-Token": csrf},
                    )
                    self.assertEqual(denied.status_code, 409)

                gateway.set_mangle_disabled.assert_not_called()
                gateway.unblock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
