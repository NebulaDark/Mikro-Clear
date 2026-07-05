import types
from unittest import TestCase

from mikroclear.telegram.commands import process_message_command


class FakeAuth:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    def is_allowed(self, chat_id: str) -> bool:
        return self.allowed


class TelegramCommandBoundaryTests(TestCase):
    def test_process_message_command_sends_authorized_dispatch_result(self):
        sent = []

        result = process_message_command(
            text="/status",
            chat_id="chat-1",
            auth=FakeAuth(True),
            status_snapshot_factory=lambda: object(),
            dispatch_message=lambda text, chat_id, auth, status_factory: types.SimpleNamespace(
                text=f"status for {chat_id}",
                alert=False,
            ),
            send_message=lambda **kwargs: sent.append(kwargs),
            token="token",
            timeout=5,
            log=lambda message: None,
        )

        self.assertTrue(result)
        self.assertEqual(sent[0]["chat_id"], "chat-1")
        self.assertEqual(sent[0]["text"], "status for chat-1")

    def test_process_message_command_logs_unauthorized_without_sending(self):
        sent = []
        logs = []

        result = process_message_command(
            text="/status",
            chat_id="unknown",
            auth=FakeAuth(False),
            status_snapshot_factory=lambda: object(),
            dispatch_message=lambda text, chat_id, auth, status_factory: types.SimpleNamespace(
                text="Unauthorized",
                alert=True,
            ),
            send_message=lambda **kwargs: sent.append(kwargs),
            token="token",
            timeout=5,
            log=lambda message: logs.append(message),
        )

        self.assertTrue(result)
        self.assertEqual(sent, [])
        self.assertEqual(logs, ["Rejected Telegram command from unauthorized chat unknown"])

    def test_process_message_command_ignores_unknown_message(self):
        result = process_message_command(
            text="hello",
            chat_id="chat-1",
            auth=FakeAuth(True),
            status_snapshot_factory=lambda: object(),
            dispatch_message=lambda text, chat_id, auth, status_factory: None,
            send_message=lambda **kwargs: None,
            token="token",
            timeout=5,
            log=lambda message: None,
        )

        self.assertFalse(result)
