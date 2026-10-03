import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.audit import BotAuditLog
from mikroclear.bot.settings import BotSettings
from mikroclear.parental.models import ParentalDevice, YouTubePolicyState
from mikroclear.telegram.parental_handler import TelegramParentalHandler
from mikroclear.telegram.commands import RetryableTelegramDeliveryError


class Response:
    ok = True


class TelegramParentalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(
            state_dir=self.temp.name,
            parental_control_enable=True,
            pihole_enable=True,
            parental_action_ttl_seconds=300,
            parental_youtube_group_name="MikroClear-YouTube-Blocked",
            pihole_app_password="pihole-test-password",
            telegram_token="/bot123:telegram-test-token/",
            routeros_password="routeros-test-password",
        )
        self.device = ParentalDevice("192.168.10.50", "Tablet", "Tablet")
        self.policy = Mock()
        self.policy.list_devices.return_value = [self.device]
        self.policy.get_state.return_value = YouTubePolicyState(self.device, False, True, True, True)
        self.bot = BotSettings(enable=True, admin_chat_ids=("admin",), modules=("parental_control",))
        self.handler = TelegramParentalHandler(
            self.settings,
            policy=self.policy,
            bot_settings=self.bot,
            audit=BotAuditLog(Path(self.temp.name) / "audit.jsonl"),
            log=lambda _message: None,
            token_factory=lambda: "token-1",
        )

    def tearDown(self):
        self.temp.cleanup()

    def callback(self, data, chat="admin", user="user"):
        return {"id": "cb", "data": data, "from": {"id": user}, "message": {"message_id": 1, "chat": {"id": chat}}}

    def test_unauthorized_callback_is_rejected(self):
        answer = Mock()
        self.assertTrue(self.handler.handle_callback(callback=self.callback("parental:v1:refresh", chat="reader"), auth=BotAuth(self.bot), answer_callback=answer, send_message=Mock(), edit_message=Mock(), telegram_token="", timeout=1, now=100))
        answer.assert_called_once()
        self.policy.list_devices.assert_not_called()

    def test_request_creates_token_without_mutating_policy(self):
        answer, edit = Mock(), Mock(return_value=Response())
        self.assertTrue(self.handler.handle_callback(callback=self.callback("parental:v1:youtube:request:0:block"), auth=BotAuth(self.bot), answer_callback=answer, send_message=Mock(), edit_message=edit, telegram_token="", timeout=1, now=100))
        self.policy.block.assert_not_called()
        self.assertTrue(Path(self.temp.name, "telegram-parental-actions.json").exists())

    def test_confirm_consumes_token_and_mutates_once(self):
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:request:0:block"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=100)
        answer = Mock()
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:confirm:token-1"), auth=BotAuth(self.bot), answer_callback=answer, send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=101)
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:confirm:token-1"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=102)
        self.policy.block.assert_called_once_with(self.device)

    def test_expired_token_does_not_mutate(self):
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:request:0:block"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=100)
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:confirm:token-1"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=401)
        self.policy.block.assert_not_called()

    def test_cancel_consumes_token_without_mutation(self):
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:request:0:block"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=100)
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:cancel:token-1"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=101)
        self.policy.block.assert_not_called()
        self.assertNotIn("token-1", Path(self.temp.name, "telegram-parental-actions.json").read_text())

    def test_token_chat_ownership_rejects_foreign_chat(self):
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:request:0:block"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=100)
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:confirm:token-1", chat="other"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=101)
        self.policy.block.assert_not_called()

    def test_token_user_ownership_rejects_foreign_user(self):
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:request:0:block", user="owner"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=100)
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:confirm:token-1", user="other"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=101)
        self.policy.block.assert_not_called()

    def test_backend_error_is_handled_and_sanitized(self):
        messages = []
        self.handler.log = messages.append
        self.policy.list_devices.side_effect = RuntimeError("pihole-test-password /bot123:telegram-test-token/ SID")
        self.assertTrue(self.handler.handle_callback(callback=self.callback("parental:v1:refresh"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=100))
        rendered = " ".join(messages)
        self.assertNotIn("pihole-test-password", rendered)
        self.assertNotIn("telegram-test-token", rendered)

    def test_telegram_delivery_retry_error_is_propagated(self):
        response = SimpleNamespace(ok=False, retryable=True, response_text="temporary")
        with self.assertRaises(RetryableTelegramDeliveryError):
            self.handler.handle_callback(callback=self.callback("parental:v1:refresh"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=response), telegram_token="", timeout=1, now=100)

    def test_audit_does_not_contain_secrets(self):
        audit_path = Path(self.temp.name) / "audit.jsonl"
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:request:0:block"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=100)
        self.handler.handle_callback(callback=self.callback("parental:v1:youtube:confirm:token-1"), auth=BotAuth(self.bot), answer_callback=Mock(), send_message=Mock(), edit_message=Mock(return_value=Response()), telegram_token="", timeout=1, now=101)
        content = audit_path.read_text()
        for secret in ("pihole-test-password", "telegram-test-token", "routeros-test-password", "token-1"):
            self.assertNotIn(secret, content)


if __name__ == "__main__":
    unittest.main()
