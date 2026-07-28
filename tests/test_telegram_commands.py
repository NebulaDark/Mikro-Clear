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

    def test_retryable_handler_failure_does_not_advance_offset(self):
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=Mock(),
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeMessageResponse()),
            send_message=Mock(
                return_value=types.SimpleNamespace(
                    ok=False,
                    retryable=True,
                    response_text="temporary",
                )
            ),
        )

        poller.process_updates()

        self.assertEqual(poller.update_offset, 0)

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

    def test_poller_routes_start_to_menu_before_mangle_and_legacy(self):
        menu = Mock()
        menu.handle_message.return_value = True
        mangle = Mock()
        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="reader"),
            bot_settings=BotSettings(allowed_chat_ids=("reader",)),
            status_snapshot_factory=Mock(),
            handle_unblock_action=Mock(),
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=Mock(),
            now=Mock(return_value=100.0),
            menu_handler=menu,
            mangle_handler=mangle,
        )

        poller.process_update(
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": "reader"},
                    "from": {"id": "user-1"},
                    "text": "/start",
                },
            }
        )

        menu.handle_message.assert_called_once()
        mangle.handle_message.assert_not_called()

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

    def test_retryable_mangle_send_does_not_advance_offset(self):
        class MangleHandler:
            def handle_message(self, **kwargs):
                kwargs["send_message"](
                    token=kwargs["token"],
                    chat_id=kwargs["chat_id"],
                    text="temporary",
                    timeout=kwargs["timeout"],
                )
                return True

            def handle_callback(self, **kwargs):
                return False

        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=Mock(),
            send_system_notification=Mock(),
            log=Mock(),
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=FakeMessageResponse(text="/mangle")),
            send_message=Mock(
                return_value=types.SimpleNamespace(
                    ok=False,
                    retryable=True,
                    response_text="network unavailable",
                )
            ),
            mangle_handler=MangleHandler(),
        )

        poller.process_updates()

        self.assertEqual(poller.update_offset, 0)

    def test_retryable_callback_answer_does_not_advance_offset(self):
        class CallbackResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 101,
                            "callback_query": {
                                "id": "cb-1",
                                "data": "mangle:refresh",
                                "message": {"chat": {"id": "chat-1"}},
                            },
                        }
                    ],
                }

        class MangleHandler:
            def handle_message(self, **kwargs):
                return False

            def handle_callback(self, **kwargs):
                kwargs["answer_callback"]("cb-1", "temporary", False)
                return True

        poller = TelegramUpdatePoller(
            Settings(enable_telegram=True, telegram_token="token", telegram_chatid="chat-1"),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=Mock(
                return_value=types.SimpleNamespace(
                    ok=False,
                    retryable=True,
                    response_text="network unavailable",
                )
            ),
            send_system_notification=Mock(),
            log=Mock(),
            now=Mock(return_value=100.0),
            http_get=Mock(return_value=CallbackResponse()),
            mangle_handler=MangleHandler(),
        )

        poller.process_updates()

        self.assertEqual(poller.update_offset, 0)

    def test_menu_renders_after_retryable_callback_answer_eventually_succeeds(self):
        class MenuCallbackResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 102,
                            "callback_query": {
                                "id": "cb-menu",
                                "data": "menu:v1:root",
                                "from": {"id": "user-1"},
                                "message": {
                                    "message_id": 7,
                                    "chat": {"id": "chat-1"},
                                },
                            },
                        }
                    ],
                }

        answer = Mock(
            side_effect=(
                types.SimpleNamespace(
                    ok=False,
                    retryable=True,
                    response_text="network unavailable",
                ),
                types.SimpleNamespace(ok=True, retryable=False),
            )
        )
        edit = Mock(return_value=types.SimpleNamespace(ok=True, retryable=False))
        menu = Mock()
        now = Mock(return_value=100.0)

        def handle_menu_callback(**kwargs):
            kwargs["answer_callback"]("cb-menu", "", False)
            kwargs["edit_message"](
                token=kwargs["telegram_token"],
                chat_id="chat-1",
                message_id=7,
                text="<b>Mikro-Clear</b>",
                reply_markup={"inline_keyboard": []},
                timeout=kwargs["timeout"],
            )
            return True

        menu.handle_callback.side_effect = handle_menu_callback
        poller = TelegramUpdatePoller(
            Settings(
                enable_telegram=True,
                telegram_token="token",
                telegram_chatid="chat-1",
            ),
            status_snapshot_factory=self.status_snapshot,
            handle_unblock_action=Mock(),
            answer_callback=answer,
            send_system_notification=Mock(),
            log=Mock(),
            now=now,
            http_get=Mock(return_value=MenuCallbackResponse()),
            menu_handler=menu,
            edit_message=edit,
        )

        poller.process_updates()
        self.assertEqual(poller.update_offset, 0)
        edit.assert_not_called()

        now.return_value = 131.0
        poller.process_updates()

        self.assertEqual(poller.update_offset, 103)
        self.assertEqual(answer.call_count, 2)
        self.assertEqual(menu.handle_callback.call_count, 2)
        edit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
