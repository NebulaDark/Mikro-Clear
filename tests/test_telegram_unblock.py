import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mikroclear.settings import Settings
from mikroclear.telegram.polling import TelegramUpdatePoller
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


class TelegramUnblockFlowTests(unittest.TestCase):
    def test_routeros_failure_returns_callback_text_and_logs_result(self):
        class FailingClient:
            def run_with_reconnect(self, operation_name, func):
                raise RuntimeError("router offline")

        from mikroclear.app import RuntimeProviders

        log = Mock()
        providers = RuntimeProviders(settings=Settings(whitelist_ips=()), service_start_time=100.0)
        providers.get_router_client = Mock(return_value=FailingClient())
        with patch("mikroclear.app.log", log):
            result = providers.handle_unblock_action({"wanted_ip": "9.9.9.9", "list_name": "Suricata", "sid": "2402000"})

        self.assertEqual(result.text, "Could not unblock 9.9.9.9")
        self.assertFalse(result.success)
        self.assertTrue(result.alert)
        self.assertIn("TELEGRAM UNBLOCK FAILED: 9.9.9.9 from Suricata", log.call_args[0][0])

    def test_process_updates_sends_system_notification_only_after_success(self):
        answer_callback = Mock()
        send_system_notification = Mock()
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=Mock(),
            handle_unblock_action=Mock(
                return_value=types.SimpleNamespace(text="9.9.9.9 was not found in Suricata", success=False, alert=False)
            ),
            answer_callback=answer_callback,
            send_system_notification=send_system_notification,
            log=Mock(),
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeTelegramResponse()),
        )
        with patch("mikroclear.telegram.unblock.consume_unblock_token", return_value={"wanted_ip": "9.9.9.9"}):
            poller.process_updates()

        answer_callback.assert_called_once_with("callback-1", "9.9.9.9 was not found in Suricata", False)
        send_system_notification.assert_not_called()

    def test_process_updates_logs_expired_unblock_token(self):
        answer_callback = Mock()
        send_system_notification = Mock()
        log = Mock()
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=Mock(),
            handle_unblock_action=Mock(),
            answer_callback=answer_callback,
            send_system_notification=send_system_notification,
            log=log,
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeTelegramResponse()),
        )
        with patch("mikroclear.telegram.unblock.consume_unblock_token", return_value=None):
            poller.process_updates()

        answer_callback.assert_called_once_with("callback-1", "Unblock request expired or already used", True)
        send_system_notification.assert_not_called()
        log.assert_called_with("TELEGRAM UNBLOCK EXPIRED: callback token expired or already used")


if __name__ == "__main__":
    unittest.main()
