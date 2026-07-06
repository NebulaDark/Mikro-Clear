import types
import unittest
from unittest.mock import Mock

from mikroclear.bot.modules.status import StatusSnapshot
from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.telegram.polling import TelegramUpdatePoller


class FakeMessageResponse:
    status_code = 200
    text = "{}"

    def __init__(self, chat_id="chat-1", text="/status"):
        self.chat_id = chat_id
        self.message_text = text

    def json(self):
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 99,
                    "message": {
                        "text": self.message_text,
                        "chat": {"id": self.chat_id},
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


if __name__ == "__main__":
    unittest.main()
