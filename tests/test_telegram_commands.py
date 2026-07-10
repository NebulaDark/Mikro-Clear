import types
import unittest
from unittest.mock import Mock
import json
import os
from unittest.mock import patch

from mikroclear.bot.modules.status import StatusSnapshot
from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.telegram.polling import TelegramUpdatePoller


class FakeMessageResponse:
    status_code = 200
    text = "{}"

    def __init__(self, chat_id="chat-1", text="/status", user_id="user-1"):
        self.chat_id = chat_id
        self.message_text = text
        self.user_id = user_id

    def json(self):
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 99,
                    "message": {
                        "text": self.message_text,
                        "chat": {"id": self.chat_id},
                        "from": {"id": self.user_id},
                    },
                }
            ],
        }


class TelegramCommandTests(unittest.TestCase):
    def status_snapshot(self):
        return StatusSnapshot(
            uptime_seconds=10,
            routeros_connected=True,
            routeros_connected_seconds=5,
            eve_path="/tmp/eve.json",
            block_list_name="Suricata",
            monitor_only=False,
            telegram_unblock_enabled=True,
            state_dir="/tmp/state",
            bot_settings=BotSettings(),
        )

    def test_process_updates_sends_status_to_allowed_chat(self):
        send = Mock(return_value=types.SimpleNamespace(ok=True, response_text="ok"))
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=Mock(),
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeMessageResponse()),
            send_message=send,
        )
        poller.process_updates()

        self.assertEqual(send.call_args.kwargs["chat_id"], "chat-1")
        self.assertIn("Mikro-Clear status", send.call_args.kwargs["text"])

    def test_process_updates_requests_message_and_callback_updates(self):
        http_get = Mock(return_value=FakeMessageResponse())
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=Mock(),
            now=Mock(return_value=100.0),
            http_get=http_get,
            send_message=Mock(return_value=types.SimpleNamespace(ok=True, response_text="ok")),
        )

        poller.process_updates()

        allowed_updates = json.loads(http_get.call_args.kwargs["params"]["allowed_updates"])
        self.assertEqual(allowed_updates, ["callback_query", "message"])

    def test_process_updates_rejects_status_from_unknown_chat(self):
        send = Mock(return_value=types.SimpleNamespace(ok=True, response_text="ok"))
        log = Mock()
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=log,
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeMessageResponse(chat_id="unknown")),
            send_message=send,
        )
        poller.process_updates()

        send.assert_not_called()
        self.assertIn("Rejected Telegram command from unauthorized chat unknown", log.call_args[0][0])

    def test_process_updates_uses_injected_bot_settings_when_environment_differs(self):
        send = Mock(return_value=types.SimpleNamespace(ok=True, response_text="ok"))
        with patch.dict(os.environ, {}, clear=True):
            poller = TelegramUpdatePoller(
                Settings(enable_telegram=True, telegram_token="token", telegram_chatid="legacy-chat"),
                status_snapshot_factory=self.status_snapshot,
                handle_unblock_action=Mock(),
                answer_callback=Mock(),
                send_system_notification=Mock(),
                log=Mock(),
                now=Mock(return_value=100.0),
                http_get=Mock(return_value=FakeMessageResponse(chat_id="chat-1")),
                send_message=send,
                bot_settings=BotSettings(allowed_chat_ids=("chat-1",)),
            )

            poller.process_updates()

        self.assertEqual(send.call_args.kwargs["chat_id"], "chat-1")
        self.assertIn("Mikro-Clear status", send.call_args.kwargs["text"])

    def test_process_updates_routes_mangle_command_to_existing_polling_loop(self):
        class MangleHandler:
            def __init__(self):
                self.messages = []

            def handle_message(self, **kwargs):
                self.messages.append(kwargs)
                return True

            def handle_callback(self, **kwargs):
                return False

        handler = MangleHandler()
        send = Mock(return_value=types.SimpleNamespace(ok=True, response_text="ok"))
        log = Mock()
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=log,
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeMessageResponse(text="/mangle")),
            send_message=send,
            mangle_handler=handler,
        )

        poller.process_updates()

        self.assertEqual(len(handler.messages), 1)
        self.assertEqual(handler.messages[0]["text"], "/mangle")
        self.assertEqual(handler.messages[0]["user_id"], "user-1")
        self.assertIn("Telegram updates received: 1 item(s), current offset=0", log.call_args_list[0].args[0])
        self.assertIn("Telegram command update: command=/mangle chat=chat-1 user=user-1", log.call_args_list[1].args[0])

    def test_process_updates_routes_mangle_callback_before_unblock_callback(self):
        class FakeCallbackResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 100,
                            "callback_query": {
                                "id": "cb-1",
                                "data": "mangle:refresh",
                                "message": {"chat": {"id": "chat-1"}},
                            },
                        }
                    ],
                }

        class MangleHandler:
            def __init__(self):
                self.callbacks = []

            def handle_message(self, **kwargs):
                return False

            def handle_callback(self, **kwargs):
                self.callbacks.append(kwargs)
                return True

        handler = MangleHandler()
        handle_unblock_action = Mock()
        log = Mock()
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=handle_unblock_action,
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=log,
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeCallbackResponse()),
            mangle_handler=handler,
        )

        poller.process_updates()

        self.assertEqual(len(handler.callbacks), 1)
        handle_unblock_action.assert_not_called()
        self.assertIn("Telegram updates received: 1 item(s), current offset=0", log.call_args_list[0].args[0])
        self.assertIn(
            "Telegram callback update: id=cb-1 action=mangle:refresh chat=chat-1 user=",
            log.call_args_list[1].args[0],
        )


if __name__ == "__main__":
    unittest.main()
