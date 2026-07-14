import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import TestCase


PROBE_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "bin"
    / "mikroclear-telegram-getupdates-probe"
)


def load_probe():
    loader = SourceFileLoader("mikroclear_telegram_probe", str(PROBE_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TelegramGetUpdatesProbeTests(TestCase):
    def test_read_only_probe_never_calls_get_updates_or_exposes_token(self):
        probe = load_probe()
        calls = []

        def request(method, token, params=None):
            calls.append((method, token, params))
            if method == "getMe":
                return {"ok": True, "result": {"id": 7, "username": "mikroclear_bot"}}
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": ["message", "callback_query"],
                },
            }

        result = probe.run_probe(
            ["probe"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
            runtime_token="token-a",
            request=request,
            service_active=lambda: True,
        )

        self.assertEqual([call[0] for call in calls], ["getMe", "getWebhookInfo"])
        self.assertNotIn("getUpdates", [call[0] for call in calls])
        self.assertNotIn("token-a", json.dumps(result))
        self.assertTrue(result["tokens_match"])

    def test_reset_refuses_while_service_is_active(self):
        probe = load_probe()

        with self.assertRaisesRegex(RuntimeError, "must be stopped"):
            probe.run_probe(
                ["probe", "--reset-allowed-updates"],
                env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
                runtime_token="token-a",
                request=lambda method, token, params=None: {},
                service_active=lambda: True,
            )

    def test_reset_records_post_state_without_update_payload(self):
        probe = load_probe()
        calls = []

        def request(method, token, params=None):
            calls.append((method, params))
            if method == "getUpdates":
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 100,
                            "message": {
                                "text": "/status secret payload",
                                "chat": {"id": 42},
                            },
                        }
                    ],
                }
            allowed_updates = (
                ["callback_query"]
                if len([call for call in calls if call[0] == "getWebhookInfo"]) == 1
                else ["message", "callback_query"]
            )
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": allowed_updates,
                },
            }

        result = probe.run_probe(
            ["probe", "--reset-allowed-updates"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
            runtime_token=None,
            request=request,
            service_active=lambda: False,
        )

        self.assertEqual(
            [call[0] for call in calls],
            ["getWebhookInfo", "getUpdates", "getWebhookInfo"],
        )
        self.assertEqual(result["webhook_before"]["allowed_updates"], ["callback_query"])
        self.assertEqual(
            result["webhook_after"]["allowed_updates"],
            ["message", "callback_query"],
        )
        self.assertEqual(
            result["updates"],
            {
                "ok": True,
                "count": 1,
                "updates": [{"update_id": 100, "type": "message"}],
            },
        )
        self.assertNotIn("secret payload", json.dumps(result))

    def test_fingerprints_distinguish_config_and_runtime_tokens(self):
        probe = load_probe()

        def request(method, token, params=None):
            if method == "getMe":
                return {"ok": True, "result": {"id": len(token), "username": "bot"}}
            return {"ok": True, "result": {"url": "", "pending_update_count": 0}}

        result = probe.run_probe(
            ["probe"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "config-token"},
            runtime_token="runtime-token",
            request=request,
            service_active=lambda: True,
        )

        self.assertFalse(result["tokens_match"])
        self.assertNotEqual(
            result["config_token_fingerprint"],
            result["runtime_token_fingerprint"],
        )
        serialized = json.dumps(result)
        self.assertNotIn("config-token", serialized)
        self.assertNotIn("runtime-token", serialized)
