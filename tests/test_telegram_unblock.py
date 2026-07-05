import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from mikroclear.telegram_unblock import (
    build_unblock_keyboard,
    consume_unblock_token,
    create_unblock_token,
    parse_unblock_callback,
)


def fake_pyinotify_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(ProcessEvent=object)


class FakeTelegramResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 42,
                    "callback_query": {
                        "id": "callback-1",
                        "data": "unblock:tok123",
                        "message": {"chat": {"id": "chat-1"}},
                    },
                }
            ],
        }


class TelegramUnblockTests(unittest.TestCase):
    def test_create_token_persists_unblock_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unblock.json"

            token = create_unblock_token(
                path,
                wanted_ip="9.9.9.9",
                list_name="Suricata",
                sid="2402000",
                now=100,
                ttl_seconds=3600,
                token_factory=lambda: "tok123",
            )

            self.assertEqual(token, "tok123")
            action = consume_unblock_token(path, "tok123", now=200)
            self.assertEqual(action["wanted_ip"], "9.9.9.9")
            self.assertEqual(action["list_name"], "Suricata")
            self.assertEqual(action["sid"], "2402000")
            self.assertIsNone(consume_unblock_token(path, "tok123", now=201))

    def test_expired_token_is_rejected_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unblock.json"
            create_unblock_token(
                path,
                wanted_ip="9.9.9.9",
                list_name="Suricata",
                sid="2402000",
                now=100,
                ttl_seconds=10,
                token_factory=lambda: "tok123",
            )

            self.assertIsNone(consume_unblock_token(path, "tok123", now=111))

    def test_parse_unblock_callback(self):
        self.assertEqual(parse_unblock_callback("unblock:abc123"), "abc123")
        self.assertIsNone(parse_unblock_callback("noop:abc123"))
        self.assertIsNone(parse_unblock_callback("unblock:bad token"))

    def test_keyboard_contains_unblock_callback(self):
        keyboard = build_unblock_keyboard("9.9.9.9", "tok123")

        buttons = keyboard["inline_keyboard"]
        self.assertEqual(buttons[0][0]["callback_data"], "unblock:tok123")
        self.assertIn("Unblock 9.9.9.9", buttons[0][0]["text"])


class LegacyTelegramUnblockFlowTests(unittest.TestCase):
    def import_legacy(self):
        with patch.dict("sys.modules", {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import legacy

        return legacy

    def test_routeros_failure_returns_callback_text_and_logs_result(self):
        legacy = self.import_legacy()

        class FailingClient:
            def run_with_reconnect(self, operation_name, func):
                raise RuntimeError("router offline")

        with (
            patch.object(legacy, "is_valid_ip", return_value=True),
            patch.object(legacy, "is_ip_in_whitelist", return_value=False),
            patch.object(legacy, "get_router_client", return_value=FailingClient()),
            patch.object(legacy, "log") as log,
        ):
            result = legacy.handle_unblock_action(
                {"wanted_ip": "9.9.9.9", "list_name": "Suricata", "sid": "2402000"}
            )

        self.assertEqual(result.text, "Could not unblock 9.9.9.9")
        self.assertFalse(result.success)
        self.assertTrue(result.alert)
        self.assertIn("TELEGRAM UNBLOCK FAILED: 9.9.9.9 from Suricata", log.call_args[0][0])

    def test_process_updates_sends_system_notification_only_after_success(self):
        legacy = self.import_legacy()

        with (
            patch.object(legacy, "ENABLE_TELEGRAM", True),
            patch.object(legacy, "TELEGRAM_UNBLOCK_ENABLE", True),
            patch.object(legacy, "TELEGRAM_TOKEN", "token"),
            patch.object(legacy, "TELEGRAM_CHATID", "chat-1"),
            patch.object(legacy, "telegram_update_offset", 0),
            patch.object(legacy.requests, "get", return_value=FakeTelegramResponse()),
            patch.object(legacy, "consume_unblock_token", return_value={"wanted_ip": "9.9.9.9"}),
            patch.object(
                legacy,
                "handle_unblock_action",
                return_value=types.SimpleNamespace(text="9.9.9.9 was not found in Suricata", success=False, alert=False),
            ),
            patch.object(legacy, "answer_telegram_callback") as answer_callback,
            patch.object(legacy, "send_system_notification") as send_system_notification,
        ):
            legacy.process_telegram_updates()

        answer_callback.assert_called_once_with("callback-1", "9.9.9.9 was not found in Suricata", False)
        send_system_notification.assert_not_called()

    def test_process_updates_logs_expired_unblock_token(self):
        legacy = self.import_legacy()

        with (
            patch.object(legacy, "ENABLE_TELEGRAM", True),
            patch.object(legacy, "TELEGRAM_UNBLOCK_ENABLE", True),
            patch.object(legacy, "TELEGRAM_TOKEN", "token"),
            patch.object(legacy, "TELEGRAM_CHATID", "chat-1"),
            patch.object(legacy, "telegram_update_offset", 0),
            patch.object(legacy.requests, "get", return_value=FakeTelegramResponse()),
            patch.object(legacy, "consume_unblock_token", return_value=None),
            patch.object(legacy, "answer_telegram_callback") as answer_callback,
            patch.object(legacy, "send_system_notification") as send_system_notification,
            patch.object(legacy, "log") as log,
        ):
            legacy.process_telegram_updates()

        answer_callback.assert_called_once_with("callback-1", "Unblock request expired or already used", True)
        send_system_notification.assert_not_called()
        log.assert_called_with("TELEGRAM UNBLOCK EXPIRED: callback token expired or already used")


if __name__ == "__main__":
    unittest.main()
