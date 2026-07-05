import types
import unittest
from unittest.mock import patch


def fake_pyinotify_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(ProcessEvent=object)


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


class LegacyTelegramCommandTests(unittest.TestCase):
    def import_legacy(self):
        with patch.dict("sys.modules", {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import legacy

        return legacy

    def test_process_updates_sends_status_to_allowed_chat(self):
        legacy = self.import_legacy()

        with (
            patch.object(legacy, "ENABLE_TELEGRAM", True),
            patch.object(legacy, "TELEGRAM_UNBLOCK_ENABLE", True),
            patch.object(legacy, "TELEGRAM_TOKEN", "token"),
            patch.object(legacy, "TELEGRAM_CHATID", "chat-1"),
            patch.object(legacy, "telegram_update_offset", 0),
            patch.object(legacy.requests, "get", return_value=FakeMessageResponse()),
            patch.object(
                legacy,
                "send_telegram_message",
                return_value=types.SimpleNamespace(ok=True, response_text="ok"),
            ) as send,
        ):
            legacy.process_telegram_updates()

        self.assertEqual(send.call_args.kwargs["chat_id"], "chat-1")
        self.assertIn("Mikro-Clear status", send.call_args.kwargs["text"])

    def test_process_updates_rejects_status_from_unknown_chat(self):
        legacy = self.import_legacy()

        with (
            patch.object(legacy, "ENABLE_TELEGRAM", True),
            patch.object(legacy, "TELEGRAM_UNBLOCK_ENABLE", True),
            patch.object(legacy, "TELEGRAM_TOKEN", "token"),
            patch.object(legacy, "TELEGRAM_CHATID", "chat-1"),
            patch.object(legacy, "telegram_update_offset", 0),
            patch.object(legacy.requests, "get", return_value=FakeMessageResponse(chat_id="unknown")),
            patch.object(
                legacy,
                "send_telegram_message",
                return_value=types.SimpleNamespace(ok=True, response_text="ok"),
            ) as send,
            patch.object(legacy, "log") as log,
        ):
            legacy.process_telegram_updates()

        send.assert_not_called()
        self.assertIn("Rejected Telegram command from unauthorized chat unknown", log.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
