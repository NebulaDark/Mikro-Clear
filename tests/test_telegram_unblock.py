import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mikroclear.settings import Settings
from mikroclear.telegram.polling import TelegramUpdatePoller
from mikroclear.telegram.unblock import (
    build_unblock_confirm_keyboard,
    build_unblock_keyboard,
    cancel_unblock_token,
    consume_unblock_token,
    create_unblock_token,
    peek_unblock_token,
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
                        "data": "unblock_execute:tok123",
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

    def test_peek_token_does_not_consume_before_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unblock.json"
            create_unblock_token(
                path,
                wanted_ip="9.9.9.9",
                list_name="Suricata",
                sid="2402000",
                now=100,
                ttl_seconds=3600,
                token_factory=lambda: "tok123",
            )

            action = peek_unblock_token(path, "tok123", now=200)

            self.assertEqual(action["wanted_ip"], "9.9.9.9")
            self.assertIsNotNone(consume_unblock_token(path, "tok123", now=201))

    def test_cancel_token_removes_without_unblock_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unblock.json"
            create_unblock_token(
                path,
                wanted_ip="9.9.9.9",
                list_name="Suricata",
                sid="2402000",
                now=100,
                ttl_seconds=3600,
                token_factory=lambda: "tok123",
            )

            self.assertTrue(cancel_unblock_token(path, "tok123", now=200))
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
        self.assertEqual(parse_unblock_callback("unblock:abc123"), ("confirm", "abc123"))
        self.assertEqual(parse_unblock_callback("unblock_confirm:abc123"), ("confirm", "abc123"))
        self.assertEqual(parse_unblock_callback("unblock_execute:abc123"), ("execute", "abc123"))
        self.assertEqual(parse_unblock_callback("unblock_cancel:abc123"), ("cancel", "abc123"))
        self.assertIsNone(parse_unblock_callback("noop:abc123"))
        self.assertIsNone(parse_unblock_callback("unblock:bad token"))

    def test_keyboard_contains_confirm_callback_and_unblock_label(self):
        keyboard = build_unblock_keyboard("9.9.9.9", "tok123")

        buttons = keyboard["inline_keyboard"]
        self.assertEqual(buttons[0][0]["callback_data"], "unblock_confirm:tok123")
        self.assertEqual(buttons[0][0]["text"], "🔓 Unblock 9.9.9.9")

    def test_confirm_keyboard_contains_execute_and_cancel_callbacks(self):
        keyboard = build_unblock_confirm_keyboard("tok123")

        buttons = keyboard["inline_keyboard"]
        self.assertEqual(buttons[0][0]["text"], "✅ Confirm unblock")
        self.assertEqual(buttons[0][0]["callback_data"], "unblock_execute:tok123")
        self.assertEqual(buttons[0][1]["text"], "❌ Cancel")
        self.assertEqual(buttons[0][1]["callback_data"], "unblock_cancel:tok123")


class TelegramUnblockFlowTests(unittest.TestCase):
    def test_answer_callback_reports_retryable_transport_failures(self):
        from mikroclear.telegram.unblock_handler import TelegramUnblockHandler

        handler = TelegramUnblockHandler(
            Settings(telegram_token="secret-token", telegram_timeout=7),
            get_router_client=Mock(),
            log=Mock(),
            http_post=Mock(side_effect=RuntimeError("secret-token unavailable")),
        )

        result = handler.answer_telegram_callback("callback-1", "Try again")

        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertNotIn("secret-token", result.response_text)

    def test_answer_callback_reports_retryable_server_response(self):
        from mikroclear.telegram.unblock_handler import TelegramUnblockHandler

        handler = TelegramUnblockHandler(
            Settings(telegram_token="secret-token", telegram_timeout=7),
            get_router_client=Mock(),
            log=Mock(),
            http_post=Mock(
                return_value=types.SimpleNamespace(
                    status_code=503,
                    text="temporary failure",
                )
            ),
        )

        result = handler.answer_telegram_callback("callback-1", "Try again")

        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertEqual(result.status_code, 503)

    def test_routeros_failure_returns_callback_text_and_logs_result(self):
        class FailingClient:
            def run_with_reconnect(self, operation_name, func):
                raise RuntimeError("router offline")

        from mikroclear.telegram.unblock_handler import TelegramUnblockHandler

        log = Mock()
        handler = TelegramUnblockHandler(
            Settings(whitelist_ips=()),
            get_router_client=Mock(return_value=FailingClient()),
            log=log,
        )
        result = handler.handle_unblock_action({"wanted_ip": "9.9.9.9", "list_name": "Suricata", "sid": "2402000"})

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

    def test_process_updates_confirm_step_sends_confirm_message_without_routeros_unblock(self):
        class ConfirmResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 43,
                            "callback_query": {
                                "id": "callback-2",
                                "data": "unblock_confirm:tok123",
                                "message": {"chat": {"id": "chat-1"}},
                            },
                        }
                    ],
                }

        answer_callback = Mock()
        send_message = Mock()
        handle_unblock_action = Mock()
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=Mock(),
            handle_unblock_action=handle_unblock_action,
            answer_callback=answer_callback,
            send_system_notification=Mock(),
            log=Mock(),
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=ConfirmResponse()),
            send_message=send_message,
        )
        with patch("mikroclear.telegram.unblock.peek_unblock_token", return_value={"wanted_ip": "9.9.9.9"}):
            poller.process_updates()

        handle_unblock_action.assert_not_called()
        answer_callback.assert_called_once_with("callback-2", "Confirm unblock in chat", False)
        send_message.assert_called_once()
        self.assertIn("Confirm unblock?", send_message.call_args.kwargs["text"])
        self.assertIn("Target: <code>9.9.9.9</code>", send_message.call_args.kwargs["text"])
        markup = send_message.call_args.kwargs["reply_markup"]
        self.assertEqual(markup["inline_keyboard"][0][0]["callback_data"], "unblock_execute:tok123")
        self.assertEqual(markup["inline_keyboard"][0][1]["callback_data"], "unblock_cancel:tok123")


if __name__ == "__main__":
    unittest.main()
