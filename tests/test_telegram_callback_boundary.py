from pathlib import Path
from unittest import TestCase

from mikroclear.telegram.commands import process_callback_update


class TelegramCallbackBoundaryTests(TestCase):
    def test_process_callback_update_rejects_unauthorized_chat(self):
        answers = []
        logs = []

        handled = process_callback_update(
            callback={"id": "cb-1", "data": "unblock:tok", "message": {"chat": {"id": "unknown"}}},
            allowed_chat_id="chat-1",
            state_file=Path("/tmp/unblock.json"),
            now=100,
            parse_unblock_callback=lambda data: "tok",
            consume_unblock_token=lambda path, token, now: {"wanted_ip": "1.1.1.1"},
            handle_unblock_action=lambda action: None,
            answer_callback=lambda callback_id, text, alert=False: answers.append((callback_id, text, alert)),
            send_system_notification=lambda text, kind: None,
            log=lambda message: logs.append(message),
        )

        self.assertTrue(handled)
        self.assertEqual(answers, [("cb-1", "Unauthorized chat", True)])
        self.assertEqual(logs, ["Rejected Telegram callback from unauthorized chat unknown"])

    def test_process_callback_update_answers_expired_token(self):
        answers = []
        logs = []

        handled = process_callback_update(
            callback={"id": "cb-1", "data": "unblock:tok", "message": {"chat": {"id": "chat-1"}}},
            allowed_chat_id="chat-1",
            state_file=Path("/tmp/unblock.json"),
            now=100,
            parse_unblock_callback=lambda data: "tok",
            consume_unblock_token=lambda path, token, now: None,
            handle_unblock_action=lambda action: None,
            answer_callback=lambda callback_id, text, alert=False: answers.append((callback_id, text, alert)),
            send_system_notification=lambda text, kind: None,
            log=lambda message: logs.append(message),
        )

        self.assertTrue(handled)
        self.assertEqual(answers, [("cb-1", "Unblock request expired or already used", True)])
        self.assertEqual(logs, ["TELEGRAM UNBLOCK EXPIRED: callback token expired or already used"])

    def test_process_callback_update_notifies_only_after_success(self):
        answers = []
        notifications = []

        class Result:
            text = "Unblocked 1.1.1.1"
            success = True
            alert = False

        handled = process_callback_update(
            callback={"id": "cb-1", "data": "unblock:tok", "message": {"chat": {"id": "chat-1"}}},
            allowed_chat_id="chat-1",
            state_file=Path("/tmp/unblock.json"),
            now=100,
            parse_unblock_callback=lambda data: "tok",
            consume_unblock_token=lambda path, token, now: {"wanted_ip": "1.1.1.1"},
            handle_unblock_action=lambda action: Result(),
            answer_callback=lambda callback_id, text, alert=False: answers.append((callback_id, text, alert)),
            send_system_notification=lambda text, kind: notifications.append((text, kind)),
            log=lambda message: None,
        )

        self.assertTrue(handled)
        self.assertEqual(answers, [("cb-1", "Unblocked 1.1.1.1", False)])
        self.assertEqual(notifications, [("Unblocked 1.1.1.1", "UNBLOCK")])
